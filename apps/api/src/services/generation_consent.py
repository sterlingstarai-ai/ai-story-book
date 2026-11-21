"""Authorize each child-data provider transmission against current account state."""

from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.consent import require_parental_consent, require_photo_consent
from src.core.exceptions import AuthorizationError
from src.models.db import Job
from src.services.photo_lifecycle import lock_photo_account

DispatchCheck = Callable[[AsyncSession], Awaitable[None]]
_dispatch_check: ContextVar[DispatchCheck | None] = ContextVar("generation_consent", default=None)


async def require_active_book_job(db: AsyncSession, job_id: str, user_key: str) -> None:
    await lock_photo_account(db, user_key)
    await require_parental_consent(db, user_key)
    photo_derived = await db.scalar(select(Job.photo_derived).where(
        Job.id == job_id, Job.user_key == user_key, Job.status.in_(("queued", "running")),
    ))
    if photo_derived is None:
        raise AuthorizationError("종료된 생성 요청입니다.")
    if photo_derived:
        await require_photo_consent(db, user_key)


@contextmanager
def provider_consent_scope(check: DispatchCheck):
    token = _dispatch_check.set(check)
    try:
        yield
    finally:
        _dispatch_check.reset(token)


async def check_current_generation(db: AsyncSession) -> None:
    check = _dispatch_check.get()
    if check is not None:
        await check(db)


async def send_with_consent(send, payload):
    """Keep withdrawal ordered with the WebSocket frame carrying child data."""
    check = _dispatch_check.get()
    if check is None:
        return await send(payload)

    from src.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await check(session)
        return await send(payload)


async def post_with_consent(client, url, **kwargs):
    """Order a request body send against withdrawal, releasing before model work.

    The HTTP transport reports completion after sending headers and body. On
    error, cancellation or a transport without tracing, session exit releases
    the transaction. Neither response parsing nor provider processing needs a
    database lock.
    """
    check = _dispatch_check.get()
    if check is None:
        return await client.post(url, **kwargs)

    from src.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await check(session)

        async def release_after_body(event, _info):
            if event in ("http11.send_request_body.complete", "http2.send_request_body.complete"):
                await session.rollback()

        return await client.post(url, extensions={"trace": release_after_body}, **kwargs)
