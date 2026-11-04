"""Admission for new paid AI work; reading, recovery and erasure stay available."""

import hashlib
import re
from functools import lru_cache

from src.core.config import settings
from src.core.exceptions import APIError


def generation_invitation_supported() -> bool:
    return settings.free_plan_first_book_trial and settings.generation_access_mode == "invite_only"


def generation_identity_hash(user_key: str) -> str:
    return hashlib.sha256(f"asb:generation-access:v1\0{user_key}".encode()).hexdigest()


@lru_cache(maxsize=1)
def _invited_hashes(configured: str) -> frozenset[str]:
    hashes = frozenset(item for value in configured.split(",") if (item := value.strip()))
    # Reject the entire configuration when any entry is malformed.
    return hashes if all(re.fullmatch(r"[a-f0-9]{64}", item) for item in hashes) else frozenset()


def require_generation_access(user_key: str | None) -> None:
    mode = settings.generation_access_mode
    if mode == "open":
        return
    if mode == "invite_only" and user_key:
        hashes = _invited_hashes(settings.generation_allowed_user_hashes)
        if hashes and generation_identity_hash(user_key) in hashes:
            return
    raise APIError(
        status_code=503,
        error_code="SERVICE_UNAVAILABLE",
        message="현재 이 계정에서는 새 AI 생성을 시작할 수 없습니다.",
        headers={"Retry-After": "3600"},
    )
