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


class PostgresBackupFence:
    def __init__(self, environment):
        self._environment = environment
        self._connection = None
        self._tables = None
        self.snapshot_id = None

    def _connect(self):
        values = self._environment
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
            tables = self._list_tables(connection)
            if not tables:
                raise BackupFenceError('Public backup tables are missing')
            connection.execute('BEGIN ISOLATION LEVEL REPEATABLE READ')
            connection.execute("SET LOCAL lock_timeout = '10s'")
            names = sql.SQL(', ').join(sql.Identifier('public', name) for _, name in tables)
            connection.execute(sql.SQL('LOCK TABLE {} IN SHARE MODE').format(names))
            snapshot = connection.execute('SELECT pg_export_snapshot()').fetchone()[0]
            if not isinstance(snapshot, str) or not re.fullmatch('[0-9A-Fa-f-]{1,80}', snapshot):
                raise BackupFenceError('Database snapshot could not be exported')
            self._tables = tables
            self.snapshot_id = snapshot
            self.verify()
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise BackupFenceError('Database write fence could not be established') from None

    def verify(self):
        try:
            if (self._connection is None or self._connection.closed
                    or self._connection.info.transaction_status != TransactionStatus.INTRANS):
                raise BackupFenceError('Database write fence is no longer active')
            self._connection.execute('SELECT 1')
            # A fresh session observes public DDL independently of the exported
            # snapshot. The operator must still exclude concurrent migrations.
            with self._connect() as check:
                if self._list_tables(check) != self._tables:
                    raise BackupFenceError('Public table inventory changed')
        except BackupFenceError:
            raise
        except Exception:
            raise BackupFenceError('Database write fence could not be verified') from None

    def __exit__(self, *_):
        if self._connection is not None:
            try:
                self._connection.close()  # Closing rolls back and releases all locks.
            finally:
                self._connection = None
                self.snapshot_id = None
