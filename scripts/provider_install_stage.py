"""Stage hash-pinned provider code without touching active services or paths.

A release directory is never usable until READY is atomically published last.
No systemd action, symlink swap, existing file replacement, or live activation
is performed by this module. The independently supplied cutover manifest hash
must be protected separately from its source directory. All future activators
must share .provider-install.lock. If a crash leaves both READY and its pending
link, the release is incomplete and must be preserved for manual inspection.
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

BOOT_MANIFEST_SHA256 = '7b5dc506b27b7e503587ae687a5cc4b5e36124ce802d65943d81a6b3c63843dc'
CUTOVER_FILES = frozenset({
    'check_backup_status.py',
    'provider_cutover_production_entry.py', 'provider_cutover_production_adapter.py',
    'provider_cutover_production_runtime.py', 'provider_cutover_production_guards.py',
    'provider_cutover_drained.py', 'provider_cutover.py', 'provider_cutover_ingress.py',
    'provider_cutover_journal.py', 'provider_cutover_portless_exec.py',
    'provider_cutover_probe_runner.py', 'provider_cutover_probe.py', 'provider_cutover_queue_probe.py',
    'provider_candidate_stage.py', 'provider_environment.py', 'provider_config_overlay.py',
})
BOOT_FILES = frozenset({
    'scripts/backup_service_guard.py', 'scripts/narration_deploy_safety.py',
    'scripts/provider_recovery_interlock.py', 'scripts/provider_rotation_quarantine.py',
    'systemd/asb-backup-recover.service.d/provider-order.conf',
    'systemd/asb-privacy-deploy-recover.service.d/provider-interlock.conf',
    'systemd/asb-provider-rotation-quarantine.service',
})
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_RELEASE = re.compile(r'provider-release-[0-9a-f]{32}\Z')
_LIMIT = 512 * 1024


class InstallError(RuntimeError):
    pass


def _read_file(directory, relative):
    parts = relative.split('/')
    if not parts or any(p in ('', '.', '..') for p in parts):
        raise InstallError('Invalid source path')
    current = os.dup(directory)
    try:
        for part in parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = nxt
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0), dir_fd=current)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > _LIMIT:
                raise ValueError()
            result = bytearray()
            while len(result) <= _LIMIT:
                chunk = os.read(fd, min(65536, _LIMIT + 1 - len(result)))
                if not chunk:
                    break
                result.extend(chunk)
            after = os.fstat(fd)
            if (len(result) != before.st_size or len(result) > _LIMIT
                    or any(getattr(before, k) != getattr(after, k) for k in
                           ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))):
                raise ValueError()
            return bytes(result)
        finally:
            os.close(fd)
    except Exception:
        raise InstallError('Pinned source file unavailable') from None
    finally:
        os.close(current)


def _dir(path, *, safe_parent=False):
    p = Path(path)
    if not p.is_absolute() or os.path.normpath(str(p)) != str(p) or str(p) == '/':
        raise InstallError('Absolute canonical directory required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in p.parts[1:]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
            st = os.fstat(fd)
            if safe_parent and (st.st_uid not in (0, os.geteuid()) or st.st_mode & 0o022):
                raise ValueError()
        return fd
    except Exception:
        os.close(fd)
        raise InstallError('Directory unavailable or unsafe') from None


def _manifest(raw, expected_hash, names, *, boot=False):
    if not isinstance(expected_hash, str) or not _SHA.fullmatch(expected_hash) or hashlib.sha256(raw).hexdigest() != expected_hash:
        raise InstallError('Manifest hash mismatch')
    try:
        obj = json.loads(raw)
        if (not isinstance(obj, dict) or obj.get('version') != 1 or not isinstance(obj.get('files'), dict)
                or set(obj['files']) != names or any(not isinstance(v, str) or not _SHA.fullmatch(v)
                                                      for v in obj['files'].values())):
            raise ValueError()
        if not boot:
            if (set(obj) != {'version', 'files', 'created_utc', 'destination_root', 'expected_previous_sha256',
                             'guard_manifest_sha256', 'installed', 'production_tested'}
                    or not isinstance(obj['created_utc'], str)
                    or obj['destination_root'] != '/opt/ai-story-book/current/scripts'
                    or obj['guard_manifest_sha256'] != BOOT_MANIFEST_SHA256
                    or obj['expected_previous_sha256'] != {'check_backup_status.py':
                        'f40c28e9e28efa36c85304d5f392dadef444df8131363ed00a600d15cead871d'}
                    or obj['installed'] is not False or obj['production_tested'] is not False):
                raise ValueError()
        return obj['files']
    except Exception:
        raise InstallError('Manifest contents invalid') from None


def _write(fd, name, raw):
    out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        view = memoryview(raw)
        while view:
            n = os.write(out, view)
            if n <= 0:
                raise OSError('short write')
            view = view[n:]
        os.fsync(out)
    finally:
        os.close(out)


def _lock_parent(parent):
    fd = os.open('.provider-install.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077 or st.st_nlink != 1:
            raise ValueError()
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.fsync(parent)
        return fd
    except Exception:
        os.close(fd)
        raise InstallError('Installation lock unavailable') from None


def stage(*, boot_directory, cutover_directory, cutover_manifest_sha256, destination_parent, release_name,
          _safe_parent=True):
    """Create one exclusive inert release; any failure preserves partial files.

    The cutover source directory contains its own frozen manifest.json with an
    exact SHA supplied independently by the operator. No active file is touched.
    """
    if not _RELEASE.fullmatch(release_name):
        raise InstallError('Invalid release identity')
    boot = _dir(boot_directory)
    try:
        cut = _dir(cutover_directory)
    except Exception:
        os.close(boot)
        raise
    parent = None
    release = None
    lock = None
    try:
        bm = _read_file(boot, 'manifest.json')
        cm = _read_file(cut, 'manifest.json')
        bfiles = _manifest(bm, BOOT_MANIFEST_SHA256, BOOT_FILES, boot=True)
        cfiles = _manifest(cm, cutover_manifest_sha256, CUTOVER_FILES)
        payload = {}
        for prefix, source, inventory in (('boot', boot, bfiles), ('cutover', cut, cfiles)):
            for name, digest in inventory.items():
                content = _read_file(source, name)
                if hashlib.sha256(content).hexdigest() != digest:
                    raise InstallError('Source content hash mismatch')
                payload[f'{prefix}/{name}'] = content
        payload['boot/manifest.json'], payload['cutover/manifest.json'] = bm, cm
        inventory = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())}
        parent = _dir(destination_parent, safe_parent=_safe_parent)
        lock = _lock_parent(parent)
        os.mkdir(release_name, 0o700, dir_fd=parent)
        os.fsync(parent)
        release = os.open(release_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        for name, data in sorted(payload.items()):
            parts = name.split('/')
            current = os.dup(release)
            try:
                for part in parts[:-1]:
                    try:
                        os.mkdir(part, 0o700, dir_fd=current)
                        os.fsync(current)
                    except FileExistsError:
                        pass
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                    os.close(current)
                    current = nxt
                _write(current, parts[-1], data)
                os.fsync(current)
            finally:
                os.close(current)
        record = json.dumps({'version': 1, 'release': release_name, 'files': inventory},
                            sort_keys=True, separators=(',', ':')).encode() + b'\n'
        _write(release, '.READY.pending', record)
        os.link('.READY.pending', 'READY', src_dir_fd=release, dst_dir_fd=release, follow_symlinks=False)
        os.fsync(release)
        os.unlink('.READY.pending', dir_fd=release)
        os.fsync(release)
        return {'status': 'STAGED_INERT', 'file_count': len(payload), 'active_changed': False,
                'ready_sha256': hashlib.sha256(record).hexdigest()}
    except InstallError:
        raise
    except Exception:
        raise InstallError('Release staging failed; preserve partial directory') from None
    finally:
        if release is not None:
            os.close(release)
        if lock is not None:
            os.close(lock)
        if parent is not None:
            os.close(parent)
        os.close(boot)
        os.close(cut)


def rollback(*, destination_parent, release_name, ready_sha256, _safe_parent=True):
    """Remove a complete owned staged release only if every file still matches."""
    if not _RELEASE.fullmatch(release_name) or not _SHA.fullmatch(ready_sha256 or ''):
        raise InstallError('Invalid release identity')
    parent = _dir(destination_parent, safe_parent=_safe_parent)
    release = None
    lock = None
    try:
        lock = _lock_parent(parent)
        release = os.open(release_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        info = os.fstat(release)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError()
        raw = _read_file(release, 'READY')
        if hashlib.sha256(raw).hexdigest() != ready_sha256:
            raise ValueError()
        record = json.loads(raw)
        expected = {f'boot/{x}' for x in BOOT_FILES} | {f'cutover/{x}' for x in CUTOVER_FILES}
        expected |= {'boot/manifest.json', 'cutover/manifest.json'}
        if (set(record) != {'version', 'release', 'files'} or record['version'] != 1
                or record['release'] != release_name or not isinstance(record['files'], dict)
                or set(record['files']) != expected):
            raise ValueError()
        entries = {}
        directories = {}

        def visit(fd, prefix=''):
            for name in os.listdir(fd):
                path = prefix + name
                st = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISDIR(st.st_mode):
                    if st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != 0o700:
                        raise ValueError()
                    directories[path] = (st.st_dev, st.st_ino)
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        visit(child, path + '/')
                    finally:
                        os.close(child)
                elif stat.S_ISREG(st.st_mode) and st.st_uid == os.geteuid() and st.st_nlink == 1:
                    entries[path] = (st.st_dev, st.st_ino)
                else:
                    raise ValueError()

        visit(release)
        if set(entries) != expected | {'READY'}:
            raise ValueError()
        for name in expected:
            if hashlib.sha256(_read_file(release, name)).hexdigest() != record['files'][name]:
                raise ValueError()
        # Withdraw publication before deleting any content. A crash from this
        # point leaves an inert partial release for manual inspection.
        os.link('READY', '.withdrawn', src_dir_fd=release, dst_dir_fd=release, follow_symlinks=False)
        os.unlink('READY', dir_fd=release)
        os.fsync(release)
        entries['.withdrawn'] = entries.pop('READY')
        # Never follow symlinks; verify the inode immediately before each unlink.
        for name in sorted(entries, key=lambda x: x == '.withdrawn'):
            parts = name.split('/')
            directory = os.dup(release)
            try:
                for index, part in enumerate(parts[:-1]):
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    st = os.fstat(child)
                    prefix = '/'.join(parts[:index + 1])
                    if (st.st_dev, st.st_ino) != directories[prefix]:
                        os.close(child)
                        raise ValueError()
                    os.close(directory)
                    directory = child
                st = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
                if (st.st_dev, st.st_ino) != entries[name]:
                    raise ValueError()
                os.unlink(parts[-1], dir_fd=directory)
                os.fsync(directory)
            finally:
                os.close(directory)
        for name in sorted(directories, key=lambda x: x.count('/'), reverse=True):
            parts = name.split('/')
            directory = os.dup(release)
            try:
                for index, part in enumerate(parts[:-1]):
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    st = os.fstat(child)
                    if (st.st_dev, st.st_ino) != directories['/'.join(parts[:index + 1])]:
                        os.close(child)
                        raise ValueError()
                    os.close(directory)
                    directory = child
                st = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
                if (st.st_dev, st.st_ino) != directories[name]:
                    raise ValueError()
                os.rmdir(parts[-1], dir_fd=directory)
                os.fsync(directory)
            finally:
                os.close(directory)
        current = os.stat(release_name, dir_fd=parent, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError()
        os.rmdir(release_name, dir_fd=parent)
        os.fsync(parent)
        return {'status': 'STAGED_RELEASE_REMOVED', 'active_changed': False}
    except Exception:
        raise InstallError('Release rollback unconfirmed; preserve remaining files') from None
    finally:
        if release is not None:
            os.close(release)
        if lock is not None:
            os.close(lock)
        os.close(parent)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    prepare = sub.add_parser('stage', help='stage an inert release without activating it')
    prepare.add_argument('--boot-directory', required=True)
    prepare.add_argument('--cutover-directory', required=True)
    prepare.add_argument('--cutover-manifest-sha256', required=True)
    remove = sub.add_parser('rollback', help='remove an unchanged owned inert release')
    remove.add_argument('--ready-sha256', required=True)
    for child in (prepare, remove):
        child.add_argument('--destination-parent', required=True)
        child.add_argument('--release-name', required=True)
    args = vars(parser.parse_args())
    action = args.pop('action')
    try:
        result = stage(**args) if action == 'stage' else rollback(**args)
        print(json.dumps(result, sort_keys=True))
        return 0
    except InstallError:
        print(json.dumps({'status': 'STAGE_OPERATION_UNCONFIRMED', 'active_changed': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
