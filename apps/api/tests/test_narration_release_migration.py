"""Migration invocation and failure boundaries with no real database."""
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def fixture(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    module = importlib.import_module('narration_release_migration')
    ca = tmp_path / 'ca.pem'
    ca.write_text('synthetic CA')
    ca.chmod(0o600)
    values = {'DATABASE_SSL_MODE': 'verify-full', 'DATABASE_URL': 'postgresql://u:fixture@127.0.0.1/example'}
    calls = []
    revisions = [b'5de7a40b6c12', b'f32a7b4d190c']
    monkeypatch.setattr(module, 'database_environment', lambda *_: {})
    monkeypatch.setattr(module, 'assert_quiescent', lambda *_: calls.append('idle'))
    monkeypatch.setattr(module, 'run_pg', lambda *_: revisions.pop(0))

    def invoke(argv, **kwargs):
        calls.append('migrate')
        assert Path(argv[1]).name == 'linux_parent_death_exec.py'
        assert argv[3] == '--'
        assert argv[-2:] == ['upgrade', 'f32a7b4d190c']
        assert 'fixture' not in ' '.join(argv)
        assert kwargs['env']['DATABASE_URL'] == kwargs['env']['DATABASE_MIGRATION_URL']
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, 'run', invoke)
    return module, ca, values, calls, revisions


def test_pinned_migration_requires_repeated_safety_checks(fixture):
    module, ca, values, calls, _ = fixture

    def safe():
        calls.append('safety')
        return True

    result = module.apply_migration(values=values, ca_file=ca, assert_release_safety=safe)
    assert result['revision'] == 'f32a7b4d190c'
    assert result['restore_authorized'] is False
    assert calls == ['safety', 'idle', 'safety', 'migrate', 'safety']


def test_no_migration_when_release_guard_fails(fixture):
    module, ca, values, calls, _ = fixture
    with pytest.raises(module.NarrationMigrationError, match='safety'):
        module.apply_migration(values=values, ca_file=ca, assert_release_safety=lambda: False)
    assert calls == []


def test_wrong_source_revision_does_not_run_alembic(fixture):
    module, ca, values, calls, revisions = fixture
    revisions[0] = b'wrong'
    with pytest.raises(module.NarrationMigrationError, match='source'):
        module.apply_migration(values=values, ca_file=ca, assert_release_safety=lambda: True)
    assert 'migrate' not in calls


def test_incorrect_final_revision_remains_failure(fixture):
    module, ca, values, calls, revisions = fixture
    revisions[1] = b'wrong'
    with pytest.raises(module.NarrationMigrationError, match='final revision'):
        module.apply_migration(values=values, ca_file=ca, assert_release_safety=lambda: True)
    assert 'migrate' in calls


def test_insecure_ca_or_tls_fails_before_alembic(fixture):
    module, ca, values, calls, _ = fixture
    ca.chmod(0o666)
    with pytest.raises(module.NarrationMigrationError, match='TLS'):
        module.apply_migration(values=values, ca_file=ca, assert_release_safety=lambda: True)
    assert 'migrate' not in calls
