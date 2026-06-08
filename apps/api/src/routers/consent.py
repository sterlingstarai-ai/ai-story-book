"""보호자 동의 기록 API (PIPA/COPPA).

기존 UserConsent 모델/테이블(user_consents)을 사용한다. 모바일 동의 화면이
로컬에만 저장하던 동의를 서버에 영속화하고, 사진 기반 기능의 게이트 근거가 된다.
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.consent import latest_active_consent
from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.core.utils import utcnow
from src.models.db import Character, UserConsent
from src.services.storage import storage_service

logger = structlog.get_logger()

router = APIRouter()


class ConsentGrantRequest(BaseModel):
    privacy: bool = False
    photos: bool = False
    data_processing: bool = False
    consent_version: Optional[str] = None


class ConsentResponse(BaseModel):
    granted: bool
    privacy: bool
    photos: bool
    data_processing: bool
    consent_version: str
    revoked: bool


def _to_response(consent: Optional[UserConsent]) -> ConsentResponse:
    if consent is None:
        return ConsentResponse(
            granted=False,
            privacy=False,
            photos=False,
            data_processing=False,
            consent_version=settings.consent_current_version,
            revoked=False,
        )
    return ConsentResponse(
        granted=consent.granted,
        privacy=consent.privacy,
        photos=consent.photos,
        data_processing=consent.data_processing,
        consent_version=consent.consent_version,
        revoked=consent.revoked_at is not None,
    )


@router.post("", response_model=ConsentResponse)
async def grant_consent(
    request: ConsentGrantRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """보호자 동의 기록. granted 는 필수 동의(개인정보+데이터 처리) 충족 시 True."""
    consent = UserConsent(
        user_key=user_key,
        consent_version=request.consent_version or settings.consent_current_version,
        privacy=request.privacy,
        photos=request.photos,
        data_processing=request.data_processing,
        granted=bool(request.privacy and request.data_processing),
    )
    db.add(consent)
    await db.commit()
    await db.refresh(consent)
    return _to_response(consent)


@router.get("", response_model=ConsentResponse)
async def get_consent(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """현재 유효한 보호자 동의 상태 조회."""
    return _to_response(await latest_active_consent(db, user_key))


@router.post("/revoke", response_model=ConsentResponse)
async def revoke_consent(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """보호자 동의 철회 + 수집된 아동 사진/그림 파생 캐릭터 파기(PIPA/COPPA 철회 의무).

    이후 사진 기반 기능은 다시 차단되고, from_photo 캐릭터 레코드·원본 사진(스토리지)은 삭제된다.
    """
    consent = await latest_active_consent(db, user_key)
    if consent is not None:
        consent.revoked_at = utcnow()
        consent.granted = False

    result = await db.execute(
        select(Character).where(
            Character.user_key == user_key,
            Character.from_photo.is_(True),
        )
    )
    for character in result.scalars().all():
        try:
            await storage_service.delete_prefix(f"characters/{character.id}/")
        except Exception as e:  # pragma: no cover - 방어적
            logger.warning(
                "character file delete failed",
                character_id=character.id,
                error=str(e),
            )
        await db.delete(character)

    await db.commit()
    return _to_response(None)
