"""
Profiles Router
다자녀 프로필 CRUD
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.core.exceptions import NotFoundError, ValidationError
from src.core.utils import derive_age_band, utcnow
from src.models.db import ChildProfile

router = APIRouter()


class ProfileCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    # 생년월을 주면 age_band는 거기서 파생(부모 임의선택 무시). 없으면 age_band 사용.
    age_band: str = Field(default="5-7", pattern="^(3-5|5-7|7-9|adult)$")
    birth_year: Optional[int] = Field(default=None, ge=2005, le=2100)
    birth_month: Optional[int] = Field(default=None, ge=1, le=12)
    preferred_theme: Optional[str] = Field(default=None, max_length=30)
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    is_default: bool = False


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=40)
    age_band: Optional[str] = Field(default=None, pattern="^(3-5|5-7|7-9|adult)$")
    birth_year: Optional[int] = Field(default=None, ge=2005, le=2100)
    birth_month: Optional[int] = Field(default=None, ge=1, le=12)
    preferred_theme: Optional[str] = Field(default=None, max_length=30)
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    is_default: Optional[bool] = None


def _profile_to_dict(p: ChildProfile) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "age_band": p.age_band,
        "birth_year": p.birth_year,
        "birth_month": p.birth_month,
        "preferred_theme": p.preferred_theme,
        "avatar_url": p.avatar_url,
        "is_default": p.is_default,
    }


def _normalize_required_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValidationError("이름은 공백일 수 없습니다.")
    return normalized


def _normalize_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


@router.get("")
async def list_profiles(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    result = await db.execute(
        select(ChildProfile)
        .where(ChildProfile.user_key == user_key)
        .order_by(ChildProfile.created_at.asc())
    )
    profiles = result.scalars().all()
    return {
        "profiles": [
            {**_profile_to_dict(p), "created_at": p.created_at} for p in profiles
        ]
    }


@router.post("")
async def create_profile(
    request: ProfileCreateRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    count_result = await db.execute(
        select(ChildProfile).where(ChildProfile.user_key == user_key)
    )
    current = count_result.scalars().all()
    if len(current) >= 3:
        raise ValidationError("프로필은 최대 3개까지 생성할 수 있습니다.")

    normalized_name = _normalize_required_name(request.name)
    normalized_preferred_theme = _normalize_optional_text(request.preferred_theme)
    normalized_avatar_url = _normalize_optional_text(request.avatar_url)

    should_be_default = request.is_default or len(current) == 0

    # 생년월이 둘 다 있으면 age_band를 파생(DOB 우선, 클라 age_band 무시).
    band = request.age_band
    if request.birth_year and request.birth_month:
        band = derive_age_band(request.birth_year, request.birth_month)

    profile = ChildProfile(
        id=f"profile_{utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}",
        user_key=user_key,
        name=normalized_name,
        age_band=band,
        birth_year=request.birth_year,
        birth_month=request.birth_month,
        preferred_theme=normalized_preferred_theme,
        avatar_url=normalized_avatar_url,
        is_default=should_be_default,
    )

    if should_be_default:
        for p in current:
            p.is_default = False

    db.add(profile)
    await db.commit()
    await db.refresh(profile)

    return _profile_to_dict(profile)


@router.patch("/{profile_id}")
async def update_profile(
    profile_id: str,
    request: ProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    result = await db.execute(
        select(ChildProfile).where(
            ChildProfile.id == profile_id,
            ChildProfile.user_key == user_key,
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise NotFoundError("프로필", profile_id)

    if request.is_default is False and profile.is_default:
        raise ValidationError(
            "기본 프로필은 직접 해제할 수 없습니다. 다른 프로필을 기본으로 지정하세요."
        )

    data = request.model_dump(exclude_none=True)
    if "name" in data:
        data["name"] = _normalize_required_name(str(data["name"]))
    if "preferred_theme" in data:
        data["preferred_theme"] = _normalize_optional_text(data["preferred_theme"])
    if "avatar_url" in data:
        data["avatar_url"] = _normalize_optional_text(data["avatar_url"])

    for key, value in data.items():
        setattr(profile, key, value)

    # 생년월(갱신값 또는 기존값)이 둘 다 있으면 age_band 재파생(DOB 우선).
    if profile.birth_year and profile.birth_month:
        profile.age_band = derive_age_band(profile.birth_year, profile.birth_month)

    if request.is_default:
        others = await db.execute(
            select(ChildProfile).where(
                ChildProfile.user_key == user_key,
                ChildProfile.id != profile_id,
            )
        )
        for other in others.scalars().all():
            other.is_default = False

    await db.commit()
    await db.refresh(profile)

    return _profile_to_dict(profile)


@router.delete("/{profile_id}")
async def delete_profile(
    profile_id: str,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    result = await db.execute(
        select(ChildProfile).where(
            ChildProfile.id == profile_id,
            ChildProfile.user_key == user_key,
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise NotFoundError("프로필", profile_id)

    was_default = profile.is_default
    await db.delete(profile)
    await db.flush()

    if was_default:
        next_result = await db.execute(
            select(ChildProfile)
            .where(ChildProfile.user_key == user_key)
            .order_by(ChildProfile.created_at.asc())
        )
        next_profile = next_result.scalars().first()
        if next_profile:
            next_profile.is_default = True

    await db.commit()

    return {"status": "success", "profile_id": profile_id}
