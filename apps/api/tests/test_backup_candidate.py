"""Local backup candidate is immutable, pinned, and excludes runtime data."""
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def candidate(monkeypatch, tmp_path):
    scripts = Path(__file__).resolve().parents[3] / 'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    module = importlib.import_module('build_backup_candidate')
    source = tmp_path / 'source'
    for name in (*[f'scripts/{name}' for name in module.SCRIPT_NAMES],
                 *[f'infra/gcp-pilot/{name}' for name in module.UNIT_NAMES],
                 'apps/api/requirements.txt', 'apps/api/scripts/activate_generation_budget.py',
                 'apps/api/src/core/config.py',
                 'apps/api/alembic/versions/example.py'):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture\n')
    (source / 'apps/api/.env').write_text('SECRET=do-not-copy')
    return module, source, tmp_path / 'candidate'


def test_candidate_requires_pin_and_preserves_source_data(candidate):
    module, source, output = candidate
    pin = module.build(source, output)
    assert module.verify(output, pin) > 10
    assert not (output / 'apps/api/.env').exists()
    for name in ('narration_marker_exec_condition.py', 'narration_deploy_safety.py',
                 'provider_rotation_quarantine.py', 'check_backup_status.py', 'publish_backup_health.py'):
        assert (output / 'scripts' / name).is_file()
    for name in ('asb-provider-rotation-quarantine.service',
                 'asb-backup-recover.service.d/provider-order.conf',
                 'asb-backup-watch.service', 'asb-backup-watch.timer',
                 'asb-backup-signal.service', 'asb-backup-signal.timer'):
        assert (output / 'infra/gcp-pilot' / name).is_file()
    assert (output / 'apps/api/scripts/activate_generation_budget.py').is_file()
    assert module.compare_source(source, output, pin) > 10
    (source / 'scripts/automatic_backup.py').write_text('source changed')
    with pytest.raises(module.CandidateError):
        module.compare_source(source, output, pin)
    with pytest.raises(module.CandidateError):
        module.verify(output, '0' * 64)
    with pytest.raises(FileExistsError):
        module.build(source, output)


@pytest.mark.parametrize('change', ['modified', 'missing', 'missing_helper', 'missing_quarantine', 'extra', 'symlink'])
def test_verifier_rejects_changed_candidate(candidate, change):
    module, source, output = candidate
    pin = module.build(source, output)
    target = output / 'scripts/automatic_backup.py'
    if change == 'modified':
        target.write_text('modified')
    elif change == 'missing':
        target.unlink()
    elif change == 'missing_helper':
        (output / 'scripts/narration_marker_exec_condition.py').unlink()
    elif change == 'missing_quarantine':
        (output / 'scripts/provider_rotation_quarantine.py').unlink()
    elif change == 'extra':
        (output / 'unexpected').write_text('extra')
    else:
        target.unlink()
        target.symlink_to(source / 'scripts/automatic_backup.py')
    with pytest.raises(module.CandidateError):
        module.verify(output, pin)
