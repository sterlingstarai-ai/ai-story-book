"""Opt-in, per-session transaction hooks for the unfinished privacy journal.

Runtime installation is disabled by default. The operator must establish full
coverage, retry, independent durability and quarantine before relying on it.
"""

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.exceptions import APIError
from src.models.db import PrivacyJournalOutbox, UserConsent
from src.services.privacy_journal_outbox import prepare_privacy_event, publish_privacy_event

_SESSION_KEY = 'privacy_journal'
logger = structlog.get_logger()


def journal_attached(db):
    return db.info.get(_SESSION_KEY) is not None


async def guardian_consent_published(db, consent: UserConsent) -> bool:
    """Require the latest consent decision in the independently stored journal."""
    event = await db.scalar(
        select(PrivacyJournalOutbox)
        .where(
            PrivacyJournalOutbox.user_key == consent.user_key,
            PrivacyJournalOutbox.action.in_(("consent_grant", "consent_revoke")),
        )
        .order_by(PrivacyJournalOutbox.revision.desc())
        .limit(1)
    )
    return bool(
        event and event.action == "consent_grant" and event.published_at is not None
        and event.consent_state == {
            "privacy": consent.privacy,
            "photos": consent.photos,
            "data_processing": consent.data_processing,
            "version": consent.consent_version,
        }
    )


async def lock_account_before_credential_change(db, user_key):
    """Use the deletion lock order when the experimental journal is injected."""
    if journal_attached(db):
        from src.services.photo_lifecycle import lock_photo_account
        await lock_photo_account(db, user_key)


async def prepare_transaction_event(db, *, user_key, action, **payload):
    journal = db.info.get(_SESSION_KEY)
    if journal is None:
        from src.core.config import settings
        if settings.privacy_journal_enabled:
            # A protected mutation must not silently bypass journaling when a
            # manually created session omitted the configured journal hook.
            await db.rollback()
            raise APIError(503, 'PRIVACY_RECORD_UNAVAILABLE',
                           '요청을 안전하게 기록하지 못했습니다. 잠시 후 다시 시도해주세요.')
        return None
    try:
        return await prepare_privacy_event(db, journal, user_key=user_key, action=action, **payload)
    except Exception:
        await db.rollback()
        raise APIError(503, 'PRIVACY_RECORD_UNAVAILABLE',
                       '요청을 안전하게 기록하지 못했습니다. 잠시 후 다시 시도해주세요.') from None


async def publish_committed_event(db, event_id):
    if event_id is None:
        return
    journal = db.info.get(_SESSION_KEY)
    try:
        if journal is None:
            raise RuntimeError('journal missing')
        factory = async_sessionmaker(db.bind, expire_on_commit=False)
        await publish_privacy_event(factory, journal, event_id)
    except Exception:
        # The actual user change is already committed. Leave its durable row
        # pending for a separate retry; never claim that publication succeeded.
        logger.warning('privacy journal publication pending')
