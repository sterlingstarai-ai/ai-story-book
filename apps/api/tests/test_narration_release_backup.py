"""Verify backup orchestration without connecting to user data or providers."""
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def fixture(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    module = importlib.import_module('narration_release_backup')
    events = []
    state = {'revision': b'5de7a40b6c12', 'journal': 'a' * 64, 'result': 'BACKUP_CREATED_NOT_RESTORE_VERIFIED'}

    class Fence:
        def __init__(self, _env):
            pass

        def __enter__(self):
            events.append('fence_enter')
            return self

        def verify(self):
            events.append('fence_verify')

        def __exit__(self, *_args):
            events.append('fence_exit')

    def checkpoint():
        events.append('journal')
        return {'status': 'CURRENT_OUTBOX_MATCHES_JOURNAL', 'restore_authorized': False,
                'event_count': 1, 'journal_sha256': state['journal']}

    def make_backup(_values, _out, _ca, *, fence):
        assert isinstance(fence, Fence)
        events.append('backup')
        return {'status': state['result'], 'backup_set': 'external-example'}

    def publish(_path, _run_id, _store, *, journal_checkpoint):
        events.append('publish')
        assert journal_checkpoint['journal_sha256'] == 'a' * 64
        return {'status': 'REMOTE_CHECKSUMS_VERIFIED_NOT_RESTORED', 'restore_authorized': False}

    def remote(_run_id, _store, *, expected_revision, expected_journal_checkpoint):
        events.append('remote_verify')
        assert expected_revision == '5de7a40b6c12'
        assert expected_journal_checkpoint['journal_sha256'] == 'a' * 64
        return {'status': 'REMOTE_CHECKSUMS_VERIFIED_NOT_RESTORED', 'restore_authorized': False}

    monkeypatch.setattr(module, 'database_environment', lambda *_: {})
    monkeypatch.setattr(module, 'assert_quiescent', lambda *_: events.append('idle'))
    monkeypatch.setattr(module, 'run_pg', lambda *_: state['revision'])
    monkeypatch.setattr(module, 'PostgresBackupFence', Fence)
    monkeypatch.setattr(module, 'create_backup', make_backup)
    monkeypatch.setattr(module, 'publish_verified_backup', publish)
    monkeypatch.setattr(module, 'verify_remote_backup', remote)
    return module, events, state, checkpoint, tmp_path


def run(fixture, *, journal=None):
    module, _, _, checkpoint, path = fixture
    return module.capture_quiesced_backup(values={}, ca_file=path / 'ca', output_dir=path,
                                           store=object(), verify_journal=journal or checkpoint)


def test_fenced_backup_rechecks_remote_without_authorizing_migration(fixture):
    result = run(fixture)
    assert result['status'] == 'REMOTE_CHECKSUMS_VERIFIED_NOT_RESTORED'
    assert result['migration_authorized'] is False
    assert result['restore_authorized'] is False
    assert fixture[1] == ['idle', 'journal', 'fence_enter', 'fence_verify', 'backup', 'fence_verify', 'journal',
                          'publish', 'remote_verify', 'fence_verify', 'idle', 'journal', 'fence_exit']


def test_wrong_revision_never_creates_backup(fixture):
    fixture[2]['revision'] = b'other'
    with pytest.raises(fixture[0].NarrationBackupError, match='revision'):
        run(fixture)
    assert 'backup' not in fixture[1]
    assert fixture[1][-1] == 'fence_exit'


def test_changed_privacy_checkpoint_never_publishes(fixture):
    _, events, state, checkpoint, _ = fixture

    def changed():
        result = checkpoint()
        if events.count('journal') == 2:
            state['journal'] = 'b' * 64
            result['journal_sha256'] = state['journal']
        return result

    with pytest.raises(fixture[0].NarrationBackupError, match='changed'):
        run(fixture, journal=changed)
    assert 'publish' not in events
    assert events[-1] == 'fence_exit'


def test_incomplete_backup_never_publishes(fixture):
    fixture[2]['result'] = 'INCOMPLETE'
    with pytest.raises(fixture[0].NarrationBackupError, match='creation'):
        run(fixture)
    assert 'publish' not in fixture[1]


def test_remote_recheck_failure_propagates_and_fence_is_released(fixture, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError('synthetic remote checksum failure')

    monkeypatch.setattr(fixture[0], 'verify_remote_backup', broken)
    with pytest.raises(RuntimeError, match='checksum'):
        run(fixture)
    assert fixture[1][-1] == 'fence_exit'


def test_privacy_change_during_publication_fails(fixture):
    _, events, _, checkpoint, _ = fixture

    def changed():
        result = checkpoint()
        if events.count('journal') == 3:
            result['journal_sha256'] = 'b' * 64
        return result

    with pytest.raises(fixture[0].NarrationBackupError, match='changed'):
        run(fixture, journal=changed)
    assert events[-1] == 'fence_exit'


def test_existing_fence_must_match_the_source_database(fixture):
    module, events, _, checkpoint, path = fixture
    fence = type('Fence', (), {'environment': {'PGDATABASE': 'different'}})()
    with pytest.raises(module.NarrationBackupError, match='identities differ'):
        module.capture_quiesced_backup(values={}, ca_file=path / 'ca', output_dir=path,
                                        store=object(), verify_journal=checkpoint, fence=fence)
    assert 'backup' not in events
