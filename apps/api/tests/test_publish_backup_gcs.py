"""Synthetic provider contract checks; no live bucket or credentials."""

import hashlib
import importlib
import json
from contextlib import nullcontext
from pathlib import Path
import tempfile
from threading import Barrier, Lock
from urllib.parse import unquote

import httpx
import pytest


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('publish_backup_gcs')


def backup(folder, *, extra_objects=0):
    folder.mkdir()
    (folder / 'objects').mkdir()
    key = 'synthetic/image.png'
    filename = 'objects/' + hashlib.sha256(key.encode()).hexdigest()
    (folder / filename).write_bytes(b'synthetic-image')
    (folder / 'database.dump').write_bytes(b'synthetic-database')
    def descriptor(relative):
        data = (folder / relative).read_bytes()
        return {'file': relative, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    objects = [{'key': key, **descriptor(filename)}]
    for index in range(extra_objects):
        extra_key = f'synthetic/extra-{index}.png'
        relative = 'objects/' + hashlib.sha256(extra_key.encode()).hexdigest()
        (folder / relative).write_bytes(f'extra-{index}'.encode())
        objects.append({'key': extra_key, **descriptor(relative)})
    manifest = {'format_version': 1, 'database_scope': 'public',
                'requires_latest_deletion_and_identity_revocations': True,
                'database': descriptor('database.dump'), 'objects': objects}
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    return filename


@pytest.mark.parametrize(('status', 'permissions', 'allowed'), [
    (200, ['storage.objects.create', 'storage.objects.get'], True),
    (200, ['storage.objects.create'], False),
    (200, ['storage.objects.get'], False),
    (200, 'malformed', False),
    (403, [], False),
    (404, [], False),
])
def test_destination_preflight_checks_permissions_without_uploading(module, status, permissions, allowed):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.method == 'GET'
        assert request.url.host == 'storage.googleapis.com'
        assert request.url.path == '/storage/v1/b/synthetic-bucket/iam/testPermissions'
        assert request.url.params.get_list('permissions') == ['storage.objects.create', 'storage.objects.get']
        assert request.headers['Authorization'] == 'Bearer fixture-token'
        assert request.content == b''
        return httpx.Response(status, json={'permissions': permissions, 'detail': 'fixture-secret'})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        store = module.GCSBackupStore('synthetic-bucket', lambda: 'fixture-token', client)
        if allowed:
            store.verify_publish_access()
        else:
            with pytest.raises(module.BackupPublishError, match='^Backup destination permissions could not be verified$'):
                store.verify_publish_access()
    assert len(requests) == 1


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


def test_changed_local_completion_marker_is_rejected_before_upload(module, tmp_path, monkeypatch):
    folder = tmp_path / 'backup'
    backup(folder)
    marker_dir = tmp_path / 'marker'
    marker_dir.mkdir()
    monkeypatch.setattr(tempfile, 'TemporaryDirectory', lambda **_: nullcontext(marker_dir))
    records = {}

    def handler(request):
        if request.method == 'POST':
            records[request.url.params['name']] = request.read()
            return httpx.Response(200)
        name = unquote(request.url.raw_path.decode().split('/o/', 1)[1].split('?', 1)[0])
        return httpx.Response(200, content=records[name])

    def change_marker():
        path = marker_dir / 'verified.json'
        marker = path.read_bytes()
        path.write_bytes(marker.replace(b'false', b' true', 1))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        store = module.GCSBackupStore('synthetic-bucket', lambda: 'fixture-token', client)
        with pytest.raises(module.BackupPublishError, match='Local backup changed'):
            module.publish_verified_backup(folder, 'b' * 32, store, verify_before_marker=change_marker)
    assert any(name.endswith('/manifest.json') for name in records)
    assert not any(name.endswith('/verified.json') for name in records)


@pytest.mark.parametrize('corrupt', [None, 'database', 'media'])
def test_dump_and_media_share_bounded_uploads_before_marker(module, tmp_path, corrupt):
    folder = tmp_path / 'backup'
    filename = backup(folder, extra_objects=3)
    records, writes, checked, first_payloads = {}, [], [], []
    lock, first_pair = Lock(), Barrier(2, timeout=5)
    active = peak = started = 0
    gate_ran = False

    def handler(request):
        nonlocal active, peak, started
        if request.method == 'POST':
            name = request.url.params['name']
            assert request.url.params['ifGenerationMatch'] == '0'
            if name.endswith('/verified.json'):
                assert gate_ran
            body = request.read()
            with lock:
                writes.append(name)
                records[name] = body
            return httpx.Response(200)
        name = unquote(request.url.raw_path.decode().split('/o/', 1)[1].split('?', 1)[0])
        if '/objects/' in name or name.endswith('/database.dump'):
            with lock:
                active += 1
                started += 1
                peak = max(peak, active)
                overlap = started <= 2
                if overlap:
                    first_payloads.append(name)
            try:
                if overlap:
                    first_pair.wait()
                if ((corrupt == 'media' and name.endswith('/' + filename))
                        or (corrupt == 'database' and name.endswith('/database.dump'))):
                    return httpx.Response(200, content=b'corrupted')
            finally:
                with lock:
                    active -= 1
        with lock:
            checked.append(name)
            return httpx.Response(200, content=records[name])

    def verify_before_marker():
        nonlocal gate_ran
        assert active == 0
        assert len([name for name in checked if '/objects/' in name]) == 4
        assert any(name.endswith('/database.dump') for name in checked)
        assert writes[-1].endswith('/manifest.json')
        gate_ran = True

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        store = module.GCSBackupStore('synthetic-bucket', lambda: 'fixture-token', client)
        options = dict(verify_before_marker=verify_before_marker, media_upload_workers=2)
        if corrupt:
            with pytest.raises(module.BackupPublishError, match='size|checksum'):
                module.publish_verified_backup(folder, 'b' * 32, store, **options)
            assert not gate_ran
            assert not any(name.endswith(('/manifest.json', '/verified.json')) for name in writes)
        else:
            result = module.publish_verified_backup(folder, 'b' * 32, store, **options)
            assert result['object_count'] == 4 and result['restore_authorized'] is False
            assert writes[-1].endswith('/verified.json')
    assert peak == 2 and active == 0
    assert any(name.endswith('/database.dump') for name in first_payloads)
    assert any('/objects/' in name for name in first_payloads)


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
