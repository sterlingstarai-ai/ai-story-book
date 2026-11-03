"""Pinned production guard installation; never run without explicit --execute.

This installer changes guard files and systemd only, before key cutover. It
holds the pilot backup lock and release-install lock, snapshots the one
existing legacy guard, and leaves a durable marker on every uncertainty.
There is no automatic reboot recovery: an interrupted installation must be
recovered before key transfer or candidate creation. Use only after isolated
verification and independent review. Do not print or stage credentials.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import uuid

import provider_activate_guard as core
import provider_activate_systemd as systemd
import provider_install_stage as staging
from provider_cutover_production_entry import verify_instance


SCRIPTS = Path('/opt/ai-story-book/releases/asb-privacy-20261102/scripts')
CURRENT = Path('/opt/ai-story-book/current')
SYSTEMD = Path('/etc/systemd/system')
STATE = Path('/var/lib/ai-story-book/provider-install')
BACKUP = Path('/var/lib/ai-story-book/backup-state')
RELEASES = Path('/opt/ai-story-book/provider-releases')
PINNED_RELEASE = RELEASES / 'provider-release-8772f79b26f945a799c343d5a916d712'
PINNED_READY_SHA = 'fa65511e18d7f4b66f74a581e324b53a068c7a47faaa8b86154254aa366aec7d'
PINNED_CUTOVER_SHA = 'c3f2f1f120477622db9b27b85dc9732ccfa14363db795d82de6cc1a97fc401e5'
ENABLED_DIR = 'multi-user.target.wants'
ENABLED_NAME = 'asb-provider-rotation-quarantine.service'
ENABLED_TARGET = '../asb-provider-rotation-quarantine.service'
PRIOR_LINKS = {
    'timers.target.wants/asb-backup.timer': '/etc/systemd/system/asb-backup.timer',
    'multi-user.target.wants/asb-backup-recover.service': '/etc/systemd/system/asb-backup-recover.service',
    'multi-user.target.wants/asb-privacy-deploy-recover.service': '/etc/systemd/system/asb-privacy-deploy-recover.service',
}
_INHIBIT_UNITS = ('asb-backup.timer', 'asb-backup.service', 'asb-backup-recover.service',
                  'asb-privacy-deploy-recover.service')
CONTROL = Path('/etc/systemd/system.control')
LEGACY_GUARD_SHA = '9de56dad4e7535116124f3f2fe89136c3e9c604679e86a4f350ab8117d504e86'
BASE_UNIT_HASHES = {
    'asb-backup-recover.service': '75dad8494d54b27dbfe7236dc3221d38a934b778a67e3761ab90ca869bf58175',
    'asb-privacy-deploy-recover.service': '14d6274c41c5a3de6465e827d8a8b84b8c551309756b0902a18fd3657d3925c8',
}
ORDER = ('scripts/backup_service_guard.py', 'scripts/narration_deploy_safety.py',
         'scripts/provider_recovery_interlock.py', 'scripts/provider_rotation_quarantine.py',
         'systemd/asb-provider-rotation-quarantine.service',
         'systemd/asb-backup-recover.service.d/provider-order.conf',
         'systemd/asb-privacy-deploy-recover.service.d/provider-interlock.conf')
BLOCKERS = (Path('/var/lib/ai-story-book/backup-state/restart-required.json'),
            Path('/var/lib/ai-story-book/privacy-deploy/rollback.json'),
            Path('/var/lib/ai-story-book/narration-deploy/narration-recovery.json'),
            Path('/var/lib/ai-story-book/provider-rotation/recovery.json'),
            Path('/var/lib/ai-story-book/provider-rotation/docker-mutation.json'),
            Path('/var/lib/ai-story-book/provider-rotation/candidate-owner.json'),
            Path('/var/lib/ai-story-book/provider-rotation/probe-owner.json'))


class ProductionInstallError(RuntimeError):
    pass


def _absent(path):
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                return
            os.close(fd)
            fd = child
        try:
            os.stat(path.name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise ProductionInstallError('Another installation or recovery is pending')
    finally:
        os.close(fd)



def _require_no_systemd_operation(state_fd):
    if core._read_at(state_fd, 'systemd-op.json', absent=True) is not None:
        raise ProductionInstallError('An earlier systemd operation remains unresolved')


def _systemd_operation(state_fd, transaction, action, execute, verify):
    """Preserve a durable intent on timeout, interruption, or failed checking."""
    if (not isinstance(transaction, str) or not re.fullmatch('[0-9a-f]{32}', transaction)
            or action not in ('timer-stop', 'timer-start', 'daemon-reload', 'reload-new', 'reload-old')
            or not callable(execute) or not callable(verify)):
        raise ProductionInstallError('Invalid systemd operation')
    raw = (json.dumps({'version': 1, 'transaction': transaction, 'action': action}, sort_keys=True) + '\n').encode()
    core._write_new(state_fd, 'systemd-op.json', raw, 0o600)
    os.fsync(state_fd)
    execute()
    if verify() is not True:
        raise ProductionInstallError('Systemd operation result is unconfirmed')
    item = core._read_at(state_fd, 'systemd-op.json')
    if item[0] != raw:
        raise ProductionInstallError('Systemd operation record changed')
    current = os.stat('systemd-op.json', dir_fd=state_fd, follow_symlinks=False)
    if (current.st_dev, current.st_ino) != (item[1].st_dev, item[1].st_ino):
        raise ProductionInstallError('Systemd operation identity changed')
    os.unlink('systemd-op.json', dir_fd=state_fd)
    os.fsync(state_fd)


def _current_identity():
    info = CURRENT.lstat()
    if not stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or os.readlink(CURRENT) != 'releases/asb-privacy-20261102':
        raise ProductionInstallError('Pinned application release changed')
    if CURRENT.resolve(strict=True) / 'scripts' != SCRIPTS:
        raise ProductionInstallError('Pinned application path changed')
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mtime_ns, info.st_ctime_ns)


def _pin_current(identity):
    if _current_identity() != identity:
        raise ProductionInstallError('Pinned application release changed')


def _root(path, *, private):
    fd = staging._dir(str(path), safe_parent=True)
    info = os.fstat(fd)
    if (info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022
            or (private and stat.S_IMODE(info.st_mode) != 0o700)):
        os.close(fd)
        raise ProductionInstallError('Installation directory is unsafe')
    return fd


def _ensure_private_state():
    parent = _root(STATE.parent, private=False)
    try:
        try:
            os.mkdir(STATE.name, 0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
    finally:
        os.close(parent)
    return _root(STATE, private=True)


def _existing_lock(directory, name):
    """Acquire a pre-existing root-owned lock without creating a new file."""
    fd = None
    try:
        fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW, dir_fd=directory)
        opened = os.fstat(fd)
        linked = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != 0 or opened.st_gid != 0
                or opened.st_mode & 0o077 or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino)):
            raise ValueError()
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BaseException:
        if fd is not None:
            os.close(fd)
        raise ProductionInstallError('Existing shared lock is unavailable') from None


def _open_locks():
    backup_dir = _root(BACKUP, private=True)
    release_dir = None
    backup_lock = None
    try:
        backup_lock = _existing_lock(backup_dir, 'backup.lock')
        release_dir = _root(RELEASES, private=False)
        install_lock = _existing_lock(release_dir, '.provider-install.lock')
        return backup_dir, release_dir, backup_lock, install_lock
    except BaseException:
        if backup_lock is not None:
            os.close(backup_lock)
        if release_dir is not None:
            os.close(release_dir)
        os.close(backup_dir)
        raise

def _read_target(roots, name):
    try:
        return core._read_target(roots, name)
    except FileNotFoundError:
        return None


def _read_release(release, ready_sha):
    if release != PINNED_RELEASE:
        raise ProductionInstallError('Release path is invalid')
    if ready_sha != PINNED_READY_SHA:
        raise ProductionInstallError('Release identity is invalid')
    fd = _root(release, private=True)
    try:
        ready = staging._read_file(fd, 'READY')
        if hashlib.sha256(ready).hexdigest() != ready_sha:
            raise ValueError()
        record = json.loads(ready)
        if (not isinstance(record, dict) or set(record) != {'version', 'release', 'files'}
                or type(record['version']) is not int or record['version'] != 1
                or record['release'] != release.name or not isinstance(record['files'], dict)):
            raise ValueError()
        manifest = staging._read_file(fd, 'boot/manifest.json')
        cutover = staging._read_file(fd, 'cutover/manifest.json')
        files = staging._manifest(manifest, staging.BOOT_MANIFEST_SHA256, staging.BOOT_FILES, boot=True)
        cutover_files = staging._manifest(cutover, PINNED_CUTOVER_SHA, staging.CUTOVER_FILES)
        expected = ({'boot/' + name for name in files} | {'cutover/' + name for name in cutover_files}
                    | {'boot/manifest.json', 'cutover/manifest.json'})
        if (set(record['files']) != expected
                or record['files'].get('boot/manifest.json') != staging.BOOT_MANIFEST_SHA256
                or record['files'].get('cutover/manifest.json') != PINNED_CUTOVER_SHA):
            raise ValueError()
        values = {}
        for prefix, inventory in (('boot', files), ('cutover', cutover_files)):
            for name, digest in inventory.items():
                data = staging._read_file(fd, prefix + '/' + name)
                if hashlib.sha256(data).hexdigest() != digest or record['files'].get(prefix + '/' + name) != digest:
                    raise ValueError()
                if prefix == 'boot':
                    values[name] = data
        return values
    except Exception:
        raise ProductionInstallError('Pinned staged release could not be verified') from None
    finally:
        os.close(fd)


def _verify_base_units(systemd_fd):
    for name, digest in BASE_UNIT_HASHES.items():
        item = core._read_at(systemd_fd, name)
        if (core._sha(item[0]) != digest or item[1].st_uid != 0 or item[1].st_gid != 0
                or stat.S_IMODE(item[1].st_mode) != 0o644):
            raise ProductionInstallError('Original recovery unit differs')


def _baseline(systemd_fd):
    _verify_base_units(systemd_fd)
    before = systemd.capture_baseline()
    for unit in ('asb-backup-recover.service', 'asb-privacy-deploy-recover.service'):
        data = before[unit]
        if data['LoadState'] != 'loaded' or data['UnitFileState'] != 'enabled' or data['NeedDaemonReload'] != 'no':
            raise ProductionInstallError('Original recovery unit is not ready')
    if before[ENABLED_NAME]['LoadState'] != 'not-found':
        raise ProductionInstallError('Quarantine unit already exists')
    return before


def _directory_exists(root, name):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
    except FileNotFoundError:
        return False
    try:
        info = os.fstat(fd)
        if info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022:
            raise ValueError()
        return True
    finally:
        os.close(fd)


def _enabled_link(root):
    fd = os.open(ENABLED_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
    try:
        info = os.fstat(fd)
        if info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022:
            raise ValueError()
        try:
            link = os.stat(ENABLED_NAME, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if not stat.S_ISLNK(link.st_mode) or link.st_uid != 0 or link.st_gid != 0:
            raise ValueError()
        return os.readlink(ENABLED_NAME, dir_fd=fd)
    finally:
        os.close(fd)




def _record_enabled_link(root, state_fd, transaction):
    fd = os.open(ENABLED_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
    try:
        item = os.stat(ENABLED_NAME, dir_fd=fd, follow_symlinks=False)
        if (not stat.S_ISLNK(item.st_mode) or item.st_uid != 0 or item.st_gid != 0
                or os.readlink(ENABLED_NAME, dir_fd=fd) != ENABLED_TARGET):
            raise ProductionInstallError('Quarantine enable link is unsafe')
        record = {'version': 1, 'transaction': transaction, 'device': item.st_dev,
                  'inode': item.st_ino, 'target': ENABLED_TARGET}
        raw = (json.dumps(record, sort_keys=True) + '\n').encode()
        core._write_matching_record(state_fd, 'enable-' + transaction + '.json', raw)
    finally:
        os.close(fd)


def _check_enabled_link(root, state_fd, transaction, *, allow_absent=False):
    fd = os.open(ENABLED_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
    try:
        try:
            item = os.stat(ENABLED_NAME, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            if allow_absent:
                return None
            raise
        saved = core._read_at(state_fd, 'enable-' + transaction + '.json')
        expected = {'version': 1, 'transaction': transaction, 'device': item.st_dev,
                    'inode': item.st_ino, 'target': ENABLED_TARGET}
        data = json.loads(saved[0])
        if (not stat.S_ISLNK(item.st_mode) or item.st_uid != 0 or item.st_gid != 0
                or os.readlink(ENABLED_NAME, dir_fd=fd) != ENABLED_TARGET or data != expected
                or type(data.get('version')) is not int):
            raise ProductionInstallError('Quarantine enable link identity changed')
        return item.st_dev, item.st_ino
    finally:
        os.close(fd)


def _unit_state(unit, *, allow_masked=False):
    if unit not in _INHIBIT_UNITS:
        raise ProductionInstallError('Unexpected unit')
    try:
        props = ('Id', 'LoadState', 'UnitFileState', 'ActiveState', 'SubState', 'NeedDaemonReload')
        result = subprocess.run(['/usr/bin/systemctl', 'show', unit, *['--property=' + x for x in props]],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=False,
                                env={'PATH': '/usr/bin:/bin', 'HOME': '/root'})
        if result.returncode != 0 or len(result.stdout) > 16384:
            raise ValueError()
        data = {}
        for row in result.stdout.decode().splitlines():
            key, value = row.split('=', 1)
            if key not in props or key in data:
                raise ValueError()
            data[key] = value
        if (data.get('Id') != unit or data.get('LoadState') not in (('loaded', 'masked') if allow_masked else ('loaded',))
                or not {'Id', 'LoadState', 'ActiveState', 'SubState'}.issubset(data)
                or (data['LoadState'] == 'loaded' and set(data) != set(props))):
            raise ValueError()
        return data
    except Exception:
        raise ProductionInstallError('Backup unit state is unavailable') from None


def _timer(action):
    if action not in ('stop', 'start'):
        raise ProductionInstallError('Unexpected timer operation')
    try:
        result = subprocess.run(['/usr/bin/systemctl', action, 'asb-backup.timer'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=60, check=False, env={'PATH': '/usr/bin:/bin', 'HOME': '/root'})
        if result.returncode != 0:
            raise ValueError()
    except Exception:
        raise ProductionInstallError('Backup timer operation is unconfirmed') from None



def _verify_systemd_platform():
    """Check the observed systemd family and persistent override precedence."""
    try:
        env = {'PATH': '/usr/bin:/bin', 'HOME': '/root'}
        version = subprocess.run(['/usr/bin/systemctl', '--version'], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, timeout=20, check=False, env=env)
        paths = subprocess.run(['/usr/bin/systemd-analyze', 'unit-paths', '--system'], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, timeout=20, check=False, env=env)
        if (version.returncode != 0 or paths.returncode != 0
                or len(version.stdout) > 8192 or len(paths.stdout) > 65536):
            raise ValueError()
        line = version.stdout.decode().splitlines()[0]
        if not re.match(r'^systemd 257(?:\s|$)', line):
            raise ValueError()
        entries = [entry.strip() for entry in paths.stdout.decode().splitlines() if entry.strip()]
        if (entries.count(str(CONTROL)) != 1 or entries.count(str(SYSTEMD)) != 1
                or entries.index(str(CONTROL)) >= entries.index(str(SYSTEMD))):
            raise ValueError()
        _assert_no_jobs()
    except Exception:
        raise ProductionInstallError('Systemd mask precedence is unconfirmed') from None


def _initial_unit_states():
    states = {unit: _unit_state(unit) for unit in _INHIBIT_UNITS}
    if (states['asb-backup.timer']['UnitFileState'] != 'enabled'
            or states['asb-backup.timer']['ActiveState'] != 'active'
            or states['asb-backup.timer']['SubState'] != 'waiting'
            or states['asb-backup.service']['UnitFileState'] != 'static'
            or any(states[unit]['ActiveState'] != 'inactive' for unit in _INHIBIT_UNITS[1:])
            or any(states[unit]['UnitFileState'] != 'enabled' for unit in _INHIBIT_UNITS[2:])
            or any(states[unit]['NeedDaemonReload'] != 'no' for unit in _INHIBIT_UNITS)):
        raise ProductionInstallError('Backup/recovery unit state changed')
    return states


def _assert_inactive_units(*, allow_masked=False):
    states = {unit: _unit_state(unit, allow_masked=allow_masked) for unit in _INHIBIT_UNITS}
    if any(states[unit]['ActiveState'] != 'inactive' for unit in _INHIBIT_UNITS):
        raise ProductionInstallError('Backup or recovery service is still active')
    return states



def _assert_prior_links(root):
    for relative, target in PRIOR_LINKS.items():
        directory, name = relative.split('/', 1)
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        try:
            info = os.fstat(fd)
            link = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if (info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022
                    or not stat.S_ISLNK(link.st_mode) or link.st_uid != 0 or link.st_gid != 0
                    or os.readlink(name, dir_fd=fd) != target):
                raise ValueError()
        finally:
            os.close(fd)


def _links(root, *, restore):
    """Remove/restore only the three exact pre-observed enable symlinks."""
    for relative, target in PRIOR_LINKS.items():
        directory, name = relative.split('/', 1)
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        try:
            info = os.fstat(fd)
            if info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022:
                raise ValueError()
            try:
                link = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                link = None
            if link is not None and (not stat.S_ISLNK(link.st_mode) or link.st_uid != 0 or link.st_gid != 0
                                     or os.readlink(name, dir_fd=fd) != target):
                raise ValueError()
            if restore and link is None:
                os.symlink(target, name, dir_fd=fd)
                os.fsync(fd)
            elif not restore:
                if link is None:
                    raise ValueError()
                current = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (link.st_dev, link.st_ino):
                    raise ValueError()
                os.unlink(name, dir_fd=fd)
                os.fsync(fd)
        finally:
            os.close(fd)



def _stop_timer_if_active():
    timer = _unit_state('asb-backup.timer', allow_masked=True)
    if timer['ActiveState'] == 'active' and timer['LoadState'] == 'loaded':
        _timer('stop')
    elif timer['ActiveState'] != 'inactive':
        raise ProductionInstallError('Backup timer state is unconfirmed')


def _remove_control_if_empty():
    try:
        fd = _control_directory(create=False)
    except FileNotFoundError:
        return
    try:
        info = os.fstat(fd)
        empty = not os.listdir(fd)
    finally:
        os.close(fd)
    if not empty:
        return
    parent = _root(CONTROL.parent, private=False)
    try:
        current = os.stat(CONTROL.name, dir_fd=parent, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError()
        os.rmdir(CONTROL.name, dir_fd=parent)
        os.fsync(parent)
    finally:
        os.close(parent)


def _assert_no_jobs():
    try:
        result = subprocess.run(['/usr/bin/systemctl', 'list-jobs', '--no-legend', '--no-pager', '--plain'],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=False,
                                env={'PATH': '/usr/bin:/bin', 'HOME': '/root'})
        if result.returncode != 0 or len(result.stdout) > 65536:
            raise ValueError()
        for row in result.stdout.decode().splitlines():
            row = row.strip()
            if not row or row == 'No jobs running.':
                continue
            fields = row.split()
            if len(fields) < 4 or not fields[0].isdigit() or fields[1] in _INHIBIT_UNITS:
                raise ValueError()
    except Exception:
        raise ProductionInstallError('A recovery systemd job is pending or unknown') from None


def _control_directory(*, create):
    parent = _root(CONTROL.parent, private=False)
    try:
        try:
            os.stat(CONTROL.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            if not create:
                raise
            os.mkdir(CONTROL.name, 0o755, dir_fd=parent)
            os.fsync(parent)
    finally:
        os.close(parent)
    return _root(CONTROL, private=False)


def _mask_record_name(unit, transaction):
    if unit not in _INHIBIT_UNITS:
        raise ProductionInstallError('Unexpected mask identity')
    if not re.fullmatch('[0-9a-f]{32}', transaction):
        raise ProductionInstallError('Unexpected mask transaction')
    return 'mask-' + transaction + '-' + unit + '.json'


def _create_masks(state_fd, transaction):
    fd = _control_directory(create=True)
    try:
        for unit in _INHIBIT_UNITS:
            # Never replace an existing operator-managed systemd override.
            os.symlink('/dev/null', unit, dir_fd=fd)
            os.fsync(fd)
            link = os.stat(unit, dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISLNK(link.st_mode) or link.st_uid != 0 or os.readlink(unit, dir_fd=fd) != '/dev/null':
                raise ValueError()
            record = {'version': 1, 'transaction': transaction, 'unit': unit,
                      'device': link.st_dev, 'inode': link.st_ino, 'target': '/dev/null'}
            raw = (json.dumps(record, sort_keys=True) + '\n').encode()
            core._write_matching_record(state_fd, _mask_record_name(unit, transaction), raw)
        os.fsync(state_fd)
    finally:
        os.close(fd)


def _verify_mask_links(state_fd, transaction, *, allow_absent=False):
    try:
        control = _control_directory(create=False)
    except FileNotFoundError:
        if allow_absent:
            return
        raise
    try:
        for unit in _INHIBIT_UNITS:
            try:
                link = os.stat(unit, dir_fd=control, follow_symlinks=False)
            except FileNotFoundError:
                if allow_absent:
                    continue
                raise
            item = core._read_at(state_fd, _mask_record_name(unit, transaction))
            record = json.loads(item[0])
            expected = {'version': 1, 'transaction': transaction, 'unit': unit,
                        'device': link.st_dev, 'inode': link.st_ino, 'target': '/dev/null'}
            if (not stat.S_ISLNK(link.st_mode) or link.st_uid != 0 or link.st_gid != 0
                    or os.readlink(unit, dir_fd=control) != '/dev/null' or record != expected
                    or type(record.get('version')) is not int):
                raise ValueError()
    finally:
        os.close(control)


def _verify_masked(state_fd, transaction):
    _verify_mask_links(state_fd, transaction)
    for unit in _INHIBIT_UNITS:
        state = _unit_state(unit, allow_masked=True)
        if state['LoadState'] != 'masked' or state['ActiveState'] != 'inactive':
            raise ProductionInstallError('Recovery units are not persistently masked and inactive')
    _assert_no_jobs()


def _remove_owned_masks(state_fd, transaction):
    # Missing own links may mean a prior interruption during removal; never
    # remove an existing link without its exact durable inode record.
    _verify_mask_links(state_fd, transaction, allow_absent=True)
    try:
        fd = _control_directory(create=False)
    except FileNotFoundError:
        return
    try:
        for unit in _INHIBIT_UNITS:
            try:
                link = os.stat(unit, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            record = json.loads(core._read_at(state_fd, _mask_record_name(unit, transaction))[0])
            if (link.st_dev, link.st_ino) != (record['device'], record['inode']):
                raise ValueError()
            os.unlink(unit, dir_fd=fd)
            os.fsync(fd)
    finally:
        os.close(fd)


def _verify_restored_timer():
    timer = _unit_state('asb-backup.timer')
    if (timer['UnitFileState'] != 'enabled' or timer['ActiveState'] != 'active'
            or timer['NeedDaemonReload'] != 'no'):
        raise ProductionInstallError('Backup timer restoration is unconfirmed')


def _open_roots():
    scripts = _root(SCRIPTS, private=False)
    try:
        units = _root(SYSTEMD, private=False)
    except BaseException:
        os.close(scripts)
        raise
    return {'scripts': scripts, 'systemd': units}


def _close_all(values):
    for fd in reversed(values):
        if fd is not None:
            os.close(fd)



def _preflight(*, release, ready_sha):
    """Read-only status: inspect existing locks, units, release, and targets."""
    verify_instance()
    _verify_systemd_platform()
    identity = _current_identity()
    source = _read_release(release, ready_sha)
    locks = ()
    roots = None
    try:
        locks = _open_locks()
        for marker in (*BLOCKERS, STATE / 'activation.json', STATE / 'systemd-op.json'):
            _absent(marker)
        _absent(CONTROL)
        roots = _open_roots()
        _pin_current(identity)
        _baseline(roots['systemd'])
        _initial_unit_states()
        _assert_prior_links(roots['systemd'])
        if _enabled_link(roots['systemd']) is not None:
            raise ProductionInstallError('Quarantine enable link already exists')
        for name in ORDER:
            old = core._describe(_read_target(roots, name))
            if name == 'scripts/backup_service_guard.py':
                if old != {'sha256': LEGACY_GUARD_SHA, 'mode': 0o644, 'uid': 0, 'gid': 0}:
                    raise ProductionInstallError('Legacy guard differs')
            elif old is not None:
                raise ProductionInstallError('A new guard target already exists')
            if not isinstance(source[name], bytes):
                raise ProductionInstallError('Pinned guard content is invalid')
        return {'status': 'GUARD_PREFLIGHT_PASSED', 'production_changed': False}
    finally:
        if roots is not None:
            _close_all(list(roots.values()))
        _close_all(list(locks))


def _install(*, release, ready_sha, transaction, after_replace=None):
    """Install using exact production layout; separated for injected fixture tests."""
    if not isinstance(transaction, str) or not re.fullmatch('[0-9a-f]{32}', transaction):
        raise ProductionInstallError('Installation transaction is invalid')
    verify_instance()
    _verify_systemd_platform()
    identity = _current_identity()
    source = _read_release(release, ready_sha)
    state_fd = _ensure_private_state()
    roots = None
    locks = ()
    try:
        locks = _open_locks()
        for marker in BLOCKERS:
            _absent(marker)
        if core._read_at(state_fd, 'activation.json', absent=True) is not None:
            raise ProductionInstallError('Earlier installation is unresolved')
        _require_no_systemd_operation(state_fd)
        _pin_current(identity)
        roots = _open_roots()
        baseline = _baseline(roots['systemd'])
        original_units = _initial_unit_states()
        _assert_prior_links(roots['systemd'])
        _absent(CONTROL)
        before_link = _enabled_link(roots['systemd'])
        if before_link is not None:
            raise ProductionInstallError('Quarantine enable link already exists')
        created_dirs = []
        for name in ('asb-backup-recover.service.d', 'asb-privacy-deploy-recover.service.d'):
            if not _directory_exists(roots['systemd'], name):
                created_dirs.append(name)
        original, record = {}, {}
        for name in ORDER:
            item = _read_target(roots, name)
            old = core._describe(item)
            if name == 'scripts/backup_service_guard.py':
                if old != {'sha256': LEGACY_GUARD_SHA, 'mode': 0o644, 'uid': 0, 'gid': 0}:
                    raise ProductionInstallError('Legacy guard differs')
            elif old is not None:
                raise ProductionInstallError('A new guard target already exists')
            original[name] = None if item is None else item[0]
            record[name] = {'old': old, 'new': {'sha256': core._sha(source[name]), 'mode': 0o644,
                                                 'uid': 0, 'gid': 0}}
        for index, name in enumerate(sorted(core.BOOT_FILES)):
            if original[name] is not None:
                core._write_new(state_fd, 'old-' + transaction + '-' + str(index), original[name], 0o600)
        os.fsync(state_fd)
        extra = {'baseline': baseline, 'created_dirs': created_dirs, 'enable_link': ENABLED_TARGET,
                 'scripts_realpath': str(SCRIPTS), 'current_identity': list(identity),
                 'prior_links': PRIOR_LINKS, 'original_units': original_units, 'control_created': True}
        raw = (json.dumps({'version': 1, 'transaction': transaction, 'files': record,
                           'systemd_before': extra}, sort_keys=True) + '\n').encode()
        core._write_matching_record(state_fd, 'activation.json', raw)
        _systemd_operation(state_fd, transaction, 'timer-stop', lambda: _timer('stop'),
                           lambda: _unit_state('asb-backup.timer')['ActiveState'] == 'inactive')
        _assert_inactive_units()
        _assert_no_jobs()
        _create_masks(state_fd, transaction)
        _systemd_operation(state_fd, transaction, 'daemon-reload', systemd._reload, lambda: True)
        _verify_masked(state_fd, transaction)
        for name in created_dirs:
            _pin_current(identity)
            os.mkdir(name, 0o755, dir_fd=roots['systemd'])
            os.fsync(roots['systemd'])
        for index, name in enumerate(ORDER):
            _pin_current(identity)
            _verify_masked(state_fd, transaction)
            core._replace(roots, name, expected=record[name]['old'], data=source[name],
                          metadata=record[name]['new'], token=transaction)
            if after_replace:
                after_replace(index, name)
        _pin_current(identity)
        enabled = os.open(ENABLED_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=roots['systemd'])
        try:
            os.symlink(ENABLED_TARGET, ENABLED_NAME, dir_fd=enabled)
            os.fsync(enabled)
        finally:
            os.close(enabled)
        _record_enabled_link(roots['systemd'], state_fd, transaction)
        _check_enabled_link(roots['systemd'], state_fd, transaction)
        # The recovery units are still masked here. Check exact on-disk
        # guard bytes and the newly loaded quarantine before unmasking.
        _systemd_operation(state_fd, transaction, 'daemon-reload', systemd._reload, lambda: True)
        _verify_masked(state_fd, transaction)
        _verify_base_units(roots['systemd'])
        systemd.verify_installed_guard_files()
        quarantine = systemd.show(ENABLED_NAME)
        if (quarantine.get('LoadState') != 'loaded' or quarantine.get('UnitFileState') != 'enabled'
                or quarantine.get('NeedDaemonReload') != 'no'):
            raise ProductionInstallError('Quarantine unit is not loaded')
        core._write_matching_record(state_fd, 'new-files-verified-' + transaction + '.json', raw)
        _remove_owned_masks(state_fd, transaction)
        _remove_control_if_empty()
        _systemd_operation(state_fd, transaction, 'reload-new', systemd.reload_new,
                           lambda: True)
        _pin_current(identity)
        # All guards and original enable links are now verified. Release only
        # the backup lock before restarting the timer so a due backup cannot
        # fail merely because this installer still owns that lock.
        locks = list(locks)
        os.close(locks[2])
        locks[2] = None
        _systemd_operation(state_fd, transaction, 'timer-start', lambda: _timer('start'),
                           lambda: (_verify_restored_timer() is None))
        core._write_matching_record(state_fd, 'new-verified-' + transaction + '.json', raw)
        os.unlink('activation.json', dir_fd=state_fd)
        os.fsync(state_fd)
        return {'status': 'GUARDS_INSTALLED', 'production_changed': True, 'transaction': transaction}
    finally:
        if roots is not None:
            _close_all(list(roots.values()))
        _close_all(list(locks))
        os.close(state_fd)


def _recover():
    verify_instance()
    _verify_systemd_platform()
    identity = _current_identity()
    state_fd = _root(STATE, private=True)
    roots = None
    locks = ()
    try:
        locks = _open_locks()
        for marker in BLOCKERS:
            _absent(marker)
        _require_no_systemd_operation(state_fd)
        record = core._record(state_fd)
        extra = record['systemd_before']
        if (not isinstance(extra, dict) or set(extra) != {'baseline', 'created_dirs', 'enable_link',
                                                          'scripts_realpath', 'current_identity',
                                                          'prior_links', 'original_units', 'control_created'}
                or extra['scripts_realpath'] != str(SCRIPTS) or extra['current_identity'] != list(identity)
                or extra['prior_links'] != PRIOR_LINKS
                or not isinstance(extra['original_units'], dict) or extra['control_created'] is not True
                or extra['enable_link'] != ENABLED_TARGET or not isinstance(extra['created_dirs'], list)
                or len(set(extra['created_dirs'])) != len(extra['created_dirs'])
                or any(x not in ('asb-backup-recover.service.d', 'asb-privacy-deploy-recover.service.d')
                       for x in extra['created_dirs'])):
            raise ProductionInstallError('Recovery record differs')
        roots = _open_roots()
        _verify_base_units(roots['systemd'])
        token = record['transaction']
        _systemd_operation(state_fd, token, 'timer-stop', _stop_timer_if_active,
                           lambda: (_unit_state('asb-backup.timer', allow_masked=True)['ActiveState'] == 'inactive'))
        _assert_inactive_units(allow_masked=True)
        raw = core._read_at(state_fd, 'activation.json')[0]
        phase = core._read_at(state_fd, 'new-files-verified-' + token + '.json', absent=True)
        if phase is not None:
            if phase[0] != raw or any(core._describe(_read_target(roots, name)) != value['new']
                                      for name, value in record['files'].items()):
                raise ProductionInstallError('Verified new guard set changed')
            _check_enabled_link(roots['systemd'], state_fd, token)
            systemd.verify_installed_guard_files()
            _remove_owned_masks(state_fd, token)
            _remove_control_if_empty()
            _systemd_operation(state_fd, token, 'reload-new', systemd.reload_new, lambda: True)
            _pin_current(identity)
            locks = list(locks)
            os.close(locks[2])
            locks[2] = None
            _systemd_operation(state_fd, token, 'timer-start', lambda: _timer('start'),
                               lambda: (_verify_restored_timer() is None))
            core._write_matching_record(state_fd, 'new-verified-' + token + '.json', raw)
            os.unlink('activation.json', dir_fd=state_fd)
            os.fsync(state_fd)
            return {'status': 'GUARDS_INSTALLATION_COMPLETED', 'production_changed': True, 'transaction': token}
        # Before all files are verified, any changed target requires all four
        # persistent masks to be loaded before restoring original files.
        all_old = True
        for name, value in record['files'].items():
            try:
                if core._describe(_read_target(roots, name)) != value['old']:
                    all_old = False
            except Exception:
                all_old = False
        if not all_old:
            _systemd_operation(state_fd, token, 'daemon-reload', systemd._reload, lambda: True)
            _verify_masked(state_fd, token)
        for name, value in record['files'].items():
            parts = name.split('/')
            if (parts[0] == 'systemd' and len(parts) == 3
                    and not _directory_exists(roots['systemd'], parts[1])):
                if value['old'] is not None:
                    raise ProductionInstallError('An original parent directory disappeared')
                continue
            core._resolve_owned_link(roots, name, value=value, token=token)
        for index, name in enumerate(sorted(core.BOOT_FILES)):
            value = record['files'][name]
            if core._describe(_read_target(roots, name)) not in (value['old'], value['new']):
                raise ProductionInstallError('A guard changed outside this transaction')
            if value['old'] is not None:
                old = core._read_at(state_fd, 'old-' + token + '-' + str(index))
                if core._sha(old[0]) != value['old']['sha256']:
                    raise ProductionInstallError('Original guard snapshot differs')
        for index, name in enumerate(sorted(core.BOOT_FILES)):
            _pin_current(identity)
            value = record['files'][name]
            current = _read_target(roots, name)
            if core._describe(current) == value['old']:
                continue
            if value['old'] is None:
                parent, leaf = core._open_parent(roots, name)
                try:
                    item = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
                    if (item.st_dev, item.st_ino) != (current[1].st_dev, current[1].st_ino):
                        raise ValueError()
                    os.unlink(leaf, dir_fd=parent)
                    os.fsync(parent)
                finally:
                    os.close(parent)
            else:
                old = core._read_at(state_fd, 'old-' + token + '-' + str(index))[0]
                core._replace(roots, name, expected=value['new'], data=old,
                              metadata=value['old'], token=token + '-restore')
        link_identity = _check_enabled_link(roots['systemd'], state_fd, token, allow_absent=True)
        if link_identity is not None:
            fd = os.open(ENABLED_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=roots['systemd'])
            try:
                current = os.stat(ENABLED_NAME, dir_fd=fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != link_identity:
                    raise ProductionInstallError('Quarantine enable link changed')
                os.unlink(ENABLED_NAME, dir_fd=fd)
                os.fsync(fd)
            finally:
                os.close(fd)
        for name in extra['created_dirs']:
            try:
                os.rmdir(name, dir_fd=roots['systemd'])
                os.fsync(roots['systemd'])
            except FileNotFoundError:
                pass
        if any(core._describe(_read_target(roots, name)) != value['old'] for name, value in record['files'].items()):
            raise ProductionInstallError('Original guard restoration differs')
        _remove_owned_masks(state_fd, token)
        _remove_control_if_empty()
        _systemd_operation(state_fd, token, 'reload-old', lambda: systemd.reload_old(extra['baseline']),
                           lambda: True)
        locks = list(locks)
        os.close(locks[2])
        locks[2] = None
        _systemd_operation(state_fd, token, 'timer-start', lambda: _timer('start'),
                           lambda: (_verify_restored_timer() is None))
        raw = core._read_at(state_fd, 'activation.json')[0]
        core._write_matching_record(state_fd, 'recovered-' + token + '.json', raw)
        os.unlink('activation.json', dir_fd=state_fd)
        os.fsync(state_fd)
        return {'status': 'GUARDS_RESTORED', 'production_changed': True, 'transaction': token}
    finally:
        if roots is not None:
            _close_all(list(roots.values()))
        _close_all(list(locks))
        os.close(state_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--preflight', action='store_true')
    actions.add_argument('--execute', action='store_true')
    actions.add_argument('--recover', action='store_true')
    parser.add_argument('--staging-release')
    parser.add_argument('--ready-sha256')
    args = parser.parse_args()
    try:
        if args.preflight or args.execute:
            if not args.staging_release or not args.ready_sha256:
                raise ProductionInstallError('Pinned staged release and READY hash are required')
            if args.preflight:
                result = _preflight(release=Path(args.staging_release), ready_sha=args.ready_sha256)
            else:
                result = _install(release=Path(args.staging_release), ready_sha=args.ready_sha256,
                                  transaction=uuid.uuid4().hex)
        else:
            if args.staging_release or args.ready_sha256:
                raise ProductionInstallError('Recovery does not accept a new release')
            result = _recover()
        print(json.dumps(result, sort_keys=True))
        return 0
    except BaseException:
        print(json.dumps({'status': 'INSTALLATION_OR_RECOVERY_UNCONFIRMED',
                          'preserve_activation_marker': True}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
