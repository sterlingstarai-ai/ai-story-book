"""Recovery exchanges a one-time backup secret for a new device credential.

The existing user_key remains an internal ownership identifier. A registered
identity must never fall back to authenticating that identifier after rotation.
"""

import hashlib
import re
import secrets
from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import APIError
from src.core.utils import utcnow
from src.models.db import AccountIdentity

DEVICE_KEY_PATTERN = r"^asb_device_[A-Za-z0-9_-]{43}$"
RECOVERY_CODE_PATTERN = r"^ASB-R1-[A-Za-z0-9_-]{43}$"
_DEVICE_KEY_RE = re.compile(DEVICE_KEY_PATTERN)
_LEGACY_KEY_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
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
    device_hash = credential_hash(credential, kind="device")
    identity = await db.get(AccountIdentity, user_key, populate_existing=True)
    if identity is None:
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
    await db.commit()
    return code, now


async def recover_account(
    db: AsyncSession, recovery_code: str, new_user_key: str
) -> tuple[str | None, datetime]:
    old_hash = credential_hash(recovery_code, kind="recovery")
    next_device_hash = credential_hash(new_user_key, kind="device")
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
    invalid = APIError(401, "RECOVERY_CODE_INVALID", "복구 코드를 확인해주세요.")
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
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise invalid from None
    return code, now


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
