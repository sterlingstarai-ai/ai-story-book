"""Check effective systemd commands, not just the presence of a pinned drop-in.

Read-only: never installs, reloads, starts or stops services. Later alphabetical
drop-ins can replace ExecStart while leaving a valid ExecStartPre behind.
"""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess


UNITS = {
    'asb-privacy-deploy-recover.service': ('/usr/bin/python3', 'deploy_pilot_privacy.py'),
    'asb-backup-recover.service': ('/usr/bin/python3', 'backup_service_guard.py'),
    'asb-backup.service': (
        '/opt/ai-story-book/current/apps/api/venv/bin/python', 'run_scheduled_backup.py',
    ),
}


class BindingError(ValueError):
    pass


def _commands(value):
    try:
        return [shlex.split(argv.strip()) for argv in re.findall(r'argv\[\]=([^;]+);', value)]
    except ValueError:
        raise BindingError('Effective service command is invalid') from None


def verify_properties(unit, properties, artifact, pin):
    artifact = Path(artifact)
    if (not re.fullmatch(r'[0-9a-f]{64}', pin)
            or artifact != Path('/opt/ai-story-book/ops-releases') / pin or unit not in UNITS):
        raise BindingError('Unknown release or service')
    interpreter, script = UNITS[unit]
    start = _commands(properties.get('ExecStart', ''))
    expected = [interpreter, str(artifact / 'scripts' / script)]
    if len(start) != 1 or start[0][:2] != expected:
        raise BindingError('Effective service does not execute the pinned source')
    if unit != 'asb-backup.service' and start[0][2:] != (
        ['--recover'] if script == 'deploy_pilot_privacy.py'
        else ['--recover', '--state-dir', '/var/lib/ai-story-book/backup-state']
    ):
        raise BindingError('Effective recovery arguments differ')
    verifier = [
        '/usr/bin/python3', str(artifact / 'scripts/build_backup_candidate.py'),
        'verify', '--output', str(artifact), '--manifest-sha256', pin,
    ]
    if verifier not in _commands(properties.get('ExecStartPre', '')):
        raise BindingError('Effective service is missing artifact verification')
    if unit == 'asb-backup.service':
        stop = _commands(properties.get('ExecStopPost', ''))
        if stop != [[
            '/usr/bin/python3', str(artifact / 'scripts/backup_service_guard.py'),
            '--recover', '--state-dir', '/var/lib/ai-story-book/backup-state',
        ]]:
            raise BindingError('Backup completion uses a different recovery source')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', required=True, type=Path)
    parser.add_argument('--manifest-sha256', required=True)
    args = parser.parse_args()
    try:
        for unit in UNITS:
            result = subprocess.run(
                ['systemctl', 'show', unit, '-p', 'ExecStart', '-p', 'ExecStartPre', '-p', 'ExecStopPost'],
                check=True, capture_output=True, text=True, timeout=15,
            )
            properties = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
            verify_properties(unit, properties, args.artifact, args.manifest_sha256)
    except (BindingError, OSError, subprocess.SubprocessError):
        print(json.dumps({'status': 'EFFECTIVE_UNIT_BINDING_FAILED'}))
        return 1
    print(json.dumps({'status': 'EFFECTIVE_UNIT_BINDINGS_VERIFIED', 'units': list(UNITS),
                      'manifest_sha256': args.manifest_sha256}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
