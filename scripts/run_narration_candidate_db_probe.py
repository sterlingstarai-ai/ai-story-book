"""Exercise candidate migration in a disposable network-isolated PostgreSQL."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

from build_narration_candidate import ROOT, checkout_hashes, docker, ensure_local_daemon


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True)
    parser.add_argument('--include-receipts', action='store_true')
    parser.add_argument('--current-migration-snapshot', action='store_true')
    args = parser.parse_args()
    ensure_local_daemon()
    with open(args.report) as stream:
        report = json.load(stream)
    if report.get('status') != 'LOCAL_CANDIDATES_BUILT':
        raise RuntimeError('Expected a local candidate build report')
    images = {role: report['images'][role]['candidate'] for role in ('api', 'worker')}
    docker('image', 'inspect', 'postgres:16')  # no pulls
    name = 'asb-narration-db-fixture-' + uuid.uuid4().hex[:12]
    identifier = None
    snapshot = None
    source_before = None
    mounts = []
    env = ['-e', 'TESTING=true', '-e', 'PYTHONDONTWRITEBYTECODE=1',
           '-e', 'DATABASE_URL=postgresql://fixture:fixture@127.0.0.1:5432/fixture']
    try:
        if args.current_migration_snapshot:
            snapshot = tempfile.TemporaryDirectory(prefix='asb-narration-db-snapshot-')
            snapshot_root = Path(snapshot.name)
            snapshot_root.chmod(0o755)
            source_before = {k: v for k, v in checkout_hashes().items()
                             if k.startswith('alembic/') or k == 'src/models/db.py'}
            migration_dir = snapshot_root / 'alembic'
            shutil.copytree(ROOT / 'apps/api/alembic', migration_dir,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            model = snapshot_root / 'db.py'
            shutil.copyfile(ROOT / 'apps/api/src/models/db.py', model)
            if source_before != {k: v for k, v in checkout_hashes().items()
                                 if k.startswith('alembic/') or k == 'src/models/db.py'}:
                raise RuntimeError('Migration source changed during fixture snapshot')
            mounts = ['--mount', f'type=bind,src={migration_dir},dst=/app/alembic,readonly',
                      '--mount', f'type=bind,src={model},dst=/app/src/models/db.py,readonly']
        identifier = docker('run', '-d', '--rm', '--name', name, '--network=none',
                            '--tmpfs', '/var/lib/postgresql/data:rw,size=128m',
                            '-e', 'POSTGRES_USER=fixture', '-e', 'POSTGRES_PASSWORD=fixture',
                            '-e', 'POSTGRES_DB=fixture', 'postgres:16').decode().strip()
        for _ in range(60):
            ready = subprocess.run(['docker', 'exec', identifier, 'pg_isready', '-U', 'fixture'],
                                   capture_output=True, timeout=5)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Disposable PostgreSQL did not become ready')
        sql = ("CREATE TABLE pages (id integer PRIMARY KEY); "
               "INSERT INTO pages VALUES (1); "
               "CREATE TABLE privacy_journal_outbox(event_id varchar(32) PRIMARY KEY); "
               "CREATE TABLE alembic_version (version_num varchar(32) NOT NULL); "
               "INSERT INTO alembic_version VALUES ('5de7a40b6c12');")
        docker('exec', identifier, 'psql', '-U', 'fixture', '-d', 'fixture',
               '-v', 'ON_ERROR_STOP=1', '-c', sql)
        prefix = ['run', '--rm', '--network=container:' + identifier, '--read-only',
                  '--tmpfs', '/tmp:rw,size=32m', *mounts, *env]
        target = '8a34e19c6b72' if args.include_receipts else '7e28d9a6b451'
        docker(*prefix, '--entrypoint', 'alembic', images['api'], 'upgrade', target)
        docker('exec', identifier, 'psql', '-U', 'fixture', '-d', 'fixture', '-v',
               'ON_ERROR_STOP=1', '-c',
               "INSERT INTO narration_variants (id,page_id,language,voice,audio_url,style,provider) "
               "VALUES ('fixture',1,'ko','deep','fixture','animated','google_gemini')")
        check = ("import psycopg; from src.models.db import NarrationVariant; "
                 "c=psycopg.connect('host=127.0.0.1 dbname=fixture user=fixture password=fixture'); "
                 f"assert c.execute('select version_num from alembic_version').fetchone()[0]=='{target}'; "
                 "assert c.execute('select count(*) from narration_variants').fetchone()[0]==1; "
                 "assert NarrationVariant.__tablename__=='narration_variants'")
        docker(*prefix, '--entrypoint', 'python', images['worker'], '-c', check)
        if args.include_receipts:
            docker('exec', identifier, 'psql', '-U', 'fixture', '-d', 'fixture', '-v', 'ON_ERROR_STOP=1',
                   '-c', "INSERT INTO book_deletion_receipts(user_key,request_id,book_id,created_at) "
                         "VALUES ('fixture','fixture','fixture',CURRENT_TIMESTAMP)")
            blocked_receipt = subprocess.run(['docker', *prefix, '--entrypoint', 'alembic', images['api'],
                                              'downgrade', '7e28d9a6b451'], capture_output=True, timeout=120)
            if (blocked_receipt.returncode == 0
                    or b'Cannot discard deletion receipt evidence' not in blocked_receipt.stderr):
                raise RuntimeError('Deletion receipt downgrade guard did not execute')
            docker('exec', identifier, 'psql', '-U', 'fixture', '-d', 'fixture', '-v', 'ON_ERROR_STOP=1',
                   '-c', "DELETE FROM book_deletion_receipts; "
                         "INSERT INTO privacy_journal_outbox(event_id,deletion_receipt) VALUES ('fixture','{}')")
            blocked_journal = subprocess.run(['docker', *prefix, '--entrypoint', 'alembic', images['api'],
                                              'downgrade', '7e28d9a6b451'], capture_output=True, timeout=120)
            if (blocked_journal.returncode == 0
                    or b'Cannot discard journal deletion receipt metadata' not in blocked_journal.stderr):
                raise RuntimeError('Journal receipt downgrade guard did not execute')
            docker('exec', identifier, 'psql', '-U', 'fixture', '-d', 'fixture', '-c',
                   'DELETE FROM privacy_journal_outbox')
        failed = subprocess.run(['docker', *prefix, '--entrypoint', 'alembic', images['api'],
                                 'downgrade', '5de7a40b6c12'], capture_output=True, timeout=120)
        if (failed.returncode == 0
                or b'Cannot downgrade while style recordings exist' not in failed.stderr):
            raise RuntimeError('Expected downgrade guard did not execute')
        result = docker('exec', identifier, 'psql', '-U', 'fixture', '-d', 'fixture', '-Atc',
                        'SELECT count(*) FROM narration_variants').decode().strip()
        if result != '1':
            raise RuntimeError('Synthetic narration row was not preserved')
        if source_before is not None and source_before != {k: v for k, v in checkout_hashes().items()
                if k.startswith('alembic/') or k == 'src/models/db.py'}:
            raise RuntimeError('Migration source changed during fixture; rerun after edits finish')
    finally:
        if identifier:
            docker('rm', '-f', identifier)
        if snapshot:
            snapshot.cleanup()
    print(json.dumps({'status': 'ISOLATED_POSTGRES_PROBE_PASSED',
                      'synthetic_data_only': True, 'real_restore_verified': False}))


if __name__ == '__main__':
    main()
