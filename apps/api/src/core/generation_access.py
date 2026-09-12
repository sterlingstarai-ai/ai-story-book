"""Admission for new paid AI work; reading, recovery and erasure stay available."""

import hashlib
import re

from src.core.config import settings
from src.core.exceptions import APIError


def generation_identity_hash(user_key: str) -> str:
    return hashlib.sha256(f"asb:generation-access:v1\0{user_key}".encode()).hexdigest()


def require_generation_access(user_key: str | None) -> None:
    mode = settings.generation_access_mode
    if mode == "open":
        return
    if mode == "invite_only" and user_key:
        hashes = {item.strip() for item in settings.generation_allowed_user_hashes.split(",") if item.strip()}
        # A malformed list must never accidentally open generation.
        if hashes and all(re.fullmatch(r"[a-f0-9]{64}", item) for item in hashes):
            if generation_identity_hash(user_key) in hashes:
                return
    raise APIError(
        status_code=503,
        error_code="SERVICE_UNAVAILABLE",
        message="현재 이 계정에서는 새 AI 생성을 시작할 수 없습니다.",
        headers={"Retry-After": "3600"},
    )
