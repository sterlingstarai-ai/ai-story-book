"""Read-only validation helpers for a future production provider cutover.

The caller must hold the deployment lock. Passing these checks does not prove
boot ordering, ingress drain, provider health, or authorize any mutation.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat


class GuardError(RuntimeError):
    pass


# A source update requires a new reviewed manifest, not a runtime override.
GUARD_HASHES = {
    'scripts/backup_service_guard.py': 'd5a8f2b2e5ce6f4b0524429300186eed8068ecaf35535f1b8c30e41df36b7ba8',
    'scripts/narration_deploy_safety.py': 'bc318c886086d29e88b556c4ca427b472e5e11203bec887607301b9524c93a91',
    'scripts/provider_recovery_interlock.py': '126d32e70c0b4b1524bec47b0227c0204c18175c1743992cbd744ac48645227f',
    'scripts/provider_rotation_quarantine.py': '9fd22daf6e6e1edaf5716bbac1df20610a0b74f97c08d60ce312c610711e637d',
    'systemd/asb-backup-recover.service.d/provider-order.conf': '7a5b7d6e7b631eeb4d546ca648d5317219690ce87060d7d015e16bf45e358920',
    'systemd/asb-privacy-deploy-recover.service.d/provider-interlock.conf': 'e7d9feabdf8e1582eaa0ae336af0f801ac0b7bbe5445425574aca8d41e481f1f',
    'systemd/asb-provider-rotation-quarantine.service': 'bec333cbd01f488bbacce21dc8cf7cb0033b64947f9cb34198c6f0ba3c4c2cf2',
}


def _verify_file(path: Path, expected: str, *, uid: int) -> None:
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != uid or before.st_nlink != 1
                or before.st_mode & 0o022 or before.st_size > 1024 * 1024):
            raise ValueError()
        digest = hashlib.sha256()
        while True:
            data = os.read(fd, 65536)
            if not data:
                break
            digest.update(data)
        after = os.fstat(fd)
        if (any(getattr(before, field) != getattr(after, field) for field in
                ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))
                or digest.hexdigest() != expected):
            raise ValueError()
    except (OSError, ValueError):
        raise GuardError('A required installed guard is unavailable or differs') from None
    finally:
        if fd is not None:
            os.close(fd)


def verify_installed_guard_files(*, scripts_dir=Path('/opt/ai-story-book/current/scripts'),
                                 systemd_dir=Path('/etc/systemd/system'), uid=0):
    """Validate exact installed bytes and owner; this is not a boot test."""
    scripts_dir, systemd_dir = Path(scripts_dir), Path(systemd_dir)
    for relative, digest in GUARD_HASHES.items():
        category, suffix = relative.split('/', 1)
        root = scripts_dir if category == 'scripts' else systemd_dir
        _verify_file(root / suffix, digest, uid=uid)
    return True


def verify_loaded_units(show):
    """Check supplied `systemctl show` properties for the exact loaded units.

    `show` must query systemd directly on the target host and return a dict; it
    must not print unit environment or arbitrary command output.
    """
    quarantine = show('asb-provider-rotation-quarantine.service')
    privacy = show('asb-privacy-deploy-recover.service')
    backup = show('asb-backup-recover.service')
    expected_unit = 'asb-provider-rotation-quarantine.service'
    if (quarantine.get('LoadState') != 'loaded'
            or quarantine.get('UnitFileState') != 'enabled'
            or quarantine.get('FragmentPath') != '/etc/systemd/system/' + expected_unit
            or quarantine.get('NeedDaemonReload') != 'no'
            or quarantine.get('DropInPaths', '').strip()
            or quarantine.get('KillMode') != 'control-group'
            or 'docker.service' not in quarantine.get('Requires', '').split()
            or 'docker.service' not in quarantine.get('After', '').split()):
        raise GuardError('Provider quarantine is not loaded and enabled')
    for values, service, dropin in (
        (privacy, 'asb-privacy-deploy-recover.service', 'provider-interlock.conf'),
        (backup, 'asb-backup-recover.service', 'provider-order.conf'),
    ):
        expected = '/etc/systemd/system/' + service + '.d/' + dropin
        if (values.get('LoadState') != 'loaded' or values.get('NeedDaemonReload') != 'no'
                or values.get('UnitFileState') != 'enabled'
                or values.get('FragmentPath') != '/etc/systemd/system/' + service
                or values.get('KillMode') != 'control-group'
                or 'docker.service' not in values.get('Requires', '').split()
                or 'docker.service' not in values.get('After', '').split()
                or values.get('DropInPaths', '').split() != [expected]
                or expected_unit not in values.get('After', '').split()
                or expected_unit not in values.get('Wants', '').split()):
            raise GuardError('A recovery service did not load the required guard')
    for values, arguments in (
        (backup, '/usr/bin/python3 /opt/ai-story-book/current/scripts/backup_service_guard.py --recover --state-dir /var/lib/ai-story-book/backup-state'),
        (privacy, '/usr/bin/python3 /opt/ai-story-book/current/scripts/provider_recovery_interlock.py'),
        (quarantine, '/usr/bin/python3 /opt/ai-story-book/current/scripts/provider_rotation_quarantine.py --recover'),
    ):
        parsed = re.findall(r'argv\[\]=([^;}]+)', values.get('ExecStart', ''))
        if len(parsed) != 1 or parsed[0].strip() != arguments:
            raise GuardError('A loaded recovery command differs from the pinned guard')
    return True
