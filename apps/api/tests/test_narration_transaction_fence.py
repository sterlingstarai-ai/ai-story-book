"""Fail-closed edges of the transaction-scoped migration building block."""
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def fence(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    module = importlib.import_module('narration_transaction_fence')
    return module, module.NarrationTransactionFence({'PGSSLMODE': 'verify-full', 'PGSSLROOTCERT': 'fixture'})


def test_unverified_restore_stops_before_migration(fence):
    module, transaction = fence
    with pytest.raises(module.NarrationFenceError, match='restore'):
        transaction.migrate(assert_backup_restored=lambda: False)


def test_commit_rejected_before_complete_migration(fence):
    module, transaction = fence
    transaction.transaction = SimpleNamespace(is_active=True)
    with pytest.raises(module.NarrationFenceError, match='not active'):
        transaction.commit()


def test_insecure_remote_database_is_rejected(fence):
    module, _ = fence
    with pytest.raises(module.NarrationFenceError, match='TLS'):
        module.NarrationTransactionFence({'PGHOST': 'remote.example', 'PGSSLMODE': 'disable'},
                                        allow_local_fixture=True)
