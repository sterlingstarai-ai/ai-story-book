"""Failure-path tests for the guarded backup cycle using synthetic data."""

from contextlib import contextmanager
import importlib
import json
from pathlib import Path

import pytest

from tests.test_publish_backup_gcs import backup


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('automatic_backup'), importlib.import_module('backup_service_guard')


class Runtime:
    def __init__(self):
        self.states = {'asb-pilot-api': True, 'asb-pilot-worker': True}

    def running(self, name):
        return self.states[name]

    def stop(self, name):
        self.states[name] = False

    def start(self, name):
        self.states[name] = True

    def reload_proxy(self):
        pass

    def verify_recovery(self):
        assert all(self.states.values())


class Store:
    def __init__(self):
        self.writes = []
        self.marker = None

    def put_verified(self, name, path, **kwargs):
        self.writes.append(name)
        if name.endswith('/verified.json'):
            self.marker = json.loads(Path(path).read_text())


def checkpoint(value='a'):
    return {'status': 'CURRENT_OUTBOX_MATCHES_JOURNAL', 'event_count': 1,
            'journal_sha256': value * 64, 'restore_authorized': False}


def test_guarded_cycle_restarts_services_and_leaves_restore_quarantined(modules, tmp_path, monkeypatch):
    automatic, guard_module = modules
    runtime = Runtime()
    guard = guard_module.BackupServiceGuard(tmp_path / 'state', runtime)
    folder = tmp_path / 'external-fixture'
    backup(folder)
    store = Store()
    def idle():
        assert not runtime.running('asb-pilot-api') and runtime.running('asb-pilot-worker')
    def take():
        assert not any(runtime.states.values())
        return {'status': 'BACKUP_CREATED_NOT_RESTORE_VERIFIED', 'backup_set': folder.name}
    ticks = iter(range(0, 100_000_000, 1_000_000))
    monkeypatch.setattr(automatic, 'monotonic_ns', lambda: next(ticks))
    timings = {}
    result = automatic.run_guarded_backup(guard=guard, verify_idle=idle, verify_journal=checkpoint,
        take_backup=take, output_dir=tmp_path, store=store, run_id='a' * 32, timings_ms=timings)
    assert all(runtime.states.values()) and result['restore_authorized'] is False
    assert store.writes[-1].endswith('/verified.json')
    assert store.marker['journal_sha256'] == 'a' * 64 and store.marker['journal_event_count'] == 1
    assert timings == {'guarded_idle': 1, 'privacy_checkpoint': 3, 'capture': 1,
                       'publication': 3, 'guarded_cycle': 13}


def test_changed_journal_prevents_publication_and_restarts_services(modules, tmp_path):
    automatic, guard_module = modules
    runtime = Runtime()
    guard = guard_module.BackupServiceGuard(tmp_path / 'state', runtime)
    folder = tmp_path / 'external-fixture'
    backup(folder)
    states = iter((checkpoint('a'), checkpoint('b')))
    store = Store()
    with pytest.raises(automatic.AutomaticBackupError, match='changed'):
        automatic.run_guarded_backup(guard=guard, verify_idle=lambda: None, verify_journal=lambda: next(states),
            take_backup=lambda: {'status': 'BACKUP_CREATED_NOT_RESTORE_VERIFIED', 'backup_set': folder.name},
            output_dir=tmp_path, store=store, run_id='a' * 32)
    assert all(runtime.states.values()) and store.writes == []


def test_journal_change_during_upload_blocks_unfenced_backup_marker(modules, tmp_path):
    automatic, guard_module = modules
    runtime = Runtime()
    guard = guard_module.BackupServiceGuard(tmp_path / 'state', runtime)
    folder = tmp_path / 'external-fixture'
    backup(folder)
    store = Store()

    def verify():
        assert not any(runtime.states.values())
        return checkpoint('b' if store.writes else 'a')

    publisher = importlib.import_module('publish_backup_gcs')
    with pytest.raises(publisher.BackupPublishError, match='publication failed'):
        automatic.run_guarded_backup(guard=guard, verify_idle=lambda: None, verify_journal=verify,
            take_backup=lambda: {'status': 'BACKUP_CREATED_NOT_RESTORE_VERIFIED', 'backup_set': folder.name},
            output_dir=tmp_path, store=store, run_id='a' * 32)
    assert store.writes[-1].endswith('/manifest.json')
    assert store.marker is None and all(runtime.states.values())


def test_lost_fence_during_upload_prevents_verified_marker(modules, tmp_path):
    automatic, guard_module = modules
    runtime = Runtime()
    guard = guard_module.BackupServiceGuard(tmp_path / 'state', runtime)
    folder = tmp_path / 'external-fixture'
    backup(folder, extra_objects=2)
    store = Store()
    closed = []

    @contextmanager
    def boundary():
        def capture():
            assert not any(runtime.states.values())
            return {'status': 'BACKUP_CREATED_NOT_RESTORE_VERIFIED', 'backup_set': folder.name}

        def verify(result):
            assert store.writes[-1].endswith('/manifest.json')
            assert result['backup_set'] == folder.name
            assert not any(runtime.states.values())
            raise RuntimeError('lost media fence')

        try:
            yield capture, verify
        finally:
            closed.append(True)

    publisher = importlib.import_module('publish_backup_gcs')
    with pytest.raises(publisher.BackupPublishError, match='publication failed'):
        automatic.run_guarded_backup(guard=guard, verify_idle=lambda: None, verify_journal=checkpoint,
            publication_boundary=boundary, output_dir=tmp_path, store=store, run_id='a' * 32,
            media_upload_workers=2)
    assert closed and all(runtime.states.values())
    assert store.marker is None


def test_busy_preflight_avoids_stopping_services(modules, tmp_path):
    automatic, guard_module = modules
    runtime = Runtime()
    guard = guard_module.BackupServiceGuard(tmp_path / 'state', runtime)
    def busy():
        assert all(runtime.states.values())
        raise RuntimeError('worker busy')
    with pytest.raises(RuntimeError, match='worker busy'):
        automatic.run_guarded_backup(guard=guard, verify_idle=lambda: None, preflight_idle=busy,
            verify_journal=checkpoint, take_backup=lambda: None, output_dir=tmp_path,
            store=Store(), run_id='a' * 32)
    assert all(runtime.states.values())
    assert not (tmp_path / 'state' / 'restart-required.json').exists()


def test_idle_preflight_is_rechecked_after_admission_stops(modules, tmp_path):
    automatic, guard_module = modules
    runtime = Runtime()
    guard = guard_module.BackupServiceGuard(tmp_path / 'state', runtime)
    observations = []
    def idle():
        observations.append(runtime.states.copy())
        if not runtime.running('asb-pilot-api'):
            raise RuntimeError('work arrived during preflight')
    with pytest.raises(RuntimeError, match='work arrived'):
        automatic.run_guarded_backup(guard=guard, verify_idle=idle, preflight_idle=idle,
            verify_journal=checkpoint, take_backup=lambda: None, output_dir=tmp_path,
            store=Store(), run_id='a' * 32)
    assert len(observations) == 2
    assert observations[0]['asb-pilot-api'] is True
    assert observations[1]['asb-pilot-api'] is False
    assert all(runtime.states.values())


@pytest.mark.parametrize('failure', ['none', 'before', 'after'])
def test_mixed_journal_must_match_before_and_after_backup(modules, tmp_path, failure):
    from src.services.privacy_journal import JournalError, PrivacyJournal
    from src.services.privacy_journal_mirror import MirroredJournalStore
    from src.services.privacy_journal_outbox import DisposableMemoryJournalStore
    from src.services.privacy_journal_s3 import S3ImmutableJournalStore
    from src.services.privacy_journal_verify import fingerprint_entries
    from tests.test_privacy_journal_s3 import FakeS3

    automatic, guard_module = modules
    runtime = Runtime()
    guard = guard_module.BackupServiceGuard(tmp_path / 'state', runtime)
    folder = tmp_path / 'external-fixture'
    backup(folder)
    primary, client = DisposableMemoryJournalStore(), FakeS3()
    witness = S3ImmutableJournalStore(client, 'synthetic-witness')
    journal = PrivacyJournal(MirroredJournalStore(primary, witness), b'k' * 32)
    event = journal.begin('consent_revoke', '00000000-0000-4000-8000-000000000001', revision=1)
    journal.commit(event)
    commit = f'privacy-journal/v1/{event}/commit'
    if failure == 'before':
        del client.objects[commit]
    def verify():
        scan = journal.scan()
        return {'status': 'CURRENT_OUTBOX_MATCHES_JOURNAL', 'event_count': len(scan.committed),
                'journal_sha256': fingerprint_entries(scan.committed), 'restore_authorized': False}
    def take():
        if failure == 'after':
            del client.objects[commit]
        return {'status': 'BACKUP_CREATED_NOT_RESTORE_VERIFIED', 'backup_set': folder.name}
    store = Store()
    if failure == 'none':
        result = automatic.run_guarded_backup(guard=guard, verify_idle=lambda: None, verify_journal=verify,
            take_backup=take, output_dir=tmp_path, store=store, run_id='a' * 32)
        assert result['restore_authorized'] is False and store.marker is not None
    else:
        with pytest.raises(JournalError):
            automatic.run_guarded_backup(guard=guard, verify_idle=lambda: None, verify_journal=verify,
                take_backup=take, output_dir=tmp_path, store=store, run_id='a' * 32)
        assert store.writes == [] and store.marker is None
    assert all(runtime.states.values())


def test_scheduled_backup_rejects_divergent_live_database(monkeypatch, tmp_path):
    from types import SimpleNamespace

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    scheduler = importlib.import_module('run_scheduled_backup')
    values = {
        'DATABASE_URL': 'postgresql://fixture:secret@pool.example.invalid/storybook?channel_binding=require',
        'DATABASE_MIGRATION_URL': 'postgresql://fixture:secret@direct.example.invalid/storybook?channel_binding=require',
        'DATABASE_SSL_MODE': 'verify-full',
    }
    runtime_env = {role: dict(values) for role in ('asb-pilot-api', 'asb-pilot-worker')}
    runtime = SimpleNamespace(_run=lambda args, **_: json.dumps(
        [f'{key}={value}' for key, value in runtime_env[args[-1]].items()]))
    ca_file = tmp_path / 'ca.pem'
    scheduler.assert_runtime_database_binding(runtime, values, ca_file)
    runtime_env['asb-pilot-worker']['DATABASE_URL'] = values['DATABASE_URL'].replace('/storybook?', '/other?')
    with pytest.raises(scheduler.ScheduledBackupError, match='database settings do not match'):
        scheduler.assert_runtime_database_binding(runtime, values, ca_file)
