import importlib.util
import json
import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest


SPEC = importlib.util.spec_from_file_location(
    'recovery_unit_bindings', Path(__file__).resolve().parents[1] / 'verify_pilot_recovery_units.py',
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
PIN = 'a' * 64
ARTIFACT = Path('/opt/ai-story-book/ops-releases') / PIN


def test_canonical_backup_unit_selects_online_capture():
    unit = Path(__file__).resolve().parents[2] / 'infra/gcp-pilot/asb-backup.service'
    starts = [line.removeprefix('ExecStart=') for line in unit.read_text().splitlines()
              if line.startswith('ExecStart=')]
    assert len(starts) == 1
    arguments = shlex.split(starts[0])
    runner = '/opt/ai-story-book/current/scripts/run_scheduled_backup.py'
    module._verify_capture_mode(arguments[arguments.index(runner) + 1:], 'online')


def command(argv):
    return '{ path=' + argv[0] + ' ; argv[]=' + ' '.join(argv) + ' ; ignore_errors=no ; }'


def properties():
    return {
        'ExecStart': command(['/usr/bin/python3', '-B', str(ARTIFACT / 'scripts/deploy_pilot_privacy.py'), '--recover']),
        'ExecStartPre': command([
            '/usr/bin/python3', '-B', str(ARTIFACT / 'scripts/build_backup_candidate.py'),
            'verify', '--output', str(ARTIFACT), '--manifest-sha256', PIN,
        ]),
        'Environment': 'PATH=/usr/bin PYTHONDONTWRITEBYTECODE=1',
    }


def test_effective_pinned_recovery_passes():
    module.verify_properties('asb-privacy-deploy-recover.service', properties(), ARTIFACT, PIN)


def test_repeated_precheck_lines_preserve_the_artifact_check_before_the_mode_gate():
    value = properties()
    raw = '\n'.join(name + '=' + content for name, content in value.items())
    raw += '\nExecStartPre=' + command([
        '/usr/bin/python3', '-B', str(ARTIFACT / 'scripts/verify_pilot_recovery_units.py'),
        '--artifact', str(ARTIFACT), '--manifest-sha256', PIN, '--expected-capture-mode', 'online',
    ])
    module.verify_properties('asb-privacy-deploy-recover.service', module.parse_properties(raw), ARTIFACT, PIN)
    assert len(module._commands(module.parse_properties(raw)['ExecStartPre'])) == 2


@pytest.mark.parametrize('name', ['Environment', 'TimeoutStartUSec', 'TimeoutStopUSec'])
def test_repeated_scalar_properties_are_ambiguous_even_when_values_match(name):
    with pytest.raises(module.BindingError, match='ambiguous'):
        module.parse_properties(name + '=same\n' + name + '=same\n')


@pytest.mark.parametrize('stage', ['ExecStart', 'ExecStopPost'])
def test_repeated_execution_lines_cannot_hide_an_unexpected_first_command(stage):
    value = properties()
    unit = 'asb-privacy-deploy-recover.service'
    if stage == 'ExecStopPost':
        unit = 'asb-backup.service'
        value['ExecStart'] = command([module.UNITS[unit][0], '-B',
            str(ARTIFACT / 'scripts/run_scheduled_backup.py'), '--execute', '--capture-mode', 'online'])
        value['TimeoutStopUSec'] = '5min 30s'
        value['ExecStopPost'] = command(['/usr/bin/python3', '-B',
            str(ARTIFACT / 'scripts/backup_service_guard.py'), '--recover',
            '--state-dir', '/var/lib/ai-story-book/backup-state'])
    raw = stage + '=' + command(['/usr/bin/false']) + '\n'
    raw += '\n'.join(name + '=' + content for name, content in value.items())
    with pytest.raises(module.BindingError):
        module.verify_properties(unit, module.parse_properties(raw), ARTIFACT, PIN)


def test_cli_checks_every_repeated_systemctl_precheck_line(monkeypatch, capsys):
    mode_gate = command(['/usr/bin/python3', '-B',
        str(ARTIFACT / 'scripts/verify_pilot_recovery_units.py'), '--artifact', str(ARTIFACT),
        '--manifest-sha256', PIN, '--expected-capture-mode', 'online'])

    def systemctl(argv, **_kwargs):
        unit = argv[2]
        if unit in module.MONITORS:
            return SimpleNamespace(stdout='docker.service asb-backup-recover.service\n')
        interpreter, script = module.UNITS[unit]
        value = properties()
        tail = {'deploy_pilot_privacy.py': ['--recover'],
                'backup_service_guard.py': ['--recover', '--state-dir', '/var/lib/ai-story-book/backup-state'],
                'run_scheduled_backup.py': ['--execute', '--capture-mode', 'online']}.get(script, [])
        value['ExecStart'] = command([interpreter, '-B', str(ARTIFACT / 'scripts' / script), *tail])
        if unit == 'asb-backup-recover.service':
            value['TimeoutStartUSec'] = '5min 30s'
        if unit == 'asb-backup.service':
            value['TimeoutStopUSec'] = '5min 30s'
            value['ExecStopPost'] = command(['/usr/bin/python3', '-B',
                str(ARTIFACT / 'scripts/backup_service_guard.py'), '--recover',
                '--state-dir', '/var/lib/ai-story-book/backup-state'])
        raw = '\n'.join(name + '=' + content for name, content in value.items())
        if unit == 'asb-backup.service':
            raw += '\nExecStartPre=' + mode_gate
        return SimpleNamespace(stdout=raw + '\n')

    monkeypatch.setattr(module.subprocess, 'run', systemctl)
    monkeypatch.setattr('sys.argv', ['verify', '--artifact', str(ARTIFACT), '--manifest-sha256', PIN,
                                   '--expected-capture-mode', 'online'])
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)['expected_capture_mode'] == 'online'
    # Reproduce the old last-value parser against the identical real-world
    # systemctl output: it drops the artifact check and rejects valid units.
    monkeypatch.setattr(module, 'parse_properties', lambda raw: dict(
        line.split('=', 1) for line in raw.splitlines() if '=' in line))
    assert module.main() == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'EFFECTIVE_UNIT_BINDING_FAILED'


def test_later_legacy_override_is_rejected_even_with_a_valid_precheck():
    value = properties()
    value['ExecStart'] = command([
        '/usr/bin/python3', '/opt/ai-story-book/current/scripts/provider_recovery_interlock.py',
    ])
    with pytest.raises(module.BindingError, match='execute the pinned source'):
        module.verify_properties('asb-privacy-deploy-recover.service', value, ARTIFACT, PIN)


@pytest.mark.parametrize('damage', ['other_release', 'missing_precheck', 'different_pin', 'execute'])
def test_drifted_verification_and_recovery_arguments_are_rejected(damage):
    value = properties()
    if damage == 'other_release':
        value['ExecStart'] = value['ExecStart'].replace(str(ARTIFACT), '/opt/ai-story-book/current')
    elif damage == 'missing_precheck':
        value['ExecStartPre'] = ''
    elif damage == 'different_pin':
        value['ExecStartPre'] = value['ExecStartPre'].replace('--manifest-sha256 ' + PIN, '--manifest-sha256 ' + 'b' * 64)
    else:
        value['ExecStart'] = value['ExecStart'].replace('--recover', '--execute')
    with pytest.raises(module.BindingError):
        module.verify_properties('asb-privacy-deploy-recover.service', value, ARTIFACT, PIN)


@pytest.mark.parametrize('timeout', [None, '3min', 'infinity', '5min 30s', '10min'])
def test_effective_cold_recovery_timeout_cannot_be_a_stale_or_unbounded_override(timeout):
    value = properties()
    value['ExecStart'] = command([
        '/usr/bin/python3', '-B', str(ARTIFACT / 'scripts/backup_service_guard.py'),
        '--recover', '--state-dir', '/var/lib/ai-story-book/backup-state',
    ])
    if timeout is not None:
        value['TimeoutStartUSec'] = timeout
    if timeout == '5min 30s':
        module.verify_properties('asb-backup-recover.service', value, ARTIFACT, PIN)
    else:
        with pytest.raises(module.BindingError, match='timeout'):
            module.verify_properties('asb-backup-recover.service', value, ARTIFACT, PIN)


@pytest.mark.parametrize('after', ['docker.service', '', 'network-online.target asb-backup-recover.service'])
def test_db_monitor_cannot_compete_with_cold_recovery(after):
    if 'asb-backup-recover.service' in after:
        module.verify_monitor_order(after)
    else:
        with pytest.raises(module.BindingError, match='race cold recovery'):
            module.verify_monitor_order(after)


@pytest.mark.parametrize('stage', ['ExecStart', 'ExecStartPre'])
def test_missing_bytecode_flag_is_rejected_for_each_pinned_python_command(stage):
    value = properties()
    value[stage] = value[stage].replace(' -B ', ' ')
    with pytest.raises(module.BindingError):
        module.verify_properties('asb-privacy-deploy-recover.service', value, ARTIFACT, PIN)


@pytest.mark.parametrize('environment', ['', 'PYTHONDONTWRITEBYTECODE=0',
                                        'PYTHONDONTWRITEBYTECODE=1 PYTHONDONTWRITEBYTECODE=0',
                                        'PYTHONDONTWRITEBYTECODE='])
def test_missing_or_drifted_bytecode_environment_is_rejected(environment):
    value = properties()
    value['Environment'] = environment
    with pytest.raises(module.BindingError, match='bytecode writes'):
        module.verify_properties('asb-privacy-deploy-recover.service', value, ARTIFACT, PIN)


@pytest.mark.parametrize('unit,script', [
    ('asb-backup-watch.service', 'check_backup_status.py'),
    ('asb-backup-signal.service', 'publish_backup_health.py'),
])
def test_backup_health_uses_the_same_pinned_release_with_bytecode_disabled(unit, script):
    value = properties()
    value['ExecStart'] = command(['/usr/bin/python3', '-B', str(ARTIFACT / 'scripts' / script)])
    module.verify_properties(unit, value, ARTIFACT, PIN)
    value['ExecStart'] = value['ExecStart'].replace(str(ARTIFACT), '/opt/ai-story-book/current')
    with pytest.raises(module.BindingError, match='pinned source'):
        module.verify_properties(unit, value, ARTIFACT, PIN)


@pytest.mark.parametrize('stop_has_bytecode_flag', [True, False])
def test_backup_stop_recovery_disables_bytecode_writes(stop_has_bytecode_flag):
    value = properties()
    value['ExecStart'] = command([
        module.UNITS['asb-backup.service'][0], '-B', str(ARTIFACT / 'scripts/run_scheduled_backup.py'),
        '--execute', '--capture-mode', 'online',
    ])
    value['TimeoutStopUSec'] = '5min 30s'
    stop = ['/usr/bin/python3'] + (['-B'] if stop_has_bytecode_flag else [])
    value['ExecStopPost'] = command(stop + [
        str(ARTIFACT / 'scripts/backup_service_guard.py'),
        '--recover', '--state-dir', '/var/lib/ai-story-book/backup-state',
    ])
    if stop_has_bytecode_flag:
        module.verify_properties('asb-backup.service', value, ARTIFACT, PIN)
    else:
        with pytest.raises(module.BindingError, match='completion uses a different recovery source'):
            module.verify_properties('asb-backup.service', value, ARTIFACT, PIN)


@pytest.mark.parametrize('arguments,expected,passes', [
    (['--execute', '--capture-mode', 'online'], 'online', True),
    (['--execute'], 'online', False),
    (['--execute', '--capture-mode', 'offline'], 'online', False),
    (['--execute'], 'offline', True),
    (['--execute', '--capture-mode', 'offline'], 'offline', True),
    (['--execute', '--capture-mode', 'online'], 'offline', False),
    (['--execute', '--capture-mode', 'unknown'], 'online', False),
    (['--execute', '--capture-mode', 'online', '--capture-mode', 'online'], 'online', False),
    (['--execute', '--capture-mode', 'offline', '--capture-mode', 'online'], 'offline', False),
    (['--execute', '--capture-mode=online'], 'online', False),
    (['--execute', '--capture-mode=offline'], 'offline', False),
    (['--execute', '--capt', 'online'], 'offline', False),
    (['--execute', '--capture-mode', 'online', '--capt', 'offline'], 'online', False),
    (['--execute', '--capture-mode'], 'online', False),
    (['--execute', '--env-file', '--capture-mode'], 'offline', False),
    (['--execute', '--', '--capture-mode', 'online'], 'online', False),
    (['--recover', '--capture-mode', 'online'], 'online', False),
    (['--execute', '--capture-mode', 'online'], 'unknown', False),
])
def test_capture_mode_gate_cannot_silently_select_the_stopping_offline_path(arguments, expected, passes):
    value = properties()
    value['ExecStart'] = command([
        module.UNITS['asb-backup.service'][0], '-B', str(ARTIFACT / 'scripts/run_scheduled_backup.py'),
        *arguments,
    ])
    value['TimeoutStopUSec'] = '5min 30s'
    value['ExecStopPost'] = command([
        '/usr/bin/python3', '-B', str(ARTIFACT / 'scripts/backup_service_guard.py'),
        '--recover', '--state-dir', '/var/lib/ai-story-book/backup-state',
    ])
    if passes:
        module.verify_properties('asb-backup.service', value, ARTIFACT, PIN, expected_capture_mode=expected)
    else:
        with pytest.raises(module.BindingError, match='capture mode'):
            module.verify_properties('asb-backup.service', value, ARTIFACT, PIN, expected_capture_mode=expected)
