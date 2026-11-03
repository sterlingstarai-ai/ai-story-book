"""Test fence ordering and fail-closed evidence without real user data."""
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def context(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    module = importlib.import_module('narration_fenced_backup_probe')
    state = {'active': False, 'journal': 'a' * 64, 'remote': b'manifest', 'probe': True}
    events = []
    folder = tmp_path / 'external-example'
    folder.mkdir()
    (folder / 'manifest.json').write_bytes(b'manifest')

    class Fence:
        def __init__(self, _environment):
            pass

        def __enter__(self):
            state['active'] = True
            return self

        def verify(self):
            assert state['active']
            events.append('verify')

        def __exit__(self, *_):
            state['active'] = False

    class Store:
        def read_small(self, *_):
            return state['remote']

    def checkpoint():
        return {'status': 'CURRENT_OUTBOX_MATCHES_JOURNAL', 'restore_authorized': False,
                'event_count': 1, 'journal_sha256': state['journal']}

    def backup(**kwargs):
        assert state['active'] and isinstance(kwargs['fence'], Fence)
        events.append('backup')
        return {'run_id': 'a' * 32, 'backup_set': folder.name}

    def probe(*_args, **_kwargs):
        assert state['active']
        events.append('restore')
        if not state['probe']:
            raise ValueError('restore failed')
        return {'status': 'OFFLINE_DATABASE_RESTORED', 'revision': module.SOURCE_REVISION,
                'restore_authorized': False, 'migration_authorized': False}

    def remote(*_args, **_kwargs):
        assert state['active']
        events.append('remote')
        return {'status': 'REMOTE_CHECKSUMS_VERIFIED_NOT_RESTORED', 'restore_authorized': False}

    monkeypatch.setattr(module, 'NarrationTransactionFence', Fence)
    monkeypatch.setattr(module, 'database_environment', lambda *_: {})
    monkeypatch.setattr(module, 'assert_quiescent', lambda *_: None)
    monkeypatch.setattr(module, 'capture_quiesced_backup', backup)
    monkeypatch.setattr(module, 'probe_database_archive', probe)
    monkeypatch.setattr(module, 'verify_remote_backup', remote)
    kwargs = dict(values={}, ca_file=tmp_path / 'ca', output_dir=tmp_path,
                  store=Store(), verify_journal=checkpoint, image_id='trusted')
    return module, state, events, kwargs


def test_fence_covers_backup_restore_and_remote_recheck(context):
    module, state, events, kwargs = context
    result = module.capture_and_probe(**kwargs)
    assert events == ['backup', 'restore', 'verify', 'remote', 'verify']
    assert not state['active']
    assert result['restore_authorized'] is False
    assert result['migration_authorized'] is False
    assert result['media_restore_verified'] is False


def test_remote_manifest_mismatch_rejects_before_restore(context):
    module, state, events, kwargs = context
    state['remote'] = b'different'
    with pytest.raises(module.FencedBackupProbeError, match='manifests differ'):
        module.capture_and_probe(**kwargs)
    assert events == ['backup']
    assert not state['active']


def test_context_retains_fence_until_caller_leaves(context):
    module, state, _, kwargs = context
    with module.fenced_backup_probe(**kwargs) as (fence, evidence):
        assert state['active']
        fence.verify()
        assert evidence['migration_authorized'] is False
    assert not state['active']


def test_failed_restore_releases_fence_and_never_rechecks_remote(context):
    module, state, events, kwargs = context
    state['probe'] = False
    with pytest.raises(ValueError, match='restore failed'):
        module.capture_and_probe(**kwargs)
    assert events == ['backup', 'restore']
    assert not state['active']


def test_changed_journal_rejects_after_restore(context, monkeypatch):
    module, state, events, kwargs = context
    original = module.probe_database_archive

    def changed(*args, **probe_kwargs):
        result = original(*args, **probe_kwargs)
        state['journal'] = 'b' * 64
        return result

    monkeypatch.setattr(module, 'probe_database_archive', changed)
    with pytest.raises(module.FencedBackupProbeError, match='journal changed'):
        module.capture_and_probe(**kwargs)
    assert 'remote' not in events
    assert not state['active']
