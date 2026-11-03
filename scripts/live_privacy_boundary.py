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
            or not isinstance(url.host, str) or not url.host or not isinstance(url.database, str)
            or not url.database or not isinstance(url.username, str) or not url.username):
        raise LivePrivacyBoundaryError('Source database identity is invalid')
    query = dict(url.query)
    if query.get('sslmode') != 'verify-full' or query.get('channel_binding') != 'require':
        raise LivePrivacyBoundaryError('Verified source TLS and channel binding are required')
    canonical = {'host': url.host.lower(), 'port': url.port or 5432,
                 'database': url.database, 'user': url.username}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class LivePrivacyBoundary:
    def __init__(self, db, journal, checkpoint, scan, identity):
        self._db = db
        self._journal = journal
        self._checkpoint = checkpoint
        self._scan = scan
        self._identity = identity
        self._active = True

    async def verify(self):
        if not self._active:
            raise LivePrivacyBoundaryError('Live source fence is no longer active')
        try:
            if not self._db.in_transaction() or source_identity(self._db.get_bind().url) != self._identity:
                raise ValueError('source or transaction changed')
            await self._db.execute(text('SELECT 1'))
            import asyncio
            scan = await asyncio.wait_for(asyncio.to_thread(self._journal.scan), timeout=120)
            checkpoint = await verify_current_outbox(self._db, scan)
            if checkpoint != self._checkpoint or fingerprint_entries(scan.committed) != fingerprint_entries(self._scan.committed):
                raise ValueError('live privacy state changed')
            return {'status': 'LIVE_SOURCE_OUTBOX_MATCHES_WHILE_FENCED',
                    'writer_coverage_verified': False, 'latest_head_verified': False,
                    'restore_authorized': False}
        except LivePrivacyBoundaryError:
            raise
        except Exception:
            raise LivePrivacyBoundaryError('Live source boundary is no longer verified') from None


@asynccontextmanager
async def hold_live_privacy_boundary(db, journal, *, expected_source_identity):
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
        async with hold_consistent_source(db, journal) as (checkpoint, scan):
            row = (await db.execute(text("""SELECT current_database(), current_user, ssl
                FROM pg_catalog.pg_stat_ssl WHERE pid=pg_backend_pid()"""))).one_or_none()
            url = db.get_bind().url
            if row is None or row[0] != url.database or row[1] != url.username or row[2] is not True:
                raise LivePrivacyBoundaryError('Live source connection is not verified')
            if (not isinstance(scan, JournalScan) or scan.pending_count != 0
                    or scan.restore_authorized is not False or checkpoint.get('restore_authorized') is not False
                    or checkpoint.get('journal_sha256') != fingerprint_entries(scan.committed)):
                raise LivePrivacyBoundaryError('Live source journal is incomplete')
            plan = plan_quarantined_replay(scan)
            if plan.get('privacy_replay_authorized') is not False:
                raise LivePrivacyBoundaryError('Live source journal plan is invalid')
            boundary = LivePrivacyBoundary(db, journal, checkpoint, scan, identity)
            await boundary.verify()
            yield boundary
            await boundary.verify()
    except LivePrivacyBoundaryError:
        raise
    except Exception:
        raise LivePrivacyBoundaryError('Live source boundary could not be established') from None
    finally:
        if boundary is not None:
            boundary._active = False
