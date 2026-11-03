"""Provider credential cutover state machine for *disposable fixtures only*.

This module does not create containers. Its fixture entry point rejects the
production marker path; a production entry point requires a separately verified
runtime and pinned paths. Boot/crash guards, ingress and worker drain, provider
probes, and daemon-operation recovery are the adapter's responsibility.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import re
import stat


class CutoverError(RuntimeError):
    pass


_PRODUCTION_STATE = Path('/var/lib/ai-story-book/provider-rotation')
_ID = re.compile(r'[0-9a-f]{64}\Z')
_IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')
_SLOTS = {
    'old_api': {'asb-pilot-api', 'asb-pilot-api-before-provider'},
    'old_worker': {'asb-pilot-worker', 'asb-pilot-worker-before-provider'},
    'new_api': {'asb-provider-next-api', 'asb-pilot-api'},
    'new_worker': {'asb-provider-next-worker', 'asb-pilot-worker'},
}
_PRE_NAMES = {'old_api': 'asb-pilot-api', 'old_worker': 'asb-pilot-worker',
              'new_api': 'asb-provider-next-api', 'new_worker': 'asb-provider-next-worker'}
_POST_NAMES = {'old_api': 'asb-pilot-api-before-provider', 'old_worker': 'asb-pilot-worker-before-provider',
               'new_api': 'asb-pilot-api', 'new_worker': 'asb-pilot-worker'}


def _directory(path, *, allow_production=False):
    path = Path(path)
    if not path.is_absolute() or (not allow_production and
                                  (path == _PRODUCTION_STATE or path.resolve() == _PRODUCTION_STATE)):
        raise CutoverError('Production cutover is not implemented')
    try:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError()
        return path
    except Exception:
        raise CutoverError('Fixture state directory is unavailable') from None


def _ids(ids):
    if (not isinstance(ids, dict) or set(ids) != set(_SLOTS)
            or any(not isinstance(v, str) or not _ID.fullmatch(v) for v in ids.values())
            or len(set(ids.values())) != len(ids)):
        raise CutoverError('Container identities are invalid')
    return dict(ids)


def _images(images):
    if (not isinstance(images, dict) or set(images) != set(_SLOTS)
            or any(not isinstance(v, str) or not _IMAGE.fullmatch(v) for v in images.values())
            or images['old_api'] != images['new_api'] or images['old_worker'] != images['new_worker']):
        raise CutoverError('Image identities are invalid')
    return dict(images)


def _lock(path):
    fd = None
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise ValueError()
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except Exception:
        if fd is not None:
            os.close(fd)
        raise CutoverError('Fixture lock unavailable') from None


def _absent(path):
    try:
        path.lstat()
    except FileNotFoundError:
        return
    except OSError:
        raise CutoverError('Recovery marker cannot be checked') from None
    raise CutoverError('Another recovery is pending')


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_marker(state, ids):
    marker = state / 'recovery.json'
    fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        data = (json.dumps({'version': 1, 'containers': ids}, sort_keys=True) + '\n').encode()
        while data:
            n = os.write(fd, data)
            if n <= 0:
                raise OSError('short marker write')
            data = data[n:]
        os.fsync(fd)
    finally:
        os.close(fd)
    _sync_dir(state)


def _read_marker(state):
    fd = None
    try:
        fd = os.open(state / 'recovery.json', os.O_RDONLY | os.O_NOFOLLOW)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or before.st_mode & 0o077 or before.st_nlink != 1 or before.st_size > 4096):
            raise ValueError()
        payload = os.read(fd, 4097)
        after = os.fstat(fd)
        if (len(payload) != before.st_size or any(getattr(before, field) != getattr(after, field) for field in
                ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))):
            raise ValueError()
        value = json.loads(payload)
        if (not isinstance(value, dict) or set(value) != {'version', 'containers'}
                or type(value['version']) is not int or value['version'] != 1):
            raise ValueError()
        return _ids(value['containers'])
    except Exception:
        raise CutoverError('Recovery marker is invalid') from None
    finally:
        if fd is not None:
            os.close(fd)


def _preflight(runtime, ids, images, lock_fd, *, old_restart):
    # An adapter MUST validate actual source/image, exact mount/env/command,
    # supervisor boot/recovery, external writers and candidate idleness.
    # No implementation of these production assertions is supplied here.
    runtime.assert_candidate_and_interlocks(ids, images, lock_fd=lock_fd, old_restart=old_restart)
    for slot, identifier in ids.items():
        item = runtime.inspect(identifier)
        if (item.get('id') != identifier or item.get('name') != _PRE_NAMES[slot]
                or item.get('image_id') != images[slot]
                or item.get('running') is not slot.startswith('old_')
                or item.get('restart_policy') != (old_restart if slot.startswith('old_') else 'no')):
            raise CutoverError('Candidate identity or initial state differs')


def _assert_slot(runtime, identifier, *, name, image, running, restart):
    item = runtime.inspect(identifier)
    if (item.get('id') != identifier or item.get('name') != name or item.get('image_id') != image
            or item.get('running') is not running or item.get('restart_policy') != restart):
        raise CutoverError('Container identity or state changed')


def _quarantine(runtime, ids):
    """Best effort on owned exact IDs only; never start any old container."""
    failed = False
    for slot, identifier in ids.items():
        try:
            item = runtime.inspect(identifier)
            if item.get('id') != identifier or item.get('name') not in _SLOTS[slot]:
                failed = True
                continue
            runtime.disable_restart(identifier)
            if runtime.inspect(identifier).get('running') is True:
                runtime.stop(identifier)
            final = runtime.inspect(identifier)
            if final.get('running') is not False or final.get('restart_policy') != 'no':
                failed = True
        except Exception:
            failed = True
    # An operation delivered to the daemon before timeout could finish later.
    # The runtime must actually prove no such operation remains in flight.
    try:
        runtime.assert_no_unresolved_daemon_operations()
    except Exception:
        failed = True
    return not failed


def _run_cutover(*, state_dir, backup_dir, ids, images, other_markers, runtime, production=False):
    """Execute the state machine with the caller's separately verified adapter."""
    state, backup = _directory(state_dir, allow_production=production), _directory(backup_dir)
    if production and (state != _PRODUCTION_STATE or backup != Path('/var/lib/ai-story-book/backup-state')):
        raise CutoverError('Production state paths are invalid')
    ids, images = _ids(ids), _images(images)
    if not isinstance(other_markers, (list, tuple)) or any(not isinstance(x, Path) or not x.is_absolute() for x in other_markers):
        raise CutoverError('Recovery paths are invalid')
    lock = _lock(backup / 'backup.lock')
    recovery_lock = None
    marked = False
    try:
        recovery_lock = _lock(state / 'recovery.lock')
        for marker in (state / 'recovery.json', *other_markers):
            _absent(marker)
        _preflight(runtime, ids, images, lock, old_restart='unless-stopped')
        runtime.assert_no_unresolved_daemon_operations()
        # Drain and disable *old* auto-restart while holding the shared lock.
        # Failure in this preparation interval is a pre-cutover partial
        # outage; no candidate may be started or renamed.
        runtime.drain_ingress()
        runtime.assert_ingress_drained()
        runtime.assert_worker_idle()
        for slot in ('old_api', 'old_worker'):
            runtime.disable_restart(ids[slot])
            _assert_slot(runtime, ids[slot], name=_PRE_NAMES[slot], image=images[slot], running=True, restart='no')
        _preflight(runtime, ids, images, lock, old_restart='no')
        runtime.assert_ingress_drained()
        runtime.assert_worker_idle()
        runtime.assert_no_unresolved_daemon_operations()
        # All four containers now have restart=no. Boot recovery and legacy
        # interlocks still need real installation and independent verification.
        _write_marker(state, ids)
        marked = True
        runtime.stop(ids['old_api'])
        _assert_slot(runtime, ids['old_api'], name=_PRE_NAMES['old_api'], image=images['old_api'],
                     running=False, restart='no')
        runtime.assert_ingress_drained()
        runtime.assert_worker_idle()
        runtime.stop(ids['old_worker'])
        _assert_slot(runtime, ids['old_worker'], name=_PRE_NAMES['old_worker'], image=images['old_worker'],
                     running=False, restart='no')
        for slot in ('old_api', 'old_worker', 'new_api', 'new_worker'):
            runtime.rename(ids[slot], _POST_NAMES[slot])
            _assert_slot(runtime, ids[slot], name=_POST_NAMES[slot], image=images[slot], running=False, restart='no')
        runtime.start(ids['new_api'])
        _assert_slot(runtime, ids['new_api'], name=_POST_NAMES['new_api'], image=images['new_api'],
                     running=True, restart='no')
        # The adapter must validate real provider output and exact config,
        # then check 200 readiness. A fake adapter proves ordering only.
        runtime.probe_provider_and_assert_readiness(ids['new_api'])
        runtime.start(ids['new_worker'])
        _assert_slot(runtime, ids['new_worker'], name=_POST_NAMES['new_worker'], image=images['new_worker'],
                     running=True, restart='no')
        runtime.assert_worker_healthy(ids['new_worker'])
        runtime.assert_no_unresolved_daemon_operations()
        for slot in ('new_api', 'new_worker'):
            runtime.enable_restart(ids[slot])
            _assert_slot(runtime, ids[slot], name=_POST_NAMES[slot], image=images[slot],
                         running=True, restart='unless-stopped')
        runtime.reload_proxy()
        runtime.open_ingress()
        runtime.assert_live_candidate(ids['new_api'], ids['new_worker'])
        runtime.assert_no_unresolved_daemon_operations()
        for slot in ('old_api', 'old_worker'):
            _assert_slot(runtime, ids[slot], name=_POST_NAMES[slot], image=images[slot], running=False, restart='no')
        for slot in ('new_api', 'new_worker'):
            _assert_slot(runtime, ids[slot], name=_POST_NAMES[slot], image=images[slot],
                         running=True, restart='unless-stopped')
        (state / 'recovery.json').unlink()
        _sync_dir(state)
        return {'status': 'PRODUCTION_CUTOVER_PASSED' if production else 'FIXTURE_CUTOVER_PASSED',
                'production_authorized': production}
    except BaseException:
        if marked:
            try:
                runtime.drain_ingress()
                runtime.assert_ingress_drained()
            except Exception:
                pass  # Marker remains; never claim this was a safe recovery.
            _quarantine(runtime, ids)
        # Deliberately do not reopen ingress or start old containers.
        raise CutoverError('Fixture cutover failed; recovery may be required') from None
    finally:
        if recovery_lock is not None:
            os.close(recovery_lock)
        os.close(lock)


def run_fixture_cutover(*, state_dir, backup_dir, ids, images, other_markers, runtime):
    """Exercise cutover in a fixture; marker remains on every failure."""
    return _run_cutover(state_dir=state_dir, backup_dir=backup_dir, ids=ids, images=images,
                        other_markers=other_markers, runtime=runtime)


def recover_fixture(*, state_dir, backup_dir, runtime):
    """Quarantine only recorded IDs, keep marker, and never restart old keys."""
    state, backup = _directory(state_dir), _directory(backup_dir)
    lock = _lock(backup / 'backup.lock')
    recovery_lock = None
    try:
        recovery_lock = _lock(state / 'recovery.lock')
        ids = _read_marker(state)
        drained = True
        try:
            runtime.drain_ingress()
            runtime.assert_ingress_drained()
        except Exception:
            drained = False
        quarantined = _quarantine(runtime, ids)
        if not drained or not quarantined:
            raise CutoverError('Fixture quarantine is unresolved')
        return {'status': 'FIXTURE_QUARANTINED', 'production_authorized': False}
    finally:
        if recovery_lock is not None:
            os.close(recovery_lock)
        os.close(lock)
