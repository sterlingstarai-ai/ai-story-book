"""Recovery exchanges a one-time backup secret for a new device credential.

The existing user_key remains an internal ownership identifier. A registered
identity must never fall back to authenticating that identifier after rotation.
"""

import hashlib
import hmac
import re
import secrets
from datetime import datetime

from sqlalchemy import or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.consent import latest_active_consent
from src.core.exceptions import APIError, AuthorizationError
from src.core.generation_access import generation_access_allowed, generation_invitation_supported
from src.core.utils import utcnow
from src.models.db import AccountIdentity, PrivacyJournalOutbox
from src.services.privacy_journal import CredentialState
from src.services.privacy_journal_transaction import (
    guardian_consent_published, journal_attached, lock_account_before_credential_change,
    prepare_transaction_event, publish_committed_event,
)

DEVICE_KEY_PATTERN = r"^asb_device_[A-Za-z0-9_-]{43}$"
RECOVERY_CODE_PATTERN = r"^ASB-R1-[A-Za-z0-9_-]{43}$"
_DEVICE_KEY_RE = re.compile(DEVICE_KEY_PATTERN)
_LEGACY_KEY_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_STORE_REVIEW_LOCK = int.from_bytes(
    hashlib.sha256(b"storybook:store-review-enrollment:v1").digest()[:8], "big", signed=True
)


def credential_hash(value: str, *, kind: str) -> str:
    return hashlib.sha256(f"asb:{kind}:v1\0{value}".encode()).hexdigest()


def deleted_account_error() -> APIError:
    return APIError(401, "ACCOUNT_DELETED", "계정 데이터가 삭제되었습니다.",
                    details={"account_deleted": True, "purge_retry_pending": True})


def authentication_error() -> APIError:
    return APIError(401, "UNAUTHORIZED", "계정 인증이 만료되었습니다. 복구 코드를 사용해주세요.")


async def resolve_user_key(db: AsyncSession, credential: str) -> str:
    """Resolve a device key, preserving unregistered legacy UUID accounts only."""
    modern = bool(_DEVICE_KEY_RE.fullmatch(credential))
    legacy = bool(_LEGACY_KEY_RE.fullmatch(credential))
    if not (modern or legacy):
        raise APIError(400, "BAD_REQUEST", "유효하지 않은 X-User-Key 형식입니다.")
    digest = credential_hash(credential, kind="device")
    identity = (
        await db.execute(select(AccountIdentity).where(AccountIdentity.device_key_hash == digest))
    ).scalar_one_or_none()
    if identity is not None:
        if identity.deleted:
            raise deleted_account_error()
        return identity.user_key
    # A modern credential can never create a legacy account. A canonical UUID
    # already enrolled (or deleted) can never bypass a rotated device credential.
    canonical = None if modern else await db.get(AccountIdentity, credential)
    if canonical is not None and canonical.deleted:
        raise deleted_account_error()
    if modern or canonical is not None:
        raise authentication_error()
    return credential


async def issue_recovery_code(db: AsyncSession, user_key: str, credential: str) -> tuple[str, datetime]:
    try:
        await lock_account_before_credential_change(db, user_key)
    except AuthorizationError:
        raise authentication_error() from None
    device_hash = credential_hash(credential, kind="device")
    identity = await db.get(AccountIdentity, user_key, populate_existing=True)
    if identity is None:
        if db.get_bind().dialect.name == "sqlite":
            # SQLite's legacy transaction mode can release the first SAVEPOINT
            # without a physical outer BEGIN, so a later rollback would leave
            # enrollment behind. An ordinary upsert starts a write transaction.
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            await db.execute(sqlite_insert(AccountIdentity).values(
                user_key=user_key, device_key_hash=device_hash,
            ).on_conflict_do_nothing())
        else:
            try:
                async with db.begin_nested():
                    db.add(AccountIdentity(user_key=user_key, device_key_hash=device_hash))
                    await db.flush()
            except IntegrityError:
                # Concurrent first enrollment must still pass the active-device CAS.
                pass
    code = "ASB-R1-" + secrets.token_urlsafe(32)
    now = utcnow()
    result = await db.execute(
        update(AccountIdentity)
        .where(
            AccountIdentity.user_key == user_key,
            AccountIdentity.device_key_hash == device_hash,
            AccountIdentity.deleted.is_(False),
        )
        .values(
            recovery_code_hash=credential_hash(code, kind="recovery"),
            previous_recovery_code_hash=None,
            recovery_code_created_at=now,
            updated_at=now,
        )
    )
    if result.rowcount != 1:
        await db.rollback()
        raise authentication_error()
    journal_event = await prepare_transaction_event(db, user_key=user_key, action='credential_revoke',
        credential_state=CredentialState(device_hash, credential_hash(code, kind='recovery'), None, now))
    await db.commit()
    await publish_committed_event(db, journal_event)
    return code, now


async def recover_account(
    db: AsyncSession, recovery_code: str, new_user_key: str
) -> tuple[str | None, datetime]:
    old_hash = credential_hash(recovery_code, kind="recovery")
    next_device_hash = credential_hash(new_user_key, kind="device")
    invalid = APIError(401, "RECOVERY_CODE_INVALID", "복구 코드를 확인해주세요.")
    review_pass = settings.store_review_pass_hash
    if re.fullmatch(r"[0-9a-f]{64}", review_pass) and hmac.compare_digest(
        credential_hash(recovery_code, kind="store-review"), review_pass
    ):
        return await _claim_store_review_slot(db, next_device_hash, invalid)
    if journal_attached(db):
        # Find only the lock key first, then repeat the authoritative lookup
        # after acquiring the same lock used by account deletion.
        owner = await db.scalar(select(AccountIdentity.user_key).where(
            or_(AccountIdentity.recovery_code_hash == old_hash,
                AccountIdentity.previous_recovery_code_hash == old_hash),
            AccountIdentity.deleted.is_(False)))
        if owner is None:
            raise invalid
        try:
            await lock_account_before_credential_change(db, owner)
        except AuthorizationError:
            raise invalid from None
    # Lock serializes competing redemption and exact retry on PostgreSQL. The
    # conditional UPDATE below also enforces single-winner semantics on SQLite.
    identity = (
        await db.execute(
            select(AccountIdentity)
            .where(
                or_(
                    AccountIdentity.recovery_code_hash == old_hash,
                    AccountIdentity.previous_recovery_code_hash == old_hash,
                ),
                AccountIdentity.deleted.is_(False),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if identity is None:
        raise invalid
    if identity.previous_recovery_code_hash == old_hash:
        # Retry can only acknowledge the same already-installed credential. It
        # cannot replay an old recovery code to install any other credential.
        if identity.device_key_hash == next_device_hash:
            return None, identity.recovery_code_created_at
        raise invalid
    if identity.device_key_hash == next_device_hash:
        raise APIError(400, "VALIDATION_ERROR", "새 기기 인증 키가 필요합니다.")
    code = "ASB-R1-" + secrets.token_urlsafe(32)
    now = utcnow()
    try:
        result = await db.execute(
            update(AccountIdentity)
            .where(
                AccountIdentity.user_key == identity.user_key,
                AccountIdentity.recovery_code_hash == old_hash,
                AccountIdentity.deleted.is_(False),
            )
            .values(
                device_key_hash=next_device_hash,
                recovery_code_hash=credential_hash(code, kind="recovery"),
                previous_recovery_code_hash=old_hash,
                recovery_code_created_at=now,
                updated_at=now,
            )
        )
        if result.rowcount != 1:
            await db.rollback()
            raise invalid
        journal_event = await prepare_transaction_event(db, user_key=identity.user_key, action='credential_revoke',
            credential_state=CredentialState(next_device_hash, credential_hash(code, kind='recovery'), old_hash, now))
        await db.commit()
        await publish_committed_event(db, journal_event)
    except IntegrityError:
        await db.rollback()
        raise invalid from None
    return code, now


async def _claim_store_review_slot(
    db: AsyncSession, device_hash: str, invalid: APIError
) -> tuple[str | None, datetime]:
    """Give each reviewer a reserved, separate account through the existing client."""
    slots = settings.store_review_account_slots.split(",")
    if (
        not journal_attached(db)
        or not generation_invitation_supported()
        or not 1 <= len(slots) <= 32
        or len(slots) != len(set(slots))
        or not all(_LEGACY_KEY_RE.fullmatch(slot) and generation_access_allowed(slot) for slot in slots)
    ):
        raise invalid

    if db.get_bind().dialect.name == "postgresql":
        # A stable lock serializes slot assignment across API replicas. Ordinary
        # account recovery retains its existing per-account locking.
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _STORE_REVIEW_LOCK})
    identity = await db.scalar(
        select(AccountIdentity).where(AccountIdentity.device_key_hash == device_hash)
    )
    if identity is not None:
        if (
            identity.user_key not in slots
            or identity.deleted
            or identity.recovery_code_created_at is None
        ):
            raise invalid
        return None, identity.recovery_code_created_at

    # Previous review devices remain barred even after their active hash was
    # rotated. The existing restore path replays this same credential history.
    if await db.scalar(
        select(PrivacyJournalOutbox.event_id)
        .where(
            PrivacyJournalOutbox.user_key.in_(slots),
            PrivacyJournalOutbox.action == "credential_revoke",
            PrivacyJournalOutbox.credential_state["device_hash"].as_string() == device_hash,
        )
        .limit(1)
    ):
        raise invalid
    code = "ASB-R1-" + secrets.token_urlsafe(32)
    code_hash = credential_hash(code, kind="recovery")
    now = utcnow()
    try:
        for slot in sorted(slots):
            try:
                await lock_account_before_credential_change(db, slot)
            except AuthorizationError:
                continue
            if settings.guardian_email_consent_enabled:
                consent = await latest_active_consent(db, slot)
                if consent is None or not await guardian_consent_published(db, consent):
                    continue
            result = await db.execute(
                update(AccountIdentity)
                .where(
                    AccountIdentity.user_key == slot,
                    AccountIdentity.deleted.is_(False),
                    AccountIdentity.device_key_hash == credential_hash(
                        slot, kind="store-review-reservation"
                    ),
                    AccountIdentity.recovery_code_hash.is_(None),
                    AccountIdentity.previous_recovery_code_hash.is_(None),
                    AccountIdentity.recovery_code_created_at.is_(None),
                )
                .values(
                    device_key_hash=device_hash,
                    recovery_code_hash=code_hash,
                    recovery_code_created_at=now,
                    updated_at=now,
                )
            )
            if result.rowcount == 1:
                event = await prepare_transaction_event(
                    db, user_key=slot, action="credential_revoke",
                    credential_state=CredentialState(device_hash, code_hash, None, now),
                )
                await db.commit()
                await publish_committed_event(db, event)
                return code, now
    except IntegrityError:
        await db.rollback()
    raise invalid


async def revoke_deleted_account(db: AsyncSession, user_key: str, credential: str) -> None:
    """Preserve only the tombstone needed to block old canonical-key fallback."""
    identity = await db.get(AccountIdentity, user_key)
    if identity is None:
        # Erasure must revoke legacy bearers too; a delayed retry must confirm
        # completion, never silently recreate balances/profiles under that key.
        db.add(AccountIdentity(user_key=user_key,
                               device_key_hash=credential_hash(credential, kind="device"),
                               deleted=True))
        await db.flush()
        return
    result = await db.execute(
        update(AccountIdentity)
        .where(
            AccountIdentity.user_key == user_key,
            AccountIdentity.device_key_hash == credential_hash(credential, kind="device"),
            AccountIdentity.deleted.is_(False),
        )
        .values(
            # Retain only a hash so the erased bearer can receive completion
            # on a lost-response retry; it cannot authenticate any data access.
            device_key_hash=credential_hash(credential, kind="device"),
            recovery_code_hash=None,
            previous_recovery_code_hash=None,
            recovery_code_created_at=None,
            deleted=True,
            updated_at=utcnow(),
        )
    )
    if result.rowcount != 1:
        # Recovery may have committed while the authenticated erasure request
        # was gathering rows. Undo all erasure/outbox writes in this transaction.
        await db.rollback()
        raise authentication_error()
