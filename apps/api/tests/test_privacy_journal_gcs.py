"""GCS JSON API contract checks using local in-memory HTTP, not real GCS."""

import importlib
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('src.services.privacy_journal'), importlib.import_module('src.services.privacy_journal_gcs')


def test_encrypted_records_use_create_only_and_roundtrip(modules):
    journal_module, gcs_module = modules
    records = {}

    def handler(request):
        assert request.url.host == 'storage.googleapis.com'
        assert request.headers['authorization'] == 'Bearer synthetic-token'
        if request.method == 'POST':
            assert request.url.params['ifGenerationMatch'] == '0'
            name = request.url.params['name']
            if name in records:
                return httpx.Response(412)
            records[name] = request.content
            return httpx.Response(200, json={})
        if request.url.params.get('alt') == 'media':
            name = unquote(request.url.raw_path.decode().split('/o/', 1)[1].split('?', 1)[0])
            return httpx.Response(200, content=records[name])
        prefix = request.url.params['prefix']
        assert prefix.startswith('privacy-journal/v1/')
        assert request.url.params['fields'] == 'kind,items(name),nextPageToken,prefixes'
        assert request.headers['accept-encoding'] == 'identity'
        return httpx.Response(200, json={'kind': 'storage#objects',
                                         'items': [{'name': name} for name in records if name.startswith(prefix)]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        store = gcs_module.GCSImmutableStore('synthetic-bucket', token_provider=lambda: 'synthetic-token', client=client)
        journal = journal_module.PrivacyJournal(store, b'k' * 32)
        event = journal.begin('account_delete', '00000000-0000-4000-8000-000000000010', revision=1)
        journal.commit(event)
        scan = journal.scan()
        assert scan.pending_count == 0 and len(scan.committed) == 1
        assert scan.restore_authorized is False
        assert all(b'00000000-0000-4000-8000-000000000010' not in value for value in records.values())
        original = dict(records)
        journal.commit(event)
        assert records == original


def test_pagination_failure_or_truncation_does_not_look_empty(modules):
    journal_module, gcs_module = modules

    def handler(request):
        token = request.url.params.get('pageToken')
        if token is None:
            return httpx.Response(200, json={'kind': 'storage#objects', 'items': [], 'nextPageToken': 'page-2'})
        return httpx.Response(200, json={'kind': 'storage#objects', 'items': [], 'nextPageToken': 'page-2'})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        store = gcs_module.GCSImmutableStore('synthetic-bucket', token_provider=lambda: 'token', client=client)
        with pytest.raises(journal_module.JournalError, match='pagination'):
            store.list_names('privacy-journal/v1/')


def test_provider_error_never_exposes_token_or_body(modules):
    journal_module, gcs_module = modules
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(403, text='sensitive-provider-detail'))) as client:
        store = gcs_module.GCSImmutableStore('synthetic-bucket', token_provider=lambda: 'secret-token', client=client)
        with pytest.raises(journal_module.JournalError) as error:
            store.list_names('privacy-journal/v1/')
        assert 'secret-token' not in str(error.value)
        assert 'sensitive-provider-detail' not in str(error.value)


@pytest.mark.parametrize('encoding,body', [
    ('identity', b'x' * 2049),
    ('gzip', b'compressed-untrusted-data'),
])
def test_listing_rejects_oversize_or_encoded_body_without_leaking_it(modules, monkeypatch, encoding, body):
    journal_module, gcs_module = modules
    monkeypatch.setattr(gcs_module, '_MAX_LIST_RESPONSE_BYTES', 2048)
    with httpx.Client(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, headers={'Content-Encoding': encoding}, content=body))) as client:
        store = gcs_module.GCSImmutableStore('synthetic-bucket', token_provider=lambda: 'token', client=client)
        with pytest.raises(journal_module.JournalError) as error:
            store.list_names('privacy-journal/v1/')
        assert 'compressed-untrusted-data' not in str(error.value)


def test_listing_stops_stream_at_size_limit_and_closes_it(modules, monkeypatch):
    journal_module, gcs_module = modules
    monkeypatch.setattr(gcs_module, '_MAX_LIST_RESPONSE_BYTES', 65536)

    class LargeStream(httpx.SyncByteStream):
        def __init__(self):
            self.reads = 0
            self.closed = False

        def __iter__(self):
            for _ in range(10):
                self.reads += 1
                yield b'x' * 65536

        def close(self):
            self.closed = True

    stream = LargeStream()
    with httpx.Client(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, stream=stream))) as client:
        store = gcs_module.GCSImmutableStore('synthetic-bucket', token_provider=lambda: 'token', client=client)
        with pytest.raises(journal_module.JournalError, match='size'):
            store.list_names('privacy-journal/v1/')
    assert stream.reads == 2
    assert stream.closed


@pytest.mark.parametrize('encoding,expected_reads', [('gzip', 0), ('identity', 2)])
def test_record_rejects_encoded_or_oversized_stream_before_more_reads(modules, encoding, expected_reads):
    journal_module, gcs_module = modules

    class UntrustedStream(httpx.SyncByteStream):
        def __init__(self):
            self.reads = 0
            self.closed = False

        def __iter__(self):
            for _ in range(10):
                self.reads += 1
                yield b'x' * 4096

        def close(self):
            self.closed = True

    stream = UntrustedStream()
    def handler(request):
        assert request.headers['accept-encoding'] == 'identity'
        return httpx.Response(200, headers={'Content-Encoding': encoding}, stream=stream)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        store = gcs_module.GCSImmutableStore('synthetic-bucket', token_provider=lambda: 'token', client=client)
        with pytest.raises(journal_module.JournalError):
            store.read('privacy-journal/v1/' + 'a' * 32 + '/intent')
    assert stream.reads == expected_reads
    assert stream.closed


@pytest.mark.parametrize('body', [
    {}, {'kind': 'wrong'}, {'kind': 'storage#objects', 'nextPageToken': None},
    {'kind': 'storage#objects', 'items': None},
    {'kind': 'storage#objects', 'prefixes': ['unexpected/']},
    {'kind': 'storage#objects', 'items': [{'name': 'privacy-journal/v1/unexpected'}]},
])
def test_malformed_list_never_becomes_empty_journal(modules, body):
    journal_module, gcs_module = modules
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
        store = gcs_module.GCSImmutableStore('synthetic-bucket', token_provider=lambda: 'token', client=client)
        with pytest.raises(journal_module.JournalError):
            journal_module.PrivacyJournal(store, b'k' * 32).scan()


def test_documented_empty_list_and_empty_terminal_page_are_valid(modules):
    journal_module, gcs_module = modules
    def handler(request):
        if request.url.params.get('pageToken') is None:
            return httpx.Response(200, json={'kind': 'storage#objects', 'nextPageToken': 'next'})
        return httpx.Response(200, json={'kind': 'storage#objects'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        store = gcs_module.GCSImmutableStore('synthetic-bucket', token_provider=lambda: 'token', client=client)
        scan = journal_module.PrivacyJournal(store, b'k' * 32).scan()
        assert scan.committed == () and scan.pending_count == 0 and scan.restore_authorized is False


def test_duplicate_records_and_unbounded_empty_pages_fail_closed(modules, monkeypatch):
    journal_module, gcs_module = modules
    name = 'privacy-journal/v1/' + 'a' * 32 + '/intent'
    calls = []
    def duplicate(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(200, json={'kind': 'storage#objects',
                'items': [{'name': name}], 'nextPageToken': 'next'})
        return httpx.Response(200, json={'kind': 'storage#objects', 'items': [{'name': name}]})
    with httpx.Client(transport=httpx.MockTransport(duplicate)) as client:
        store = gcs_module.GCSImmutableStore('synthetic-bucket', token_provider=lambda: 'token', client=client)
        with pytest.raises(journal_module.JournalError):
            store.list_names('privacy-journal/v1/')
    monkeypatch.setattr(gcs_module, '_MAX_PAGES', 2)
    calls.clear()
    def infinite(_request):
        calls.append(1)
        return httpx.Response(200, json={'kind': 'storage#objects', 'nextPageToken': str(len(calls))})
    with httpx.Client(transport=httpx.MockTransport(infinite)) as client:
        store = gcs_module.GCSImmutableStore('synthetic-bucket', token_provider=lambda: 'token', client=client)
        with pytest.raises(journal_module.JournalError, match='limit'):
            store.list_names('privacy-journal/v1/')
        assert len(calls) == 2


def test_unresolved_intent_and_malformed_listing_both_block_replay(modules):
    journal_module, gcs_module = modules
    from replay_privacy_journal import ReplayIncomplete, plan_quarantined_replay
    objects = {}
    corrupt = [False]
    def handler(request):
        if request.method == 'POST':
            objects[request.url.params['name']] = request.content
            return httpx.Response(200, json={})
        if request.url.params.get('alt') == 'media':
            name = unquote(request.url.raw_path.decode().split('/o/', 1)[1].split('?', 1)[0])
            return httpx.Response(200, content=objects[name])
        if corrupt[0]:
            return httpx.Response(200, json={})
        prefix = request.url.params['prefix']
        return httpx.Response(200, json={'kind': 'storage#objects',
            'items': [{'name': name} for name in objects if name.startswith(prefix)]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        store = gcs_module.GCSImmutableStore('synthetic-bucket', token_provider=lambda: 'token', client=client)
        journal = journal_module.PrivacyJournal(store, b'k' * 32)
        journal.begin('account_delete', '00000000-0000-4000-8000-000000000010', revision=1)
        with pytest.raises(ReplayIncomplete):
            plan_quarantined_replay(journal.scan())
        corrupt[0] = True
        with pytest.raises(journal_module.JournalError):
            journal.scan()
