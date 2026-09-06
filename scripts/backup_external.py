"""Read an authorized, quiesced external DB/private bucket into a private backup set.

Default is a configuration-only dry run. No remote writes, automatic restore,
retention deletion, provider calls, or project .env discovery. Credentials stay
out of command arguments and output. See docs/BACKUP_RESTORE.md before --execute.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit

from dotenv import dotenv_values

from final_external_preflight import external_infrastructure_errors, present


class BackupError(RuntimeError):
    pass


def database_environment(values, ca_file):
    """Pass libpq secrets through a child-only environment, never a URL on argv."""
    url = urlsplit(values.get('DATABASE_MIGRATION_URL') or values['DATABASE_URL'])
    return {
        'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
        'PGHOST': url.hostname, 'PGPORT': str(url.port or 5432),
        'PGUSER': unquote(url.username), 'PGPASSWORD': unquote(url.password),
        'PGDATABASE': unquote(url.path.lstrip('/')), 'PGSSLMODE': 'verify-full',
        'PGSSLROOTCERT': str(ca_file), 'PGCONNECT_TIMEOUT': '15',
    }


def run_pg(command, environment, *, destination=None):
    try:
        result = subprocess.run(command, env=environment, stdout=destination or subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True, timeout=1800)
        return result.stdout or b''
    except (OSError, subprocess.SubprocessError):
        raise BackupError('PostgreSQL backup/read validation failed; provider details were suppressed') from None


def storage_client(values):
    import boto3
    from botocore.config import Config
    return boto3.client('s3', endpoint_url=values['S3_ENDPOINT'],
                        aws_access_key_id=values['S3_ACCESS_KEY'],
                        aws_secret_access_key=values['S3_SECRET_KEY'],
                        region_name=values['S3_REGION'],
                        config=Config(signature_version='s3v4', s3={'addressing_style': 'path'},
                                      connect_timeout=15, read_timeout=60,
                                      retries={'max_attempts': 2, 'mode': 'standard'}))


def inventory(client, bucket):
    objects = {}
    for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket):
        for item in page.get('Contents', []):
            key = item['Key']
            if key in objects:
                raise BackupError('Object inventory changed while listing; retry in a quiesced window')
            objects[key] = {name: str(item.get(name, '')) for name in ('ETag', 'Size', 'LastModified')}
    return objects


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for data in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


def create_backup(values, destination, ca_file):
    """Only called after CLI authorization; all remote methods here are read-only."""
    if not ca_file.is_file():
        raise BackupError('Provider CA file is not readable on this backup host')
    environment = database_environment(values, ca_file)
    query = ['psql', '-X', '--no-password', '--tuples-only', '--no-align', '--set', 'ON_ERROR_STOP=1', '-c']
    active = run_pg(query + ["SELECT count(*) FROM public.jobs WHERE status IN ('queued','running')"], environment).strip()
    if active != b'0':
        raise BackupError('Pending/running generation jobs remain; finish the quiescence procedure first')
    revision = run_pg(query + ['SELECT version_num FROM public.alembic_version ORDER BY version_num'], environment).decode().strip()
    if not revision:
        raise BackupError('Alembic revision is missing')
    if destination.exists() and (destination.is_symlink() or destination.stat().st_mode & 0o077):
        raise BackupError('Backup destination must be a private directory (0700), without a symlink')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder = Path(tempfile.mkdtemp(prefix='.partial-external-', dir=destination))
    final = destination / folder.name.replace('.partial-external-', 'external-', 1)
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
            run_pg(['pg_dump', '--no-password', '--format=custom', '--schema=public',
                    '--no-owner', '--no-privileges'], environment, destination=output)
        run_pg(['pg_restore', '--list', str(dump)], environment)
        media = []
        for key, expected in sorted(before.items()):
            filename = hashlib.sha256(key.encode()).hexdigest()
            path = objects_dir / filename  # Never interpret remote object keys as local paths.
            obj = client.get_object(Bucket=bucket, Key=key, IfMatch=expected['ETag'])
            size = 0
            digest = hashlib.sha256()
            try:
                with path.open('xb') as output:
                    os.chmod(path, 0o600)
                    for data in iter(lambda: obj['Body'].read(1024 * 1024), b''):
                        size += len(data)
                        digest.update(data)
                        output.write(data)
            finally:
                obj['Body'].close()
            if size != int(expected['Size']) or size != obj['ContentLength']:
                raise BackupError('Media changed or was truncated during backup')
            media.append({'key': key, 'file': f'objects/{filename}', 'sha256': digest.hexdigest(),
                          'size': size, 'content_type': obj.get('ContentType', 'application/octet-stream'),
                          'metadata': obj.get('Metadata', {}),
                          'cache_control': obj.get('CacheControl'),
                          'content_disposition': obj.get('ContentDisposition'),
                          'content_encoding': obj.get('ContentEncoding')})
        if inventory(client, bucket) != before:
            raise BackupError('Media inventory changed during backup; no complete set will be published')
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
                'backup_set': final.name, 'contains_private_data': True}
    except BaseException:
        shutil.rmtree(folder, ignore_errors=False)
        raise


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
