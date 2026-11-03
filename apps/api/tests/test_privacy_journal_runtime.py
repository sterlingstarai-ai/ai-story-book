"""Explicit journal configuration is opt-in and fails closed."""

import pytest

from src.core.config import settings
from src.services.privacy_journal import JournalError, PrivacyJournal
from src.services.privacy_journal_runtime import configured_journal


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    for suffix in ('endpoint', 'bucket', 'region', 'access_key', 'secret_key'):
        monkeypatch.setattr(settings, 'privacy_journal_witness_s3_' + suffix, '')
    configured_journal.cache_clear()
    yield
    configured_journal.cache_clear()


def test_disabled_journal_does_not_read_a_key(monkeypatch):
    monkeypatch.setattr(settings, 'privacy_journal_enabled', False)
    monkeypatch.setattr(settings, 'privacy_journal_key_file', '/nonexistent/private-key')
    assert configured_journal() is None


def test_enabled_journal_requires_private_owner_only_32_byte_key(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'privacy_journal_enabled', True)
    monkeypatch.setattr(settings, 'privacy_journal_bucket', 'synthetic-private-bucket')
    path = tmp_path / 'key'
    path.write_bytes(b'k' * 32)
    path.chmod(0o644)
    monkeypatch.setattr(settings, 'privacy_journal_key_file', str(path))
    with pytest.raises(JournalError):
        configured_journal()
    path.chmod(0o600)
    journal = configured_journal()
    assert isinstance(journal, PrivacyJournal)
    journal._store.close()


def test_enabled_journal_refuses_symlink(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'privacy_journal_enabled', True)
    monkeypatch.setattr(settings, 'privacy_journal_bucket', 'synthetic-private-bucket')
    key = tmp_path / 'key'
    key.write_bytes(b'k' * 32)
    key.chmod(0o600)
    path = tmp_path / 'link'
    path.symlink_to(key)
    monkeypatch.setattr(settings, 'privacy_journal_key_file', str(path))
    with pytest.raises(JournalError):
        configured_journal()


def test_witness_is_opt_in_and_must_be_distinct(monkeypatch, tmp_path):
    from src.services.privacy_journal_mirror import MirroredJournalStore

    monkeypatch.setattr(settings, 'privacy_journal_enabled', True)
    monkeypatch.setattr(settings, 'privacy_journal_bucket', 'synthetic-private-bucket')
    key = tmp_path / 'key'
    key.write_bytes(b'k' * 32)
    key.chmod(0o600)
    monkeypatch.setattr(settings, 'privacy_journal_key_file', str(key))
    monkeypatch.setattr(settings, 'privacy_journal_witness_bucket', 'synthetic-private-bucket')
    with pytest.raises(JournalError):
        configured_journal()
    configured_journal.cache_clear()
    monkeypatch.setattr(settings, 'privacy_journal_witness_bucket', 'synthetic-witness-bucket')
    journal = configured_journal()
    assert isinstance(journal._store, MirroredJournalStore)
    journal._store.close()


@pytest.fixture
def s3_witness_config(monkeypatch, tmp_path):
    key = tmp_path / 'key'
    key.write_bytes(b'k' * 32)
    key.chmod(0o600)
    monkeypatch.setattr(settings, 'privacy_journal_enabled', True)
    monkeypatch.setattr(settings, 'privacy_journal_bucket', 'synthetic-primary-bucket')
    monkeypatch.setattr(settings, 'privacy_journal_key_file', str(key))
    monkeypatch.setattr(settings, 'privacy_journal_witness_bucket', '')
    monkeypatch.setattr(settings, 's3_access_key', 'app-access')
    monkeypatch.setattr(settings, 's3_secret_key', 'app-secret')
    values = {'endpoint': 'https://synthetic.example', 'bucket': 'synthetic-witness-bucket',
              'region': 'us-east-1', 'access_key': 'witness-access', 'secret_key': 'witness-secret'}
    for field, value in values.items():
        monkeypatch.setattr(settings, 'privacy_journal_witness_s3_' + field, value)
    return values


@pytest.mark.parametrize('missing', ['endpoint', 'bucket', 'region', 'access_key', 'secret_key'])
def test_partial_s3_witness_configuration_fails_closed(monkeypatch, s3_witness_config, missing):
    monkeypatch.setattr(settings, 'privacy_journal_witness_s3_' + missing, '')
    with pytest.raises(JournalError, match='configuration is invalid'):
        configured_journal()


@pytest.mark.parametrize('endpoint', ['http://example.com', 'https://user:secret@example.com',
                                      'https://@example.com',
                                      'https://example.com/path', 'https://example.com/?key=secret',
                                      'https://example.com/#fragment', 'https://example.com:0',
                                      'https://example.com?', 'https://example.com#'])
def test_s3_witness_requires_clean_https_endpoint(monkeypatch, s3_witness_config, endpoint):
    monkeypatch.setattr(settings, 'privacy_journal_witness_s3_endpoint', endpoint)
    with pytest.raises(JournalError):
        configured_journal()


@pytest.mark.parametrize('shared', ['access_key', 'secret_key'])
def test_s3_witness_refuses_shared_app_credentials(monkeypatch, s3_witness_config, shared):
    monkeypatch.setattr(settings, 'privacy_journal_witness_s3_' + shared, getattr(settings, 's3_' + shared))
    with pytest.raises(JournalError):
        configured_journal()


def test_s3_and_gcs_witness_are_mutually_exclusive(monkeypatch, s3_witness_config):
    monkeypatch.setattr(settings, 'privacy_journal_witness_bucket', 'synthetic-gcs-witness')
    with pytest.raises(JournalError):
        configured_journal()


def test_s3_witness_cannot_share_application_bucket(monkeypatch, s3_witness_config):
    monkeypatch.setattr(settings, 's3_endpoint', 'https://synthetic.example')
    monkeypatch.setattr(settings, 's3_bucket', 'synthetic-witness-bucket')
    with pytest.raises(JournalError):
        configured_journal()


@pytest.mark.parametrize('field,value', [('access_key', 'CHANGE_ME'), ('secret_key', 'placeholder'),
                                         ('access_key', 'contains space')])
def test_placeholder_or_malformed_witness_credentials_are_rejected(monkeypatch, s3_witness_config, field, value):
    monkeypatch.setattr(settings, 'privacy_journal_witness_s3_' + field, value)
    with pytest.raises(JournalError):
        configured_journal()


def test_explicit_s3_witness_wires_and_closes_separate_client(monkeypatch, s3_witness_config):
    from src.services import privacy_journal_runtime as runtime
    from src.services.privacy_journal_mirror import MirroredJournalStore
    from src.services.privacy_journal_s3 import S3ImmutableJournalStore

    calls = []
    class Client:
        closed = False
        def close(self):
            self.closed = True
    client = Client()
    def create(service, **kwargs):
        calls.append((service, kwargs))
        return client
    monkeypatch.setattr(runtime.boto3, 'client', create)
    journal = configured_journal()
    assert isinstance(journal._store, MirroredJournalStore)
    assert isinstance(journal._store._witness, S3ImmutableJournalStore)
    assert calls[0][0] == 's3'
    assert calls[0][1]['endpoint_url'] == 'https://synthetic.example'
    assert calls[0][1]['aws_access_key_id'] == 'witness-access'
    journal._store.close()
    assert client.closed


def test_s3_client_initialization_failure_does_not_expose_secrets(monkeypatch, s3_witness_config):
    from src.services import privacy_journal_runtime as runtime
    def failure(*_args, **_kwargs):
        raise RuntimeError('witness-secret')
    monkeypatch.setattr(runtime.boto3, 'client', failure)
    with pytest.raises(JournalError) as error:
        configured_journal()
    assert 'witness-secret' not in str(error.value)


def test_runtime_mirrors_authenticated_events_and_fails_closed_on_witness_outage(monkeypatch, s3_witness_config):
    import io
    from src.services import privacy_journal_runtime as runtime

    class Primary:
        def __init__(self):
            self.data = {}
        def create(self, name, value):
            if name in self.data:
                raise ValueError('already exists')
            self.data[name] = value
        def read(self, name):
            return self.data[name]
        def list_names(self, prefix):
            return [name for name in self.data if name.startswith(prefix)]
        def close(self):
            pass

    class Witness:
        def __init__(self):
            self.data = {}
            self.offline = False
        def put_object(self, *, Bucket, Key, Body, ContentType, IfNoneMatch):
            assert IfNoneMatch == '*'
            if self.offline or Key in self.data:
                raise ValueError('unavailable or exists')
            self.data[Key] = Body
            return {'ResponseMetadata': {'HTTPStatusCode': 200}}
        def get_object(self, *, Bucket, Key):
            value = self.data[Key]
            return {'ResponseMetadata': {'HTTPStatusCode': 200}, 'ContentLength': len(value),
                    'Body': io.BytesIO(value)}
        def list_objects_v2(self, *, Bucket, Prefix, MaxKeys, **kwargs):
            return {'ResponseMetadata': {'HTTPStatusCode': 200}, 'IsTruncated': False,
                    'Contents': [{'Key': name} for name in self.data if name.startswith(Prefix)]}
        def close(self):
            pass

    primary, witness = Primary(), Witness()
    monkeypatch.setattr(runtime, 'GCSImmutableStore', lambda _bucket: primary)
    monkeypatch.setattr(runtime.boto3, 'client', lambda *_args, **_kwargs: witness)
    journal = configured_journal()
    owner = '00000000-0000-4000-8000-000000000011'
    first = journal.begin('consent_revoke', owner, revision=1)
    journal.commit(first)
    assert primary.data == witness.data
    assert len(journal.scan().committed) == 1 and journal.scan().restore_authorized is False
    witness.offline = True
    with pytest.raises(JournalError):
        journal.begin('account_delete', owner, revision=2)
    with pytest.raises(JournalError):
        journal.scan()
    journal._store.close()


@pytest.mark.asyncio
async def test_request_database_session_attaches_configured_journal(monkeypatch):
    from src.core.database import get_db
    from src.services import privacy_journal_runtime

    sentinel = object()
    monkeypatch.setattr(privacy_journal_runtime, 'configured_journal', lambda: sentinel)
    dependency = get_db()
    session = await dependency.__anext__()
    try:
        assert session.info['privacy_journal'] is sentinel
    finally:
        await dependency.aclose()
