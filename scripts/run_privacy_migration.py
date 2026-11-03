"""Guarded additive migration for the private pilot after a verified backup.

This does not deploy application code or approve a restore. Only the exact
legacy revision is accepted. API and worker restart even if migration fails.
"""

import argparse
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

from backup_external import database_environment, run_pg
from backup_service_guard import BackupServiceGuard, DockerRuntime
from bootstrap_privacy_backup import assert_legacy_quiescent
from publish_backup_gcs import GCSBackupStore, verify_remote_backup
from run_scheduled_backup import assert_idle_worker, private_file

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / 'apps/api'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--ca-file', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--backup-bucket', required=True)
    parser.add_argument('--backup-run-id', required=True)
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({'status': 'DRY_RUN', 'database_changed': False}))
        return 0
    try:
        if not re.fullmatch('[0-9a-f]{32}', args.backup_run_id):
            raise ValueError('invalid backup run')
        raw = private_file(args.env_file, max_bytes=1024 * 1024)
        values = {k: v or '' for k, v in dotenv_values(stream=io.StringIO(raw.decode()), interpolate=False).items()}
        if values.get('DATABASE_SSL_MODE') != 'verify-full' or not args.ca_file.is_file() or args.ca_file.is_symlink():
            raise ValueError('invalid TLS configuration')
        sys.path.insert(0, str(API))
        from src.services.privacy_journal_gcs import application_default_token

        store = GCSBackupStore(args.backup_bucket, application_default_token)
        try:
            verify_remote_backup(args.backup_run_id, store, expected_revision='2a8d9e4f610b')
        finally:
            store.close()
        environment = database_environment(values, args.ca_file)
        query = ['psql', '-X', '--no-password', '--tuples-only', '--no-align', '--set', 'ON_ERROR_STOP=1', '-c']
        runtime = DockerRuntime()
        guard = BackupServiceGuard(args.state_dir, runtime)

        def idle():
            assert_legacy_quiescent(environment, query)
            assert_idle_worker(runtime)

        def migrate():
            assert_legacy_quiescent(environment, query)
            child_env = dict(os.environ)
            for name in ('DATABASE_URL', 'DATABASE_MIGRATION_URL'):
                raw_url = values.get(name, '')
                if raw_url:
                    if raw_url.startswith('postgres://'):
                        raw_url = 'postgresql://' + raw_url[len('postgres://'):]
                    child_env[name] = make_url(raw_url).difference_update_query(['sslrootcert']).render_as_string(hide_password=False)
            child_env.update(DATABASE_SSL_MODE='verify-full', DATABASE_SSL_ROOT_CERT=str(args.ca_file),
                             TESTING='false', DEBUG='false', PYTHONPATH=str(API))
            process = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=API,
                                     env=child_env, capture_output=True, timeout=1800)
            revision = run_pg(query + ['SELECT version_num FROM public.alembic_version ORDER BY version_num'], environment).strip()
            if process.returncode or revision != b'5de7a40b6c12':
                raise RuntimeError('Migration did not reach its expected revision')
            return {'status': 'MIGRATION_APPLIED', 'revision': '5de7a40b6c12'}

        result = guard.run(verify_idle=idle, backup=migrate)
        print(json.dumps(result))
        return 0
    except Exception:
        print(json.dumps({'status': 'FAILED_OR_UNVERIFIED',
                          'message': 'Inspect DB revision and service recovery before retrying.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
