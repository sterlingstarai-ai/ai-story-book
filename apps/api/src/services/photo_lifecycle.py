"""Serialize photo publication and erasure within one owner's short transaction."""

import hashlib

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import AuthorizationError
from src.models.db import AccountIdentity


async def lock_photo_account(db: AsyncSession, user_key: str) -> None:
    """Lock before consent/character/job rows. At provider dispatch, hold through the body send.

    An unenrolled legacy account has no AccountIdentity row to lock. PostgreSQL's
    transaction advisory lock also covers that gap without creating an identity
    or changing legacy authentication. Every photo publish/erase path uses the
    same opaque namespace. SQLite has no advisory locks and is only the unit
    test/local dialect; it does not prove concurrent production serialization.
    """
    if db.get_bind().dialect.name == "postgresql":
        digest = hashlib.sha256(f"storybook:photo-lifecycle:v1:{user_key}".encode()).digest()
        lock_key = int.from_bytes(digest[:8], "big", signed=True)
        await db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})
    identity = await db.scalar(
        select(AccountIdentity)
        .where(AccountIdentity.user_key == user_key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if identity is not None and identity.deleted:
        raise AuthorizationError()
