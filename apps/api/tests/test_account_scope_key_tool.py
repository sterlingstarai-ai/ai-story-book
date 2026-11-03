"""Synthetic account-scope key enrollment and recovery; no cloud calls."""
import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def tool(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('account_scope_key')


def test_envelope_recovers_only_with_matching_key_and_reference(tool):
    recovery = b'r' * 32
    key, envelope, reference = tool.issue(recovery_key=recovery, namespace='storybook')
    assert tool.recover(recovery_key=recovery, envelope=envelope, reference=reference) == key
    with pytest.raises(Exception):
        tool.recover(recovery_key=b'x' * 32, envelope=envelope, reference=reference)
    with pytest.raises(Exception):
        tool.recover(recovery_key=recovery, envelope=envelope[:-1] + b'x', reference=reference)
    with pytest.raises(Exception):
        tool.recover(recovery_key=recovery, envelope=envelope, reference={**reference, 'namespace': 'other'})


def test_cli_never_overwrites_and_does_not_print_key(tool, tmp_path, capsys):
    tmp_path.chmod(0o700)
    recovery = tmp_path / 'recovery'
    recovery.write_bytes(b'r' * 32)
    recovery.chmod(0o600)
    key, envelope, reference = (tmp_path / name for name in ('key', 'envelope', 'reference'))
    args = ['--recovery-key-file', str(recovery), '--key-output', str(key),
            '--envelope-file', str(envelope), '--reference-file', str(reference)]
    assert tool.main(['issue', *args, '--namespace', 'storybook']) == 0
    assert not key.exists()
    assert tool.main(['issue', *args, '--namespace', 'storybook', '--execute']) == 0
    output = capsys.readouterr().out
    assert key.read_bytes().hex() not in output and 'rrrr' not in output
    assert json.loads(reference.read_bytes())['scope_key_sha256']
    saved = key.read_bytes()
    assert tool.main(['issue', *args, '--namespace', 'storybook', '--execute']) == 1
    assert key.read_bytes() == saved
    restored = tmp_path / 'restored'
    args[args.index(str(key))] = str(restored)
    assert tool.main(['recover', *args, '--execute']) == 0
    assert restored.read_bytes() == saved
