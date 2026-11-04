"""Hold a live source privacy fence while checking its outbox and journal.

This adapter is useful only while the authoritative source is reachable. It
does not prove every writer participates in the fence, independent durability,
or complete event coverage; it never authorizes a restore or reopening.
"""
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import re
import sys

from sqlalchemy import text

API = Path(__file__).resolve().parents[1] / 'apps' / 'api'
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

from src.services.privacy_journal import JournalScan, PrivacyJournal  # noqa: E402
from src.services.privacy_journal_verify import fingerprint_entries, verify_current_outbox  # noqa: E402
from src.services.privacy_restore_source_guard import hold_consistent_source  # noqa: E402
from replay_privacy_journal import plan_quarantined_replay  # noqa: E402


class LivePrivacyBoundaryError(RuntimeError):
    pass


def source_identity(url):
    """Hash non-secret endpoint identity; credentials are never returned."""
    if (url.get_backend_name() != 'postgresql' or url.drivername != 'postgresql+psycopg'
            or not isinstance(url.host, str) or not url.host or ',' in url.host or '/' in url.host
            or not isinstance(url.database, str)
            or not url.database or not isinstance(url.username, str) or not url.username):
        raise LivePrivacyBoundaryError('Source database identity is invalid')
    query = dict(url.query)
    if (set(query) - {'sslmode', 'sslrootcert', 'channel_binding', 'connect_timeout'}
            or any(not isinstance(value, str) or not value for value in query.values())
            or query.get('sslmode') != 'verify-full' or query.get('channel_binding') != 'require'):
        raise LivePrivacyBoundaryError('Verified source TLS and channel binding are required')
    canonical = {'host': url.host.lower(), 'port': url.port or 5432,
                 'database': url.database, 'user': url.username}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class LivePrivacyBoundary:
    def __init__(self, db, journal, checkpoint, identity, backend_pid, *, legacy_source=False):
        self._db = db
        self._journal = journal
        self._checkpoint = checkpoint
        self._identity = identity
        self._backend_pid = backend_pid
        self._transaction = db.sync_session.get_transaction()
        self._legacy_source = legacy_source
        self._active = True

    async def _verify_connection(self):
        if (not self._active or self._transaction is None or not self._transaction.is_active
                or self._db.sync_session.get_transaction() is not self._transaction
                or source_identity(self._db.get_bind().url) != self._identity
                or await self._db.scalar(text('SELECT pg_backend_pid()')) != self._backend_pid):
            raise LivePrivacyBoundaryError('Live source fence is no longer verified')

    async def verify(self):
        if not self._active:
            raise LivePrivacyBoundaryError('Live source fence is no longer active')
        try:
            await self._verify_connection()
            import asyncio
            scan = await asyncio.wait_for(asyncio.to_thread(self._journal.scan), timeout=120)
            checkpoint = await verify_current_outbox(self._db, scan, legacy_source=self._legacy_source)
            if (checkpoint != self._checkpoint or not self._transaction.is_active
                    or self._db.sync_session.get_transaction() is not self._transaction):
                raise ValueError('live privacy state changed')
            return {'status': 'LIVE_SOURCE_OUTBOX_MATCHES_WHILE_FENCED',
                    'journal_binding': (len(scan.committed), self._checkpoint['journal_sha256']),
                    'writer_coverage_verified': False, 'latest_head_verified': False,
                    'restore_authorized': False}
        except LivePrivacyBoundaryError:
            raise
        except Exception:
            raise LivePrivacyBoundaryError('Live source boundary is no longer verified') from None


@asynccontextmanager
async def hold_live_privacy_boundary(db, journal, *, expected_source_identity, legacy_source=False):
    """Hold the shared advisory fence until the consumer exits.

    `expected_source_identity` must be provisioned from an authenticated source
    separately from the backup. Matching it does not prove complete coverage.
    """
    if (not isinstance(expected_source_identity, str)
            or not re.fullmatch('[0-9a-f]{64}', expected_source_identity)
            or not isinstance(journal, PrivacyJournal) or db.in_transaction()):
        raise LivePrivacyBoundaryError('Live source boundary input is invalid')
    identity = source_identity(db.get_bind().url)
    if identity != expected_source_identity:
        raise LivePrivacyBoundaryError('Live source database does not match')
    boundary = None
    try:
        async with hold_consistent_source(db, journal, freeze_tables=True,
                                          legacy_source=legacy_source) as (checkpoint, scan):
            row = (await db.execute(text('SELECT current_database(), current_user, pg_backend_pid()'))).one()
            url = db.get_bind().url
            # Neon terminates TLS at its proxy. pg_stat_ssl describes the
            # server-side hop; inspect the connected libpq client instead.
            connection = await db.connection()
            driver = (await connection.get_raw_connection()).driver_connection
            parameters = driver.info.get_parameters()
            if (row[:2] != (url.database, url.username)
                    or parameters.get('host') != url.host
                    or parameters.get('port', '5432') != str(url.port or 5432)
                    or parameters.get('sslmode') != 'verify-full'
                    or parameters.get('channel_binding') != 'require'):
                raise LivePrivacyBoundaryError('Live source connection is not verified')
            if (not isinstance(scan, JournalScan) or scan.pending_count != 0
                    or scan.restore_authorized is not False or checkpoint.get('restore_authorized') is not False
                    or checkpoint.get('journal_sha256') != fingerprint_entries(scan.committed)):
                raise LivePrivacyBoundaryError('Live source journal is incomplete')
            plan = plan_quarantined_replay(scan)
            if plan.get('privacy_replay_authorized') is not False:
                raise LivePrivacyBoundaryError('Live source journal plan is invalid')
            boundary = LivePrivacyBoundary(db, journal, checkpoint, identity, row[2], legacy_source=legacy_source)
            yield boundary
            # The source guard compares the full outbox and journal at entry
            # and exit. Only recheck physical connection identity here.
            await boundary._verify_connection()
    except LivePrivacyBoundaryError:
        raise
    except Exception:
        raise LivePrivacyBoundaryError('Live source boundary could not be established') from None
    finally:
        if boundary is not None:
            boundary._active = False
