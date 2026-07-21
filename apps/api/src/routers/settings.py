"""
Settings Router
사용자 설정 및 화면시간 제한
"""

from __future__ import annotations

from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.models.db import ScreenTimeLimit, UserSettings

router = APIRouter()


class SettingsPatchRequest(BaseModel):
    language: Optional[str] = Field(default=None, pattern="^(ko|en)$")
    # 하루/월 경계 판정용 IANA 타임존(H2). 유효한 zoneinfo 키만 허용.
    timezone: Optional[str] = Field(default=None, max_length=40)
    dark_mode: Optional[bool] = None
    bedtime_notification_enabled: Optional[bool] = None
    bedtime_notification_hour: Optional[int] = Field(default=None, ge=0, le=23)
    bedtime_notification_minute: Optional[int] = Field(default=None, ge=0, le=59)
    sleep_mode_default_minutes: Optional[int] = Field(default=None, ge=10, le=60)
    allow_kakao_share: Optional[bool] = None
    screen_time_enabled: Optional[bool] = None
    daily_limit_minutes: Optional[int] = Field(default=None, ge=30, le=120)

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            ZoneInfo(v)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Invalid IANA timezone: {v!r}") from exc
        return v


async def _get_or_create_settings(db: AsyncSession, user_key: str) -> UserSettings:
    result = await db.execute(select(UserSettings).where(UserSettings.user_key == user_key))
    settings = result.scalar_one_or_none()
    if settings:
        return settings

    settings = UserSettings(user_key=user_key)
    db.add(settings)
    await db.flush()
    return settings


async def _get_or_create_limit(db: AsyncSession, user_key: str) -> ScreenTimeLimit:
    result = await db.execute(
        select(ScreenTimeLimit).where(ScreenTimeLimit.user_key == user_key)
    )
    limit = result.scalar_one_or_none()
    if limit:
        return limit

    limit = ScreenTimeLimit(user_key=user_key)
    db.add(limit)
    await db.flush()
    return limit


@router.get("")
async def get_settings(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    settings = await _get_or_create_settings(db, user_key)
    limit = await _get_or_create_limit(db, user_key)
    await db.commit()

    return {
        "language": settings.language,
        "timezone": settings.timezone,
        "dark_mode": settings.dark_mode,
        "bedtime_notification_enabled": settings.bedtime_notification_enabled,
        "bedtime_notification_hour": settings.bedtime_notification_hour,
        "bedtime_notification_minute": settings.bedtime_notification_minute,
        "sleep_mode_default_minutes": settings.sleep_mode_default_minutes,
        "allow_kakao_share": settings.allow_kakao_share,
        "screen_time_enabled": limit.enabled,
        "daily_limit_minutes": limit.daily_limit_minutes,
        "used_minutes_today": limit.used_minutes_today,
    }


@router.patch("")
async def patch_settings(
    request: SettingsPatchRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    settings = await _get_or_create_settings(db, user_key)
    limit = await _get_or_create_limit(db, user_key)

    data = request.model_dump(exclude_none=True)

    for key in (
        "language",
        "timezone",
        "dark_mode",
        "bedtime_notification_enabled",
        "bedtime_notification_hour",
        "bedtime_notification_minute",
        "sleep_mode_default_minutes",
        "allow_kakao_share",
    ):
        if key in data:
            setattr(settings, key, data[key])

    if "screen_time_enabled" in data:
        limit.enabled = data["screen_time_enabled"]
    if "daily_limit_minutes" in data:
        limit.daily_limit_minutes = data["daily_limit_minutes"]

    await db.commit()

    return {
        "status": "success",
        "message": "설정이 업데이트되었습니다.",
    }
