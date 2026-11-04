"""Hold write-blocking table locks and export one PostgreSQL backup snapshot.

Caller must stop application admission and workers first and exclude concurrent
schema migrations. This protects existing public tables, not external storage.
"""

import re

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
