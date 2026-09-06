"""Never infer bucket privacy from a nonexistent object or a failed signed URL."""
import importlib.util
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def checker(monkeypatch):
    path = Path(__file__).resolve().parents[3] / "scripts/check_bucket_exposure.py"
    spec = importlib.util.spec_from_file_location("bucket_preflight", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_public_url_bases", lambda: ["https://media.example/"])
    monkeypatch.setattr(module, "canonical_media_url", lambda key: f"https://media.example/{key}")
    monkeypatch.setattr(module, "media_url", lambda url: "https://s3.example/bucket/key?signature=secret")
    return module


def test_nonexistent_object_is_inconclusive(checker, monkeypatch, capsys):
    s3 = Mock()
    s3.head_object.side_effect = RuntimeError("NoSuchKey: sensitive-object")
    monkeypatch.setattr(checker, "get_s3_client", lambda: s3)
    client = Mock(side_effect=AssertionError("Do not probe nonexistent media"))
    monkeypatch.setattr(checker.httpx, "Client", client)
    assert checker.verify("https://media.example", "sensitive-object") == 2
    client.assert_not_called()
    assert "sensitive-object" not in capsys.readouterr().out


@pytest.mark.parametrize("statuses,expected", [
    ([206, 403, 404], 0),
    ([206, 200], 1),
    ([403], 2),
    ([206, 302], 2),
])
def test_requires_signed_success_and_both_anonymous_reads_blocked(
    checker, monkeypatch, statuses, expected, capsys,
):
    monkeypatch.setattr(checker, "get_s3_client", Mock())
    responses = iter(statuses)

    @contextmanager
    def stream(*args, **kwargs):
        yield SimpleNamespace(status_code=next(responses))

    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.stream = stream
    monkeypatch.setattr(checker.httpx, "Client", Mock(return_value=client))
    assert checker.verify("https://media.example", "key") == expected
    output = capsys.readouterr().out
    assert "signature=secret" not in output
    if expected != 0:
        assert not output.startswith("PRIVATE:")
