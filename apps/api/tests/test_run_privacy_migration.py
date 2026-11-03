"""Migration runner stays inert until explicitly executed."""

import importlib
from pathlib import Path


def test_migration_dry_run_has_no_side_effects(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    module = importlib.import_module('run_privacy_migration')
    state = tmp_path / 'state'
    result = module.main(['--env-file', str(tmp_path / 'missing.env'), '--ca-file', str(tmp_path / 'missing.ca'),
                          '--state-dir', str(state), '--backup-bucket', 'synthetic-bucket',
                          '--backup-run-id', 'a' * 32])
    assert result == 0 and not state.exists()
