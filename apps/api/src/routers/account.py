"""Parent-managed account backup and device recovery."""

import hashlib
import uuid

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.core.exceptions import APIError, RateLimitError
from src.core.rate_limit import rate_limiter
from src.core.utils import utcnow
from src.models.db import AccountIdentity
from src.models.dto import (
    AccountSessionResponse,
    RecoverAccountRequest,
    RecoverAccountResponse,
    RecoveryCodeResponse,
    RecoveryStatusResponse,
)
from src.services.account_recovery import issue_recovery_code, recover_account

router = APIRouter()
RECOVERY_ATTEMPT_WINDOW = 600
RECOVERY_ATTEMPT_LIMIT = 10


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
