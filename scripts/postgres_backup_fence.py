"""Hold write-blocking table locks and export one PostgreSQL backup snapshot.

Caller must stop application admission and workers first and exclude concurrent
schema migrations. This protects existing public tables, not external storage.
"""

import math
import os
import re
import socket
import threading
import time

import psycopg
from psycopg import sql
from psycopg.pq import TransactionStatus


class BackupFenceError(RuntimeError):
    pass


MEDIA_WRITE_LOCK = 0x4153424D45444941


def media_write_lock_held(connection):
    return connection.execute("""SELECT EXISTS (
        SELECT 1 FROM pg_catalog.pg_locks
        WHERE locktype = 'advisory' AND pid = pg_backend_pid()
          AND classid = %s::oid AND objid = %s::oid AND objsubid = 1
          AND mode = 'ExclusiveLock' AND granted
    )""", (MEDIA_WRITE_LOCK >> 32, MEDIA_WRITE_LOCK & 0xffffffff)).fetchone()[0] is True


class PostgresBackupFence:
    def __init__(self, environment):
        self.environment = dict(environment)
        self._connection = None
        self._tables = None
        self.snapshot_id = None

    def _connect(self):
        values = self.environment
        params = {'host': values['PGHOST'], 'port': int(values['PGPORT']), 'user': values['PGUSER'],
                  'password': values['PGPASSWORD'], 'dbname': values['PGDATABASE'],
                  'sslmode': values['PGSSLMODE'], 'connect_timeout': 15}
        if values.get('PGSSLROOTCERT') and values['PGSSLMODE'] != 'disable':
            params['sslrootcert'] = values['PGSSLROOTCERT']
        if values.get('PGCHANNELBINDING'):
            params['channel_binding'] = values['PGCHANNELBINDING']
        return psycopg.connect(**params, autocommit=True)

    @staticmethod
    def _list_tables(connection):
        return tuple(connection.execute("""SELECT c.oid, c.relname FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind IN ('r','p') ORDER BY c.oid""").fetchall())

    def __enter__(self):
        try:
            connection = self._connect()
            self._connection = connection
            connection.execute("SET lock_timeout = '10s'")
            connection.execute('SELECT pg_advisory_lock(%s)', (MEDIA_WRITE_LOCK,))
            tables = self._list_tables(connection)
            if not tables:
                raise BackupFenceError('Public backup tables are missing')
            connection.execute('BEGIN ISOLATION LEVEL REPEATABLE READ')
            connection.execute("SET LOCAL lock_timeout = '10s'")
            names = sql.SQL(', ').join(sql.Identifier('public', name) for _, name in tables)
            connection.execute(sql.SQL('LOCK TABLE {} IN SHARE MODE').format(names))
            if any(name == 'media_write_intents' for _, name in tables):
                pending = connection.execute(
                    'SELECT EXISTS (SELECT 1 FROM public.media_write_intents)'
                ).fetchone()[0]
                if pending:
                    raise BackupFenceError('Unresolved media writes prevent a consistent backup')
            snapshot = connection.execute('SELECT pg_export_snapshot()').fetchone()[0]
            if not isinstance(snapshot, str) or not re.fullmatch('[0-9A-Fa-f-]{1,80}', snapshot):
                raise BackupFenceError('Database snapshot could not be exported')
            self._tables = tables
            self.snapshot_id = snapshot
            self.verify()
            return self
        except (BackupFenceError, KeyboardInterrupt, SystemExit):
            self.__exit__(None, None, None)
            raise
        except Exception:
            self.__exit__(None, None, None)
            raise BackupFenceError('Database write fence could not be established') from None

    def verify(self):
        try:
            if (self._connection is None or self._connection.closed
                    or self._connection.info.transaction_status != TransactionStatus.INTRANS):
                raise BackupFenceError('Database write fence is no longer active')
            if not media_write_lock_held(self._connection):
                raise BackupFenceError('Media write lock is no longer held')
            # A fresh session observes public DDL independently of the exported
            # snapshot. The operator must still exclude concurrent migrations.
            with self._connect() as check:
                if self._list_tables(check) != self._tables:
                    raise BackupFenceError('Public table inventory changed')
        except BackupFenceError:
            raise
        except Exception:
            raise BackupFenceError('Database write fence could not be verified') from None

    def verify_no_media_references(self):
        """Reject the empty-bucket path if application media may already be referenced."""
        self.verify()
        verify_no_media_references(self._connection)

    def verify_revision(self, expected_revision):
        self.verify()
        rows = self._connection.execute('SELECT version_num FROM public.alembic_version').fetchall()
        if rows != [(expected_revision,)]:
            raise BackupFenceError('Database revision does not match the planned media detach')

    def __exit__(self, *_):
        if self._connection is not None:
            try:
                self._connection.close()  # Closing rolls back and releases all locks.
            finally:
                self._connection = None
                self.snapshot_id = None


class OnlineSnapshotCut:
    """Transfer a bounded write-fenced cut to a long-lived read-only snapshot.

    The callback must check the idle source and freeze the media inventory.
    Full checkpoint/revision/reference reads may use read_snapshot() after
    release: that is the identical imported S, without holding write locks.
    Both TLS sessions are prepared before taking locks. No service is stopped.
    """

    _TABLE_QUERY = """SELECT c.oid, c.relname FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p') ORDER BY c.oid"""

    def __init__(self, environment, cut_timeout_seconds=2.0):
        if (type(cut_timeout_seconds) not in (int, float)
                or not math.isfinite(cut_timeout_seconds) or not 0 < cut_timeout_seconds <= 2.0):
            raise BackupFenceError('Online snapshot cut must have a bounded timeout')
        self.environment = dict(environment)
        self.cut_timeout_seconds = float(cut_timeout_seconds)
        self.snapshot_id = None
        self.cut_elapsed_ms = None
        self.cut_released = False
        self._cut_connection = None
        self._holder = None
        self._cut_socket = None
        self._holder_socket = None
        self._tables = None
        self._timer = None
        self._deadline = None
        self._started = None
        self._expired_at = None
        self._released_at = None
        self._expired = threading.Event()
        self._state_lock = threading.Lock()
        self._finished = False
        self._captured = False

    def _connect(self):
        return PostgresBackupFence(self.environment)._connect()

    @staticmethod
    def _socket_copy(connection):
        # A duplicate descriptor can interrupt blocked libpq/TLS I/O without
        # using the non-thread-safe Connection.close() from the watchdog.
        return socket.socket(fileno=os.dup(connection.fileno()))

    @staticmethod
    def _shutdown(stream):
        if stream is not None:
            try:
                stream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _expire(self):
        with self._state_lock:
            if self._finished:
                return
            self._expired_at = time.monotonic()
            self._expired.set()
            self._shutdown(self._cut_socket)
            self._shutdown(self._holder_socket)

    def _check_deadline(self):
        if self._expired.is_set() or time.monotonic() >= self._deadline:
            raise BackupFenceError('Online snapshot cut exceeded its deadline')

    def _stop_watchdog(self):
        with self._state_lock:
            self._finished = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer.join()
            self._timer = None

    def _close_cut(self):
        if self._cut_connection is not None:
            try:
                self._cut_connection.close()
            except Exception:
                # The raw socket shutdown remains the final release path.
                # Successful capture still requires the live pg_locks check.
                pass
            finally:
                self._shutdown(self._cut_socket)
                self._cut_connection = None

    def __enter__(self):
        try:
            self._cut_connection = self._connect()
            self._holder = self._connect()
            self._cut_socket = self._socket_copy(self._cut_connection)
            self._holder_socket = self._socket_copy(self._holder)
            # Even a paused process/GIL stall must not leave a server-side
            # write fence behind. A late query can consume at most one second
            # before cancellation, then at most one idle second before close.
            timeout = f'{max(1, int(min(self.cut_timeout_seconds, 1.0) * 1000))}ms'
            self._cut_connection.execute(sql.SQL(
                'SET statement_timeout = {}; SET idle_in_transaction_session_timeout = {}'
            ).format(sql.Literal(timeout), sql.Literal(timeout)))
            self._holder.execute(sql.SQL(
                "SET statement_timeout = {}; SET idle_in_transaction_session_timeout = '65min'"
            ).format(sql.Literal(timeout)))
            # BEGIN does not establish a snapshot. Import remains the first
            # snapshot operation on this holder, after the cut exports S.
            self._holder.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
            self._tables = PostgresBackupFence._list_tables(self._cut_connection)
            if not self._tables:
                raise BackupFenceError('Public backup tables are missing')
            return self
        except (KeyboardInterrupt, SystemExit):
            self.__exit__(None, None, None)
            raise
        except Exception:
            self.__exit__(None, None, None)
            raise BackupFenceError('Online snapshot connections could not be prepared') from None

    def capture(self, callback):
        if (not callable(callback) or self._captured or self._cut_connection is None
                or self._holder is None or self.snapshot_id is not None):
            raise BackupFenceError('Online snapshot capture requires fresh prepared connections')
        self._captured = True
        # Session-level advisory acquisition precedes BEGIN so S cannot be
        # established before the media fence. Cover that autocommit gap too;
        # idle_in_transaction_session_timeout alone cannot release it.
        timeout = f'{max(1, int(min(self.cut_timeout_seconds, 1.0) * 1000))}ms'
        try:
            self._cut_connection.execute(sql.SQL('SET idle_session_timeout = {}').format(sql.Literal(timeout)))
        except Exception:
            self.__exit__(None, None, None)
            raise BackupFenceError('Online snapshot deadline protection could not be prepared') from None
        self._started = time.monotonic()
        self._deadline = self._started + self.cut_timeout_seconds
        self._timer = threading.Timer(self.cut_timeout_seconds, self._expire)
        self._timer.daemon = True
        self._timer.start()
        success = False
        try:
            connection = self._cut_connection
            backend_pid = connection.info.backend_pid
            if connection.execute('SELECT pg_try_advisory_lock(%s)', (MEDIA_WRITE_LOCK,)).fetchone() != (True,):
                raise BackupFenceError('Media writes are active; online snapshot cut was not acquired')
            self._check_deadline()
            names = sql.SQL(', ').join(sql.Identifier('public', name) for _, name in self._tables)
            # Simple Query sends the ordered statements in one message. In
            # some environments pipeline execute() still communicates after
            # every command, making the bounded cross-region cut too slow.
            tables = connection.execute(sql.SQL('; ').join((
                sql.SQL('BEGIN ISOLATION LEVEL REPEATABLE READ'),
                sql.SQL('LOCK TABLE {} IN SHARE MODE NOWAIT').format(names),
                sql.SQL('SET TRANSACTION READ ONLY'), sql.SQL(self._TABLE_QUERY),
            )), prepare=False)
            self._check_deadline()
            for _ in range(3):
                if tables.nextset() is not True:
                    raise BackupFenceError('Online cut statement results are incomplete')
            if tuple(tables.fetchall()) != self._tables:
                raise BackupFenceError('Public table inventory changed')
            if tables.nextset() is not None:
                raise BackupFenceError('Online cut statement results are ambiguous')
            value = callback(connection)
            self._check_deadline()
            if (not isinstance(value, dict) or connection.closed
                    or connection.info.transaction_status != TransactionStatus.INTRANS):
                raise BackupFenceError('Online snapshot cut callback lost its fence')
            held, exported = connection.execute("""SELECT EXISTS (
                SELECT 1 FROM pg_catalog.pg_locks
                WHERE locktype = 'advisory' AND pid = pg_backend_pid()
                  AND classid = %s::oid AND objid = %s::oid AND objsubid = 1
                  AND mode = 'ExclusiveLock' AND granted
            ), pg_export_snapshot()""", (MEDIA_WRITE_LOCK >> 32, MEDIA_WRITE_LOCK & 0xffffffff)).fetchone()
            if held is not True:
                raise BackupFenceError('Online snapshot cut callback lost its fence')
            if not isinstance(exported, str) or not re.fullmatch('[0-9A-Fa-f-]{1,80}', exported):
                raise BackupFenceError('Database snapshot could not be exported')
            transfer = self._holder.execute(sql.SQL('; ').join((
                sql.SQL('SET TRANSACTION SNAPSHOT {}').format(sql.Literal(exported)),
                sql.SQL('SELECT pg_export_snapshot()'),
            )), prepare=False)
            self._check_deadline()
            if transfer.nextset() is not True:
                raise BackupFenceError('Read-only snapshot statement results are incomplete')
            transferred = transfer.fetchone()[0]
            if transfer.nextset() is not None:
                raise BackupFenceError('Read-only snapshot statement results are ambiguous')
            if not isinstance(transferred, str) or not re.fullmatch('[0-9A-Fa-f-]{1,80}', transferred):
                raise BackupFenceError('Read-only backup snapshot could not be exported')
            self._close_cut()
            self._check_deadline()
            released = self._holder.execute("""SELECT NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_locks WHERE pid = %s AND granted
                AND ((locktype = 'advisory' AND mode = 'ExclusiveLock')
                     OR (locktype = 'relation' AND mode = 'ShareLock'))
            )""", (backend_pid,)).fetchone()
            if released != (True,):
                raise BackupFenceError('Online snapshot cut locks were not released')
            with self._state_lock:
                self._check_deadline()
                self.snapshot_id = transferred
                self.cut_released = True
                self._released_at = time.monotonic()
                self._finished = True
            success = True
            return value
        except (BackupFenceError, KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            raise BackupFenceError('Online snapshot cut could not be established') from None
        finally:
            self._close_cut()
            self._stop_watchdog()
            end = self._released_at or self._expired_at or time.monotonic()
            self.cut_elapsed_ms = max(0, int((end - self._started) * 1000))
            if not success:
                self.__exit__(None, None, None)

    def verify(self):
        try:
            if (not self.cut_released or self.snapshot_id is None or self._holder is None
                    or self._holder.closed or self._holder.info.transaction_status != TransactionStatus.INTRANS):
                raise BackupFenceError('Read-only backup snapshot is no longer active')
            if self._holder.execute('SHOW transaction_read_only').fetchone() != ('on',):
                raise BackupFenceError('Backup snapshot is not read-only')
            with self._connect() as check:
                if PostgresBackupFence._list_tables(check) != self._tables:
                    raise BackupFenceError('Public table inventory changed')
        except BackupFenceError:
            raise
        except Exception:
            raise BackupFenceError('Read-only backup snapshot could not be verified') from None

    def read_snapshot(self, callback):
        """Run full validation on the original S2 holder after lock release.

        A lost holder never causes a reconnect or a read from the changing
        live database. The caller must finish these checks before dumping,
        uploading or recording backup success.
        """
        if not callable(callback):
            raise BackupFenceError('Snapshot inspection requires a callback')
        self.verify()
        holder = self._holder
        result = callback(holder)
        if self._holder is not holder:
            raise BackupFenceError('Read-only backup snapshot holder changed')
        self.verify()
        return result

    def __exit__(self, *_):
        self._close_cut()
        self._stop_watchdog()
        if self._holder is not None:
            try:
                self._holder.close()
            except Exception:
                pass
            finally:
                self._shutdown(self._holder_socket)
                self._holder = None
        for name in ('_cut_socket', '_holder_socket'):
            stream = getattr(self, name)
            if stream is not None:
                stream.close()
                setattr(self, name, None)
        self.snapshot_id = None


def verify_no_media_references(connection):
    """Inspect media references on the caller’s locked PostgreSQL snapshot."""
    columns = connection.execute("""SELECT table_name, column_name, data_type
        FROM information_schema.columns WHERE table_schema = 'public'
        AND ((column_name ~ '_url(_[a-z]{2})?$' AND data_type IN ('text', 'character varying'))
             OR (column_name IN ('image_keys', 'learning_assets') AND data_type IN ('json', 'jsonb'))
             OR (table_name = 'storage_purge_tasks' AND column_name = 'status'
                 AND data_type IN ('text', 'character varying')))"""
    ).fetchall()
    covered = {(table, column) for table, column, _ in columns}
    required = {('books', 'cover_image_url'), ('pages', 'image_url'), ('jobs', 'image_keys'),
                ('storage_purge_tasks', 'status')}
    if not required <= covered:
        raise BackupFenceError('Media reference schema could not be verified')
    checks = []
    for table, column, data_type in columns:
        if table == 'storage_purge_tasks' and column == 'status':
            checks.append(sql.SQL("EXISTS (SELECT 1 FROM public.storage_purge_tasks WHERE status IS DISTINCT FROM 'done')"))
            continue
        field = sql.Identifier(column)
        predicate = (sql.SQL("{}::jsonb NOT IN ('null', '[]', '{{}}')").format(field)
                     if data_type in ('json', 'jsonb') else sql.SQL("{} <> ''").format(field))
        checks.append(sql.SQL('EXISTS (SELECT 1 FROM {} WHERE {})').format(
            sql.Identifier('public', table), predicate))
    statement = sql.SQL('SELECT {}').format(sql.SQL(' OR ').join(checks))
    if connection.execute(statement).fetchone()[0]:
        raise BackupFenceError('Persisted media references require explicit migration')
