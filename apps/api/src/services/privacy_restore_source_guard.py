"""Read-only source consistency fence; never authorizes a restored system.

Only journal writers using the shared advisory lock are fenced. This does not
prove journal coverage, source identity, independent durability, target
isolation, or the safety of publishing a restored service.
"""
import asyncio
from contextlib import asynccontextmanager

from sqlalchemy import text

from src.services.privacy_journal_outbox import _FENCE_KEY
from src.services.privacy_journal_verify import verify_current_outbox


class SourceGuardError(RuntimeError):
    pass


@asynccontextmanager
async def hold_consistent_source(db, journal):
    """Keep cooperating Postgres privacy writers fenced while a caller works.

    The caller must retain quarantine even if this succeeds. The source must be
    a separately authenticated authoritative primary; that identity is not
    established by this primitive. A killed DB session releases the fence.
    """
    if db.in_transaction() or db.get_bind().dialect.name != 'postgresql':
        raise SourceGuardError('A fresh PostgreSQL session is required')
    try:
        async with db.begin():
            await db.execute(text("SET LOCAL lock_timeout = '5s'"))
            await db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': _FENCE_KEY})
            scan = await asyncio.wait_for(asyncio.to_thread(journal.scan), timeout=120)
            before = await verify_current_outbox(db, scan)
            yield before, scan
            # Confirm the fence connection remains live and the observed source
            # and journal still agree before allowing the caller to proceed.
            await db.execute(text('SELECT 1'))
            later = await asyncio.wait_for(asyncio.to_thread(journal.scan), timeout=120)
            after = await verify_current_outbox(db, later)
            if before != after:
                raise SourceGuardError('Source state changed while fenced')
    except SourceGuardError:
        raise
    except Exception:
        raise SourceGuardError('Source consistency could not be verified') from None
