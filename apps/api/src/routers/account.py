"""Parent-managed account backup and device recovery."""

import hashlib
import asyncio
import re
import uuid

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.config import settings
from src.core.dependencies import get_user_key
from src.core.exceptions import APIError, RateLimitError
from src.core.generation_access import generation_identity_hash, generation_invitation_supported
from src.core.rate_limit import rate_limiter
from src.core.utils import utcnow
from src.models.db import AccountIdentity
from src.models.dto import (
    AccountSessionResponse,
    AccountMediaScopeResponse,
    GenerationInvitationResponse,
    RecoverAccountRequest,
    RecoverAccountResponse,
    RecoveryCodeResponse,
    RecoveryStatusResponse,
)
from src.services.account_recovery import issue_recovery_code, recover_account
from src.services.account_scope import AccountScopeUnavailable, derive_account_scope
from src.services.photo_lifecycle import lock_photo_account

router = APIRouter()
RECOVERY_ATTEMPT_WINDOW = 600
RECOVERY_ATTEMPT_LIMIT = 10
_APP_ACCOUNT_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


async def check_recovery_rate_limit(request: Request) -> None:
    """Bound anonymous redemption attempts, independent of attacker-chosen keys.

    Only the ASGI peer address is used. Configure trusted proxy forwarding at
    the server; never read client-supplied X-Forwarded-For here.
    """
    peer = request.client.host if request.client is not None else "unknown"
    bucket = hashlib.sha256(peer.encode()).hexdigest()
    key = f"account_recovery:{bucket}"
    now = utcnow().timestamp()
    try:
        redis = await rate_limiter.get_redis()
        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, 0, now - RECOVERY_ATTEMPT_WINDOW)
        pipe.zadd(key, {f"{now}:{uuid.uuid4().hex}": now})
        pipe.zcard(key)
        pipe.expire(key, RECOVERY_ATTEMPT_WINDOW + 1)
        results = await pipe.execute()
    except Exception as exc:
        raise APIError(
            503,
            "SERVICE_UNAVAILABLE",
            "계정 복구를 확인할 수 없습니다. 잠시 후 다시 시도해주세요.",
            details={"retry_after": 30},
            headers={"Retry-After": "30"},
        ) from exc
    if int(results[2]) > RECOVERY_ATTEMPT_LIMIT:
        raise RateLimitError(retry_after=RECOVERY_ATTEMPT_WINDOW)


@router.get("/session", response_model=AccountSessionResponse)
async def get_account_session(user_key: str = Depends(get_user_key)):
    return AccountSessionResponse()


@router.get("/generation-invitation", response_model=GenerationInvitationResponse)
async def get_generation_invitation(
    response: Response,
    user_key: str = Depends(get_user_key),
):
    if not generation_invitation_supported() or not _APP_ACCOUNT_ID.fullmatch(user_key):
        raise APIError(404, "NOT_FOUND", "이 계정의 베타 참여 ID를 사용할 수 없습니다.")
    response.headers["Cache-Control"] = "private, no-store"
    return GenerationInvitationResponse(invitation_id=generation_identity_hash(user_key))


@router.get('/media-scope', response_model=AccountMediaScopeResponse)
async def get_account_media_scope(
    response: Response,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    # Revalidate after the same lock used by account erasure; a request that
    # authenticated just before deletion must not obtain a new scope afterward.
    await lock_photo_account(db, user_key)
    try:
        scope = await asyncio.to_thread(derive_account_scope, owner=user_key,
            namespace=settings.account_scope_namespace, key_path=settings.account_scope_key_file,
            expected_sha256=settings.account_scope_key_sha256)
    except AccountScopeUnavailable:
        raise APIError(503, 'ACCOUNT_SCOPE_UNAVAILABLE', '계정 보관 범위를 확인할 수 없습니다.') from None
    response.headers['Cache-Control'] = 'private, no-store'
    return AccountMediaScopeResponse(scope_id=scope)


@router.get("/recovery", response_model=RecoveryStatusResponse)
async def get_recovery_status(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    identity = await db.get(AccountIdentity, user_key)
    return RecoveryStatusResponse(
        enabled=identity is not None and bool(identity.recovery_code_hash),
        recovery_code_created_at=identity.recovery_code_created_at if identity else None,
    )


@router.post("/recovery-code", response_model=RecoveryCodeResponse)
async def create_recovery_code(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    x_user_key: str = Header(...),
):
    code, created_at = await issue_recovery_code(db, user_key, x_user_key)
    return RecoveryCodeResponse(recovery_code=code, created_at=created_at)


@router.post(
    "/recover",
    response_model=RecoverAccountResponse,
    dependencies=[Depends(check_recovery_rate_limit)],
)
async def redeem_recovery_code(
    request: RecoverAccountRequest,
    db: AsyncSession = Depends(get_db),
):
    code, created_at = await recover_account(db, request.recovery_code, request.new_user_key)
    return RecoverAccountResponse(recovery_code=code, created_at=created_at)
