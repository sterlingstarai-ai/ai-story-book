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
from sqlalchemy.pool import NullPool

from narration_release_backup import SOURCE_REVISION
from narration_release_migration import TARGET_REVISION
from postgres_backup_fence import MEDIA_WRITE_LOCK, media_write_lock_held, verify_no_media_references

API = Path(__file__).resolve().parents[1] / 'apps' / 'api'
REVISIONS = (('9c1e3a7f620d', SOURCE_REVISION), ('7e28d9a6b451', '9c1e3a7f620d'),
             ('8a34e19c6b72', '7e28d9a6b451'), ('b3f149ac52d7', '8a34e19c6b72'),
             ('d52b81c9a734', 'b3f149ac52d7'), ('4c2d8f71b906', 'd52b81c9a734'),
             ('e7b93d2a601f', '4c2d8f71b906'), ('f32a7b4d190c', 'e7b93d2a601f'))


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
            self.engine = create_engine('postgresql+psycopg://', creator=self._connect, poolclass=NullPool)
            self.connection = self.engine.connect()
            # Hold the session lock on the migration backend itself. A
            # disconnect must release the lock and roll back the migration
            # together, including between the final check and COMMIT.
            self.connection.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
            self.connection.execute(text('SELECT pg_advisory_lock(:key)'), {'key': MEDIA_WRITE_LOCK})
            self.connection.commit()
            # Start the snapshot after taking the advisory lock, and discover
            # tables before opening the repeatable-read transaction.
            with self.engine.connect() as discovery:
                self.tables = self._tables(discovery)
            if not self.tables:
                raise NarrationFenceError('Public tables are missing')
            self.connection = self.connection.execution_options(isolation_level='REPEATABLE READ')
            self.transaction = self.connection.begin()
            self.connection.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
            quote = self.connection.dialect.identifier_preparer.quote_identifier
            tables = ', '.join(f'{quote("public")}.{quote(name)}' for _, name in self.tables)
            self.connection.exec_driver_sql('LOCK TABLE ' + tables + ' IN SHARE MODE')
            if any(name == 'media_write_intents' for _, name in self.tables):
                if self.connection.exec_driver_sql(
                    'SELECT EXISTS (SELECT 1 FROM public.media_write_intents)'
                ).scalar_one():
                    raise NarrationFenceError('Unresolved media writes prevent migration')
            self.snapshot_id = self.connection.exec_driver_sql('SELECT pg_export_snapshot()').scalar_one()
            if not isinstance(self.snapshot_id, str) or not re.fullmatch('[0-9A-Fa-f-]{1,80}', self.snapshot_id):
                raise NarrationFenceError('Snapshot identity is invalid')
            self.verify()
            return self
        except (KeyboardInterrupt, SystemExit):
            self.__exit__(None, None, None)
            raise
        except Exception:
            self.__exit__(None, None, None)
            raise NarrationFenceError('Database write fence could not be established') from None

    def verify(self):
        try:
            if self.connection is None or self.transaction is None or not self.transaction.is_active:
                raise NarrationFenceError('Database write fence is no longer active')
            self.connection.exec_driver_sql('SELECT 1')
            self._verify_media_lock()
            # Independent read catches new public tables outside this snapshot.
            with self.engine.connect() as check:
                if self._tables(check) != self.tables:
                    raise NarrationFenceError('Public table inventory changed')
        except NarrationFenceError:
            raise
        except Exception:
            raise NarrationFenceError('Database write fence could not be verified') from None

    def _verify_media_lock(self):
        driver = None
        try:
            driver = self.connection.connection.driver_connection
            held = media_write_lock_held(driver)
        except psycopg.Error as exc:
            if driver is not None and driver.closed:
                self.connection.invalidate(exc)
            raise NarrationFenceError('Media write lock could not be verified') from None
        except Exception:
            raise NarrationFenceError('Media write lock could not be verified') from None
        if held is not True:
            raise NarrationFenceError('Media write lock is no longer held')

    def verify_no_media_references(self):
        """Use the same locked snapshot that will be used for migration."""
        self.verify()
        verify_no_media_references(self.connection.connection.driver_connection)

    def verify_revision(self, expected_revision):
        self.verify()
        current = self.connection.exec_driver_sql('SELECT version_num FROM public.alembic_version').scalars().all()
        if current != [expected_revision]:
            raise NarrationFenceError('Database revision does not match the planned media detach')

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
        self._verify_media_lock()
        self.transaction.commit()

    def __exit__(self, *_):
        self._close_transaction()

    def _close_transaction(self):
        transaction, connection, engine = self.transaction, self.connection, self.engine
        self.transaction = self.connection = self.engine = self.snapshot_id = None
        self._migration_applied = False
        try:
            if transaction is not None and transaction.is_active:
                transaction.rollback()
        finally:
            try:
                if connection is not None:
                    connection.close()
            finally:
                if engine is not None:
                    engine.dispose()
