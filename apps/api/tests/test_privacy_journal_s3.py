import io

import pytest

from src.services.privacy_journal import JournalError, PrivacyJournal
from src.services.privacy_journal_s3 import S3ImmutableJournalStore


class FakeS3:
    def __init__(self):
        self.objects = {}
    def put_object(self, *, Bucket, Key, Body, ContentType, IfNoneMatch):
        assert IfNoneMatch == '*'
        if Key in self.objects:
            raise RuntimeError('precondition failed')
        self.objects[Key] = Body
        return {'ResponseMetadata': {'HTTPStatusCode': 200}}
    def get_object(self, *, Bucket, Key):
        data = self.objects[Key]
        return {'ResponseMetadata': {'HTTPStatusCode': 200}, 'ContentLength': len(data), 'Body': io.BytesIO(data)}
    def list_objects_v2(self, *, Bucket, Prefix, MaxKeys, **kwargs):
        return {'ResponseMetadata': {'HTTPStatusCode': 200}, 'IsTruncated': False,
                'Contents': [{'Key': name} for name in self.objects if name.startswith(Prefix)]}


def test_journal_uses_create_only_s3_and_detects_conflicts():
    client = FakeS3()
    store = S3ImmutableJournalStore(client, 'test-bucket')
    journal = PrivacyJournal(store, b'k' * 32)
    event = journal.begin('consent_revoke', '00000000-0000-4000-8000-000000000001', revision=1)
    journal.commit(event)
    assert len(journal.scan().committed) == 1
    name = next(iter(client.objects))
    original = client.objects[name]
    with pytest.raises(JournalError):
        store.create(name, b'replacement')
    assert client.objects[name] == original


def test_invalid_pagination_and_unexpected_keys_are_rejected():
    client = FakeS3()
    store = S3ImmutableJournalStore(client, 'test-bucket')
    client.list_objects_v2 = lambda **kw: {'ResponseMetadata': {'HTTPStatusCode': 200},
                                           'IsTruncated': True, 'NextContinuationToken': 'same'}
    with pytest.raises(JournalError):
        store.list_names('privacy-journal/v1/')
    client.list_objects_v2 = lambda **kw: {'ResponseMetadata': {'HTTPStatusCode': 200},
                                           'IsTruncated': False, 'Contents': [{'Key': 'privacy-journal/v1/unexpected'}]}
    with pytest.raises(JournalError):
        store.list_names('privacy-journal/v1/')


def test_unbounded_empty_pages_are_rejected(monkeypatch):
    from src.services import privacy_journal_s3 as module
    client = FakeS3()
    pages = []
    def endless(**kwargs):
        pages.append(1)
        return {'ResponseMetadata': {'HTTPStatusCode': 200}, 'IsTruncated': True,
                'NextContinuationToken': str(len(pages))}
    client.list_objects_v2 = endless
    monkeypatch.setattr(module, '_MAX_PAGES', 2)
    with pytest.raises(JournalError, match='limit'):
        S3ImmutableJournalStore(client, 'test-bucket').list_names('privacy-journal/v1/')
    assert len(pages) == 2


def test_empty_last_page_is_valid_but_truncated_without_token_fails():
    client = FakeS3()
    store = S3ImmutableJournalStore(client, 'test-bucket')
    client.list_objects_v2 = lambda **kw: {'ResponseMetadata': {'HTTPStatusCode': 200}, 'IsTruncated': False}
    assert store.list_names('privacy-journal/v1/') == []
    client.list_objects_v2 = lambda **kw: {'ResponseMetadata': {'HTTPStatusCode': 200}, 'IsTruncated': True}
    with pytest.raises(JournalError, match='pagination'):
        store.list_names('privacy-journal/v1/')


@pytest.mark.parametrize('changes', [
    {'KeyCount': 1},
    {'KeyCount': True},
    {'KeyCount': -1},
    {'CommonPrefixes': [{'Prefix': 'privacy-journal/v1/hidden/'}]},
    {'CommonPrefixes': None},
    {'Prefix': 'other/'},
    {'Name': 'other-bucket'},
])
def test_listing_rejects_contradictory_page_metadata(changes):
    client = FakeS3()
    store = S3ImmutableJournalStore(client, 'test-bucket')
    client.list_objects_v2 = lambda **_: {
        'ResponseMetadata': {'HTTPStatusCode': 200}, 'IsTruncated': False,
        **changes,
    }
    with pytest.raises(JournalError, match='listing is invalid'):
        store.list_names('privacy-journal/v1/')


def test_listing_allows_compatible_empty_pages_with_or_without_key_count():
    client = FakeS3()
    store = S3ImmutableJournalStore(client, 'test-bucket')
    for extras in ({}, {'KeyCount': 0, 'CommonPrefixes': [],
                        'Name': 'test-bucket', 'Prefix': 'privacy-journal/v1/'}):
        client.list_objects_v2 = lambda **_: {
            'ResponseMetadata': {'HTTPStatusCode': 200}, 'IsTruncated': False,
            **extras,
        }
        assert store.list_names('privacy-journal/v1/') == []
