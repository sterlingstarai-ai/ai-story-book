"""Exercise a cooperative S3/PG write fence against disposable local services.

This experiment is not connected to the application or the backup scheduler.
It deliberately demonstrates that loss of the lock connection permits a
still-running remote write. Its result never authorizes production use.
"""
from concurrent.futures import ThreadPoolExecutor
import os
import threading
import time
import uuid
from urllib.parse import urlsplit

import boto3
from botocore.config import Config
import psycopg

from run_restore_replay_fixture import require_local_fixture
from synthetic_storage_intent import LOCK, run_durable_mutation

_LOCK = LOCK


def _db_params():
    url = urlsplit(os.environ['DATABASE_URL'])
    return {'host': url.hostname, 'port': url.port, 'user': url.username,
            'password': url.password, 'dbname': url.path.lstrip('/'), 'sslmode': 'disable'}


def _storage():
    return boto3.client('s3', endpoint_url=os.environ['S3_ENDPOINT'], aws_access_key_id='runtime_test',
                        aws_secret_access_key='disposable-runtime-password', region_name='us-east-1',
                        config=Config(signature_version='s3v4', s3={'addressing_style': 'path'},
                                      connect_timeout=3, read_timeout=5, retries={'total_max_attempts': 1}))


def _exclusive(connection):
    connection.execute("SET lock_timeout = '300ms'")
    connection.execute('BEGIN')
    connection.execute('SELECT pg_advisory_xact_lock(%s)', (_LOCK,))


def _mutation(params, bucket, operation, entered, release, state):
    client = _storage()
    try:
        with psycopg.connect(**params, autocommit=True) as connection:
            connection.execute("SET lock_timeout = '300ms'")
            connection.execute('BEGIN')
            connection.execute('SELECT pg_advisory_xact_lock_shared(%s)', (_LOCK,))
            state['pid'] = connection.execute('SELECT pg_backend_pid()').fetchone()[0]
            entered.set()
            if not release.wait(10):
                raise RuntimeError('Synthetic writer was not released')
            if operation == 'put':
                client.put_object(Bucket=bucket, Key='put', Body=b'synthetic')
            elif operation == 'copy':
                client.copy_object(Bucket=bucket, Key='copy', CopySource={'Bucket': bucket, 'Key': 'source'})
            elif operation == 'delete':
                client.delete_object(Bucket=bucket, Key='deletable')
            else:
                raise RuntimeError('Unexpected fixture operation')
            # A disconnected lock session is noticed only after S3 changed.
            connection.execute('SELECT 1')
            connection.execute('COMMIT')
    finally:
        client.close()


def _expect_exclusive_blocked(params):
    with psycopg.connect(**params, autocommit=True) as connection:
        try:
            _exclusive(connection)
        except psycopg.errors.LockNotAvailable:
            return
        raise RuntimeError('Synthetic writer did not retain its shared fence')


def _durable_mutation(params, bucket, entered, release, state, payload, operation_id='one'):
    """Run the reusable synthetic intent protocol with controlled S3 timing."""
    client = _storage()
    try:
        if params != _db_params():
            raise RuntimeError('Unexpected synthetic database parameters')

        def on_locked(connection):
            state['pid'] = connection.execute('SELECT pg_backend_pid()').fetchone()[0]

        def before_io():
            if state.get('simulate_ambiguous_commit'):
                # Inject a lost acknowledgement AFTER a real committed insert.
                raise RuntimeError('Synthetic commit acknowledgement lost')
            entered.set()
            if not release.wait(10):
                raise RuntimeError('Synthetic durable writer was not released')

        def put():
            object_key = 'durable' if operation_id == 'one' else 'ambiguous'
            client.put_object(Bucket=bucket, Key=object_key, Body=payload)

        return run_durable_mutation(operation_id, put, on_locked=on_locked, before_io=before_io)
    finally:
        client.close()


def _pending_count(connection):
    return connection.execute("SELECT count(*) FROM public.asb_storage_intent_fixture WHERE status <> 'done'").fetchone()[0]


def main():
    require_local_fixture()
    params = _db_params()
    client = _storage()
    bucket = 'asb-write-fence-' + uuid.uuid4().hex
    created = False
    release = threading.Event()
    pool = ThreadPoolExecutor(max_workers=3)
    intent_table_created = False
    try:
        client.create_bucket(Bucket=bucket)
        created = True
        with psycopg.connect(**params, autocommit=True) as setup:
            setup.execute('CREATE TABLE public.asb_storage_intent_fixture (operation_id text PRIMARY KEY, status text NOT NULL)')
            intent_table_created = True
        client.put_object(Bucket=bucket, Key='source', Body=b'synthetic')
        client.put_object(Bucket=bucket, Key='deletable', Body=b'synthetic')
        # Exercise successful copy/delete through the same durable protocol,
        # and verify a completed operation ID never repeats remote I/O.
        def copy_once():
            client.copy_object(Bucket=bucket, Key='durable-copy',
                               CopySource={'Bucket': bucket, 'Key': 'source'})

        if run_durable_mutation('copy-success', copy_once) != 'done':
            raise RuntimeError('Synthetic durable copy did not complete')
        if run_durable_mutation('copy-success', lambda: (_ for _ in ()).throw(
                RuntimeError('Duplicate copy must not run'))) != 'reconciliation_required':
            raise RuntimeError('Synthetic durable copy was repeated')
        if run_durable_mutation('delete-success', lambda: client.delete_object(
                Bucket=bucket, Key='durable-copy')) != 'done':
            raise RuntimeError('Synthetic durable delete did not complete')
        if client.list_objects_v2(Bucket=bucket, Prefix='durable-copy').get('Contents'):
            raise RuntimeError('Synthetic durable delete did not remove the object')
        # A held exclusive lock blocks each cooperating PUT/copy/delete before S3.
        with psycopg.connect(**params, autocommit=True) as owner:
            _exclusive(owner)
            pending = [pool.submit(_mutation, params, bucket, op, threading.Event(), release, {})
                       for op in ('put', 'copy', 'delete')]
            for future in pending:
                try:
                    future.result(timeout=5)
                except psycopg.errors.LockNotAvailable:
                    continue
                raise RuntimeError('An S3 mutation bypassed the synthetic exclusive fence')
            response = client.list_objects_v2(Bucket=bucket)
            if {item['Key'] for item in response.get('Contents', [])} != {'source', 'deletable'}:
                raise RuntimeError('Blocked fixture mutations changed storage')
            owner.execute('ROLLBACK')

        # Cancelling the caller cannot terminate an already running S3 task;
        # the cooperative worker must retain its lock until it really exits.
        entered = threading.Event()
        state = {}
        future = pool.submit(_mutation, params, bucket, 'put', entered, release, state)
        if not entered.wait(5) or future.cancel():
            raise RuntimeError('Synthetic writer did not start')
        _expect_exclusive_blocked(params)
        release.set()
        future.result(timeout=10)
        with psycopg.connect(**params, autocommit=True) as owner:
            _exclusive(owner)
            owner.execute('ROLLBACK')

        # A real session loss releases the advisory lock before the separate
        # S3 operation completes: this intentionally proves the design gap.
        release.clear()
        entered = threading.Event()
        state = {}
        future = pool.submit(_mutation, params, bucket, 'copy', entered, release, state)
        if not entered.wait(5):
            raise RuntimeError('Synthetic disconnected writer did not start')
        with psycopg.connect(**params, autocommit=True) as killer:
            if not killer.execute('SELECT pg_terminate_backend(%s)', (state['pid'],)).fetchone()[0]:
                raise RuntimeError('Could not terminate synthetic lock session')
            deadline = time.monotonic() + 5
            while killer.execute('SELECT count(*) FROM pg_stat_activity WHERE pid=%s', (state['pid'],)).fetchone()[0]:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Synthetic lock session did not exit')
                time.sleep(.05)
        with psycopg.connect(**params, autocommit=True) as owner:
            _exclusive(owner)
            release.set()
            try:
                future.result(timeout=10)
            except psycopg.Error:
                pass
            else:
                raise RuntimeError('Disconnected writer unexpectedly reported success')
            client.head_object(Bucket=bucket, Key='copy')
            owner.execute('ROLLBACK')

        # A precommitted in-flight record gives the backup a fail-closed signal
        # even though DB disconnect releases the advisory lock. It is only a
        # fixture; no live writer or scheduler uses this prototype.
        release.clear()
        entered = threading.Event()
        state = {}
        future = pool.submit(_durable_mutation, params, bucket, entered, release, state, b'first')
        if not entered.wait(5):
            raise RuntimeError('Synthetic durable intent was not recorded')
        with psycopg.connect(**params, autocommit=True) as killer:
            if not killer.execute('SELECT pg_terminate_backend(%s)', (state['pid'],)).fetchone()[0]:
                raise RuntimeError('Could not terminate synthetic durable session')
            deadline = time.monotonic() + 5
            while killer.execute('SELECT count(*) FROM pg_stat_activity WHERE pid=%s', (state['pid'],)).fetchone()[0]:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Synthetic durable session did not exit')
                time.sleep(.05)
        with psycopg.connect(**params, autocommit=True) as owner:
            _exclusive(owner)
            if _pending_count(owner) != 1:
                raise RuntimeError('Lost in-flight intent did not block synthetic backup')
            owner.execute('ROLLBACK')
        # Repeated submission must refuse to issue a second S3 write while the
        # earlier request remains uncertain, even before it completes.
        retry = pool.submit(_durable_mutation, params, bucket, threading.Event(), release, {}, b'second')
        if retry.result(timeout=5) != 'reconciliation_required':
            raise RuntimeError('Synthetic uncertain operation was retried')
        with psycopg.connect(**params, autocommit=True) as owner:
            _exclusive(owner)
            # Even while the hypothetical backup owns the exclusive lock,
            # the disconnected writer can finish S3; its durable intent must
            # continue to make the backup decline publication.
            release.set()
            try:
                future.result(timeout=10)
            except psycopg.Error:
                pass
            else:
                raise RuntimeError('Lost durable session unexpectedly reported success')
            if _pending_count(owner) != 1:
                raise RuntimeError('Uncertain completed write did not block backup')
            owner.execute('ROLLBACK')
        retry = pool.submit(_durable_mutation, params, bucket, threading.Event(), release, {}, b'second')
        if retry.result(timeout=5) != 'reconciliation_required':
            raise RuntimeError('Completed uncertain operation was retried')
        body = client.get_object(Bucket=bucket, Key='durable')['Body']
        try:
            if body.read() != b'first':
                raise RuntimeError('Retry overwrote an uncertain synthetic write')
        finally:
            body.close()

        # A commit acknowledgement can be lost even after the DB committed.
        # Simulate that boundary and ensure no storage call is initiated.
        ambiguous_entered = threading.Event()
        ambiguous = pool.submit(_durable_mutation, params, bucket, ambiguous_entered, release,
                                {'simulate_ambiguous_commit': True}, b'never-written', 'ambiguous')
        try:
            ambiguous.result(timeout=5)
        except RuntimeError as error:
            if str(error) != 'Synthetic commit acknowledgement lost':
                raise
        else:
            raise RuntimeError('Synthetic lost commit acknowledgement was accepted')
        if ambiguous_entered.is_set() or client.list_objects_v2(Bucket=bucket, Prefix='ambiguous').get('Contents'):
            raise RuntimeError('An ambiguous intent initiated an S3 write')
        with psycopg.connect(**params, autocommit=True) as owner:
            _exclusive(owner)
            if _pending_count(owner) != 2:
                raise RuntimeError('Ambiguous committed intent did not block backup')
            owner.execute('ROLLBACK')
        print('Cooperative S3 fence blocks writes; DB loss permits late S3 but committed intent blocks backup and retry; ambiguous intent performs no S3')
    finally:
        release.set()
        pool.shutdown(wait=True, cancel_futures=True)
        try:
            if intent_table_created:
                with psycopg.connect(**params, autocommit=True) as cleanup:
                    cleanup.execute('DROP TABLE public.asb_storage_intent_fixture')
            if created:
                for key in ('source', 'deletable', 'put', 'copy', 'durable', 'ambiguous', 'durable-copy'):
                    client.delete_object(Bucket=bucket, Key=key)
                client.delete_bucket(Bucket=bucket)
        finally:
            client.close()


if __name__ == '__main__':
    main()
