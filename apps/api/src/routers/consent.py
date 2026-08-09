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
from src.services.data_deletion import collect_book_image_keys, purge_book_children
from src.services.storage import delete_book_files, delete_keys, storage_service

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


def _to_response(
    consent: Optional[UserConsent], *, revoked: bool = False
) -> ConsentResponse:
    """활성 동의 행 → 응답. 활성 행이 없을 때 `revoked` 로 '철회됨'과 '동의한 적 없음'을 구분한다.

    L3: 이전에는 활성 행이 없으면 무조건 `revoked=False` 를 돌려줬다. 철회 직후에도
    `revoked=False` 라 이 필드를 신뢰하는 클라이언트는 '철회된 적 없음'으로 오판한다
    (게이트 자체는 granted=False 로 정확히 막히므로 기능 영향은 없었다).
    """
    if consent is None:
        return ConsentResponse(
            granted=False,
            privacy=False,
            photos=False,
            data_processing=False,
            consent_version=settings.consent_current_version,
            revoked=revoked,
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



async def _has_revoked_consent(db: AsyncSession, user_key: str) -> bool:
    """이 사용자가 동의를 철회한 이력이 있는지(활성 행이 없을 때만 의미 있음)."""
    result = await db.execute(
        select(UserConsent.id)
        .where(
            UserConsent.user_key == user_key,
            UserConsent.revoked_at.is_not(None),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


@router.get("", response_model=ConsentResponse)
async def get_consent(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """현재 유효한 보호자 동의 상태 조회."""
    active = await latest_active_consent(db, user_key)
    revoked = False
    if active is None:
        revoked = await _has_revoked_consent(db, user_key)
    resp = _to_response(active, revoked=revoked)
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
    image_keys: list[str] = []
    if character_ids:
        books_result = await db.execute(
            select(Book.id).where(
                Book.user_key == user_key,
                Book.character_id.in_(character_ids),
            )
        )
        book_ids = [bid for (bid,) in books_result.all()]
        # N1: 파이프라인 이미지(images/{provider}/…)는 books/{id}/ prefix 밖이라 아래
        # delete_book_files로 지워지지 않는다. 행을 지우면 image_url이 사라져 역산도
        # 불가능해지므로(아동 likeness 영구 잔존), 행 삭제 '전에' 키를 수집한다.
        image_keys = await collect_book_image_keys(db, book_ids)
        await purge_book_children(db, book_ids)
        if book_ids:
            await db.execute(delete(Book).where(Book.id.in_(book_ids)))

    for character in characters:
        try:
            # H8: delete_prefix가 실패키 목록을 반환 — 삼키지 말고 표면화(PII 잔존 관측).
            failed = await storage_service.delete_prefix(f"characters/{character.id}/")
            if failed:
                logger.warning(
                    "character file delete failures on revoke",
                    character_id=character.id,
                    failed_keys=failed,
                )
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
            failed = await delete_book_files(book_id)
            if failed:
                logger.warning(
                    "book file delete failures on revoke",
                    book_id=book_id,
                    failed_keys=failed,
                )
        except Exception as e:  # pragma: no cover - 방어적
            logger.warning("book file delete failed on revoke", book_id=book_id, error=str(e))

    # N1: prefix 밖 파이프라인 이미지(아동 likeness 렌더)를 역산 키로 파기.
    if image_keys:
        try:
            failed = await delete_keys(image_keys)
            if failed:
                logger.warning(
                    "pipeline image delete failures on revoke", failed_keys=failed
                )
        except Exception as e:  # pragma: no cover - 방어적
            logger.warning("pipeline image delete failed on revoke", error=str(e))

    return _to_response(None, revoked=True)
