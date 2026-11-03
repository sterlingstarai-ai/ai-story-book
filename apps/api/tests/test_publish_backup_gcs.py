"""Synthetic provider contract checks; no live bucket or credentials."""

import hashlib
import importlib
import json
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('publish_backup_gcs')


def backup(folder):
    folder.mkdir()
    (folder / 'objects').mkdir()
    key = 'synthetic/image.png'
    filename = 'objects/' + hashlib.sha256(key.encode()).hexdigest()
    (folder / filename).write_bytes(b'synthetic-image')
    (folder / 'database.dump').write_bytes(b'synthetic-database')
    def descriptor(relative):
        data = (folder / relative).read_bytes()
        return {'file': relative, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    manifest = {'format_version': 1, 'database_scope': 'public',
                'requires_latest_deletion_and_identity_revocations': True,
                'database': descriptor('database.dump'), 'objects': [{'key': key, **descriptor(filename)}]}
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    return filename


def test_remote_backup_is_verified_before_last_marker_and_retry_is_safe(module, tmp_path):
    folder = tmp_path / 'backup'
    filename = backup(folder)
    records = {}
    writes = []
    def handler(request):
        if request.method == 'POST':
            assert request.url.params['ifGenerationMatch'] == '0'
            name = request.url.params['name']
            writes.append(name)
            if name in records:
                return httpx.Response(412)
            records[name] = request.read()
            return httpx.Response(200)
        name = unquote(request.url.raw_path.decode().split('/o/', 1)[1].split('?', 1)[0])
        return httpx.Response(200, content=records[name])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        store = module.GCSBackupStore('synthetic-bucket', lambda: 'fixture-token', client)
        result = module.publish_verified_backup(folder, 'a' * 32, store)
        assert result['restore_authorized'] is False and result['object_count'] == 1
        assert writes[-1].endswith('/verified.json')
        assert records['backups/v1/' + 'a' * 32 + '/' + filename] == b'synthetic-image'
        before = dict(records)
        module.publish_verified_backup(folder, 'a' * 32, store)
        assert records == before
        assert module.verify_remote_backup('a' * 32, store)['object_count'] == 1
        records['backups/v1/' + 'a' * 32 + '/' + filename] = b'tampered'
        with pytest.raises(module.BackupPublishError):
            module.verify_remote_backup('a' * 32, store)


def test_bad_remote_data_never_publishes_completion_marker(module, tmp_path):
    folder = tmp_path / 'backup'
    backup(folder)
    writes = []
    def handler(request):
        if request.method == 'POST':
            writes.append(request.url.params['name'])
            return httpx.Response(200)
        return httpx.Response(200, content=b'corrupted')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        store = module.GCSBackupStore('synthetic-bucket', lambda: 'fixture-token', client)
        with pytest.raises(module.BackupPublishError):
            module.publish_verified_backup(folder, 'b' * 32, store)
    assert not any(name.endswith('/verified.json') for name in writes)


def test_empty_database_is_rejected_before_upload_or_remote_verification(module, tmp_path):
    folder = tmp_path / 'backup'
    backup(folder)
    manifest_path = folder / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    (folder / 'database.dump').write_bytes(b'')
    manifest['database'].update(size=0, sha256=hashlib.sha256(b'').hexdigest())
    raw = json.dumps(manifest).encode()
    manifest_path.write_bytes(raw)
    prefix = 'backups/v1/' + 'e' * 32 + '/'
    records = {prefix + 'manifest.json': raw,
               prefix + 'verified.json': json.dumps({'version': 1,
                   'manifest_sha256': hashlib.sha256(raw).hexdigest(),
                   'restore_authorized': False}).encode()}
    writes = []
    def handler(request):
        if request.method == 'POST':
            writes.append(request.url.params['name'])
            return httpx.Response(200)
        name = unquote(request.url.raw_path.decode().split('/o/', 1)[1].split('?', 1)[0])
        return httpx.Response(200, content=records[name])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        store = module.GCSBackupStore('synthetic-bucket', lambda: 'fixture-token', client)
        with pytest.raises(module.BackupPublishError):
            module.publish_verified_backup(folder, 'e' * 32, store)
        assert writes == []
        with pytest.raises(module.BackupPublishError):
            module.verify_remote_backup('e' * 32, store)


def test_remote_checkpoint_must_match_independent_expected_value(module, tmp_path):
    folder = tmp_path / 'backup'
    backup(folder)
    records = {}
    def handler(request):
        if request.method == 'POST':
            records[request.url.params['name']] = request.read()
            return httpx.Response(200)
        name = unquote(request.url.raw_path.decode().split('/o/', 1)[1].split('?', 1)[0])
        return httpx.Response(200, content=records[name])
    checkpoint = {'status': 'CURRENT_OUTBOX_MATCHES_JOURNAL', 'event_count': 2,
                  'journal_sha256': 'a' * 64, 'restore_authorized': False}
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        store = module.GCSBackupStore('synthetic-bucket', lambda: 'fixture-token', client)
        module.publish_verified_backup(folder, 'c' * 32, store, journal_checkpoint=checkpoint)
        assert module.verify_remote_backup('c' * 32, store, expected_journal_checkpoint=checkpoint)[
            'restore_authorized'] is False
        key = 'backups/v1/' + 'c' * 32 + '/verified.json'
        original = json.loads(records[key])
        for mutation in ({'version': True}, {'journal_sha256': 'b' * 64}, {'journal_event_count': True},
                         {'journal_event_count': -1}, {'journal_sha256': None}):
            records[key] = json.dumps({**original, **mutation}).encode()
            with pytest.raises(module.BackupPublishError):
                module.verify_remote_backup('c' * 32, store, expected_journal_checkpoint=checkpoint)
        del original['journal_sha256']
        records[key] = json.dumps(original).encode()
        with pytest.raises(module.BackupPublishError):
            module.verify_remote_backup('c' * 32, store)
        del original['journal_event_count']
        records[key] = json.dumps(original).encode()
        with pytest.raises(module.BackupPublishError):
            module.verify_remote_backup('c' * 32, store, expected_journal_checkpoint=checkpoint)
        # Pre-migration backups with no journal marker remain readable when
        # the caller does not request a separately authenticated checkpoint.
        assert module.verify_remote_backup('c' * 32, store)['restore_authorized'] is False


def test_invalid_checkpoint_fails_before_any_remote_write(module, tmp_path):
    folder = tmp_path / 'backup'
    backup(folder)
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        store = module.GCSBackupStore('synthetic-bucket', lambda: 'fixture-token', client)
        for checkpoint in ({'event_count': 1, 'journal_sha256': 'a' * 64},
                           {'status': 'CURRENT_OUTBOX_MATCHES_JOURNAL', 'event_count': 1,
                            'journal_sha256': 'a' * 64, 'restore_authorized': True}):
            with pytest.raises(module.BackupPublishError):
                module.publish_verified_backup(folder, 'd' * 32, store, journal_checkpoint=checkpoint)
    assert requests == []
