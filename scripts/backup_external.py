"""Read an authorized, quiesced external DB/private bucket into a private backup set.

Default is a configuration-only dry run. No remote writes, automatic restore,
retention deletion, provider calls, or project .env discovery. Credentials stay
out of command arguments and output. See docs/BACKUP_RESTORE.md before --execute.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
import hashlib
from itertools import islice
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
from urllib.parse import parse_qs, unquote, urlsplit

from dotenv import dotenv_values

from final_external_preflight import external_infrastructure_errors, present


class BackupError(RuntimeError):
    pass


_MAX_INVENTORY_PAGES = 10000


def database_environment(values, ca_file):
    """Pass libpq secrets through a child-only environment, never a URL on argv."""
    url = urlsplit(values.get('DATABASE_MIGRATION_URL') or values['DATABASE_URL'])
    query = parse_qs(url.query, keep_blank_values=True)
    if (set(query) - {'sslmode', 'sslrootcert', 'channel_binding', 'connect_timeout'}
            or any(len(items) != 1 or not items[0] for items in query.values())
            or not url.hostname or ',' in url.hostname):
        raise BackupError('Unsupported database connection options')
    binding = query.get('channel_binding')
    if binding is not None and binding != ['require']:
        raise BackupError('Unsupported database channel binding configuration')
    result = {
        'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
        'PGHOST': url.hostname, 'PGPORT': str(url.port or 5432),
        'PGUSER': unquote(url.username), 'PGPASSWORD': unquote(url.password),
        'PGDATABASE': unquote(url.path.lstrip('/')), 'PGSSLMODE': 'verify-full',
        'PGSSLROOTCERT': str(ca_file), 'PGCONNECT_TIMEOUT': '15',
    }
    if binding:
        result['PGCHANNELBINDING'] = 'require'
    return result


def run_pg(command, environment, *, destination=None):
    try:
        result = subprocess.run(command, env=environment, stdout=destination or subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True, timeout=1800)
        return result.stdout or b''
    except (OSError, subprocess.SubprocessError):
        raise BackupError('PostgreSQL backup/read validation failed; provider details were suppressed') from None


def storage_client(values, *, cut_timeout_seconds=None):
    import boto3
    from botocore.config import Config
    limits = {'connect_timeout': 15, 'read_timeout': 60,
              'retries': {'max_attempts': 2, 'mode': 'standard'}}
    if cut_timeout_seconds is not None:
        if (type(cut_timeout_seconds) not in (int, float) or not math.isfinite(cut_timeout_seconds)
                or not 0 < cut_timeout_seconds <= 2.0):
            raise BackupError('Invalid online inventory timeout')
        timeout = cut_timeout_seconds / 4
        limits = {'connect_timeout': timeout, 'read_timeout': timeout,
                  'retries': {'total_max_attempts': 1, 'mode': 'standard'}}
    return boto3.client('s3', endpoint_url=values['S3_ENDPOINT'],
                        aws_access_key_id=values['S3_ACCESS_KEY'],
                        aws_secret_access_key=values['S3_SECRET_KEY'],
                        region_name=values['S3_REGION'],
                        config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}, **limits))


def inventory(client, bucket):
    objects = {}
    saw_page = False
    awaiting_page = False
    tokens = set()
    pages_seen = 0
    for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket):
        pages_seen += 1
        if pages_seen > _MAX_INVENTORY_PAGES:
            raise BackupError('Media inventory pagination exceeds limit')
        if saw_page and not awaiting_page:
            raise BackupError('Media inventory pagination is invalid')
        saw_page = True
        truncated = page.get('IsTruncated')
        if type(truncated) is not bool:
            raise BackupError('Media inventory pagination is invalid')
        if truncated:
            token = page.get('NextContinuationToken')
            if not isinstance(token, str) or not token or token in tokens:
                raise BackupError('Media inventory pagination is incomplete')
            tokens.add(token)
        awaiting_page = truncated
        contents = page.get('Contents', [])
        if (not isinstance(contents, list)
                or page.get('CommonPrefixes', []) != []
                or ('Name' in page and page['Name'] != bucket)
                or ('KeyCount' in page and (type(page['KeyCount']) is not int
                                             or page['KeyCount'] != len(contents)))
                or any(not isinstance(item, dict) or not isinstance(item.get('Key'), str)
                       or not item['Key'] for item in contents)):
            raise BackupError('Media inventory page is invalid')
        for item in contents:
            key = item['Key']
            if key in objects:
                raise BackupError('Object inventory changed while listing; retry in a quiesced window')
            objects[key] = {name: str(item.get(name, '')) for name in ('ETag', 'Size', 'LastModified')}
    if not saw_page or awaiting_page:
        raise BackupError('Media inventory pagination is incomplete')
    return objects


def _http_last_modified(value):
    try:
        stamp = datetime.fromisoformat(str(value))
        if stamp.tzinfo is None:
            raise ValueError
        return stamp.astimezone(timezone.utc).replace(microsecond=0)
    except ValueError:
        raise BackupError('Media modification time is invalid') from None


def inventory_fingerprint(objects):
    payload = json.dumps(objects, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(payload).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for data in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


def assert_quiescent(environment, query):
    # A single statement checks all queues against one snapshot and avoids
    # opening separate TLS sessions or counting every outstanding row.
    state = run_pg(query + ["""SELECT CASE
        WHEN EXISTS (SELECT 1 FROM public.jobs
                     WHERE status IS NULL OR status NOT IN ('done','failed','cancelled'))
            THEN 'active_jobs'
        WHEN EXISTS (SELECT 1 FROM public.storage_purge_tasks
                     WHERE status IS NULL OR status NOT IN ('done','cancelled'))
            THEN 'pending_purges'
        WHEN EXISTS (SELECT 1 FROM public.privacy_journal_outbox WHERE published_at IS NULL)
            THEN 'pending_journal'
        ELSE 'idle' END"""], environment).strip()
    if state != b'idle':
        reasons = {
            b'active_jobs': 'Pending or unknown generation jobs remain',
            b'pending_purges': 'Unfinished or unknown storage deletion tasks remain',
            b'pending_journal': 'Unpublished privacy events remain',
        }
        raise BackupError(reasons.get(state, 'Database quiescence could not be verified'))


def transaction_snapshot(environment, query):
    """Detect intervening DB transactions; this does not replace write quiescence."""
    snapshot = run_pg(query + ['SELECT txid_current_snapshot()::text'], environment).strip()
    if not re.fullmatch(rb'\d+:\d+:[\d,]*', snapshot):
        raise BackupError('Database transaction snapshot could not be verified')
    return snapshot


def verify_database_backup_tools(environment, query):
    """Check the read-only connection and matching libpq tools before capture."""
    version = run_pg(query + ['SHOW server_version_num'], environment).strip()
    if not version.isdigit() or int(version) < 100000:
        raise BackupError('Unsupported or unknown PostgreSQL server version')
    server_major = int(version) // 10000
    for tool in ('pg_dump', 'pg_restore'):
        output = run_pg([tool, '--version'], environment)
        match = re.fullmatch(rb'pg_(?:dump|restore) \(PostgreSQL\) (\d+)(?:\.\d+)*(?:[^\r\n]*)?[\r\n]*', output)
        if not match or int(match.group(1)) != server_major:
            raise BackupError('PostgreSQL backup tools must match the server major version')


def _download_media_object(client, bucket, objects_dir, entry):
    key, expected = entry
    if not expected['ETag'] or not expected['LastModified'] or not expected['Size'].isdigit():
        raise BackupError('Media inventory is missing object identity metadata')
    expected_size = int(expected['Size'])
    filename = hashlib.sha256(key.encode()).hexdigest()
    path = objects_dir / filename  # Never interpret remote object keys as local paths.
    version = ({'Generation': expected['generation'], 'Metageneration': expected['metageneration']}
               if 'generation' in expected else {})
    obj = client.get_object(Bucket=bucket, Key=key, IfMatch=expected['ETag'], **version)
    size = 0
    digest = hashlib.sha256()
    try:
        if (obj.get('ETag') != expected['ETag']
                or _http_last_modified(obj.get('LastModified')) != _http_last_modified(expected['LastModified'])
                or obj.get('ContentLength') != expected_size):
            raise BackupError('Media object identity changed before download')
        if version and any(obj.get(name) != value for name, value in version.items()):
            raise BackupError('Media object version changed before download')
        with path.open('xb') as output:
            os.chmod(path, 0o600)
            for data in iter(lambda: obj['Body'].read(1024 * 1024), b''):
                size += len(data)
                if size > expected_size:
                    raise BackupError('Media object exceeded its listed size')
                digest.update(data)
                output.write(data)
    finally:
        obj['Body'].close()
    if size != expected_size:
        raise BackupError('Media changed or was truncated during backup')
    return {'key': key, 'file': f'objects/{filename}', 'sha256': digest.hexdigest(),
            'size': size, 'content_type': obj.get('ContentType', 'application/octet-stream'),
            'metadata': obj.get('Metadata', {}), 'cache_control': obj.get('CacheControl'),
            'content_disposition': obj.get('ContentDisposition'), 'content_encoding': obj.get('ContentEncoding')}


def _download_media(client, bucket, objects_dir, objects, workers):
    download = partial(_download_media_object, client, bucket, objects_dir)
    entries = sorted(objects.items())
    if workers == 1 or len(entries) < 2:
        return [download(entry) for entry in entries]

    media = []
    remaining = iter(entries)
    # The client was created on the caller's thread. Bound outstanding reads
    # and wait for them before closing it or removing the partial directory.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while batch := list(islice(remaining, workers)):
            media.extend(pool.map(download, batch))
    return media


def create_backup(values, destination, ca_file, *, quiescence_check=None, fence=None, media_download_workers=1):
    """Only called after CLI authorization; all remote methods here are read-only."""
    if quiescence_check is None:
        quiescence_check = assert_quiescent
    if type(media_download_workers) is not int or media_download_workers not in (1, 2):
        raise BackupError('Invalid media download worker count')
    if not ca_file.is_file():
        raise BackupError('Provider CA file is not readable on this backup host')
    environment = database_environment(values, ca_file)
    if fence is not None and fence.environment != environment:
        raise BackupError('Backup and fence database identities differ')
    query = ['psql', '-X', '--no-password', '--tuples-only', '--no-align', '--set', 'ON_ERROR_STOP=1', '-c']
    verify_database_backup_tools(environment, query)
    quiescence_check(environment, query)
    if fence is None:
        transaction_baseline = transaction_snapshot(environment, query)
    else:
        fence.verify()
        transaction_baseline = None
    revision = run_pg(query + ['SELECT version_num FROM public.alembic_version ORDER BY version_num'], environment).decode().strip()
    if not revision:
        raise BackupError('Alembic revision is missing')
    if destination.exists() and (destination.is_symlink() or destination.stat().st_mode & 0o077):
        raise BackupError('Backup destination must be a private directory (0700), without a symlink')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder = Path(tempfile.mkdtemp(prefix='.partial-external-', dir=destination))
    final = destination / folder.name.replace('.partial-external-', 'external-', 1)
    client = None
    try:
        objects_dir = folder / 'objects'
        objects_dir.mkdir(mode=0o700)
        client = storage_client(values)
        bucket = values['S3_BUCKET']
        before = inventory(client, bucket)
        dump = folder / 'database.dump'
        with dump.open('xb') as output:
            os.chmod(dump, 0o600)
            # Only application/public data, not Supabase's managed auth/storage schemas.
            dump_command = ['pg_dump', '--no-password', '--format=custom', '--schema=public',
                            '--no-owner', '--no-privileges']
            if fence is not None:
                dump_command.extend(['--snapshot', fence.snapshot_id])
            run_pg(dump_command, environment, destination=output)
        run_pg(['pg_restore', '--list', str(dump)], environment)
        media = _download_media(client, bucket, objects_dir, before, media_download_workers)
        if inventory(client, bucket) != before:
            raise BackupError('Media inventory changed during backup; no complete set will be published')
        quiescence_check(environment, query)
        if fence is not None:
            fence.verify()
        elif transaction_snapshot(environment, query) != transaction_baseline:
            raise BackupError('Database transaction state changed during backup; no complete set will be published')
        manifest = {'format_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
                    'database_scope': 'public', 'alembic_revision': revision,
                    'database': {'file': 'database.dump', 'sha256': file_hash(dump), 'size': dump.stat().st_size},
                    'api_image': values['API_IMAGE'], 'worker_image': values['WORKER_IMAGE'],
                    'objects': media, 'restore_verified': False,
                    'requires_latest_deletion_and_identity_revocations': True}
        path = folder / 'manifest.json'
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        os.chmod(path, 0o600)
        folder.rename(final)
        return {'status': 'BACKUP_CREATED_NOT_RESTORE_VERIFIED', 'object_count': len(media),
                'backup_set': final.name, 'contains_private_data': True,
                'media_inventory_sha256': inventory_fingerprint(before)}
    except BaseException:
        shutil.rmtree(folder, ignore_errors=False)
        raise
    finally:
        if client is not None:
            client.close()


def create_online_backup(values, destination, ca_file, *, snapshot, frozen_inventory,
                         frozen_revision, media_download_workers=2, media_client=None):
    """Capture the supplied cut, allowing unrelated live DB/media changes.

    The caller must obtain revision and inventory from the same fenced cut,
    verify media-reference coverage and independently verify its privacy
    checkpoint. An object's deletion or changed identity fails this backup;
    this function never stops services, retries the cut, or authorizes restore.
    """
    if type(media_download_workers) is not int or media_download_workers not in (1, 2):
        raise BackupError('Invalid media download worker count')
    if not ca_file.is_file():
        raise BackupError('Provider CA file is not readable on this backup host')
    environment = database_environment(values, ca_file)
    if (snapshot.environment != environment or snapshot.cut_released is not True
            or not isinstance(snapshot.snapshot_id, str)
            or not re.fullmatch('[0-9A-Fa-f-]{1,80}', snapshot.snapshot_id)
            or type(snapshot.cut_elapsed_ms) is not int or not 0 <= snapshot.cut_elapsed_ms <= 2000):
        raise BackupError('Online backup snapshot is not the released database cut')
    if not isinstance(frozen_revision, str) or not re.fullmatch('[A-Za-z0-9_]{1,100}', frozen_revision):
        raise BackupError('Online backup schema revision is invalid')
    if not isinstance(frozen_inventory, dict):
        raise BackupError('Online backup inventory is invalid')
    objects = {}
    for key, metadata in frozen_inventory.items():
        if (not isinstance(key, str) or not key or not isinstance(metadata, dict)
                or set(metadata) not in ({'ETag', 'Size', 'LastModified'},
                                        {'ETag', 'Size', 'LastModified', 'generation', 'metageneration'})
                or any(not isinstance(value, str) or not value for value in metadata.values())
                or not re.fullmatch('[0-9]{1,20}', metadata['Size'])):
            raise BackupError('Online backup inventory is invalid')
        if 'generation' in metadata and any(
                re.fullmatch('[1-9][0-9]{0,19}', metadata[name]) is None
                for name in ('generation', 'metageneration')):
            raise BackupError('Online backup object version is invalid')
        _http_last_modified(metadata['LastModified'])
        objects[key] = dict(metadata)
    snapshot_id = snapshot.snapshot_id
    snapshot_metadata = {'snapshot_sha256': hashlib.sha256(snapshot_id.encode()).hexdigest(),
                         'cut_elapsed_ms': snapshot.cut_elapsed_ms, 'cut_released': True}
    snapshot.verify()
    query = ['psql', '-X', '--no-password', '--tuples-only', '--no-align', '--set', 'ON_ERROR_STOP=1', '-c']
    verify_database_backup_tools(environment, query)
    if destination.exists() and (destination.is_symlink() or destination.stat().st_mode & 0o077):
        raise BackupError('Backup destination must be a private directory (0700), without a symlink')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder = Path(tempfile.mkdtemp(prefix='.partial-external-', dir=destination))
    final = destination / folder.name.replace('.partial-external-', 'external-', 1)
    client = media_client
    owns_client = media_client is None
    try:
        objects_dir = folder / 'objects'
        objects_dir.mkdir(mode=0o700)
        dump = folder / 'database.dump'
        with dump.open('xb') as output:
            os.chmod(dump, 0o600)
            run_pg(['pg_dump', '--no-password', '--format=custom', '--schema=public',
                    '--no-owner', '--no-privileges', '--snapshot', snapshot_id], environment, destination=output)
        run_pg(['pg_restore', '--list', str(dump)], environment)
        snapshot.verify()
        if snapshot.snapshot_id != snapshot_id or snapshot.cut_released is not True:
            raise BackupError('Online backup snapshot changed')
        if client is None:
            client = storage_client(values)
        media = _download_media(client, values['S3_BUCKET'], objects_dir, objects, media_download_workers)
        snapshot.verify()
        if snapshot.snapshot_id != snapshot_id or snapshot.cut_released is not True:
            raise BackupError('Online backup snapshot changed')
        manifest = {'format_version': 1, 'capture_mode': 'online_snapshot',
                    'snapshot': snapshot_metadata,
                    'media_inventory_sha256': inventory_fingerprint(objects),
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'database_scope': 'public', 'alembic_revision': frozen_revision,
                    'database': {'file': 'database.dump', 'sha256': file_hash(dump), 'size': dump.stat().st_size},
                    'api_image': values['API_IMAGE'], 'worker_image': values['WORKER_IMAGE'],
                    'objects': media, 'restore_verified': False,
                    'requires_latest_deletion_and_identity_revocations': True}
        path = folder / 'manifest.json'
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        os.chmod(path, 0o600)
        folder.rename(final)
        return {'status': 'BACKUP_CREATED_NOT_RESTORE_VERIFIED', 'capture_mode': 'online_snapshot',
                'snapshot': snapshot_metadata, 'object_count': len(media), 'backup_set': final.name,
                'contains_private_data': True, 'media_inventory_sha256': inventory_fingerprint(objects)}
    except BaseException:
        shutil.rmtree(folder, ignore_errors=False)
        raise
    finally:
        if client is not None and owns_client:
            client.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='Private directory on the approved encrypted backup destination')
    parser.add_argument('--ca-file', type=Path, help='Provider CA path on this host (not container path)')
    parser.add_argument('--execute', action='store_true', help='Perform authorized DB and bucket reads')
    parser.add_argument('--quiesced', action='store_true', help='Operator confirms API writes/workers are stopped')
    parser.add_argument('--destination-encrypted', action='store_true', help='Operator confirms approved encrypted storage')
    args = parser.parse_args(argv)
    try:
        if not args.env_file.is_file():
            raise BackupError('Explicit environment file is missing')
        values = {k: v or '' for k, v in dotenv_values(args.env_file, interpolate=False).items()}
        errors = external_infrastructure_errors(values)
        for name in ['S3_ACCESS_KEY', 'S3_SECRET_KEY', 'S3_BUCKET']:
            if not present(values.get(name)):
                errors.append(name)
        if errors:
            print(json.dumps({'status': 'BLOCKED', 'invalid_configuration': errors}))
            return 1
        if not args.execute:
            print(json.dumps({'status': 'DRY_RUN', 'remote_calls': 0, 'files_written': 0,
                              'scope': 'public PostgreSQL schema and complete dedicated private bucket',
                              'requires': ['quiesced API/workers', 'provider CA on backup host',
                                           'approved encrypted destination', 'pg_dump/pg_restore/psql tools']}))
            return 0
        if not (args.quiesced and args.destination_encrypted and args.ca_file):
            raise BackupError('Execution requires --quiesced, --destination-encrypted and --ca-file')
        def interrupted(*_):
            raise BackupError('Backup interrupted; incomplete files removed')
        signal.signal(signal.SIGTERM, interrupted)
        result = create_backup(values, args.output_dir, args.ca_file)
        print(json.dumps(result))
        return 0
    except BackupError as error:
        print(json.dumps({'status': 'FAILED', 'message': str(error)}))
        return 1
    except (Exception, KeyboardInterrupt):
        # Provider/OS exceptions may contain credentials, object keys or data.
        print(json.dumps({'status': 'FAILED', 'message': 'Backup not completed; check configuration, quiescence, tools and private destination. Provider details suppressed.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
