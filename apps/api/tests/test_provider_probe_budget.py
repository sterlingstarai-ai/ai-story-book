import importlib.util
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    'provider_probe_budget', Path(__file__).resolve().parents[3] / 'scripts/provider_probe_budget.py')
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)


@pytest.fixture
def ledger(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / 'ledger.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE claims (claimed_at INTEGER NOT NULL)')
        db.execute('PRAGMA user_version = 1')
    path.chmod(0o600)
    return path


def test_claim_before_attempt_prevents_retry_and_clock_rollback(ledger):
    assert budget.claim(ledger, now=1_000_000)
    assert not budget.claim(ledger, now=1_000_001)
    with pytest.raises(budget.ProbeBudgetError):
        budget.claim(ledger, now=999_999)
    assert budget.claim(ledger, now=1_064_800)


def test_monthly_cap_and_expiration(ledger):
    for slot in range(41):
        assert budget.claim(ledger, now=1_000_000 + slot * 18 * 3600)
    assert not budget.claim(ledger, now=1_000_000 + 41 * 18 * 3600)
    assert budget.claim(ledger, now=1_000_000 + 31 * 86400)


def test_concurrent_claims_cannot_exceed_limit(ledger):
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: budget.claim(ledger, now=1_000_000), range(8)))
    assert sum(claims) == 1


def test_missing_or_insecure_ledger_fails_closed(ledger):
    ledger.chmod(0o644)
    with pytest.raises(budget.ProbeBudgetError):
        budget.claim(ledger, now=1_000_000)
    ledger.unlink()
    with pytest.raises(budget.ProbeBudgetError):
        budget.claim(ledger, now=1_000_000)
