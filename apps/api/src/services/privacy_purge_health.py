"""Report unresolved privacy erasure work without returning task details.

This read-only snapshot is a monitoring signal, not proof that every deleted
asset was recorded in the queue or physically erased from storage.
"""
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select

from src.models.db import StoragePurgeTask
from src.services.purge_queue import MAX_ATTEMPTS, UNATTEMPTED_GRACE_SECONDS

# Allow the deliberately delayed guard to age beyond its 15-minute grace.
MAX_PENDING_SECONDS = UNATTEMPTED_GRACE_SECONDS + 5 * 60
MAX_FUTURE_SKEW_SECONDS = 5 * 60
# These guards are intentionally cancelled when the referenced upload is
# committed. Cancellation of an actual erasure or an unknown reason alerts.
SAFE_CANCELLED_GUARDS = (
    'retell_copy_guard', 'character_reference_copy_guard', 'character_source_upload_guard',
    'avatar_attempt_guard', 'incomplete_narration', 'unpublished_illustration_edit', 'voice_sample_upload_guard',
)


async def assess_purge_queue(db, *, now):
    """Return only a binary result; missing tables/failed queries are ALERT."""
    try:
        if not isinstance(now, datetime) or now.tzinfo is not None:
            raise ValueError('Naive UTC is required')
        stale = now - timedelta(seconds=MAX_PENDING_SECONDS)
        future = now + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS)
        row = StoragePurgeTask
        unresolved = or_(
            row.status.is_(None),
            row.status.not_in(('pending', 'done', 'cancelled')),
            and_(row.status == 'cancelled', or_(
                row.reason.is_(None), row.reason.not_in(SAFE_CANCELLED_GUARDS),
            )),
            and_(row.status == 'pending', or_(
                row.attempts.is_(None), row.attempts < 0, row.attempts >= MAX_ATTEMPTS,
                row.created_at.is_(None), row.created_at > future, row.created_at <= stale,
                row.updated_at.is_(None), row.updated_at > future,
                row.last_error.is_not(None),
            )),
        )
        found = await db.scalar(select(row.id).where(unresolved).limit(1))
        return {'status': 'ALERT' if found is not None else 'OK', 'restore_authorized': False}
    except Exception:
        return {'status': 'ALERT', 'restore_authorized': False}
