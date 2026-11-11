import importlib.util
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    'recovery_unit_bindings', Path(__file__).resolve().parents[1] / 'verify_pilot_recovery_units.py',
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
PIN = 'a' * 64
ARTIFACT = Path('/opt/ai-story-book/ops-releases') / PIN


def command(argv):
    return '{ path=' + argv[0] + ' ; argv[]=' + ' '.join(argv) + ' ; ignore_errors=no ; }'


def properties():
    return {
        'ExecStart': command(['/usr/bin/python3', str(ARTIFACT / 'scripts/deploy_pilot_privacy.py'), '--recover']),
        'ExecStartPre': command([
            '/usr/bin/python3', str(ARTIFACT / 'scripts/build_backup_candidate.py'),
            'verify', '--output', str(ARTIFACT), '--manifest-sha256', PIN,
        ]),
    }


def test_effective_pinned_recovery_passes():
    module.verify_properties('asb-privacy-deploy-recover.service', properties(), ARTIFACT, PIN)


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
