"""Recheck an isolated restored DB/media target without applying events."""
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
from quarantined_restore_runtime import ROOT, PG_BIN, _assert_local_sandbox, _read_media, _run
from verify_backup_set import verify


class ReplayPreflightError(RuntimeError):
    pass


def preflight(token):
    _assert_local_sandbox()
    if not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token):
        raise ReplayPreflightError('Sandbox token is invalid')
    backup = ROOT / ('ingest-' + token)
    runtime = ROOT / ('runtime-' + token) / 'runtime.json'
    if (backup.is_symlink() or not backup.is_dir() or runtime.is_symlink() or not runtime.is_file()):
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
    _read_media(client, config['bucket'], manifest['objects'])
    return {'status': 'RESTORED_TARGET_MATCHES_BACKUP_QUARANTINED',
            'latest_journal_verified': False, 'privacy_replay_authorized': False,
            'restore_authorized': False}


def main():
    try:
        if len(sys.argv) != 2:
            raise ReplayPreflightError('Sandbox token is required')
        print(json.dumps(preflight(sys.argv[1]), sort_keys=True))
        return 0
    except BaseException:
        print(json.dumps({'status': 'RESTORED_TARGET_NOT_VERIFIED', 'restore_authorized': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
