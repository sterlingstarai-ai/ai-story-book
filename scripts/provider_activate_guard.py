"""Crash-aware guard file activation primitive, exercised only in test directories.

No production entry point or systemd bootstrap installation is provided.
A real deployment must first install and prove a boot-ordered recovery unit,
coordinate every writer with the same locks, and bind the exact active paths
and previous file identities. Synthetic tests do not establish those facts.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

from provider_install_stage import BOOT_FILES


class ActivationError(RuntimeError):
    pass


_TOKEN = re.compile(r'[0-9a-f]{32}\Z')
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_LIMIT = 1024 * 1024
_BLOCKERS = ('restart-required.json', 'privacy-rollback.json', 'narration-recovery.json',
             'recovery.json', 'docker-mutation.json', 'candidate-owner.json', 'probe-owner.json')


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _directory(path):
    path = Path(path)
    if (not path.is_absolute() or path == Path('/') or path.is_symlink()
            or path.resolve(strict=True) != path):
        raise ActivationError('Fixture directory is unsafe')
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        os.close(fd)
        raise ActivationError('Fixture directory is unsafe')
    return fd


def _open_parent(root, name):
    parts = name.split('/')
    if name not in BOOT_FILES or any(x in ('', '.', '..') for x in parts):
        raise ActivationError('Unexpected guard target')
    if isinstance(root, dict):
        if set(root) != {'scripts', 'systemd'} or parts[0] not in root:
            raise ActivationError('Unexpected guard target root')
        fd = os.dup(root[parts[0]])
        parts = parts[1:]
    else:
        fd = os.dup(root)
    try:
        for part in parts[:-1]:
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = new
        return fd, parts[-1]
    except BaseException:
        os.close(fd)
        raise


def _read_at(directory, name, *, absent=False):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0), dir_fd=directory)
    except FileNotFoundError:
        if absent:
            return None
        raise
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1
                or info.st_mode & 0o022 or info.st_size > _LIMIT):
            raise ActivationError('Guard file is unsafe')
        # A replacement would otherwise silently drop Linux ACL/security
        # xattrs. Mac's Python lacks listxattr, so Mac results remain fixture
        # evidence only and never establish production metadata safety.
        if hasattr(os, 'listxattr'):
            if os.listxattr(fd):
                raise ActivationError('Extended metadata requires explicit preservation')
        elif sys.platform.startswith('linux'):
            raise ActivationError('Extended metadata cannot be verified')
        data = bytearray()
        while len(data) <= _LIMIT:
            chunk = os.read(fd, min(65536, _LIMIT + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(fd)
        if (len(data) != info.st_size or len(data) > _LIMIT
                or any(getattr(info, n) != getattr(after, n) for n in
                       ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_uid', 'st_gid', 'st_mode'))):
            raise ActivationError('Guard file changed while reading')
        return bytes(data), info
    finally:
        os.close(fd)


def _read_target(root, name, *, absent=True):
    directory, leaf = _open_parent(root, name)
    try:
        return _read_at(directory, leaf, absent=absent)
    finally:
        os.close(directory)


def _write_new(directory, name, data, mode):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=directory)
    try:
        os.fchmod(fd, mode)
        view = memoryview(data)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise OSError('short file write')
            view = view[count:]
        os.fsync(fd)
    finally:
        os.close(fd)



def _write_matching_record(directory, name, data):
    """Publish complete fsynced bytes atomically under the shared locks.

    The containing directory is private to the owner; all cooperating writers
    hold both locks. A non-cooperating privileged writer remains outside this
    primitive's guarantee.
    """
    existing = _read_at(directory, name, absent=True)
    if existing is not None:
        if existing[0] != data or stat.S_IMODE(existing[1].st_mode) != 0o600:
            raise ActivationError('Existing completion record differs')
        return
    temporary = '.' + name + '.' + _sha(data)[:16] + '.pending'
    pending = _read_at(directory, temporary, absent=True)
    if pending is None:
        _write_new(directory, temporary, data, 0o600)
    elif pending[0] != data:
        # A matching deterministic prefix under our private, locked state
        # directory is a torn write by this transaction; any other bytes are
        # preserved and require investigation.
        if stat.S_IMODE(pending[1].st_mode) != 0o600 or not data.startswith(pending[0]):
            raise ActivationError('Pending record differs')
        current = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (pending[1].st_dev, pending[1].st_ino):
            raise ActivationError('Pending record identity changed')
        os.unlink(temporary, dir_fd=directory)
        os.fsync(directory)
        _write_new(directory, temporary, data, 0o600)
    elif stat.S_IMODE(pending[1].st_mode) != 0o600:
        raise ActivationError('Pending record differs')
    if _read_at(directory, name, absent=True) is not None:
        raise ActivationError('Record appeared during publication')
    os.rename(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
    os.fsync(directory)

def _lock(directory, name):
    fd = os.open(name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise ValueError()
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BaseException:
        os.close(fd)
        raise ActivationError('Shared installation lock is unavailable') from None


def _locked(state):
    # Fixture root itself holds both locks. A production integration must use
    # the *actual* backup and staging lock in a consistent global order.
    first = _lock(state, 'backup.lock')
    try:
        second = _lock(state, 'provider-install.lock')
    except BaseException:
        os.close(first)
        raise
    return first, second


def _describe(item):
    if item is None:
        return None
    data, info = item
    return {'sha256': _sha(data), 'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}


def _record(state, name='activation.json'):
    item = _read_at(state, name)
    record = json.loads(item[0])
    if (not isinstance(record, dict) or set(record) != {'version', 'transaction', 'files', 'systemd_before'}
            or type(record['version']) is not int or record['version'] != 1
            or not isinstance(record['transaction'], str) or not _TOKEN.fullmatch(record['transaction'])
            or not isinstance(record['files'], dict) or set(record['files']) != BOOT_FILES
            or (record['systemd_before'] is not None and not isinstance(record['systemd_before'], dict))):
        raise ActivationError('Activation record is invalid')
    for value in record['files'].values():
        if (not isinstance(value, dict) or set(value) != {'old', 'new'} or not isinstance(value['new'], dict)
                or set(value['new']) != {'sha256', 'mode', 'uid', 'gid'}):
            raise ActivationError('Activation record is invalid')
        for entry in (value['old'], value['new']):
            if entry is not None and (not isinstance(entry, dict) or set(entry) != {'sha256', 'mode', 'uid', 'gid'}
                    or not isinstance(entry['sha256'], str) or not _HASH.fullmatch(entry['sha256'])
                    or any(type(entry[k]) is not int or entry[k] < 0 for k in ('mode', 'uid', 'gid'))
                    or entry['mode'] & 0o022 or entry['uid'] != os.geteuid() or entry['gid'] != os.getegid()):
                raise ActivationError('Activation record is invalid')
    return record


def _replace(root, name, *, expected, data, metadata, token):
    directory, leaf = _open_parent(root, name)
    temporary = '.' + leaf + '.activate-' + token
    try:
        before = _read_at(directory, leaf, absent=True)
        if _describe(before) != expected:
            raise ActivationError('Guard target changed before replacement')
        pending = _read_at(directory, temporary, absent=True)
        if pending is None:
            _write_new(directory, temporary, data, metadata['mode'])
        elif _describe(pending) != metadata or pending[0] != data:
            raise ActivationError('Existing transaction temporary file differs')
        if expected is None:
            # link provides no-overwrite semantics for a previously absent file.
            os.link(temporary, leaf, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
            os.unlink(temporary, dir_fd=directory)
        else:
            # Safe against cooperating writers under shared locks. A hostile
            # root writer can race pathname replacement; production must exclude it.
            current = os.stat(leaf, dir_fd=directory, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (before[1].st_dev, before[1].st_ino):
                raise ActivationError('Guard target changed before replacement')
            os.replace(temporary, leaf, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        # An interrupted pre-rename temp is not unlinked blindly on retry.
        os.close(directory)


def activate_fixture(*, active_directory, staged_directory, state_directory, expected_old, expected_new,
                     transaction, reload_and_verify, after_replace=None, systemd_before=None):
    """Apply seven guards to the supplied private fixture directory layout."""
    if (not _TOKEN.fullmatch(transaction or '') or not callable(reload_and_verify)
            or not isinstance(expected_old, dict) or set(expected_old) != BOOT_FILES
            or (systemd_before is not None and not isinstance(systemd_before, dict))
            or not isinstance(expected_new, dict) or set(expected_new) != BOOT_FILES
            or any(not isinstance(h, str) or not _HASH.fullmatch(h) for h in expected_new.values())):
        raise ActivationError('Guard activation plan is invalid')
    active = _directory(active_directory)
    staged = _directory(staged_directory)
    state = _directory(state_directory)
    locks = ()
    try:
        locks = _locked(state)
        for marker in ('activation.json', *_BLOCKERS):
            if _read_at(state, marker, absent=True) is not None:
                raise ActivationError('Earlier activation or recovery remains unresolved')
        original, replacement, record = {}, {}, {}
        for name in sorted(BOOT_FILES):
            old = _read_target(active, name)
            new = _read_target(staged, name, absent=False)
            old_meta = _describe(old)
            if (old_meta != expected_old[name] or _sha(new[0]) != expected_new[name]
                    or (old_meta is not None and old_meta['gid'] != os.getegid())):
                raise ActivationError('Pinned input or previous guard differs')
            original[name] = None if old is None else old[0]
            replacement[name] = new[0]
            record[name] = {'old': old_meta, 'new': {'sha256': _sha(new[0]), 'mode': 0o600,
                                                      'uid': os.geteuid(), 'gid': os.getegid()}}
        for index, name in enumerate(sorted(BOOT_FILES)):
            if original[name] is not None:
                snapshot_name = 'old-' + transaction + '-' + str(index)
                saved = _read_at(state, snapshot_name, absent=True)
                if saved is None:
                    _write_new(state, snapshot_name, original[name], 0o600)
                elif saved[0] != original[name] or stat.S_IMODE(saved[1].st_mode) != 0o600:
                    raise ActivationError('Existing transaction snapshot differs')
        os.fsync(state)
        raw = (json.dumps({'version': 1, 'transaction': transaction, 'files': record,
                           'systemd_before': systemd_before}, sort_keys=True) + '\n').encode()
        if len(raw) > _LIMIT:
            raise ActivationError('Systemd baseline is too large')
        _write_matching_record(state, 'activation.json', raw)
        for index, name in enumerate(sorted(BOOT_FILES)):
            _replace(active, name, expected=record[name]['old'], data=replacement[name],
                     metadata=record[name]['new'], token=transaction)
            if after_replace is not None:
                after_replace(index, name)
        if reload_and_verify('new', systemd_before) is not True:
            raise ActivationError('Reload or guard verification is unconfirmed')
        # Commit evidence and snapshots survive success. Write a separate
        # immutable record before withdrawing the in-progress marker.
        _write_matching_record(state, 'new-verified-' + transaction + '.json', raw)
        os.unlink('activation.json', dir_fd=state)
        os.fsync(state)
        return {'status': 'FIXTURE_ACTIVATED', 'production_changed': False}
    except Exception:
        raise ActivationError('Activation incomplete; preserve the recovery record') from None
    finally:
        for fd in reversed(locks):
            os.close(fd)
        os.close(state)
        os.close(staged)
        os.close(active)



def _resolve_owned_link(root, name, *, value, token):
    """Resolve the create link/unlink crash window without touching other links."""
    if value['old'] is not None:
        return
    directory, leaf = _open_parent(root, name)
    temporary = '.' + leaf + '.activate-' + token
    fds = []
    try:
        try:
            target = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        except FileNotFoundError:
            return
        fds.append(target)
        target_info = os.fstat(target)
        if target_info.st_nlink == 1:
            return
        temp = os.open(temporary, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        fds.append(temp)
        temp_info = os.fstat(temp)
        metadata = value['new']
        if (not stat.S_ISREG(target_info.st_mode) or target_info.st_nlink != 2
                or (target_info.st_dev, target_info.st_ino) != (temp_info.st_dev, temp_info.st_ino)
                or target_info.st_uid != metadata['uid'] or target_info.st_gid != metadata['gid']
                or stat.S_IMODE(target_info.st_mode) != metadata['mode']
                or target_info.st_size > _LIMIT):
            raise ValueError()
        digest = hashlib.sha256()
        count = 0
        for chunk in iter(lambda: os.read(target, 65536), b''):
            count += len(chunk)
            if count > _LIMIT:
                raise ValueError()
            digest.update(chunk)
        after = os.fstat(target)
        if (count != target_info.st_size or digest.hexdigest() != metadata['sha256']
                or any(getattr(target_info, n) != getattr(after, n) for n in
                       ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink'))):
            raise ValueError()
        current = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (target_info.st_dev, target_info.st_ino):
            raise ValueError()
        os.unlink(temporary, dir_fd=directory)
        os.fsync(directory)
    except Exception:
        raise ActivationError('Guard link recovery is unresolved') from None
    finally:
        for fd in reversed(fds):
            os.close(fd)
        os.close(directory)

def recover_fixture(*, active_directory, state_directory, reload_and_verify):
    """Restore only matching new versions to the exact previously verified files."""
    if not callable(reload_and_verify):
        raise ActivationError('Reload verification is required')
    active = _directory(active_directory)
    state = _directory(state_directory)
    locks = ()
    try:
        locks = _locked(state)
        for marker in _BLOCKERS:
            if _read_at(state, marker, absent=True) is not None:
                raise ActivationError('Another recovery is pending')
        record = _record(state)
        token = record['transaction']
        for name, value in record['files'].items():
            _resolve_owned_link(active, name, value=value, token=token)
        # Validate the entire recovery set before changing any target, so an
        # unrelated edit cannot cause a partially applied rollback.
        for index, name in enumerate(sorted(BOOT_FILES)):
            values = record['files'][name]
            current = _read_target(active, name)
            if _describe(current) not in (values['old'], values['new']):
                raise ActivationError('A guard was changed outside this transaction')
            if values['old'] is not None:
                old = _read_at(state, 'old-' + token + '-' + str(index))
                if _sha(old[0]) != values['old']['sha256']:
                    raise ActivationError('Guard snapshot differs')
        for index, name in enumerate(sorted(BOOT_FILES)):
            values = record['files'][name]
            current = _read_target(active, name)
            if _describe(current) == values['old']:
                continue
            directory, leaf = _open_parent(active, name)
            try:
                if values['old'] is None:
                    current_info = os.stat(leaf, dir_fd=directory, follow_symlinks=False)
                    if (current_info.st_dev, current_info.st_ino) != (current[1].st_dev, current[1].st_ino):
                        raise ValueError()
                    os.unlink(leaf, dir_fd=directory)
                    os.fsync(directory)
                else:
                    old = _read_at(state, 'old-' + token + '-' + str(index))
                    if _sha(old[0]) != values['old']['sha256']:
                        raise ValueError()
                    _replace(active, name, expected=values['new'], data=old[0],
                             metadata=values['old'], token=token + '-restore')
            finally:
                os.close(directory)
        if any(_describe(_read_target(active, name)) != values['old']
               for name, values in record['files'].items()):
            raise ActivationError('Old guard restoration is unconfirmed')
        if reload_and_verify('old', record['systemd_before']) is not True:
            raise ActivationError('Old unit reload is unconfirmed')
        raw = _read_at(state, 'activation.json')[0]
        _write_matching_record(state, 'recovered-' + token + '.json', raw)
        os.unlink('activation.json', dir_fd=state)
        os.fsync(state)
        return {'status': 'FIXTURE_RECOVERED', 'production_changed': False}
    except Exception:
        raise ActivationError('Guard recovery is unresolved; preserve all files') from None
    finally:
        for fd in reversed(locks):
            os.close(fd)
        os.close(state)
        os.close(active)


def restore_committed_fixture(*, active_directory, state_directory, transaction, reload_and_verify):
    """Prepare and execute restoration only before any separate key transition.

    The synthetic blocker set and locks are not proof about a production host.
    Production use needs the actual backup/install locks, every real recovery
    marker and an independent guarantee that no new-key transition began.
    """
    if not isinstance(transaction, str) or not _TOKEN.fullmatch(transaction) or not callable(reload_and_verify):
        raise ActivationError('Restoration plan is invalid')
    active = _directory(active_directory)
    state = _directory(state_directory)
    locks = ()
    try:
        locks = _locked(state)
        for marker in ('activation.json', *_BLOCKERS):
            if _read_at(state, marker, absent=True) is not None:
                raise ActivationError('Another activation or recovery is pending')
        source = 'new-verified-' + transaction + '.json'
        record = _record(state, source)
        if record['transaction'] != transaction:
            raise ActivationError('Committed activation identity differs')
        for index, name in enumerate(sorted(BOOT_FILES)):
            values = record['files'][name]
            if _describe(_read_target(active, name)) != values['new']:
                raise ActivationError('An activated guard changed after verification')
            if values['old'] is not None:
                previous = _read_at(state, 'old-' + transaction + '-' + str(index))
                if _sha(previous[0]) != values['old']['sha256']:
                    raise ActivationError('Guard snapshot differs')
        raw = _read_at(state, source)[0]
        _write_matching_record(state, 'activation.json', raw)
    except Exception:
        raise ActivationError('Committed guard restoration is not prepared') from None
    finally:
        for fd in reversed(locks):
            os.close(fd)
        os.close(state)
        os.close(active)
    # The durable marker prevents cooperating key/cutover writers in the
    # interval while recovery re-acquires the same shared locks.
    return recover_fixture(active_directory=active_directory, state_directory=state_directory,
                           reload_and_verify=reload_and_verify)
