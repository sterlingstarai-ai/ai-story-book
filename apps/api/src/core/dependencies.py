"""Common FastAPI dependencies."""

import re
from typing import Optional

from fastapi import Header, HTTPException

# UUID v4 format: 8-4-4-4-12 hex characters
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def get_user_key(
    x_user_key: str = Header(..., description="User identification key"),
) -> str:
    """
    Extract and validate user key from header.

    Raises:
        HTTPException: If X-User-Key header is missing or not a valid UUID
    """
    if not x_user_key or not _UUID_RE.match(x_user_key):
        raise HTTPException(status_code=400, detail="Invalid X-User-Key header: UUID format required")
    return x_user_key


def get_profile_id(
    x_profile_id: Optional[str] = Header(
        default=None,
        description="Optional active child profile id",
    ),
) -> Optional[str]:
    """
    Extract optional profile id from header.

    Format rule:
    - 1~60 chars
    - alnum, underscore, hyphen only
    """
    if x_profile_id is None:
        return None
    value = x_profile_id.strip()
    if value == "":
        return None
    if len(value) > 60 or not re.match(r"^[A-Za-z0-9_-]+$", value):
        raise HTTPException(status_code=400, detail="Invalid X-Profile-Id header")
    return value


async def validate_profile_ownership(db, user_key: str, profile_id: Optional[str]):
    """profile_id가 user_key 소유인지 검증(L12 공용 승격).

    형식만 검사하던 growth 라우터가 소유권을 검증하지 않아 삭제/타인 profile_id로
    전부 0인 리포트를 응답하고 dangling QuizAnswer를 저장하며 age_band 폴백 우회가
    가능했다. 무효/타인/삭제 profile_id면 422, 미지정(문자열 아님/빈값)이면 None(계정 단위).
    """
    from sqlalchemy import select

    from src.core.exceptions import ValidationError
    from src.models.db import ChildProfile

    if not isinstance(profile_id, str):
        return None
    normalized = profile_id.strip()
    if not normalized:
        return None
    profile = (
        await db.execute(
            select(ChildProfile).where(
                ChildProfile.id == normalized,
                ChildProfile.user_key == user_key,
            )
        )
    ).scalar_one_or_none()
    if not profile:
        raise ValidationError("유효하지 않은 프로필입니다.")
    return normalized
