"""The pre-migration exception applies only to one known empty schema state."""

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('bootstrap_privacy_backup')


def test_legacy_check_requires_exact_schema_and_no_active_work(module, monkeypatch):
    def check(responses):
        replies = iter(responses)
        monkeypatch.setattr(module, 'run_pg', lambda *args, **kwargs: next(replies))
        module.assert_legacy_quiescent({}, ['psql'])
    check([b'2a8d9e4f610b', b't', b'0', b'0'])
    for values in ([b'other', b't', b'0', b'0'], [b'2a8d9e4f610b', b'f', b'0', b'0'],
                   [b'2a8d9e4f610b', b't', b'1', b'0'], [b'2a8d9e4f610b', b't', b'0', b'1']):
        with pytest.raises(module.BackupError):
            check(values)
