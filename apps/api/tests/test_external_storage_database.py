"""No-network checks of external PostgreSQL TLS and private S3 configuration."""

import asyncio
import ssl
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from botocore.exceptions import ClientError
import pytest
from sqlalchemy.engine import make_url

from src.core.database_options import database_options
from src.services import storage

REAL_GET_S3_CLIENT = storage.get_s3_client


@pytest.mark.parametrize('asynchronous', [False, True])
def test_sqlite_keeps_local_defaults_even_when_tls_is_configured(asynchronous):
    url, options = database_options('sqlite+aiosqlite:///./test.db', asynchronous=asynchronous,
                                   ssl_mode='verify-full', ssl_root_cert='/not-mounted')
    assert make_url(url).get_backend_name() == 'sqlite'
    assert options == {}


def test_asyncpg_tls_preserves_encoded_credentials_without_forwarding_libpq_keywords():
    raw = 'postgres://postgres.project:p%40ss%25%2Fword@aws-0.pooler.supabase.com:5432/postgres?sslmode=verify-full'
    url, options = database_options(raw, asynchronous=True)
    parsed = make_url(url)
    assert parsed.drivername == 'postgresql+asyncpg'
    assert parsed.password == 'p@ss%/word'
    assert 'sslmode' not in parsed.query
    assert options['ssl'].check_hostname is True
    assert options['ssl'].verify_mode == ssl.CERT_REQUIRED
    sync_url, sync_options = database_options(raw, asynchronous=False)
    assert make_url(sync_url).query['sslmode'] == 'verify-full'
    assert make_url(sync_url).password == parsed.password
    assert sync_options == {}


def test_explicit_ca_is_used_by_both_drivers(monkeypatch):
    ctx = Mock()
    constructor = Mock(return_value=ctx)
    monkeypatch.setattr(ssl, 'create_default_context', constructor)
    raw = 'postgresql+asyncpg://user:secret@db.project.supabase.co:5432/postgres'
    url, options = database_options(raw, asynchronous=True, ssl_mode='verify-full',
                                   ssl_root_cert='/run/storybook-certs/provider.crt')
    constructor.assert_called_once_with(cafile='/run/storybook-certs/provider.crt')
    assert options['ssl'] is ctx
    assert ctx.check_hostname is True
    assert not make_url(url).query
    url, _ = database_options(raw, asynchronous=False, ssl_mode='verify-full',
                              ssl_root_cert='/run/storybook-certs/provider.crt')
    assert make_url(url).query == {'sslmode': 'verify-full', 'sslrootcert': '/run/storybook-certs/provider.crt'}


@pytest.mark.parametrize('overrides', [
    {'ssl_mode': 'disable'}, {'ssl_root_cert': '/different-cert'},
])
def test_conflicting_tls_configuration_fails_without_exposing_credentials(overrides):
    raw = 'postgresql://user:secret-marker@db.host/postgres?sslmode=verify-full&sslrootcert=/original-cert'
    with pytest.raises(ValueError) as error:
        database_options(raw, asynchronous=True, **overrides)
    assert 'secret-marker' not in str(error.value)
    assert 'Conflicting' in str(error.value)


def test_missing_ca_is_not_silently_downgraded():
    with pytest.raises(ValueError, match='CA certificate cannot be loaded'):
        database_options('postgresql://user:secret@db.host/postgres', asynchronous=True,
                         ssl_mode='verify-full', ssl_root_cert='/missing-provider-ca.pem')


@pytest.mark.parametrize('asynchronous', [False, True])
def test_supabase_transaction_pooler_rejected_for_both_drivers(asynchronous):
    with pytest.raises(ValueError, match='transaction pooling is unsupported'):
        database_options('postgresql://user:secret@aws-0.pooler.supabase.com:6543/postgres',
                         asynchronous=asynchronous)


def test_celery_reuses_tls_options_when_rebuilding_its_null_pool(monkeypatch):
    from src.core import database
    from sqlalchemy.pool import NullPool
    context = ssl.create_default_context()
    options = {'echo': False, 'connect_args': {'ssl': context}}
    created = Mock(pool=NullPool(lambda: None))
    factory = Mock(return_value=created)
    session = Mock()
    monkeypatch.setattr(database, '_ASYNC_ENGINE_KWARGS', options)
    monkeypatch.setattr(database, 'async_engine', Mock(pool=object()))
    monkeypatch.setattr(database, 'create_async_engine', factory)
    monkeypatch.setattr(database, 'AsyncSessionLocal', session)
    database.configure_for_worker()
    assert factory.call_args.kwargs['connect_args']['ssl'] is context
    assert factory.call_args.kwargs['poolclass'] is NullPool
    session.configure.assert_called_once_with(bind=created)


def test_upload_and_signing_clients_use_the_same_supabase_region_and_path(monkeypatch):
    monkeypatch.setattr(storage.settings, 's3_region', 'ap-northeast-2')
    monkeypatch.setattr(storage.settings, 's3_addressing_style', 'path')
    constructor = Mock()
    monkeypatch.setattr(storage.boto3, 'client', constructor)
    storage._signing_client.cache_clear()
    REAL_GET_S3_CLIENT()
    storage.media_url(storage.canonical_media_url('books/book/page.png'))
    assert constructor.call_count == 2
    for call in constructor.call_args_list:
        assert call.kwargs['region_name'] == 'ap-northeast-2'
        assert call.kwargs['config'].s3['addressing_style'] == 'path'
        assert call.kwargs['config'].signature_version == 's3v4'
    monkeypatch.setattr(storage.settings, 's3_region', 'eu-west-1')
    storage.media_url(storage.canonical_media_url('books/book/page.png'))
    assert constructor.call_count == 3  # Region is part of the signer cache key.
    storage._signing_client.cache_clear()


def test_presigned_url_uses_project_region_and_preserves_s3_prefix(monkeypatch):
    endpoint = 'https://project.storage.supabase.co/storage/v1/s3'
    for key, value in {'s3_endpoint': endpoint, 's3_download_endpoint': endpoint,
                       's3_public_url': endpoint + '/storybook', 's3_bucket': 'storybook',
                       's3_access_key': 'synthetic-access', 's3_secret_key': 'synthetic-secret',
                       's3_region': 'ap-northeast-2', 's3_addressing_style': 'path'}.items():
        monkeypatch.setattr(storage.settings, key, value)
    storage._signing_client.cache_clear()
    # Boto3 signing is entirely local: no S3 request is made.
    signed = storage.media_url(storage.canonical_media_url('books/id/시우.png'))
    url = urlsplit(signed)
    assert url.path.startswith('/storage/v1/s3/storybook/books/id/')
    assert '/ap-northeast-2/s3/aws4_request' in parse_qs(url.query)['X-Amz-Credential'][0]
    assert storage.key_from_public_url(signed) == 'books/id/시우.png'
    storage._signing_client.cache_clear()


def test_virtual_host_keys_accept_only_the_configured_bucket(monkeypatch):
    monkeypatch.setattr(storage.settings, 's3_addressing_style', 'virtual')
    monkeypatch.setattr(storage.settings, 's3_endpoint', 'https://s3.eu-west-1.amazonaws.com')
    monkeypatch.setattr(storage.settings, 's3_download_endpoint', None)
    monkeypatch.setattr(storage.settings, 's3_bucket', 'storybook')
    assert storage.key_from_public_url('https://storybook.s3.eu-west-1.amazonaws.com/books/id/a.png') == 'books/id/a.png'
    assert storage.key_from_public_url('https://other.s3.eu-west-1.amazonaws.com/books/id/a.png') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('auto_create,code,creates', [(False, '404', False), (True, '403', False), (True, '404', True)])
async def test_external_bucket_is_never_created_and_denial_is_not_mistaken_for_missing(
    monkeypatch, auto_create, code, creates,
):
    client = Mock()
    client.head_bucket.side_effect = ClientError({'Error': {'Code': code, 'Message': 'secret-payload'}}, 'HeadBucket')
    monkeypatch.setattr(storage, 'get_s3_client', lambda: client)
    monkeypatch.setattr(storage, '_bucket_verified', False)
    monkeypatch.setattr(storage, '_bucket_lock', asyncio.Lock())
    monkeypatch.setattr(storage.settings, 's3_auto_create_bucket', auto_create)
    monkeypatch.setattr(storage.settings, 's3_region', 'ap-northeast-2')
    if creates:
        await storage.ensure_bucket_exists()
        client.create_bucket.assert_called_once_with(
            Bucket=storage.settings.s3_bucket,
            CreateBucketConfiguration={'LocationConstraint': 'ap-northeast-2'},
        )
    else:
        with pytest.raises(storage.StorageError) as error:
            await storage.ensure_bucket_exists()
        client.create_bucket.assert_not_called()
        assert 'secret-payload' not in str(error.value)
        assert storage._bucket_verified is False


def test_alembic_direct_url_keeps_percent_credentials_and_shared_tls(monkeypatch):
    from contextlib import nullcontext
    from pathlib import Path
    import runpy
    import sys
    from unittest.mock import MagicMock
    from alembic import context
    import sqlalchemy
    from src.core.config import settings

    raw = 'postgresql+asyncpg://user:p%40ss%25word@db.project.supabase.co:5432/postgres'
    monkeypatch.setattr(settings, 'database_migration_url', raw)
    monkeypatch.setattr(settings, 'database_ssl_mode', 'verify-full')
    monkeypatch.setattr(settings, 'database_ssl_root_cert', '/run/storybook-certs/provider.crt')
    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.setattr(context, 'config', Mock(config_file_name=None), raising=False)
    monkeypatch.setattr(context, 'is_offline_mode', lambda: False)
    configure = Mock()
    monkeypatch.setattr(context, 'configure', configure)
    monkeypatch.setattr(context, 'begin_transaction', nullcontext)
    monkeypatch.setattr(context, 'run_migrations', Mock())
    engine = MagicMock()
    factory = Mock(return_value=engine)
    monkeypatch.setattr(sqlalchemy, 'create_engine', factory)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'alembic/env.py'))
    actual = make_url(factory.call_args.args[0])
    assert actual.password == 'p@ss%word'
    assert actual.host == 'db.project.supabase.co'
    assert actual.query['sslmode'] == 'verify-full'
    assert actual.query['sslrootcert'] == '/run/storybook-certs/provider.crt'
    configure.assert_called_once()
