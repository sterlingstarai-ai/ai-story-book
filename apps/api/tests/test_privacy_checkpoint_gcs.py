"""Provider contract checks; these mock GCS and do not prove cloud settings."""
from urllib.parse import unquote

import httpx
import pytest

from src.services.privacy_checkpoint_gcs import GCSCheckpointStore
from src.services.privacy_journal import JournalError


def test_checkpoint_create_only_roundtrip_and_conflict():
    objects = {}
    name = 'privacy-checkpoints/v1/' + 'a' * 32 + '/' + '0' * 19 + '1'

    def handler(request):
        assert request.headers['authorization'] == 'Bearer synthetic-token'
        if request.method == 'POST':
            assert request.url.params['ifGenerationMatch'] == '0'
            key = request.url.params['name']
            if key in objects:
                return httpx.Response(412)
            objects[key] = request.content
            return httpx.Response(200)
        key = unquote(request.url.raw_path.decode().split('/o/', 1)[1].split('?', 1)[0])
        return httpx.Response(200, content=objects[key])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        store = GCSCheckpointStore('synthetic-bucket', token_provider=lambda: 'synthetic-token', client=client)
        store.create(name, b'encrypted-blob')
        assert store.read(name) == b'encrypted-blob'
        with pytest.raises(JournalError):
            store.create(name, b'overwrite')
        with pytest.raises(JournalError):
            store.list_names('privacy-checkpoints/v1/')
        with pytest.raises(JournalError):
            store.read('privacy-journal/v1/invalid')


def test_checkpoint_provider_failures_do_not_expose_secrets():
    name = 'privacy-checkpoints/v1/' + 'a' * 32 + '/' + '0' * 19 + '1'
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(403, text='provider-detail'))) as client:
        store = GCSCheckpointStore('synthetic-bucket', token_provider=lambda: 'secret-token', client=client)
        with pytest.raises(JournalError) as error:
            store.read(name)
        assert 'secret-token' not in str(error.value)
        assert 'provider-detail' not in str(error.value)
