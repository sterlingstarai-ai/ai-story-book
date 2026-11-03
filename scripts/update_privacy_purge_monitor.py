"""Safely switch only an already installed purge-monitor bundle on the pilot VM.

The current systemd units and alert policy are never changed. A failed switch
is rolled back to the previously pinned bundle where possible. A killed host
or process may leave the timer stopped; the operator must inspect and recover.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import time

from manage_privacy_purge_monitor import (
    BUNDLE_FILES, PYTHON, ROOT, UNITS, UNIT_DIR, bundle_check, checked_file,
    config_paths, digest, require_pilot_vm, require_root, run,
)

_HEX = re.compile(r'^[0-9a-f]{64}$')


def _active_state(unit):
    result = subprocess.run(['systemctl', 'show', unit, '--property=ActiveState', '--value'],
                            capture_output=True, text=True, timeout=15, check=True)
    return result.stdout.strip()


def _validate_installed_release(path, expected):
    """Allow runtime Python cache files; still verify every pinned source file."""
    if path.is_symlink() or not path.is_dir():
        raise ValueError('Installed release is not a directory')
    root_info = path.lstat()
    if root_info.st_uid != 0 or root_info.st_mode & 0o022:
        raise ValueError('Unsafe installed release directory')
    manifest_path = path / 'manifest.json'
    checked_file(manifest_path)
    if digest(manifest_path) != expected:
        raise ValueError('Current manifest does not match operator pin')
    manifest = json.loads(manifest_path.read_text())
    files = manifest.get('files')
    if (manifest.get('version') != 1 or not isinstance(files, dict)
            or any(name not in files for name in BUNDLE_FILES)):
        raise ValueError('Invalid installed manifest')
    actual = set()
    for entry in path.rglob('*'):
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('Unsafe installed release')
        if not entry.is_file():
            if not entry.is_dir():
                raise ValueError('Invalid installed release entry')
            continue
        relative = entry.relative_to(path).as_posix()
        if relative == 'manifest.json':
            continue
        if '__pycache__' in entry.parts and entry.suffix == '.pyc':
            continue
        if relative not in files or hashlib.sha256(entry.read_bytes()).hexdigest() != files[relative]:
            raise ValueError('Installed release content differs')
        actual.add(relative)
    if actual != set(files):
        raise ValueError('Installed release is incomplete')
    return files


def _atomic_switch(target):
    temporary = ROOT / ('.current-switch-' + secrets.token_hex(12))
    os.symlink(target, temporary)
    try:
        os.replace(temporary, ROOT / 'current')
    finally:
        if temporary.is_symlink():
            temporary.unlink()


def update(args):
    require_root()
    require_pilot_vm()
    info = ROOT.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError('Unsafe monitor installation directory')
    if not _HEX.fullmatch(args.expected_current_sha256) or not _HEX.fullmatch(args.manifest_sha256):
        raise ValueError('Invalid manifest pins')
    if args.expected_current_sha256 == args.manifest_sha256:
        raise ValueError('Candidate matches current release')
    receipt = ROOT / 'installation.json'
    checked_file(receipt, mode_mask=0o077)
    prior_receipt = json.loads(receipt.read_text())
    if prior_receipt.get('version') != 1 or set(prior_receipt.get('units', {})) != set(UNITS):
        raise ValueError('Invalid installation receipt')
    if args.reuse_existing_target:
        expected_target = args.reuse_existing_target
        if not (expected_target == 'release' or expected_target == 'release-' + args.manifest_sha256):
            raise ValueError('Invalid existing release identity')
        if args.bundle != ROOT / expected_target:
            raise ValueError('Existing release path does not match target')
        new_files = _validate_installed_release(args.bundle, args.manifest_sha256)
    else:
        new_files = bundle_check(args.bundle, args.manifest_sha256)
    for unit in UNITS:
        target = UNIT_DIR / unit
        checked_file(target)
        if (digest(target) != prior_receipt['units'][unit]
                or digest(target) != new_files[f'infra/gcp-pilot/{unit}']):
            raise ValueError('Unit changed; separate review required')
    inputs = config_paths()
    if not PYTHON.is_file() or not os.access(PYTHON, os.X_OK):
        raise ValueError('Application virtualenv unavailable')
    link = ROOT / 'current'
    if not link.is_symlink():
        raise ValueError('Current release link missing')
    old_target = os.readlink(link)
    if not (old_target == 'release' or re.fullmatch(r'release-[0-9a-f]{64}', old_target)):
        raise ValueError('Unexpected current release link')
    _validate_installed_release(ROOT / old_target, args.expected_current_sha256)
    new_target = args.reuse_existing_target or 'release-' + args.manifest_sha256
    new_path = ROOT / new_target
    if not args.reuse_existing_target and (new_path.exists() or new_path.is_symlink()):
        raise ValueError('Candidate release path already exists')
    # The candidate must be able to read the selected queue before any switch.
    run(str(PYTHON), str(args.bundle / BUNDLE_FILES[0]), '--execute',
        '--env-file', str(inputs['ASB_PURGE_MONITOR_ENV_FILE']),
        '--ca-file', str(inputs['ASB_PURGE_MONITOR_CA_FILE']))
    if not args.reuse_existing_target:
        shutil.copytree(args.bundle, new_path, symlinks=False)
        bundle_check(new_path, args.manifest_sha256)
    lock_path = ROOT / '.update.lock'
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        lock_info = os.fstat(fd)
        if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != 0 or lock_info.st_mode & 0o077:
            raise ValueError('Unsafe update lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if os.readlink(link) != old_target or _active_state(UNITS[1]) != 'active':
            raise ValueError('Monitor state changed before update')
        timer_stopped = False
        switched = False
        try:
            timer_stopped = True
            run('systemctl', 'stop', UNITS[1])
            # Allow an in-flight old invocation to finish before switching its
            # script path. No background process is killed by this update.
            deadline = time.monotonic() + 155
            while _active_state(UNITS[0]) in ('active', 'activating', 'deactivating'):
                if time.monotonic() >= deadline:
                    raise ValueError('Previous monitor invocation did not finish')
                time.sleep(1)
            if os.readlink(link) != old_target:
                raise ValueError('Release changed during update')
            _atomic_switch(new_target)
            switched = True
            # Service success means the new snapshot was accepted for sending;
            # it does not prove email delivery or restore safety.
            run('systemctl', 'start', UNITS[0])
            run('systemctl', 'start', UNITS[1])
            timer_stopped = False
        except Exception:
            if switched:
                _atomic_switch(old_target)
                # Best effort: publish the previous monitor's status again.
                try:
                    run('systemctl', 'start', UNITS[0])
                except Exception:
                    pass
            raise
        finally:
            if timer_stopped:
                run('systemctl', 'start', UNITS[1])
        return 'MONITOR_BUNDLE_SWITCHED'
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--expected-current-sha256', required=True)
    parser.add_argument('--reuse-existing-target', help='Pinned release name for an explicit rollback')
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({'status': 'DRY_RUN', 'changed': False}))
        return 0
    try:
        if not args.bundle.is_absolute():
            raise ValueError('Absolute candidate path required')
        status = update(args)
        print(json.dumps({'status': status, 'restore_authorized': False}))
        return 0
    except Exception:
        print(json.dumps({'status': 'UPDATE_FAILED_REVIEW_REQUIRED', 'restore_authorized': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
