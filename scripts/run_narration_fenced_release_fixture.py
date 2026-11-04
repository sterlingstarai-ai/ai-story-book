"""Synthetic database dump, restore and migration under one live write fence.

All database containers use a network namespace with no external interface.
This fixture does not test external media, privacy replay, or a production VM.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

from build_narration_candidate import checkout_hashes, docker, ensure_local_daemon
from postgres_backup_fence import MEDIA_WRITE_LOCK


RUNNER = '''import os, pathlib, sys, time
sys.path.insert(0, '/opt/fixture-scripts')
import narration_transaction_fence as n
n.API = pathlib.Path('/app')
e = {'PGHOST':'127.0.0.1', 'PGPORT':'5432', 'PGUSER':'fixture',
     'PGPASSWORD':'fixture', 'PGDATABASE':'fixture', 'PGSSLMODE':'disable'}
root = pathlib.Path('/fixture')
with n.NarrationTransactionFence(e, allow_local_fixture=True) as fence:
    (root / 'snapshot').write_text(fence.snapshot_id)
    for _ in range(240):
        if (root / 'proceed').exists():
            break
        time.sleep(0.25)
    else:
        raise RuntimeError('Fixture did not verify backup in time')
    fence.migrate(assert_backup_restored=lambda: (root / 'proceed').read_text() == 'verified')
    if (root / 'disconnect-media-before-commit').exists():
        pid = fence.connection.connection.driver_connection.info.backend_pid
        with fence._connect() as observer:
            stopped = observer.execute('SELECT pg_terminate_backend(%s, 5000)', (pid,)).fetchone()
        if stopped != (True,):
            raise RuntimeError('Synthetic migration session termination failed')
        try:
            fence.commit()
        except n.NarrationFenceError:
            (root / 'commit-rejected').write_text('verified')
            sys.exit(0)
        raise RuntimeError('Commit succeeded without media session')
    if (root / 'interrupt-before-commit').exists():
        (root / 'migration-applied').write_text('pending')
        while True:
            time.sleep(1)
    fence.commit()
    (root / 'complete').write_text('committed')
'''


def ready(identifier):
    for _ in range(60):
        check = subprocess.run(['docker', 'exec', identifier, 'pg_isready', '-U', 'fixture'],
                               capture_output=True, timeout=5)
        if check.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError('Synthetic database did not become ready')


def pg_container(name):
    return docker('run', '-d', '--rm', '--name', name, '--network=none',
                  '--tmpfs', '/var/lib/postgresql/data:rw,size=128m', '-e', 'POSTGRES_USER=fixture',
                  '-e', 'POSTGRES_PASSWORD=fixture', '-e', 'POSTGRES_DB=fixture',
                  'postgres:16').decode().strip()


def psql(identifier, query):
    return docker('exec', identifier, 'psql', '-U', 'fixture', '-d', 'fixture',
                  '-v', 'ON_ERROR_STOP=1', '-Atc', query).decode().strip()


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True, type=Path)
    failure = parser.add_mutually_exclusive_group()
    failure.add_argument('--interrupt-before-commit', action='store_true')
    failure.add_argument('--disconnect-media-before-commit', action='store_true')
    parser.add_argument('--current-migration-snapshot', action='store_true',
                        help='test a private snapshot of current migration files instead of those in the image')
    args = parser.parse_args()
    ensure_local_daemon()
    report = json.loads(args.report.read_text())
    if report.get('status') != 'LOCAL_CANDIDATES_BUILT':
        raise RuntimeError('Local candidate report is required')
    image = report['images']['api']['candidate']
    docker('image', 'inspect', 'postgres:16')
    prefix = 'asb-narration-fenced-fixture-' + uuid.uuid4().hex[:12]
    owned = []
    cleanup_failed = False
    try:
        with tempfile.TemporaryDirectory(prefix='asb-narration-fenced-') as folder:
            root = Path(folder)
            root.chmod(0o777)  # only random synthetic data; container runs as non-root
            (root / 'runner.py').write_text(RUNNER)
            migration_mount = []
            migration_before = None
            if args.current_migration_snapshot:
                source_root = Path(__file__).resolve().parents[1] / 'apps/api/alembic'
                migration_before = {k: v for k, v in checkout_hashes().items() if k.startswith('alembic/')}
                snapshot_dir = root / 'alembic'
                shutil.copytree(source_root, snapshot_dir, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
                if migration_before != {k: v for k, v in checkout_hashes().items() if k.startswith('alembic/')}:
                    raise RuntimeError('Migration source changed during fixture snapshot')
                migration_mount = ['--mount', f'type=bind,src={snapshot_dir},dst=/app/alembic,readonly']
            source = pg_container(prefix + '-source')
            owned.append(source)
            ready(source)
            psql(source, "CREATE TABLE pages (id integer PRIMARY KEY); INSERT INTO pages VALUES (1); "
                 "CREATE TABLE privacy_journal_outbox(event_id varchar(32) PRIMARY KEY, "
                 "user_key varchar(80) NOT NULL, revision bigint NOT NULL, action varchar(30) NOT NULL, "
                 "credential_state json, resource_id varchar(60), consent_state json, "
                 "created_at timestamp NOT NULL, published_at timestamp, "
                 "CONSTRAINT uq_privacy_journal_user_revision UNIQUE(user_key, revision), "
                 "CONSTRAINT ck_privacy_journal_revision_positive CHECK (revision > 0), "
                 "CONSTRAINT ck_privacy_journal_action CHECK (action IN "
                 "('account_delete','consent_revoke','consent_grant','photo_revoke','credential_revoke',"
                 "'book_delete','character_delete','profile_delete','voice_delete','voice_revoke','share_revoke'))); "
                 "CREATE INDEX ix_privacy_journal_unpublished ON privacy_journal_outbox(published_at, created_at); "
                 "CREATE TABLE alembic_version(version_num varchar(32) NOT NULL); "
                 "INSERT INTO alembic_version VALUES ('5de7a40b6c12')")
            script_dir = Path(__file__).resolve().parent
            runner = docker('run', '-d', '--name', prefix + '-runner',
                            '--network=container:' + source, '--read-only', '--tmpfs', '/tmp:rw,size=32m',
                            *migration_mount,
                            '--mount', f'type=bind,src={root},dst=/fixture',
                            '--mount', f'type=bind,src={script_dir},dst=/opt/fixture-scripts,readonly',
                            '-e', 'TESTING=true', '-e', 'DATABASE_URL=sqlite+aiosqlite:////tmp/fixture.db',
                            '--entrypoint', 'python', image, '/fixture/runner.py').decode().strip()
            owned.append(runner)
            for _ in range(240):
                if (root / 'snapshot').is_file():
                    break
                running = subprocess.run(['docker', 'inspect', '--format', '{{.State.Running}}', runner],
                                         capture_output=True, text=True, timeout=5)
                if running.returncode != 0 or running.stdout.strip() != 'true':
                    raise RuntimeError('Synthetic fence runner exited before snapshot')
                time.sleep(.25)
            else:
                raise RuntimeError('Synthetic database fence did not start')
            snapshot = (root / 'snapshot').read_text().strip()
            attempt_write = f'SELECT pg_try_advisory_xact_lock_shared({MEDIA_WRITE_LOCK})'
            if psql(source, attempt_write) != 'f':
                raise RuntimeError('Concurrent synthetic media writer was not fenced')
            blocked = subprocess.run(['docker', 'exec', source, 'psql', '-U', 'fixture', '-d', 'fixture',
                                      '-v', 'ON_ERROR_STOP=1', '-c',
                                      "SET lock_timeout='1s'; INSERT INTO pages VALUES (2)"],
                                     capture_output=True, timeout=15)
            if blocked.returncode == 0 or b'lock timeout' not in blocked.stderr:
                raise RuntimeError('Concurrent synthetic writer was not fenced')
            dump = root / 'database.dump'
            with dump.open('xb') as output:
                result = subprocess.run(['docker', 'exec', source, 'pg_dump', '-U', 'fixture',
                                         '-d', 'fixture', '--format=custom', '--schema=public',
                                         '--no-owner', '--no-privileges', '--snapshot', snapshot],
                                        stdout=output, stderr=subprocess.PIPE, timeout=120)
            if result.returncode != 0:
                raise RuntimeError('Synthetic snapshot backup failed')
            restored = pg_container(prefix + '-restore')
            owned.append(restored)
            ready(restored)
            psql(restored, 'DROP SCHEMA public CASCADE')
            with dump.open('rb') as source_dump:
                result = subprocess.run(['docker', 'exec', '-i', restored, 'pg_restore', '-U', 'fixture',
                                         '-d', 'fixture', '--no-owner', '--no-privileges'],
                                        stdin=source_dump, capture_output=True, timeout=120)
            if result.returncode != 0:
                raise RuntimeError('Synthetic isolated database restore failed: '
                                   + result.stderr.decode(errors='replace')[-1200:])
            if psql(restored, 'SELECT version_num FROM alembic_version') != '5de7a40b6c12':
                raise RuntimeError('Restored source revision differs')
            if psql(restored, 'SELECT count(*) FROM pages') != '1':
                raise RuntimeError('Restored synthetic data differs')
            if args.interrupt_before_commit:
                (root / 'interrupt-before-commit').write_text('synthetic')
            if args.disconnect_media_before_commit:
                (root / 'disconnect-media-before-commit').write_text('synthetic')
            (root / 'proceed').write_text('verified')
            milestone = 'migration-applied' if args.interrupt_before_commit else 'complete'
            if args.disconnect_media_before_commit:
                milestone = 'commit-rejected'
            for _ in range(240):
                if (root / milestone).is_file():
                    break
                time.sleep(.25)
            else:
                raise RuntimeError('Fenced synthetic migration did not reach its milestone')
            if args.interrupt_before_commit:
                docker('kill', runner)
            else:
                if docker('wait', runner).strip() != b'0':
                    raise RuntimeError('Synthetic runner did not exit cleanly')
            if psql(source, attempt_write) != 't':
                raise RuntimeError('Synthetic media write lock was not released')
            if args.interrupt_before_commit or args.disconnect_media_before_commit:
                if psql(source, 'SELECT version_num FROM alembic_version') != '5de7a40b6c12':
                    raise RuntimeError('Interrupted migration did not roll back')
                if psql(source, "SELECT COALESCE(to_regclass('public.narration_variants')::text,'missing')") != 'missing':
                    raise RuntimeError('Interrupted migration left a target table')
                if psql(source, "SELECT COALESCE(to_regclass('public.book_deletion_receipts')::text,'missing')") != 'missing':
                    raise RuntimeError('Interrupted migration left a receipt table')
                if psql(source, "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' "
                                "AND table_name='privacy_journal_outbox' AND column_name='deletion_receipt'") != '0':
                    raise RuntimeError('Interrupted migration left a receipt column')
                if psql(source, "SELECT COALESCE(to_regclass('public.gemini_tts_request_budget')::text,'missing')") != 'missing':
                    raise RuntimeError('Interrupted migration left a budget table')
                if psql(source, "SELECT COALESCE(to_regclass('public.privacy_journal_retry_cursor')::text,'missing')") != 'missing':
                    raise RuntimeError('Interrupted migration left a privacy retry cursor')
                if psql(source, "SELECT count(*) FROM pg_constraint WHERE conname='ck_privacy_journal_action' "
                                "AND pg_get_constraintdef(oid) LIKE '%voice_changed%'") != '0':
                    raise RuntimeError('Interrupted migration left a changed voice constraint')
            elif psql(source, 'SELECT version_num FROM alembic_version') != 'f32a7b4d190c':
                raise RuntimeError('Synthetic target revision differs')
            elif psql(source, "SELECT COALESCE(to_regclass('public.book_deletion_receipts')::text,'missing')") != 'book_deletion_receipts':
                raise RuntimeError('Synthetic receipt table was not created')
            elif psql(source, "SELECT COALESCE(to_regclass('public.gemini_tts_request_budget')::text,'missing')") != 'gemini_tts_request_budget':
                raise RuntimeError('Synthetic budget table was not created')
            elif psql(source, "SELECT COALESCE(to_regclass('public.privacy_journal_retry_cursor')::text,'missing')") != 'privacy_journal_retry_cursor':
                raise RuntimeError('Synthetic privacy retry cursor was not created')
            elif psql(source, "SELECT count(*) FROM pg_constraint WHERE conname='ck_privacy_journal_action' "
                               "AND pg_get_constraintdef(oid) LIKE '%voice_changed%'") != '1':
                raise RuntimeError('Synthetic voice constraint was not updated')
            if migration_before is not None and migration_before != {
                    k: v for k, v in checkout_hashes().items() if k.startswith('alembic/')}:
                raise RuntimeError('Migration source changed during fixture; rerun after editing completes')
    finally:
        for identifier in reversed(owned):
            try:
                # --rm may already have removed the runner after success.
                check = subprocess.run(['docker', 'inspect', identifier], capture_output=True, timeout=10)
                if check.returncode == 0:
                    docker('rm', '-f', identifier)
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            raise RuntimeError('Owned synthetic fixture cleanup failed')
    status = 'FENCED_DATABASE_SIGKILL_ROLLBACK_PASSED' if args.interrupt_before_commit else 'FENCED_DATABASE_BACKUP_MIGRATION_PASSED'
    if args.disconnect_media_before_commit:
        status = 'FENCED_DATABASE_MEDIA_DISCONNECT_ROLLBACK_PASSED'
    print(json.dumps({'status': status, 'synthetic_data_only': True,
                      'media_verified': False, 'privacy_replay_verified': False,
                      'production_deployment_authorized': False}))


if __name__ == '__main__':
    main()
