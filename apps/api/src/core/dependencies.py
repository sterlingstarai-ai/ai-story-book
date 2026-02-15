"""Common FastAPI dependencies."""

import re

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
