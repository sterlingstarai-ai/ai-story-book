"""Exercise online backup with owned local PostgreSQL 16 and private MinIO.

Uses copied application sources, mock AI settings, local Redis, real API/worker
processes, and an in-memory GCS publisher stand-in. Never reads project .env,
uses a provider credential, accepts a remote Docker daemon, or restores service
access. All databases, archives, certificates and media are disposable.
"""

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import select
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import unquote
from unittest.mock import patch
import uuid

import httpx
import psycopg

from run_backup_restore_rehearsal import CREDENTIAL, storage, wait_for_host_database
from run_runtime_e2e import (MINIO_TEST_IMAGE, clean_environment, free_port,
                             port_for, require, run, stop_process_group)

ROOT = Path(__file__).resolve().parents[1]
BUCKET = 'restore-rehearsal'
PG_IMAGE = 'postgres:16'
_PG16_LOCATIONS = (Path('/usr/lib/postgresql/16/bin'),
                   Path('/opt/homebrew/opt/postgresql@16/bin'),
                   Path('/usr/local/opt/postgresql@16/bin'))


def find_pg16_bin(environment, *, explicit=None):
    """Find installed tools only; never install or accept another major version.

    ASB_FIXTURE_PG16_BIN may explicitly choose an existing directory. Otherwise
    use supported Ubuntu/Homebrew locations or the calling process's PATH.
    An invalid explicit selection fails instead of silently using other tools.
    """
    path_dump = shutil.which('pg_dump', path=environment.get('PATH', '/usr/bin:/bin'))
    candidates = ([Path(explicit)] if explicit is not None else
                  [*_PG16_LOCATIONS, *([Path(path_dump).parent] if path_dump else [])])
    for directory in dict.fromkeys(candidates):
        try:
            directory = directory.resolve()
            valid = True
            for name in ('pg_dump', 'pg_restore', 'psql'):
                binary = directory / name
                if not binary.is_file() or not os.access(binary, os.X_OK):
                    valid = False
                    break
                result = subprocess.run([str(binary), '--version'], env=environment,
                    capture_output=True, text=True, check=True, timeout=5)
                if (len(result.stdout) > 1024 or not re.fullmatch(
                        re.escape(name) + r' \(PostgreSQL\) 16(?:\.\d+)*(?: [^\r\n]+)?',
                        result.stdout.strip())):
                    valid = False
                    break
            if valid:
                return directory
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            continue
    raise RuntimeError('Existing PostgreSQL 16 pg_dump, pg_restore and psql tools are required')


def _digest(data):
    return hashlib.sha256(data).hexdigest()


class FixtureRuntime:
    def __init__(self, api, worker):
        self.services = {'asb-pilot-api': api, 'asb-pilot-worker': worker}
        self.operations = []

    def running(self, name):
        return self.services[name].poll() is None

    def identity(self, name):
        process = self.services[name]
        require(process.poll() is None, 'A fixture service exited during identity verification')
        return process.pid, id(process)

    def stop(self, name):
        self.operations.append(('stop', name))
        raise AssertionError('Online backup must not stop a service')

    def start(self, name):
        self.operations.append(('start', name))
        raise AssertionError('Online backup must not start a service')


class MemoryPublisher:
    """Real publisher protocol with only a thread-safe HTTP transport double."""
    def __init__(self):
        self.records = {}
        self.lock = threading.Lock()

    def handle(self, request):
        with self.lock:
            if request.method == 'POST':
                require(request.url.params['ifGenerationMatch'] == '0', 'Publisher lost create-only writes')
                name = request.url.params['name']
                if name in self.records:
                    return httpx.Response(412)
                self.records[name] = request.read()
                return httpx.Response(200)
            name = unquote(request.url.raw_path.decode().split('/o/', 1)[1].split('?', 1)[0])
            return httpx.Response(200, content=self.records[name]) if name in self.records else httpx.Response(404)


def _database(environment):
    return psycopg.connect(host=environment['PGHOST'], port=int(environment['PGPORT']),
        user=environment['PGUSER'], password=environment['PGPASSWORD'], dbname=environment['PGDATABASE'],
        sslmode=environment['PGSSLMODE'], sslrootcert=environment['PGSSLROOTCERT'], autocommit=True)


def _worker(workspace, report_dir):
    """Fresh process: application imports can only see the copied source tree."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy import delete, update
    from sqlalchemy.pool import NullPool

    from backup_external import database_environment, run_pg
    from backup_service_guard import BackupServiceGuard
    from online_backup import run_online_backup
    from postgres_backup_fence import OnlineSnapshotCut
    from publish_backup_gcs import GCSBackupStore
    from src.services.privacy_journal import PrivacyJournal
    from src.services.privacy_journal_outbox import (
        DisposableMemoryJournalStore, prepare_privacy_event, publish_privacy_event,
    )

    values = {name: os.environ[name] for name in ('DATABASE_URL', 'DATABASE_MIGRATION_URL', 'S3_ENDPOINT',
        'S3_PUBLIC_URL', 'S3_BUCKET', 'S3_ACCESS_KEY', 'S3_SECRET_KEY', 'S3_REGION', 'API_IMAGE', 'WORKER_IMAGE')}
    ca_file = workspace / 'certs/server.crt'
    environment = database_environment(values, ca_file)
    engine = create_async_engine(values['DATABASE_URL'], poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    journal = PrivacyJournal(DisposableMemoryJournalStore(), os.urandom(32))
    source = storage(values['S3_ENDPOINT'])
    source.create_bucket(Bucket=BUCKET)
    original = b'owned-synthetic-original-image'
    source.put_object(Bucket=BUCKET, Key='books/original.png', Body=original, ContentType='image/png')
    source.put_object(Bucket=BUCKET, Key='books/qc-replaced.png', Body=b'synthetic-rejected-image')
    source.delete_object(Bucket=BUCKET, Key='books/qc-replaced.png')
    with _database(environment) as db:
        db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ')
        db.execute('LOCK TABLE books IN SHARE MODE')
        try:
            db.execute('SET TRANSACTION READ ONLY')
            read_only_after_share_lock = db.execute('SHOW transaction_read_only').fetchone() == ('on',)
        except psycopg.Error:
            read_only_after_share_lock = False
        finally:
            db.execute('ROLLBACK')
        db.execute('CREATE TABLE public.online_fixture_counter (id integer PRIMARY KEY, value integer NOT NULL)')
        db.execute('INSERT INTO public.online_fixture_counter VALUES (1,0)')
        db.execute("INSERT INTO jobs(id,status,user_key,image_keys) VALUES ('online-job','done',%s,%s)",
                   (str(uuid.uuid4()), json.dumps(['books/original.png', 'books/qc-replaced.png'])))
        db.execute("INSERT INTO storage_purge_tasks(user_key,reason,kind,target,status,attempts) "
                   "SELECT user_key,'synthetic_qc_replaced','keys','books/qc-replaced.png','done',1 "
                   "FROM jobs WHERE id='online-job'")
        db.execute("INSERT INTO books(id,job_id,title,language,target_age,style,user_key,cover_image_url) "
                   "VALUES ('online-book','online-job','before','ko','7-9','watercolor',%s,%s)",
                   (str(uuid.uuid4()), values['S3_PUBLIC_URL'] + '/books/original.png'))
        require(db.execute('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()').fetchone() == (True,),
                'Source snapshot fixture is not using TLS')

    async def event(*, publish=True):
        from src.models.db import AccountIdentity
        subject = str(uuid.uuid4())
        async with sessions() as db:
            event_id = await prepare_privacy_event(db, journal, user_key=subject, action='account_delete')
            db.add(AccountIdentity(user_key=subject, deleted=True))
            await db.commit()
        if publish:
            await publish_privacy_event(sessions, journal, event_id)
        return event_id

    first_event = asyncio.run(event())
    erase_owner = str(uuid.uuid4())
    with _database(environment) as db:
        db.execute('INSERT INTO account_identities(user_key,deleted,created_at,updated_at) VALUES (%s,false,now(),now())',
                   (erase_owner,))
        db.execute("INSERT INTO jobs(id,status,user_key) VALUES ('erase-job','done',%s)", (erase_owner,))
        db.execute("INSERT INTO books(id,job_id,title,language,target_age,style,user_key) "
                   "VALUES ('erase-book','erase-job','synthetic erase','ko','7-9','watercolor',%s)", (erase_owner,))

    async def post_cut_deletion():
        from src.models.db import AccountIdentity, Book, Job
        async with sessions() as db:
            book_event = await prepare_privacy_event(db, journal, user_key=erase_owner,
                                                    action='book_delete', resource_id='erase-book')
            await db.execute(delete(Book).where(Book.id == 'erase-book'))
            await db.commit()
        await publish_privacy_event(sessions, journal, book_event)
        async with sessions() as db:
            account_event = await prepare_privacy_event(db, journal, user_key=erase_owner, action='account_delete')
            await db.execute(delete(Job).where(Job.id == 'erase-job'))
            await db.execute(update(AccountIdentity).where(AccountIdentity.user_key == erase_owner).values(deleted=True))
            await db.commit()
        await publish_privacy_event(sessions, journal, account_event)
    processes = []
    checks = []
    stop = threading.Event()
    try:
        with ExitStack() as stack:
            def start(name, command):
                output = stack.enter_context((report_dir / (name + '.log')).open('w'))
                process = subprocess.Popen(command, cwd=workspace / 'api', env=os.environ,
                    stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                processes.append(process)
                return process

            api_port = free_port()
            api = start('api', [sys.executable, '-B', '-m', 'uvicorn', 'src.main:app',
                               '--host', '127.0.0.1', '--port', str(api_port)])
            worker = start('worker', [sys.executable, '-B', '-m', 'celery', '-A', 'src.worker', 'worker',
                '--pool=solo', '--concurrency=1', '--loglevel=WARNING', '--without-gossip', '--without-mingle'])
            http = stack.enter_context(httpx.Client(base_url=f'http://127.0.0.1:{api_port}', timeout=5,
                                                   trust_env=False, follow_redirects=False))
            until = time.monotonic() + 45
            while time.monotonic() < until:
                require(api.poll() is None and worker.poll() is None, 'Owned API/worker exited during startup')
                try:
                    if http.get('/health/live').status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.2)
            else:
                raise RuntimeError('Owned API did not start')
            owner = {'X-User-Key': str(uuid.uuid4())}
            require(http.get('/v1/settings', headers=owner).status_code == 200, 'Initial real settings request failed')
            runtime = FixtureRuntime(api, worker)
            guard = BackupServiceGuard(workspace / 'guard', runtime)

            def bindings():
                require(api.poll() is None and worker.poll() is None, 'A real fixture service stopped')

            publisher = MemoryPublisher()
            transport = stack.enter_context(httpx.Client(transport=httpx.MockTransport(publisher.handle)))
            store = GCSBackupStore('synthetic-backup', lambda: 'fixture-token', transport)
            output_dir = workspace / 'backup'
            timings = {}
            progress = {'sql_writes': 0, 'http_writes': 0, 'http_reads': 0, 'errors': [], 'max_request_ms': 0}

            def requests_and_writes():
                try:
                    with _database(environment) as db, httpx.Client(base_url=http.base_url, timeout=5,
                                                                  trust_env=False) as requests:
                        while not stop.is_set():
                            began = time.monotonic()
                            db.execute('UPDATE online_fixture_counter SET value=value+1 WHERE id=1')
                            progress['sql_writes'] += 1
                            require(requests.patch('/v1/settings', headers=owner,
                                json={'dark_mode': bool(progress['http_writes'] % 2)}).status_code == 200,
                                'A real API write failed during bulk backup')
                            progress['http_writes'] += 1
                            require(requests.get('/health/live').status_code == 200,
                                    'A real API read failed during bulk backup')
                            progress['http_reads'] += 1
                            progress['max_request_ms'] = max(progress['max_request_ms'],
                                                           round((time.monotonic() - began) * 1000))
                            stop.wait(.01)
                except Exception as exc:
                    progress['errors'].append(type(exc).__name__)

            pool = stack.enter_context(ThreadPoolExecutor(max_workers=3))
            # ExitStack is LIFO: stop background writers before joining pool
            # threads, including when capture or publication raises midway.
            stack.callback(stop.set)
            writer = None

            def post_cut():
                nonlocal writer
                source.put_object(Bucket=BUCKET, Key='post-cut/new.png', Body=b'synthetic-post-cut')
                with _database(environment) as db:
                    db.execute("UPDATE books SET title='after', cover_image_url=%s WHERE id='online-book'",
                               (values['S3_PUBLIC_URL'] + '/post-cut/new.png',))
                asyncio.run(post_cut_deletion())
                writer = pool.submit(requests_and_writes)
                # Keep overlap deterministic even on tiny backups.
                until = time.monotonic() + 5
                while progress['http_writes'] < 2 and not progress['errors'] and time.monotonic() < until:
                    time.sleep(.01)

            mutations = {'applied': False}
            class AfterReleaseSnapshot(OnlineSnapshotCut):
                def read_snapshot(self, callback):
                    require(self.cut_released and not mutations['applied'],
                            'Deferred validation did not follow the single released cut')
                    post_cut()
                    mutations['applied'] = True
                    return super().read_snapshot(callback)

            run_id = uuid.uuid4().hex
            result = run_online_backup(guard=guard, values=values, environment=environment, ca_file=ca_file,
                output_dir=output_dir, store=store, run_id=run_id, journal=journal, session_factory=sessions,
                verify_bindings=bindings, timings_ms=timings,
                snapshot_factory=lambda: AfterReleaseSnapshot(environment), allow_local_fixture=True)
            require(mutations['applied'], 'Deferred validation did not exercise post-cut live mutations')
            stop.set()
            if writer is not None:
                writer.result(timeout=10)
            require(not progress['errors'] and progress['http_writes'] >= 2 and progress['sql_writes'] >= 2,
                    'Bulk backup lacked successful concurrent real API and SQL writes')
            require(result['services_stopped'] is False and not runtime.operations,
                    'Online backup attempted a service lifecycle change')
            manifest_name = f'backups/v1/{run_id}/manifest.json'
            manifest = json.loads(publisher.records[manifest_name])
            require({item['key'] for item in manifest['objects']} == {'books/original.png'},
                    'Post-cut objects leaked into the captured snapshot')
            require(manifest['objects'][0]['sha256'] == _digest(original), 'Captured original media bytes changed')
            require(next(reversed(publisher.records)) == f'backups/v1/{run_id}/verified.json',
                    'Publisher completion marker was not last')
            checks.append('Real PostgreSQL snapshot, API writes, SQL writes, and new MinIO objects overlap the bulk capture')
            checks.append('Real API/worker processes keep the same PIDs; online guard makes zero stop/start calls')
            checks.append('Full metadata validation reads old S2 after live URLs, SQL and privacy history change')

            restore_env = dict(environment, PGPORT=os.environ['ASB_FIXTURE_RESTORE_PORT'], PGSSLMODE='disable')
            dump_path = next(output_dir.glob('external-*/database.dump'))
            with _database(restore_env) as restored:
                restored.execute('DROP SCHEMA public CASCADE')
            run_pg(['pg_restore', '--no-password', '--no-owner', '--no-privileges',
                    '--dbname', 'runtime_test', str(dump_path)], restore_env)
            with _database(restore_env) as restored:
                require(restored.execute("SELECT title FROM books WHERE id='online-book'").fetchone() == ('before',),
                        'Restored database did not retain S before post-cut updates')
                require(restored.execute('SELECT value FROM online_fixture_counter WHERE id=1').fetchone() == (0,),
                        'Restored database contains post-cut writes')
                require(restored.execute('SELECT count(*) FROM privacy_journal_outbox').fetchone() == (1,),
                        'Restored snapshot absorbed a later privacy event')
                require(restored.execute("SELECT count(*) FROM books WHERE id='erase-book'").fetchone() == (1,),
                        'S dump did not retain the book deleted after S')
            checks.append('Real pg_dump/pg_restore retains S across exporter handoff and excludes all later mutations')
            from replay_privacy_journal import encode_replay_transfer
            from src.services.privacy_journal_verify import fingerprint_entries
            target_endpoint = os.environ['ASB_FIXTURE_RESTORE_S3']
            target_s3 = storage(target_endpoint)
            try:
                target_s3.create_bucket(Bucket=BUCKET)
                for item in manifest['objects']:
                    target_s3.put_object(Bucket=BUCKET, Key=item['key'],
                        Body=publisher.records[f'backups/v1/{run_id}/' + item['file']],
                        ContentType=item['content_type'])
            finally:
                target_s3.close()
            latest = journal.scan()
            transfer = json.loads(encode_replay_transfer(latest, fingerprint_entries(latest.committed), values['S3_PUBLIC_URL']))
            transfer['backup_marker'] = json.loads(publisher.records[f'backups/v1/{run_id}/verified.json'])
            transfer['erase_owner'] = erase_owner
            (workspace / 'replay-transfer.json').write_text(json.dumps(transfer))
            replay_token = uuid.uuid4().hex
            with _database(restore_env) as restored:
                restored.execute('CREATE TABLE public.asb_disposable_fixture_guard (token text PRIMARY KEY,s3_endpoint text)')
                restored.execute('INSERT INTO public.asb_disposable_fixture_guard VALUES (%s,%s)',
                                 (replay_token, target_endpoint))
            replay_env = dict(os.environ, TESTING='true', ASB_DISPOSABLE_REPLAY_TOKEN=replay_token,
                DATABASE_URL=f'postgresql+asyncpg://runtime_test:{CREDENTIAL}@127.0.0.1:{restore_env["PGPORT"]}/runtime_test',
                S3_ENDPOINT=target_endpoint, S3_DOWNLOAD_ENDPOINT=target_endpoint,
                S3_PUBLIC_URL=target_endpoint + '/' + BUCKET, S3_LEGACY_PUBLIC_URLS=values['S3_PUBLIC_URL'])
            replay_raw = run([sys.executable, '-B', str(Path(__file__).resolve()), '--report-dir', str(report_dir),
                              '--owned-replay', str(workspace)], env=replay_env, cwd=workspace / 'api',
                             timeout=60, log=report_dir / 'replay.log')
            replay_result = json.loads(replay_raw)
            require(replay_result['restore_authorized'] is False and replay_result['event_count'] == 3,
                    'Latest deletion replay did not remain quarantined')
            checks.append('S dump contains the later-deleted book; actual H1 replay removes it and tombstones the account')

            failures = []
            pre_dump_rejections = []
            deferred_attempts = {}
            def expect_failure(label, callback=None, alternate_journal=None, snapshot_factory=None,
                               expect_before_dump=False, expect_deferred=False):
                import backup_external
                failed_id = uuid.uuid4().hex
                original_run_pg = backup_external.run_pg
                dumps = []
                deferred_attempts[label] = 0
                def tracked_pg(command, *args, **kwargs):
                    if command[0] == 'pg_dump':
                        dumps.append(True)
                    return original_run_pg(command, *args, **kwargs)
                def observed_factory():
                    snapshot = snapshot_factory() if snapshot_factory else OnlineSnapshotCut(environment)
                    original_read = snapshot.read_snapshot
                    def tracked_read(callback):
                        require(snapshot.cut_released, 'Full metadata read preceded cut release')
                        deferred_attempts[label] += 1
                        return original_read(callback)
                    snapshot.read_snapshot = tracked_read
                    return snapshot
                try:
                    with patch.object(backup_external, 'run_pg', side_effect=tracked_pg):
                        run_online_backup(guard=guard, values=values, environment=environment, ca_file=ca_file,
                            output_dir=workspace / ('fail-' + failed_id), store=store, run_id=failed_id,
                            journal=alternate_journal or journal, session_factory=sessions,
                            verify_bindings=bindings, on_snapshot_ready=callback, snapshot_factory=observed_factory,
                            allow_local_fixture=True)
                except Exception:
                    require(f'backups/v1/{failed_id}/verified.json' not in publisher.records,
                            'A failed online backup published a verified marker')
                    if expect_before_dump:
                        require(not dumps and not any(name.startswith(f'backups/v1/{failed_id}/')
                                                       for name in publisher.records),
                                'Failed source validation started a dump or remote upload')
                        pre_dump_rejections.append(label)
                    if expect_deferred:
                        require(deferred_attempts[label] > 0, 'Failure never exercised released snapshot validation')
                    bindings()
                    failures.append(label)
                else:
                    raise RuntimeError('An injected online backup failure was accepted: ' + label)

            expect_failure('post_cut_same_size_overwrite', lambda: source.put_object(
                Bucket=BUCKET, Key='books/original.png', Body=b'x' * len(original), ContentType='image/png'))
            source.put_object(Bucket=BUCKET, Key='books/original.png', Body=original, ContentType='image/png')
            expect_failure('post_cut_delete', lambda: source.delete_object(Bucket=BUCKET, Key='books/original.png'))
            source.put_object(Bucket=BUCKET, Key='books/original.png', Body=original, ContentType='image/png')
            class LostHolderSnapshot(OnlineSnapshotCut):
                def read_snapshot(self, callback):
                    self._holder.close()
                    return super().read_snapshot(callback)
            expect_failure('snapshot_holder_connection_lost',
                snapshot_factory=lambda: LostHolderSnapshot(environment), expect_before_dump=True, expect_deferred=True)

            class PrescanRaceSnapshot(OnlineSnapshotCut):
                def __enter__(self):
                    # Each retry sees a new fully published event committed
                    # after scan0 but before S, so idle alone cannot reject it.
                    asyncio.run(event())
                    return super().__enter__()
            expect_failure('prescan_snapshot_checkpoint_mismatch',
                snapshot_factory=lambda: PrescanRaceSnapshot(environment), expect_before_dump=True, expect_deferred=True)
            with _database(environment) as locked:
                locked.execute('BEGIN')
                locked.execute('UPDATE online_fixture_counter SET value=value+1 WHERE id=1')
                expect_failure('busy_table_cut_is_nowait')
                locked.execute('ROLLBACK')
            with _database(environment) as db:
                db.execute("UPDATE jobs SET status='running' WHERE id='online-job'")
            expect_failure('active_job_defers_backup')
            with _database(environment) as db:
                db.execute("UPDATE jobs SET status='done' WHERE id='online-job'")

            # A lost DB lock connection does not cancel independent storage
            # work. The precommitted intent must reject a new online cut even
            # after its advisory lock disappeared and the S3 task is still live.
            entered_late = threading.Event()
            release_late = threading.Event()
            late_state = {}
            intent_id = uuid.uuid4().hex
            def delayed_write():
                from postgres_backup_fence import MEDIA_WRITE_LOCK
                with _database(environment) as db:
                    db.execute('INSERT INTO media_write_intents(id) VALUES (%s)', (intent_id,))
                    db.execute('BEGIN')
                    db.execute('SELECT pg_advisory_xact_lock_shared(%s)', (MEDIA_WRITE_LOCK,))
                    late_state['pid'] = db.info.backend_pid
                    entered_late.set()
                    require(release_late.wait(10), 'Late storage fixture was not released')
                    source.put_object(Bucket=BUCKET, Key='late-after-disconnect.png', Body=b'synthetic-late')
                    db.execute('DELETE FROM media_write_intents WHERE id=%s', (intent_id,))
                    db.execute('COMMIT')
            late = pool.submit(delayed_write)
            require(entered_late.wait(5), 'Late write did not commit its intent')
            with _database(environment) as db:
                require(db.execute('SELECT pg_terminate_backend(%s)', (late_state['pid'],)).fetchone() == (True,),
                        'Could not disconnect the owned synthetic writer')
            try:
                expect_failure('db_disconnect_late_storage_write_intent')
            finally:
                release_late.set()
                try:
                    late.result(timeout=5)
                except psycopg.Error:
                    pass
            require(source.head_object(Bucket=BUCKET, Key='late-after-disconnect.png')['ContentLength'] > 0,
                    'Delayed S3 write did not reproduce the DB-disconnect gap')
            with _database(environment) as db:
                require(db.execute('SELECT count(*) FROM media_write_intents WHERE id=%s',
                                   (intent_id,)).fetchone() == (1,), 'Disconnected writer lost its durable intent')
                # Fixture-only cleanup of this run's synthetic row.
                db.execute('DELETE FROM media_write_intents WHERE id=%s', (intent_id,))
            with _database(environment) as db:
                db.execute('UPDATE privacy_journal_outbox SET published_at=NULL WHERE event_id=%s', (first_event,))
            expect_failure('snapshot_outbox_unpublished')
            with _database(environment) as db:
                db.execute('UPDATE privacy_journal_outbox SET published_at=now() WHERE event_id=%s', (first_event,))
            incomplete = PrivacyJournal(DisposableMemoryJournalStore(), os.urandom(32))
            incomplete.begin('account_delete', str(uuid.uuid4()), revision=1)
            expect_failure('external_journal_pending', alternate_journal=incomplete,
                           expect_before_dump=True, expect_deferred=True)
            with _database(environment) as db:
                db.execute("UPDATE books SET cover_image_url=%s WHERE id='online-book'",
                           (values['S3_PUBLIC_URL'] + '/missing.png',))
            expect_failure('snapshot_missing_media_reference', expect_before_dump=True, expect_deferred=True)
            with _database(environment) as db:
                db.execute("UPDATE books SET cover_image_url=%s WHERE id='online-book'",
                           (values['S3_PUBLIC_URL'] + '/books/original.png',))

            # Real PG callback stall: watchdog must release source DML locks
            # before the blocked callback returns, not merely after it fails.
            entered = threading.Event()
            release = threading.Event()
            cut = OnlineSnapshotCut(environment, cut_timeout_seconds=.5)
            with cut:
                def slow_capture():
                    def callback(db):
                        db.execute('SELECT count(*) FROM books')
                        entered.set()
                        require(release.wait(5), 'Slow-cut test callback was not released')
                        return None
                    return cut.capture(callback)

                stalled = pool.submit(slow_capture)
                require(entered.wait(5), 'Slow-cut test did not acquire source locks')
                began = time.monotonic()
                with _database(environment) as db:
                    db.execute("SET statement_timeout='4s'")
                    db.execute('UPDATE online_fixture_counter SET value=value+1 WHERE id=1')
                dml_wait_ms = round((time.monotonic() - began) * 1000)
                require(dml_wait_ms < 3500 and not stalled.done(),
                        'Watchdog did not release DML while capture callback remained blocked')
                release.set()
                try:
                    stalled.result(timeout=5)
                except Exception:
                    failures.append('slow_cut_watchdog_releases_dml_before_callback_exit')
                else:
                    raise RuntimeError('Expired snapshot cut was accepted')

            checks.append('Overwrite, deletion, missing media, incomplete journal, and delayed callback all fail closed')
            # Stop only this owned cut child, including its timer thread. The
            # PostgreSQL server's independent idle timeout must release locks.
            stopped_source = """import json,os,signal
from postgres_backup_fence import OnlineSnapshotCut
e={k:os.environ[k] for k in ('PATH','PGHOST','PGPORT','PGUSER','PGPASSWORD','PGDATABASE','PGSSLMODE','PGSSLROOTCERT','PGCONNECT_TIMEOUT')}
try:
 with OnlineSnapshotCut(e) as cut:
  def frozen(db):
   db.execute('SELECT count(*) FROM books')
   print('OWNED_CUT_LOCKED',flush=True)
   os.kill(os.getpid(),signal.SIGSTOP)
   return {}
  cut.capture(frozen)
 print('UNEXPECTED_CUT_SUCCESS',flush=True)
except Exception:
 print('OWNED_CUT_REJECTED',flush=True)
"""
            stopped = subprocess.Popen([sys.executable, '-B', '-c', stopped_source], env=dict(os.environ, **environment),
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True)
            try:
                readable, _, _ = select.select([stopped.stdout], [], [], 5)
                require(bool(readable) and stopped.stdout.readline().strip() == 'OWNED_CUT_LOCKED',
                        'Owned stopped-cut child did not acquire locks')
                began = time.monotonic()
                with _database(environment) as db:
                    db.execute("SET statement_timeout='4s'")
                    db.execute('UPDATE online_fixture_counter SET value=value+1 WHERE id=1')
                stopped_dml_ms = round((time.monotonic() - began) * 1000)
                require(stopped_dml_ms < 3500, 'Server idle timeout did not release a stopped backup child')
                os.kill(stopped.pid, signal.SIGCONT)
                stdout, _ = stopped.communicate(timeout=5)
                require('OWNED_CUT_REJECTED' in stdout and 'UNEXPECTED_CUT_SUCCESS' not in stdout,
                        'Resumed expired cut was accepted')
                failures.append('sigstopped_cut_server_timeout_releases_dml')
            finally:
                if stopped.poll() is None:
                    os.kill(stopped.pid, signal.SIGCONT)
                    stop_process_group(stopped)
            bindings()
            return {'status': 'ONLINE_BACKUP_FIXTURE_PASSED', 'synthetic_data_only': True,
                'production_touched': False, 'restore_authorized': False,
                'source_postgres_major': 16, 'source_tls_verified': True,
                'read_only_after_share_lock_supported': read_only_after_share_lock,
                'publisher_is_http_transport_standin': True, 'media_provider': 'local_minio',
                'gcs_generation_preconditions_proved': False, 'services_stop_start_calls': runtime.operations,
                'concurrent_progress': progress, 'watchdog_dml_wait_ms': dml_wait_ms,
                'stopped_process_dml_wait_ms': stopped_dml_ms, 'latest_deletion_replay': replay_result,
                'result': result, 'timings_ms': timings, 'failure_cases': failures, 'checks': checks,
                'pre_dump_rejections': pre_dump_rejections,
                'post_cut_live_changes_precede_full_validation': mutations['applied'],
                'limits': ['MinIO conditional ETag reads do not prove GCS generation identity',
                           'Synthetic settings writes do not prove live paid generation traffic',
                           'Cut starts from idle jobs/purges; busy admission may defer backup only',
                           'No production restore or device playback is authorized']}
    except Exception:
        # This process contains fixed synthetic inputs only. Keep a bounded
        # validation diagnosis when the production publisher suppresses its
        # inner exception; never retain a database archive or media payload.
        from verify_backup_set import verify
        diagnosis = []
        for folder in (workspace / 'backup').glob('external-*'):
            try:
                diagnosis.append({'local_validation': verify(folder)['status']})
            except Exception as exc:
                diagnosis.append({'validation_error_type': type(exc).__name__, 'message': str(exc)})
        print(json.dumps({'fixture_local_diagnosis': diagnosis}), file=sys.stderr)
        raise
    finally:
        for process in reversed(processes):
            stop_process_group(process)
        source.close()
        asyncio.run(engine.dispose())


async def _replay(workspace):
    """Use the existing replayer with its original disposable-target guards."""
    from run_restore_replay_fixture import require_local_fixture
    require_local_fixture()
    require(workspace.name.startswith('storybook-restore-private-')
            and os.environ.get('ASB_ONLINE_FIXTURE') == 'true', 'Owned replay workspace is required')
    from sqlalchemy import text
    from src.core.database import AsyncSessionLocal, dispose_async_engines
    from src.services.privacy_journal import JournalScan, PrivacyJournal
    from src.services.privacy_journal_verify import fingerprint_entries, verify_current_outbox
    from replay_privacy_journal import replay_quarantined
    path = workspace / 'replay-transfer.json'
    require(path.is_file() and not path.is_symlink() and path.stat().st_size < 128 * 1024,
            'Owned synthetic replay transfer is invalid')
    payload = json.loads(path.read_bytes())
    entries = tuple(PrivacyJournal._validate_intent(item['id'], item) for item in payload['events'])
    require(fingerprint_entries(entries) == payload['journal_sha256'], 'Synthetic replay transfer hash changed')
    scan = JournalScan(entries, 0)
    try:
        async with AsyncSessionLocal() as db:
            require(await db.scalar(text("SELECT count(*) FROM books WHERE id='erase-book'")) == 1,
                    'Replay fixture no longer contains the S book')
            result = await replay_quarantined(db, scan, backup_marker=payload['backup_marker'])
            require(await db.scalar(text("SELECT count(*) FROM books WHERE id='erase-book'")) == 0,
                    'Replay resurrected a later deleted book')
            require(await db.scalar(text('SELECT deleted FROM account_identities WHERE user_key=:owner'),
                                    {'owner': payload['erase_owner']}) is True,
                    'Replay did not reapply latest account deletion')
            checkpoint = await verify_current_outbox(db, scan)
            require(checkpoint['journal_sha256'] == payload['journal_sha256'], 'Replay failed to apply H1 exactly')
        return {'status': result['status'], 'event_count': result['event_count'],
                'applied_count': result['applied_count'], 'restore_authorized': False,
                'post_cut_book_absent': True, 'post_cut_account_tombstoned': True}
    finally:
        await dispose_async_engines()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--owned-worker', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--owned-replay', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    os.umask(0o077)
    report_dir = args.report_dir.resolve()
    report_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.owned_replay:
        print(json.dumps(asyncio.run(_replay(args.owned_replay.resolve())), sort_keys=True))
        return 0
    if args.owned_worker:
        workspace = args.owned_worker.resolve()
        require(workspace.name.startswith('storybook-restore-private-') and (workspace / 'api').is_dir()
                and os.environ.get('ASB_ONLINE_FIXTURE') == 'true', 'Owned synthetic worker is required')
        print(json.dumps(_worker(workspace, report_dir), sort_keys=True))
        return 0

    env = clean_environment()
    pg_bin = find_pg16_bin(env, explicit=os.environ.get('ASB_FIXTURE_PG16_BIN'))
    env['PATH'] = str(pg_bin) + os.pathsep + env.get('PATH', '/usr/bin:/bin')
    endpoint = run(['docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}'], env=env).strip()
    require(endpoint.startswith('unix://') and (not env.get('DOCKER_HOST') or env['DOCKER_HOST'].startswith('unix://')),
            'Only a local Docker daemon is accepted')
    for image in (PG_IMAGE, MINIO_TEST_IMAGE, 'redis:7-alpine'):
        run(['docker', 'image', 'inspect', image, '--format', '{{.Id}}'], env=env)
    project = 'asb-online-' + uuid.uuid4().hex[:12]
    report = {'status': 'FAILED', 'synthetic_data_only': True, 'production_touched': False,
              'restore_authorized': False}
    try:
        with tempfile.TemporaryDirectory(prefix='storybook-restore-private-') as temporary:
            workspace = Path(temporary)
            api = workspace / 'api'
            api.mkdir()
            for name in ('src', 'alembic', 'assets'):
                shutil.copytree(ROOT / 'apps/api' / name, api / name,
                    ignore=shutil.ignore_patterns('.env*', '__pycache__', '*.pyc', '*.db', '*.pem', '*.key'))
            shutil.copy2(ROOT / 'apps/api/alembic.ini', api / 'alembic.ini')
            certs = workspace / 'certs'
            certs.mkdir()
            run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                 '-subj', '/CN=127.0.0.1', '-addext', 'subjectAltName=IP:127.0.0.1',
                 '-keyout', str(certs / 'server.key'), '-out', str(certs / 'server.crt')], env=env)
            pg = {'image': PG_IMAGE, 'environment': {'POSTGRES_USER': 'runtime_test',
                  'POSTGRES_PASSWORD': CREDENTIAL, 'POSTGRES_DB': 'runtime_test'},
                  'ports': ['127.0.0.1::5432'], 'tmpfs': ['/var/lib/postgresql/data'],
                  'healthcheck': {'test': ['CMD-SHELL', 'pg_isready -U runtime_test -d runtime_test'],
                                  'interval': '1s', 'timeout': '2s', 'retries': 40}}
            source_pg = dict(pg, volumes=[str(certs) + ':/fixture:ro'], entrypoint=['/bin/bash', '-ec'],
                command=['cp /fixture/server.crt /tmp/server.crt; cp /fixture/server.key /tmp/server.key; '
                         'chown postgres:postgres /tmp/server.*; chmod 600 /tmp/server.key; '
                         'exec docker-entrypoint.sh postgres -c ssl=on '
                         '-c ssl_cert_file=/tmp/server.crt -c ssl_key_file=/tmp/server.key'])
            compose_file = workspace / 'compose.json'
            compose_file.write_text(json.dumps({'services': {'source': source_pg, 'restored': pg,
                'minio': {'image': MINIO_TEST_IMAGE, 'environment': {'MINIO_ROOT_USER': 'runtime_test',
                    'MINIO_ROOT_PASSWORD': CREDENTIAL}, 'command': ['server', '/data'],
                    'ports': ['127.0.0.1::9000'], 'tmpfs': ['/data']},
                'restored_minio': {'image': MINIO_TEST_IMAGE, 'environment': {'MINIO_ROOT_USER': 'runtime_test',
                    'MINIO_ROOT_PASSWORD': CREDENTIAL}, 'command': ['server', '/data'],
                    'ports': ['127.0.0.1::9000'], 'tmpfs': ['/data']},
                'redis': {'image': 'redis:7-alpine', 'command': ['redis-server', '--save', '', '--appendonly', 'no'],
                          'ports': ['127.0.0.1::6379']}}}))
            compose = ['docker', 'compose', '--project-name', project, '--env-file', os.devnull,
                       '-f', str(compose_file)]
            try:
                run(compose + ['up', '-d', '--pull', 'never', '--wait', '--wait-timeout', '90'],
                    env=env, timeout=120, log=report_dir / 'dependencies.log')
                source_port = port_for(compose, 'source', 5432, env)
                restored_port = port_for(compose, 'restored', 5432, env)
                minio = f'http://127.0.0.1:{port_for(compose, "minio", 9000, env)}'
                redis_port = port_for(compose, 'redis', 6379, env)
                asyncio.run(wait_for_host_database(source_port))
                runtime_env = dict(env, PYTHONPATH=str(api) + os.pathsep + str(ROOT / 'scripts'),
                    PYTHONDONTWRITEBYTECODE='1', TESTING='false', ASB_ONLINE_FIXTURE='true', USE_CELERY='true',
                    DATABASE_URL=f'postgresql+asyncpg://runtime_test:{CREDENTIAL}@127.0.0.1:{source_port}/runtime_test',
                    DATABASE_MIGRATION_URL=f'postgresql://runtime_test:{CREDENTIAL}@127.0.0.1:{source_port}/runtime_test',
                    ASB_FIXTURE_RESTORE_PORT=str(restored_port),
                    ASB_FIXTURE_RESTORE_S3=f'http://127.0.0.1:{port_for(compose, "restored_minio", 9000, env)}',
                    REDIS_URL=f'redis://127.0.0.1:{redis_port}/0',
                    CELERY_BROKER_URL=f'redis://127.0.0.1:{redis_port}/1',
                    CELERY_RESULT_BACKEND=f'redis://127.0.0.1:{redis_port}/2',
                    S3_ENDPOINT=minio, S3_DOWNLOAD_ENDPOINT=minio, S3_PUBLIC_URL=minio + '/' + BUCKET,
                    S3_BUCKET=BUCKET, S3_ACCESS_KEY='runtime_test', S3_SECRET_KEY=CREDENTIAL, S3_REGION='us-east-1',
                    LLM_PROVIDER='mock', IMAGE_PROVIDER='mock', TTS_PROVIDER='mock', STT_PROVIDER='mock',
                    PHOTO_ANALYSIS_PROVIDER='mock', PHOTO_PROCESSING_ENABLED='false', AUDIO_FEATURE_ENABLED='false',
                    POD_ORDERING_ENABLED='false', PURCHASES_ENABLED='false', RATE_LIMIT_REQUESTS='100000',
                    API_IMAGE='synthetic-api:fixture', WORKER_IMAGE='synthetic-worker:fixture')
                run([sys.executable, '-B', '-m', 'alembic', 'upgrade', 'head'], env=runtime_env,
                    cwd=api, timeout=120, log=report_dir / 'migrations.log')
                raw = run([sys.executable, '-B', str(Path(__file__).resolve()), '--report-dir', str(report_dir),
                           '--owned-worker', str(workspace)], env=runtime_env, cwd=api,
                          timeout=180, log=report_dir / 'fixture.log')
                report = json.loads(raw)
            finally:
                run(compose + ['down', '--volumes', '--remove-orphans'], env=env, timeout=90,
                    log=report_dir / 'cleanup.log')
    except Exception as exc:
        report['error_type'] = type(exc).__name__
        raise
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        (report_dir / 'verification.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
