"""Common FastAPI dependencies."""
from fastapi import Header, HTTPException


def get_user_key(x_user_key: str = Header(..., description="User identification key")) -> str:
    """
    Extract and validate user key from header.

    Raises:
        HTTPException: If X-User-Key header is missing or invalid
    """
    if not x_user_key or len(x_user_key) < 10:
        raise HTTPException(status_code=400, detail="Invalid X-User-Key header")
    return x_user_key
