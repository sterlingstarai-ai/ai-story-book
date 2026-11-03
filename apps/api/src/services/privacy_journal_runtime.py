"""Opt-in journal wiring; disabled by default and not a restore approval."""

from functools import lru_cache
import os
import stat
from urllib.parse import urlsplit

import boto3
from botocore.config import Config

from src.core.config import settings
from src.services.privacy_journal import JournalError, PrivacyJournal
from src.services.privacy_journal_gcs import GCSImmutableStore
from src.services.privacy_journal_mirror import MirroredJournalStore
from src.services.privacy_journal_s3 import S3ImmutableJournalStore


def create_s3_witness(*, endpoint, bucket, region, access, secret,
                      app_endpoint, app_bucket, app_access, app_secret, gcs_witness_bucket=''):
    """Create an explicit S3 client; never use ambient credential fallback."""
    values = (endpoint, bucket, region, access, secret)
    if not any(values):
        return None
    if (not all(isinstance(value, str) and value and value == value.strip()
                and not any(ord(char) < 32 or ord(char) == 127 for char in value) for value in values)
            or gcs_witness_bucket or access == app_access or secret == app_secret
            or any(any(char.isspace() for char in value) for value in (access, secret))
            or any(value.lower() in {'change_me', 'changeme', 'replace_me', 'placeholder'}
                   for value in (access, secret))):
        raise ValueError('incomplete or shared witness configuration')
    parsed = urlsplit(endpoint)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.path not in ('', '/') or '?' in endpoint or '#' in endpoint or parsed.port == 0):
        raise ValueError('invalid witness endpoint')
    app_parsed = urlsplit(app_endpoint)
    if parsed.hostname == app_parsed.hostname and bucket == app_bucket:
        raise ValueError('witness must not share the application bucket')
    if (not region.isascii() or len(region) > 64
            or not all(char.isalnum() or char in '-_' for char in region)):
        raise ValueError('invalid witness region')
    client = boto3.client('s3', endpoint_url=endpoint, region_name=region,
        aws_access_key_id=access, aws_secret_access_key=secret,
        config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}, proxies={},
                      connect_timeout=5, read_timeout=15,
                      retries={'mode': 'standard', 'total_max_attempts': 2}))
    try:
        return S3ImmutableJournalStore(client, bucket, owns_client=True)
    except Exception:
        client.close()
        raise


def _configured_s3_witness():
    return create_s3_witness(endpoint=settings.privacy_journal_witness_s3_endpoint,
        bucket=settings.privacy_journal_witness_s3_bucket, region=settings.privacy_journal_witness_s3_region,
        access=settings.privacy_journal_witness_s3_access_key, secret=settings.privacy_journal_witness_s3_secret_key,
        app_endpoint=settings.s3_endpoint, app_bucket=settings.s3_bucket,
        app_access=settings.s3_access_key, app_secret=settings.s3_secret_key,
        gcs_witness_bucket=settings.privacy_journal_witness_bucket)


@lru_cache(maxsize=1)
def configured_journal() -> PrivacyJournal | None:
    if not settings.privacy_journal_enabled:
        return None
    primary = None
    witness = None
    try:
        path = settings.privacy_journal_key_file
        if not path or not os.path.isabs(path):
            raise ValueError('invalid key path')
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ValueError('key file is not private')
            key = os.read(fd, 33)
            if len(key) != 32:
                raise ValueError('invalid key length')
        finally:
            os.close(fd)
        primary = GCSImmutableStore(settings.privacy_journal_bucket)
        witness_bucket = settings.privacy_journal_witness_bucket
        witness = _configured_s3_witness()
        if witness is not None:
            return PrivacyJournal(MirroredJournalStore(primary, witness), key)
        if not witness_bucket:
            return PrivacyJournal(primary, key)
        if witness_bucket == settings.privacy_journal_bucket:
            raise ValueError('witness must use a distinct bucket')
        witness = GCSImmutableStore(witness_bucket)
        return PrivacyJournal(MirroredJournalStore(primary, witness), key)
    except Exception:
        for store in (primary, witness):
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass
        raise JournalError('Privacy journal configuration is invalid') from None
