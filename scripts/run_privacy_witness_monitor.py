"""Observe a source snapshot against an externally provisioned head reference.

Disabled unless explicitly configured. A match does not prove anchor
independence, newest-head availability or permission to restore.
"""
import argparse
import asyncio
import io
import json
import os
from pathlib import Path
import stat
import sys
import time

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

from run_scheduled_backup import private_file

API = Path(__file__).resolve().parents[1] / 'apps' / 'api'


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    for name in ('env-file', 'ca-file', 'journal-key-file', 'checkpoint-key-file', 'head-key-file', 'trusted-reference-file'):
        parser.add_argument('--' + name, type=Path)
    for name in ('journal-bucket', 'journal-witness-bucket', 'checkpoint-bucket', 'head-bucket'):
        parser.add_argument('--' + name)
    parser.add_argument('--max-age', type=int, default=600)
    return parser.parse_args(argv)


async def check(args):
    required = (args.env_file, args.ca_file, args.journal_key_file, args.checkpoint_key_file,
                args.head_key_file, args.trusted_reference_file, args.journal_bucket,
                args.journal_witness_bucket, args.checkpoint_bucket, args.head_bucket)
    if (not all(required) or len({args.journal_bucket, args.journal_witness_bucket,
                                 args.checkpoint_bucket, args.head_bucket}) != 4
            or not 1 <= args.max_age <= 86400):
        raise ValueError('Incomplete witness settings')
    keys = [private_file(path, max_bytes=32) for path in (
        args.journal_key_file, args.checkpoint_key_file, args.head_key_file)]
    if any(len(key) != 32 for key in keys) or len(set(keys)) != 3:
        raise ValueError('Invalid witness keys')
    reference = json.loads(private_file(args.trusted_reference_file, max_bytes=1024))
    if (not isinstance(reference, dict) or set(reference) != {'version', 'namespace', 'head'}
            or type(reference['version']) is not int or reference['version'] != 1):
        raise ValueError('Invalid witness reference')
    values = dotenv_values(stream=io.StringIO(private_file(args.env_file, max_bytes=1024 * 1024).decode()),
                           interpolate=False)
    raw_url = values.get('DATABASE_MIGRATION_URL') or values.get('DATABASE_URL') or ''
    if values.get('DATABASE_SSL_MODE') != 'verify-full':
        raise ValueError('Verified database TLS is required')
    ca = args.ca_file.lstat()
    if (not stat.S_ISREG(ca.st_mode) or stat.S_ISLNK(ca.st_mode) or ca.st_uid != os.geteuid() or ca.st_mode & 0o022):
        raise ValueError('Invalid CA file')
    if raw_url.startswith('postgres://'):
        raw_url = 'postgresql://' + raw_url[len('postgres://'):]
    url = make_url(raw_url)
    if not url.drivername.startswith('postgresql') or not url.host or not url.database:
        raise ValueError('PostgreSQL source is required')
    # Preserve the same endpoint and database while substituting the trusted CA.
    os.environ['DATABASE_URL'] = url.difference_update_query(['sslrootcert']).render_as_string(hide_password=False)
    os.environ['DATABASE_SSL_MODE'] = 'verify-full'
    os.environ['DATABASE_SSL_ROOT_CERT'] = str(args.ca_file)
    os.environ['TESTING'] = 'false'
    sys.path.insert(0, str(API))
    from src.core.database import AsyncSessionLocal, async_engine
    from src.services.privacy_checkpoint_gcs import GCSCheckpointStore
    from src.services.privacy_journal import PrivacyJournal
    from src.services.privacy_journal_gcs import GCSImmutableStore
    from src.services.privacy_journal_mirror import MirroredJournalStore
    from src.services.privacy_witness_watch import assess_witness

    stores = []
    try:
        stores.append(GCSImmutableStore(args.journal_bucket))
        stores.append(GCSImmutableStore(args.journal_witness_bucket))
        stores.append(GCSCheckpointStore(args.checkpoint_bucket))
        stores.append(GCSCheckpointStore(args.head_bucket))
        journal = PrivacyJournal(MirroredJournalStore(stores[0], stores[1]), keys[0])
        async with AsyncSessionLocal() as db:
            return await assess_witness(db, journal, stores[3], stores[2], namespace=reference['namespace'],
                head_key=keys[2], checkpoint_key=keys[1], trusted_head=reference['head'],
                now=lambda: int(time.time()), max_age=args.max_age)
    finally:
        for store in stores:
            store.close()
        await async_engine.dispose()


def main(argv=None):
    args = arguments(argv)
    if not args.execute:
        print(json.dumps({'status': 'DISABLED', 'restore_authorized': False}))
        return 0
    try:
        result = asyncio.run(check(args))
    except Exception:
        result = {'status': 'ALERT', 'restore_authorized': False}
    print(json.dumps(result, sort_keys=True))
    return 0 if result == {'status': 'SNAPSHOT_MATCHES', 'restore_authorized': False} else 1


if __name__ == '__main__':
    sys.exit(main())
