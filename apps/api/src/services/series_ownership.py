"""Series ownership is enforced at admission and delayed publication."""
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import AuthorizationError, NotFoundError
from src.models.db import Series


async def owned_series(db: AsyncSession, series_id: str, user_key: str, *, allow_missing: bool = False):
    series = await db.get(Series, series_id)
    if series is None:
        if allow_missing:
            return None
        raise NotFoundError("Series", series_id)
    if series.user_key != user_key:
        raise AuthorizationError()
    return series
