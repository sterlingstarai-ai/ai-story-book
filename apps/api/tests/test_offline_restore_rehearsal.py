import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('run_offline_restore_rehearsal')


def test_build_context_refuses_symlinks_and_excludes_sensitive_suffixes(module, tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'code.py').write_text('pass')
    (source / '.env').write_text('synthetic')
    (source / 'secret.key').write_text('synthetic')
    dest = tmp_path / 'dest'
    module.source_tree(source, dest)
    assert (dest / 'code.py').is_file()
    assert not (dest / '.env').exists()
    assert not (dest / 'secret.key').exists()
    (source / 'link').symlink_to(tmp_path / 'elsewhere')
    with pytest.raises(module.OfflineRehearsalError):
        module.source_tree(source, tmp_path / 'another')


def test_existing_output_image_tag_is_never_removed(module, tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'local_daemon', lambda: None)
    monkeypatch.setattr(module.secrets, 'token_hex', lambda _: 'a' * 32)
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0))
    calls = []
    monkeypatch.setattr(module, 'command', lambda args, **kwargs: calls.append(args))
    assert module.main(['--report-dir', str(tmp_path)]) == 1
    assert calls == []
    report = json.loads(next(tmp_path.glob('*.json')).read_text())
    assert report['status'] == 'FAILED'
    assert report['restore_authorized'] is False
