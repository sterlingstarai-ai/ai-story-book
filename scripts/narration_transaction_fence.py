"""One PostgreSQL transaction for a fenced snapshot and additive migrations.

An operator adapter must supply all external storage/admission controls, a
fresh backup and an isolated restore verification while this fence is alive.
This building block alone is not a deployment or a restore authorization.
"""
from pathlib import Path
import re

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import psycopg
from sqlalchemy import create_engine, text

from narration_release_backup import SOURCE_REVISION
from narration_release_migration import TARGET_REVISION

API = Path(__file__).resolve().parents[1] / 'apps' / 'api'
REVISIONS = (('9c1e3a7f620d', SOURCE_REVISION), ('7e28d9a6b451', '9c1e3a7f620d'),
             ('8a34e19c6b72', '7e28d9a6b451'), ('b3f149ac52d7', '8a34e19c6b72'),
             ('d52b81c9a734', 'b3f149ac52d7'), ('4c2d8f71b906', 'd52b81c9a734'),
             ('e7b93d2a601f', '4c2d8f71b906'))


class NarrationFenceError(RuntimeError):
    pass


class NarrationTransactionFence:
    def __init__(self, environment, *, allow_local_fixture=False):
        self.environment = environment
        is_fixture = (allow_local_fixture is True and environment.get('PGHOST') in {'127.0.0.1', '::1'}
                      and environment.get('PGSSLMODE') == 'disable')
        if not is_fixture and (environment.get('PGSSLMODE') != 'verify-full'
                               or not environment.get('PGSSLROOTCERT')):
            raise NarrationFenceError('Verified database TLS is required')
        self.engine = None
        self.connection = None
        self.transaction = None
        self.tables = None
        self.snapshot_id = None
        self._migration_applied = False

    def _connect(self):
        e = self.environment
        params = {'host': e['PGHOST'], 'port': int(e['PGPORT']), 'user': e['PGUSER'],
                  'password': e['PGPASSWORD'], 'dbname': e['PGDATABASE'],
                  'sslmode': e['PGSSLMODE'], 'connect_timeout': 15}
        if e.get('PGSSLROOTCERT') and e['PGSSLMODE'] != 'disable':
            params['sslrootcert'] = e['PGSSLROOTCERT']
        if e.get('PGCHANNELBINDING'):
            params['channel_binding'] = e['PGCHANNELBINDING']
        return psycopg.connect(**params)

    @staticmethod
    def _tables(connection):
        return tuple(connection.execute(text("""SELECT c.oid, c.relname FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind IN ('r','p') ORDER BY c.oid""")).all())

    def __enter__(self):
        try:
            self.engine = create_engine('postgresql+psycopg://', creator=self._connect, pool_pre_ping=True)
            # Discover tables before BEGIN: a prior SELECT inside a repeatable
            # read transaction would freeze a snapshot before writer locks.
            with self.engine.connect() as discovery:
                self.tables = self._tables(discovery)
            if not self.tables:
                raise NarrationFenceError('Public tables are missing')
            self.connection = self.engine.connect().execution_options(isolation_level='REPEATABLE READ')
            self.transaction = self.connection.begin()
            self.connection.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
            quote = self.connection.dialect.identifier_preparer.quote_identifier
            tables = ', '.join(f'{quote("public")}.{quote(name)}' for _, name in self.tables)
            self.connection.exec_driver_sql('LOCK TABLE ' + tables + ' IN SHARE MODE')
            self.snapshot_id = self.connection.exec_driver_sql('SELECT pg_export_snapshot()').scalar_one()
            if not isinstance(self.snapshot_id, str) or not re.fullmatch('[0-9A-Fa-f-]{1,80}', self.snapshot_id):
                raise NarrationFenceError('Snapshot identity is invalid')
            self.verify()
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise NarrationFenceError('Database write fence could not be established') from None

    def verify(self):
        try:
            if self.connection is None or self.transaction is None or not self.transaction.is_active:
                raise NarrationFenceError('Database write fence is no longer active')
            self.connection.exec_driver_sql('SELECT 1')
            # Independent read catches new public tables outside this snapshot.
            with self.engine.connect() as check:
                if self._tables(check) != self.tables:
                    raise NarrationFenceError('Public table inventory changed')
        except NarrationFenceError:
            raise
        except Exception:
            raise NarrationFenceError('Database write fence could not be verified') from None

    def migrate(self, *, assert_backup_restored):
        """Use the same locking transaction; caller must keep admission closed."""
        if self._migration_applied:
            raise NarrationFenceError('Migration already applied in this transaction')
        if assert_backup_restored() is not True:
            raise NarrationFenceError('Fresh isolated restore is unverified')
        self.verify()
        try:
            config = Config(str(API / 'alembic.ini'))
            config.set_main_option('script_location', str(API / 'alembic'))
            scripts = ScriptDirectory.from_config(config)
            context = MigrationContext.configure(self.connection)
            current = self.connection.exec_driver_sql('SELECT version_num FROM public.alembic_version').scalars().all()
            if current != [SOURCE_REVISION]:
                raise NarrationFenceError('Unexpected source revision')
            for revision, parent in REVISIONS:
                script = scripts.get_revision(revision)
                if script is None or script.down_revision != parent:
                    raise NarrationFenceError('Unexpected migration chain')
                with Operations.context(context):
                    script.module.upgrade()
                result = self.connection.execute(text('UPDATE public.alembic_version SET version_num=:new WHERE version_num=:old'),
                                                 {'new': revision, 'old': parent})
                if result.rowcount != 1:
                    raise NarrationFenceError('Migration revision could not be recorded')
            if self.connection.exec_driver_sql('SELECT version_num FROM public.alembic_version').scalars().all() != [TARGET_REVISION]:
                raise NarrationFenceError('Migration revision did not match')
            if assert_backup_restored() is not True:
                raise NarrationFenceError('Fresh isolated restore could not be reverified')
            self._migration_applied = True
            # New table inventory is intentionally changed by this transaction.
            # Caller must keep all other writers blocked through commit.
        except NarrationFenceError:
            raise
        except Exception:
            raise NarrationFenceError('Migration failed; transaction requires rollback') from None

    def commit(self):
        if self.transaction is None or not self.transaction.is_active or not self._migration_applied:
            raise NarrationFenceError('Migration transaction is not active')
        self.transaction.commit()

    def __exit__(self, *_):
        if self.transaction is not None and self.transaction.is_active:
            self.transaction.rollback()
        if self.connection is not None:
            self.connection.close()
        if self.engine is not None:
            self.engine.dispose()
        self.transaction = None
        self.connection = None
        self.snapshot_id = None
        self._migration_applied = False
