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
    'asb-backup-watch.service': ('/usr/bin/python3', 'check_backup_status.py'),
    'asb-backup-signal.service': ('/usr/bin/python3', 'publish_backup_health.py'),
}
MONITORS = ('asb-readiness-signal.service', 'asb-privacy-purge-signal.service',
            'asb-observe-ready.service')
BACKUP_OPTIONS = {'--env-file', '--ca-file', '--journal-key-file', '--journal-bucket',
                  '--journal-witness-bucket', '--backup-bucket', '--state-dir', '--output-dir',
                  '--capture-mode'}


class BindingError(ValueError):
    pass


def parse_properties(raw):
    """Keep every systemctl command record; reject repeated scalar values.

    systemctl emits a separate ExecStartPre= line per command. A last-value
    dictionary would silently discard the first artifact-verification command.
    """
    properties = {}
    commands = {'ExecStart', 'ExecStartPre', 'ExecStopPost'}
    for line in raw.splitlines():
        if '=' not in line:
            continue
        name, value = line.split('=', 1)
        if name in properties:
            if name not in commands:
                raise BindingError('Effective service properties are ambiguous')
            properties[name] += ' ' + value
        else:
            properties[name] = value
    return properties


def _commands(value):
    try:
        return [shlex.split(argv.strip()) for argv in re.findall(r'argv\[\]=([^;]+);', value)]
    except ValueError:
        raise BindingError('Effective service command is invalid') from None


def _verify_capture_mode(arguments, expected):
    if expected not in ('online', 'offline') or not arguments or arguments[0] != '--execute':
        raise BindingError('Effective backup capture mode is invalid')
    fields = arguments[1:]
    options = fields[::2]
    values = fields[1::2]
    if (len(fields) != 2 * len(options) or len(options) != len(set(options))
            or any(option not in BACKUP_OPTIONS for option in options)
            or any(value.startswith('--') for value in values)):
        raise BindingError('Effective backup capture mode or arguments are ambiguous')
    actual = dict(zip(options, values, strict=True)).get('--capture-mode', 'offline')
    if actual not in ('online', 'offline') or actual != expected:
        raise BindingError('Effective backup capture mode differs from the expected mode')


def verify_properties(unit, properties, artifact, pin, *, expected_capture_mode='online'):
    artifact = Path(artifact)
    if (not re.fullmatch(r'[0-9a-f]{64}', pin)
            or artifact != Path('/opt/ai-story-book/ops-releases') / pin or unit not in UNITS):
        raise BindingError('Unknown release or service')
    interpreter, script = UNITS[unit]
    start = _commands(properties.get('ExecStart', ''))
    expected = [interpreter, '-B', str(artifact / 'scripts' / script)]
    if len(start) != 1 or start[0][:3] != expected:
        raise BindingError('Effective service does not execute the pinned source')
    expected_args = {
        'deploy_pilot_privacy.py': ['--recover'],
        'backup_service_guard.py': ['--recover', '--state-dir', '/var/lib/ai-story-book/backup-state'],
        'check_backup_status.py': [],
        'publish_backup_health.py': [],
    }
    if script in expected_args and start[0][3:] != expected_args[script]:
        raise BindingError('Effective recovery arguments differ')
    if unit == 'asb-backup.service':
        _verify_capture_mode(start[0][3:], expected_capture_mode)
    try:
        bytecode_settings = [value.partition('=')[2] for value in shlex.split(properties.get('Environment', ''))
                             if value.partition('=')[0] == 'PYTHONDONTWRITEBYTECODE']
    except ValueError:
        raise BindingError('Effective service environment is invalid') from None
    if bytecode_settings != ['1']:
        raise BindingError('Effective service must disable bytecode writes for child Python processes')
    verifier = [
        '/usr/bin/python3', '-B', str(artifact / 'scripts/build_backup_candidate.py'),
        'verify', '--output', str(artifact), '--manifest-sha256', pin,
    ]
    if verifier not in _commands(properties.get('ExecStartPre', '')):
        raise BindingError('Effective service is missing artifact verification')
    # Checking only ExecStart misses an old unit killing valid cold recovery.
    timeout_property = ({'asb-backup-recover.service': 'TimeoutStartUSec',
                         'asb-backup.service': 'TimeoutStopUSec'}).get(unit)
    if timeout_property and properties.get(timeout_property) != '5min 30s':
        raise BindingError('Effective recovery timeout differs from the bounded release')
    if unit == 'asb-backup.service':
        stop = _commands(properties.get('ExecStopPost', ''))
        if stop != [[
            '/usr/bin/python3', '-B', str(artifact / 'scripts/backup_service_guard.py'),
            '--recover', '--state-dir', '/var/lib/ai-story-book/backup-state',
        ]]:
            raise BindingError('Backup completion uses a different recovery source')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', required=True, type=Path)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--expected-capture-mode', choices=('online', 'offline'), default='online')
    args = parser.parse_args()
    try:
        for unit in UNITS:
            result = subprocess.run(
                ['systemctl', 'show', unit, '-p', 'ExecStart', '-p', 'ExecStartPre', '-p', 'ExecStopPost',
                 '-p', 'TimeoutStartUSec', '-p', 'TimeoutStopUSec', '-p', 'Environment'],
                check=True, capture_output=True, text=True, timeout=15,
            )
            properties = parse_properties(result.stdout)
            verify_properties(unit, properties, args.artifact, args.manifest_sha256,
                              expected_capture_mode=args.expected_capture_mode)
        for unit in MONITORS:
            result = subprocess.run(['systemctl', 'show', unit, '-p', 'After', '--value'],
                                    check=True, capture_output=True, text=True, timeout=15)
            verify_monitor_order(result.stdout)
    except (BindingError, OSError, subprocess.SubprocessError):
        print(json.dumps({'status': 'EFFECTIVE_UNIT_BINDING_FAILED'}))
        return 1
    print(json.dumps({'status': 'EFFECTIVE_UNIT_BINDINGS_VERIFIED', 'units': list(UNITS),
                      'manifest_sha256': args.manifest_sha256, 'boot_monitor_order_verified': True,
                      'expected_capture_mode': args.expected_capture_mode}))
    return 0


def verify_monitor_order(after):
    if 'asb-backup-recover.service' not in after.split():
        raise BindingError('DB monitor can race cold recovery')


if __name__ == '__main__':
    raise SystemExit(main())
