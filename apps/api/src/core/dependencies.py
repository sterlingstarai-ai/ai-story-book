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
