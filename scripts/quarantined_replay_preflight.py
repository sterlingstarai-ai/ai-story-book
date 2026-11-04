"""Recheck an isolated restored DB/media target without applying events."""
import asyncio
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import sys

import boto3
from botocore.config import Config

from quarantined_db_fingerprint import fingerprint
from quarantined_restore_runtime import ROOT, PG_BIN, MINIO, _assert_local_sandbox, _read_media, _run
from verify_backup_set import verify


class ReplayPreflightError(RuntimeError):
    pass


_SOURCE_REVISION = '5de7a40b6c12'
_REPLAY_REVISION = 'f32a7b4d190c'


def _verify_runtime_process(pid, binary, data_dir):
    if type(pid) is not int or pid < 2:
        raise ReplayPreflightError('Quarantined service process is invalid')
    process = Path('/proc') / str(pid)
    executable = (process / 'exe').resolve(strict=True)
    arguments = (process / 'cmdline').read_bytes().split(b'\0')
    if (process.stat().st_uid != os.geteuid() or executable != Path(binary).resolve(strict=True)
            or os.fsencode(data_dir) not in arguments):
        raise ReplayPreflightError('Quarantined service process does not match')


def preflight(token):
    _assert_local_sandbox()
    if not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token):
        raise ReplayPreflightError('Sandbox token is invalid')
    backup = ROOT / ('ingest-' + token)
    data_dir = ROOT / ('runtime-' + token)
    runtime = data_dir / 'runtime.json'
    if (backup.is_symlink() or not backup.is_dir() or data_dir.is_symlink()
            or runtime.is_symlink() or not runtime.is_file() or runtime.stat().st_size > 4096):
        raise ReplayPreflightError('Quarantined target is unavailable')
    info = runtime.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ReplayPreflightError('Quarantined target metadata is invalid')
    if verify(backup).get('restore_verified') is not False:
        raise ReplayPreflightError('Original backup no longer matches')
    manifest = json.loads((backup / 'manifest.json').read_bytes())
    config = json.loads(runtime.read_bytes())
    if (not isinstance(config, dict) or set(config) != {
            'version', 'database', 'db_port', 'storage_endpoint', 'bucket', 'storage_user',
            'storage_password', 'minio_pid', 'database_fingerprint', 'restore_authorized'}
            or type(config['version']) is not int or config['version'] != 1
            or config['database'] != 'restored' or config['db_port'] != 54321
            or config['storage_endpoint'] != 'http://127.0.0.1:59000' or config['bucket'] != 'quarantine-restore'
            or config['restore_authorized'] is not False or not isinstance(config['database_fingerprint'], str)
            or not re.fullmatch('[0-9a-f]{64}', config['database_fingerprint'])
            or not isinstance(config['storage_user'], str) or not isinstance(config['storage_password'], str)):
        raise ReplayPreflightError('Quarantined target metadata is invalid')
    _verify_runtime_process(config['minio_pid'], MINIO, data_dir / 'media')
    pgdata = data_dir / 'pg'
    pg_pid = int((pgdata / 'postmaster.pid').read_text().splitlines()[0])
    _verify_runtime_process(pg_pid, PG_BIN / 'postgres', pgdata)
    env = dict(os.environ, PGHOST='127.0.0.1', PGPORT='54321', PGUSER='sandbox')
    revision = _run([str(PG_BIN / 'psql'), '-X', '-At', '-d', 'restored', '-c',
                     'SELECT version_num FROM public.alembic_version ORDER BY version_num'], env=env).decode().strip()
    if revision != manifest.get('alembic_revision'):
        raise ReplayPreflightError('Restored database revision changed')
    if not hmac.compare_digest(fingerprint(), config['database_fingerprint']):
        raise ReplayPreflightError('Restored database content changed')
    client = boto3.client('s3', endpoint_url=config['storage_endpoint'],
        aws_access_key_id=config['storage_user'], aws_secret_access_key=config['storage_password'],
        region_name='us-east-1', config=Config(signature_version='s3v4', proxies={},
            s3={'addressing_style': 'path'}, connect_timeout=3, read_timeout=15, retries={'max_attempts': 1}))
    try:
        _read_media(client, config['bucket'], manifest['objects'])
    finally:
        client.close()
    _verify_runtime_process(config['minio_pid'], MINIO, data_dir / 'media')
    _verify_runtime_process(pg_pid, PG_BIN / 'postgres', pgdata)
    return {'status': 'RESTORED_TARGET_MATCHES_BACKUP_QUARANTINED',
            'latest_journal_verified': False, 'privacy_replay_authorized': False,
            'restore_authorized': False}


def main():
    try:
        if len(sys.argv) == 3 and sys.argv[1] == '--apply':
            with open(os.devnull, 'w') as sink, redirect_stdout(sink), redirect_stderr(sink):
                result = asyncio.run(apply_replay(sys.argv[2]))
            print(json.dumps(result, sort_keys=True))
            return 0
        if len(sys.argv) != 2:
            raise ReplayPreflightError('Sandbox token is required')
        print(json.dumps(preflight(sys.argv[1]), sort_keys=True))
        return 0
    except BaseException:
        print(json.dumps({'status': 'RESTORED_TARGET_NOT_VERIFIED', 'restore_authorized': False}))
        return 1


def upgrade_replay_schema(token):
    """Upgrade only the verified, disposable legacy target, never the source."""
    preflight(token)
    from quarantined_outbox_binding import inspect_checkpoint

    checkpoint = inspect_checkpoint(token)
    data_dir = ROOT / ('runtime-' + token)
    pgdata = data_dir / 'pg'
    pg_pid = int((pgdata / 'postmaster.pid').read_text().splitlines()[0])
    _verify_runtime_process(pg_pid, PG_BIN / 'postgres', pgdata)
    env = {'PATH': '/opt/venv/bin:/usr/lib/postgresql/16/bin:/usr/bin:/bin',
           'HOME': '/tmp', 'PYTHONDONTWRITEBYTECODE': '1',
           'DATABASE_URL': 'postgresql://sandbox@127.0.0.1:54321/restored',
           'DATABASE_MIGRATION_URL': '', 'DATABASE_SSL_MODE': 'disable',
           'TESTING': 'true', 'DEBUG': 'false',
           'PGHOST': '127.0.0.1', 'PGPORT': '54321', 'PGUSER': 'sandbox'}
    query = [str(PG_BIN / 'psql'), '-X', '-At', '-d', 'restored', '-c']
    revision = 'SELECT version_num FROM public.alembic_version ORDER BY version_num'
    if _run(query + [revision], env=env).decode().strip() != _SOURCE_REVISION:
        raise ReplayPreflightError('Unexpected legacy replay schema')
    if Path.cwd() != Path('/offline/apps/api'):
        raise ReplayPreflightError('Isolated migration working directory does not match')
    _run(['/opt/venv/bin/python', '-m', 'alembic', 'upgrade', _REPLAY_REVISION], env=env, timeout=120)
    _verify_runtime_process(pg_pid, PG_BIN / 'postgres', pgdata)
    if _run(query + [revision], env=env).decode().strip() != _REPLAY_REVISION:
        raise ReplayPreflightError('Isolated replay schema upgrade did not complete')
    if inspect_checkpoint(token, migrated_revision=_REPLAY_REVISION) != checkpoint:
        raise ReplayPreflightError('Isolated replay upgrade changed the backup checkpoint')
    return {'status': 'ISOLATED_REPLAY_SCHEMA_UPGRADED',
            'backup_event_count': len(checkpoint['event_ids']), 'restore_authorized': False}


async def verify_replay_destination(db, token):
    """Independently bind the replay ORM and storage clients to the sandbox."""
    from sqlalchemy import text
    from src.core.config import settings

    _assert_local_sandbox()
    if not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token):
        raise ReplayPreflightError('Sandbox token is invalid')
    data = ROOT / ('runtime-' + token)
    path = data / 'runtime.json'
    info = path.lstat()
    if (data.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077 or info.st_size > 4096):
        raise ReplayPreflightError('Isolated replay metadata is invalid')
    runtime = json.loads(path.read_bytes())
    pgdata = data / 'pg'
    pg_pid = int((pgdata / 'postmaster.pid').read_text().splitlines()[0])
    _verify_runtime_process(pg_pid, PG_BIN / 'postgres', pgdata)
    _verify_runtime_process(runtime['minio_pid'], MINIO, data / 'media')
    url = db.get_bind().url
    if ((url.drivername, url.host, url.port, url.database, url.username, url.password) !=
            ('postgresql+asyncpg', '127.0.0.1', 54321, 'restored', 'sandbox', None)
            or url.query or settings.privacy_journal_enabled or not settings.testing
            or runtime['restore_authorized'] is not False
            or settings.s3_endpoint != 'http://127.0.0.1:59000'
            or settings.s3_bucket != 'quarantine-restore'
            or settings.s3_download_endpoint not in (None, '', settings.s3_endpoint)
            or settings.s3_access_key != runtime['storage_user']
            or settings.s3_secret_key != runtime['storage_password']):
        raise ReplayPreflightError('Replay client is not bound to the isolated target')
    if await db.scalar(text('SELECT version_num FROM public.alembic_version')) != _REPLAY_REVISION:
        raise ReplayPreflightError('Replay target schema does not match')


async def apply_replay(token):
    """Consume an authenticated host's event transfer inside quarantine only."""
    preflight(token)
    limit = 32 * 1024 * 1024
    raw = sys.stdin.buffer.read(limit + 1)
    if len(raw) > limit:
        raise ReplayPreflightError('Replay transfer exceeds its limit')
    payload = json.loads(raw)
    if (not isinstance(payload, dict)
            or set(payload) != {'events', 'journal_sha256', 'legacy_public_url'}
            or not isinstance(payload['events'], list) or len(payload['events']) > 100000
            or not isinstance(payload['legacy_public_url'], str)
            or len(payload['legacy_public_url']) > 1024 or ',' in payload['legacy_public_url']):
        raise ReplayPreflightError('Replay transfer is invalid')
    data = ROOT / ('runtime-' + token)
    runtime = json.loads((data / 'runtime.json').read_bytes())
    os.environ.update(DATABASE_URL='postgresql://sandbox@127.0.0.1:54321/restored',
                      DATABASE_MIGRATION_URL='', DATABASE_SSL_MODE='disable', DATABASE_SSL_ROOT_CERT='',
                      TESTING='true', DEBUG='false', PRIVACY_JOURNAL_ENABLED='false',
                      S3_ENDPOINT='http://127.0.0.1:59000', S3_DOWNLOAD_ENDPOINT='http://127.0.0.1:59000',
                      S3_PUBLIC_URL='http://127.0.0.1:59000/quarantine-restore',
                      S3_LEGACY_PUBLIC_URLS=payload['legacy_public_url'], S3_REGION='us-east-1',
                      S3_ADDRESSING_STYLE='path', S3_BUCKET='quarantine-restore',
                      S3_ACCESS_KEY=runtime['storage_user'], S3_SECRET_KEY=runtime['storage_password'])
    sys.path.insert(0, '/offline/apps/api')
    from src.core.database import AsyncSessionLocal, dispose_async_engines
    from src.services.privacy_journal import JournalScan, PrivacyJournal
    from src.services.privacy_journal_verify import fingerprint_entries, verify_current_outbox
    from replay_privacy_journal import _apply_replay_core, plan_quarantined_replay

    events = tuple(PrivacyJournal._validate_intent(item['id'], item) for item in payload['events'])
    scan = JournalScan(events, 0)
    plan_quarantined_replay(scan)
    if fingerprint_entries(events) != payload['journal_sha256']:
        raise ReplayPreflightError('Replay transfer fingerprint does not match')
    backup = ROOT / ('ingest-' + token)
    marker_path = backup / 'verified.json'
    if marker_path.is_symlink() or not marker_path.is_file() or marker_path.stat().st_size > 4096:
        raise ReplayPreflightError('Backup checkpoint is unavailable')
    marker = json.loads(marker_path.read_bytes())
    manifest_bytes = (backup / 'manifest.json').read_bytes()
    if marker.get('manifest_sha256') != hashlib.sha256(manifest_bytes).hexdigest():
        raise ReplayPreflightError('Backup checkpoint does not bind this manifest')
    manifest = json.loads(manifest_bytes)
    if manifest['alembic_revision'] == _SOURCE_REVISION:
        upgrade_replay_schema(token)
    elif manifest['alembic_revision'] != _REPLAY_REVISION:
        raise ReplayPreflightError('Unsupported replay schema')
    try:
        async with AsyncSessionLocal() as db:
            result = await _apply_replay_core(db, scan, backup_marker=marker, sandbox_token=token)
            await verify_replay_destination(db, token)
            checkpoint = await verify_current_outbox(db, scan)
        if checkpoint['journal_sha256'] != payload['journal_sha256']:
            raise ReplayPreflightError('Replayed journal fingerprint does not match')
        return {'status': 'REPLAYED_STILL_QUARANTINED', 'applied_count': result['applied_count'],
                'restore_authorized': False}
    finally:
        await dispose_async_engines()


if __name__ == '__main__':
    raise SystemExit(main())
