"""A missing critical file must not be reported as a matching file."""
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def audit(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('audit_narration_candidate_drift')


def test_missing_file_never_counts_as_current(audit, monkeypatch):
    monkeypatch.setattr(audit, 'ensure_local_daemon', lambda: None)
    monkeypatch.setattr(audit, 'checkout_hashes', lambda: {'src/routers/library.py': 'same'})
    monkeypatch.setattr(audit, 'source_hashes', lambda _image: {'src/routers/library.py': 'same'})
    report = {'status': 'LOCAL_CANDIDATES_BUILT', 'images': {
        'api': {'candidate': 'fixture'}, 'worker': {'candidate': 'fixture'}}}
    result = audit.audit(report)
    assert result['sensitive_paths']['src/routers/library.py']['matches_current_checkout'] is True
    receipt = result['sensitive_paths']['alembic/versions/8a34e19c6b72_book_deletion_receipts.py']
    assert receipt['matches_current_checkout'] is False
    assert receipt['present_in_checkout'] is False and receipt['present_in_candidate'] is False
    assert result['production_deployment_authorized'] is False


def test_concurrent_checkout_edit_aborts_audit(audit, monkeypatch):
    monkeypatch.setattr(audit, 'ensure_local_daemon', lambda: None)
    states = iter(({'src/a.py': 'one'}, {'src/a.py': 'two'}))
    monkeypatch.setattr(audit, 'checkout_hashes', lambda: next(states))
    monkeypatch.setattr(audit, 'source_hashes', lambda _image: {})
    report = {'status': 'LOCAL_CANDIDATES_BUILT', 'images': {
        'api': {'candidate': 'fixture'}, 'worker': {'candidate': 'fixture'}}}
    with pytest.raises(RuntimeError, match='changed during comparison'):
        audit.audit(report)
