"""공통 유틸리티 함수"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)
