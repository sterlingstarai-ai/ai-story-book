"""Create a pinned, non-installed provider-recovery guard package.

The package contains code and systemd units only; no provider key, user data,
environment file, installation, or service modification is performed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

from provider_legacy_backup_guard import SOURCE_SHA256, build_overlay
from provider_recovery_interlock import _LEGACY_PRIVACY_SHA256


ROOT = Path(__file__).resolve().parents[1]
_FILES = {
    'scripts/provider_recovery_interlock.py': ROOT / 'scripts/provider_recovery_interlock.py',
    'scripts/provider_rotation_quarantine.py': ROOT / 'scripts/provider_rotation_quarantine.py',
    'scripts/narration_deploy_safety.py': ROOT / 'scripts/narration_deploy_safety.py',
    'systemd/asb-provider-rotation-quarantine.service': ROOT / 'infra/gcp-pilot/asb-provider-rotation-quarantine.service',
    'systemd/asb-privacy-deploy-recover.service.d/provider-interlock.conf': ROOT / 'infra/gcp-pilot/asb-privacy-deploy-recover.service.d/provider-interlock.conf',
    'systemd/asb-backup-recover.service.d/provider-order.conf': ROOT / 'infra/gcp-pilot/asb-backup-recover.service.d/provider-order.conf',
}


class PackageError(RuntimeError):
    pass


def _private_source(path, expected):
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > 200000:
            raise ValueError()
        data = os.read(fd, 200001)
        after = os.fstat(fd)
        if (len(data) != info.st_size or hashlib.sha256(data).hexdigest() != expected
                or any(getattr(info, key) != getattr(after, key) for key in
                       ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))):
            raise ValueError()
        return data
    except Exception:
        raise PackageError('Pinned private source could not be verified') from None
    finally:
        if fd is not None:
            os.close(fd)


def _assemble(backup_overlay, privacy_source):
    _private_source(privacy_source, _LEGACY_PRIVACY_SHA256)
    files = {'scripts/backup_service_guard.py': backup_overlay}
    for name, path in _FILES.items():
        if path.is_symlink() or not path.is_file():
            raise PackageError('Guard package source is unavailable')
        files[name] = path.read_bytes()
    for name, data in files.items():
        if name.endswith('.py'):
            compile(data, '<provider-boot-package>', 'exec')
    manifest = {'version': 1, 'backup_source_sha256': SOURCE_SHA256,
                'privacy_source_sha256': _LEGACY_PRIVACY_SHA256,
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
                'installed': False, 'boot_verified': False}
    return files, manifest


def build_package(*, backup_source, privacy_source, output):
    backup = _private_source(backup_source, SOURCE_SHA256)
    files, manifest = _assemble(build_overlay(backup), privacy_source)
    return _write_package(files, manifest, output)


def rebuild_from_verified_overlay(*, backup_overlay, overlay_sha256, privacy_source, output):
    # Re-use only the previously hash-verified output from the pinned legacy
    # source; this lets us avoid another production source read during freeze.
    if overlay_sha256 != 'd5a8f2b2e5ce6f4b0524429300186eed8068ecaf35535f1b8c30e41df36b7ba8':
        raise PackageError('Unexpected legacy backup overlay version')
    overlay = _private_source(backup_overlay, overlay_sha256)
    files, manifest = _assemble(overlay, privacy_source)
    return _write_package(files, manifest, output)


def _write_package(files, manifest, output):
    destination = Path(output)
    if not destination.is_absolute() or destination.exists() or destination.is_symlink():
        raise PackageError('A new absolute package directory is required')
    destination.mkdir(mode=0o700)
    try:
        for name, data in files.items():
            path = destination / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                view = memoryview(data)
                while view:
                    size = os.write(fd, view)
                    if size <= 0:
                        raise OSError('short write')
                    view = view[size:]
                os.fsync(fd)
            finally:
                os.close(fd)
        path = destination / 'manifest.json'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            raw = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode() + b'\n'
            if os.write(fd, raw) != len(raw):
                raise OSError('short manifest write')
            os.fsync(fd)
        finally:
            os.close(fd)
        for directory in sorted({destination, *(p.parent for p in destination.rglob('*') if p.is_file())},
                                key=lambda p: len(p.parts), reverse=True):
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        return manifest
    except Exception:
        # Preserve any incomplete package for exact owned-path inspection.
        raise PackageError('Guard package creation did not complete') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-source', required=True)
    parser.add_argument('--privacy-source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        manifest = build_package(backup_source=args.backup_source, privacy_source=args.privacy_source,
                                 output=args.output)
        print(json.dumps({'status': 'GUARD_PACKAGE_BUILT', 'file_count': len(manifest['files']),
                          'installed': False, 'boot_verified': False}))
        return 0
    except Exception:
        print(json.dumps({'status': 'GUARD_PACKAGE_FAILED', 'installed': False, 'boot_verified': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
