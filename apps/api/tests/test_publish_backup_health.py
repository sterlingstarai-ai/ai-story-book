from datetime import datetime, timezone
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def signal(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('publish_backup_health')


def test_only_an_explicit_clean_check_is_healthy(signal):
    ok = '{"status":"OK","problems":[],"restore_authorized":false}'
    assert signal.measurement(SimpleNamespace(returncode=0, stdout=ok)) == 1
    for result in (SimpleNamespace(returncode=1, stdout=ok),
                   SimpleNamespace(returncode=0, stdout='not json'),
                   SimpleNamespace(returncode=0, stdout='{"status":"OK"}'),
                   SimpleNamespace(returncode=0, stdout='{"status":"OK","problems":["x"],"restore_authorized":false}')):
        assert signal.measurement(result) == 0


def test_signal_contains_only_health_and_fixed_resource(signal):
    value = signal.payload(0, datetime(2026, 11, 2, tzinfo=timezone.utc))['timeSeries'][0]
    assert value['points'][0]['value'] == {'int64Value': '0'}
    assert value['resource']['type'] == 'global'
    with pytest.raises(ValueError):
        signal.payload(True, datetime.now(timezone.utc))
    with pytest.raises(ValueError):
        signal.payload(1, datetime.now())
