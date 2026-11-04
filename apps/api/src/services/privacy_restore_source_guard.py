"""Read-only source consistency fence; never authorizes a restored system.

The live restore path also locks public tables against direct SQL writes.
Storage permissions and independent journal durability are separate controls.
"""
import asyncio
from contextlib import asynccontextmanager

from sqlalchemy import text

from src.services.privacy_journal_outbox import _FENCE_KEY
from src.services.privacy_journal_verify import verify_current_outbox
from src.services.storage_write_guard import MEDIA_WRITE_LOCK


class SourceGuardError(RuntimeError):
    pass


_TABLES = text("""SELECT c.oid, format('%I.%I', n.nspname, c.relname)
    FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') ORDER BY c.oid""")


@asynccontextmanager
async def hold_consistent_source(db, journal, *, freeze_tables=False, legacy_source=False):
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
            if freeze_tables:
                await db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': MEDIA_WRITE_LOCK})
            await db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': _FENCE_KEY})
            if freeze_tables:
                tables = (await db.execute(_TABLES)).all()
                if not tables:
                    raise SourceGuardError('Public table inventory is empty')
                # PostgreSQL quotes both identifiers in the catalog query.
                connection = await db.connection()
                await connection.exec_driver_sql(
                    'LOCK TABLE ' + ', '.join(row[1] for row in tables) + ' IN SHARE MODE'
                )
                if (await db.execute(_TABLES)).all() != tables:
                    raise SourceGuardError('Public table inventory changed while locking')
                media_intents = await db.scalar(text("SELECT to_regclass('public.media_write_intents') IS NOT NULL"))
                if media_intents and await db.scalar(text('SELECT EXISTS (SELECT 1 FROM public.media_write_intents)')):
                    raise SourceGuardError('Unresolved media writes prevent a consistent source snapshot')
            scan = await asyncio.wait_for(asyncio.to_thread(journal.scan), timeout=120)
            before = await verify_current_outbox(db, scan, legacy_source=legacy_source)
            yield before, scan
            # Confirm the fence connection remains live and the observed source
            # and journal still agree before allowing the caller to proceed.
            await db.execute(text('SELECT 1'))
            if freeze_tables and (await db.execute(_TABLES)).all() != tables:
                raise SourceGuardError('Public table inventory changed while fenced')
            later = await asyncio.wait_for(asyncio.to_thread(journal.scan), timeout=120)
            after = await verify_current_outbox(db, later, legacy_source=legacy_source)
            if before != after:
                raise SourceGuardError('Source state changed while fenced')
    except SourceGuardError:
        raise
    except Exception:
        raise SourceGuardError('Source consistency could not be verified') from None
