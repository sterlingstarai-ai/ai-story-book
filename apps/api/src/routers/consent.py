"""보호자 동의 기록 API (PIPA/COPPA).

기존 UserConsent 모델/테이블(user_consents)을 사용한다. 모바일 동의 화면이
로컬에만 저장하던 동의를 서버에 영속화하고, 사진 기반 기능의 게이트 근거가 된다.
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.consent import _has_active_photo_consent, latest_active_consent
from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.core.utils import utcnow
from src.models.db import Book, Character, UserConsent
from src.services.data_deletion import purge_book_children
from src.services.storage import delete_book_files, storage_service

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
    """보호자 동의 기록. granted 는 필수 동의(개인정보+데이터 처리) 충족 시 True.

    유저당 비철회 동의 행은 최대 1개가 되도록, 새 동의 시 기존 비철회 행을 폐기(supersede)한다.
    """
    # 기존 비철회 행 폐기(누적 방지 — 게이트/철회 일관성)
    await db.execute(
        update(UserConsent)
        .where(
            UserConsent.user_key == user_key,
            UserConsent.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )
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
    resp = _to_response(await latest_active_consent(db, user_key))
    # photos 게이트는 'granted'와 독립으로 평가되므로(require_photo_consent와 동일 소스),
    # JIT 판단이 서버 집행과 어긋나지 않게 photos 필드를 게이트 기준으로 보정한다.
    resp.photos = await _has_active_photo_consent(db, user_key)
    return resp


@router.post("/revoke", response_model=ConsentResponse)
async def revoke_consent(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """보호자 동의 철회 + 수집된 아동 사진/그림 파생 캐릭터 파기(PIPA/COPPA 철회 의무).

    이후 사진 기반 기능은 다시 차단되고, from_photo 캐릭터 레코드·원본 사진(스토리지)은 삭제된다.
    """
    # 비철회 동의 행 '전부' 폐기 — granted=False/photos=True 같은 잔여 행이 게이트를 열어두지 않도록.
    await db.execute(
        update(UserConsent)
        .where(
            UserConsent.user_key == user_key,
            UserConsent.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow(), granted=False)
    )

    result = await db.execute(
        select(Character).where(
            Character.user_key == user_key,
            Character.from_photo.is_(True),
        )
    )
    characters = result.scalars().all()
    character_ids = [c.id for c in characters]

    # 철회된 사진/그림 캐릭터로 만든 '책'에는 아이 얼굴 likeness가 렌더되어 남는다.
    # 캐릭터 행/원본만 지우면 책의 얼굴 이미지가 공개 URL에 영구 잔존하므로(PIPA/COPPA
    # 철회-파기 의무 위반), 그 책들을 자식 행·스토리지 파일까지 함께 파기한다.
    book_ids: list[str] = []
    if character_ids:
        books_result = await db.execute(
            select(Book.id).where(
                Book.user_key == user_key,
                Book.character_id.in_(character_ids),
            )
        )
        book_ids = [bid for (bid,) in books_result.all()]
        await purge_book_children(db, book_ids)
        if book_ids:
            await db.execute(delete(Book).where(Book.id.in_(book_ids)))

    for character in characters:
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

    # 스토리지 파일 파기는 실패해도 동의 철회 자체는 성공 처리(행은 이미 삭제됨).
    for book_id in book_ids:
        try:
            await delete_book_files(book_id)
        except Exception as e:  # pragma: no cover - 방어적
            logger.warning("book file delete failed on revoke", book_id=book_id, error=str(e))

    return _to_response(None)
