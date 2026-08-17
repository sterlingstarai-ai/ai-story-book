"""보호자 동의 기록 API (PIPA/COPPA).

기존 UserConsent 모델/테이블(user_consents)을 사용한다. 모바일 동의 화면이
로컬에만 저장하던 동의를 서버에 영속화하고, 사진 기반 기능의 게이트 근거가 된다.
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends
from pydantic import ConfigDict, BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.consent import _has_active_photo_consent, latest_active_consent
from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.core.utils import utcnow
from src.models.db import Book, Character, UserConsent
from src.services.data_deletion import (
    collect_book_job_ids,
    collect_books_referencing_characters,
    collect_purgeable_image_keys,
    detach_series_from_characters,
    purge_book_children,
    purge_job_artifacts,
)
from src.services.purge_queue import (
    enqueue_purge_keys,
    enqueue_purge_prefix,
    run_purge_tasks,
)
from src.services.storage import (
    book_file_prefix,
    character_file_prefix,
    mask_file_prefix,
)

logger = structlog.get_logger()

router = APIRouter()


class ConsentGrantRequest(BaseModel):
    # R3-4b: 미지 필드를 조용히 버리면 오타 payload가 "동의 성공"으로 보인다. 실제로
    # tests/test_character_idempotency.py 가 `{"granted":.., "photo_consent":..}` 라는
    # 존재하지 않는 필드로 동의를 시도하고 200을 받아, 아무것도 grant 되지 않았는데
    # 사진 테스트가 통과하고 있었다(게이트가 꺼져 있어서만 green — false-green).
    # 동의는 규제 대상 행위이므로 fail-closed: 모르는 필드는 422로 거부한다.
    model_config = ConfigDict(extra="forbid")

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

    M9/R1-6: **사진 동의 항목을 해제**(photos=true → false)하는 재-grant는 철회와 같은
    파기 의무를 진다. 항목만 끄고 기수집 아동 사진·파생물을 남기면 '동의 철회'와 '동의
    항목 해제'의 의미가 이원화되고, 사용자가 사진 사용을 껐는데 얼굴은 그대로 남는다.
    """
    # 사진 동의 해제 여부를 새 행 기록 '전'에 판정(기존 활성 행 기준).
    photos_revoked = (
        await _has_active_photo_consent(db, user_key)
    ) and not request.photos

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

    if photos_revoked:
        failed_keys = await purge_photo_derived_data(
            db, user_key, reason="consent_photos_off"
        )
        if failed_keys:
            logger.warning(
                "photo consent withdrawal purge incomplete; queued for retry",
                user_key=user_key[:8] + "...",
                failed_key_count=len(failed_keys),
            )

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


async def purge_photo_derived_data(
    db: AsyncSession, user_key: str, *, reason: str
) -> list[str]:
    """사진/그림 파생(from_photo) 캐릭터와 그 파생물 전부를 파기한다. 반환: 실패 키 목록.

    철회(revoke)와 '사진 동의 해제(re-grant photos=false, M9/R1-6)'가 **같은 경로**를 쓰도록
    추출했다 — 두 벌 규칙이면 한 쪽이 샌다.

    순서가 계약이다:
      1. Series FK 명시 해제(H1) — 없으면 Postgres commit이 IntegrityError로 500,
         **철회가 영구 차단**된다(SQLite FK-off라 테스트가 구조적으로 못 잡음).
      2. 파기 대상 키 수집 → **durable outbox에 적재**(M8) — 행 삭제 후엔 URL 역산이
         불가능하므로, 파기 의도를 삭제와 같은 커밋에 남긴다.
      3. 커밋.
      4. 커밋 성공 **후**에만 스토리지 파기(H1 악화 항목). 커밋 전에 지우면 첫 실패에서
         아동 원본 사진은 이미 파괴됐는데 DB엔 동의가 active로 남는다.
    """
    result = await db.execute(
        select(Character).where(
            Character.user_key == user_key,
            Character.from_photo.is_(True),
        )
    )
    characters = result.scalars().all()
    character_ids = [c.id for c in characters]
    if not characters:
        return []

    # H2/R1-2: 스칼라 FK 뿐 아니라 character_ids(가족 다중) 참조 책도 파기 대상.
    book_ids = await collect_books_referencing_characters(db, user_key, character_ids)

    # N1: 파이프라인 이미지(images/{provider}/…)는 books/{id}/ prefix 밖이라 prefix 삭제로
    # 지워지지 않는다. 행을 지우면 image_url이 사라져 역산도 불가능해지므로 행 삭제 '전에'
    # 수집한다. M12(잡 중간 산출물)·H6(다른 책이 참조 중인 공유 키 제외)은 공통 진입점이 처리.
    image_keys = await collect_purgeable_image_keys(db, book_ids)

    # M7/R1-4: 잡 id는 **책 삭제 전**에 확보해야 한다 — 책이 사라지면 job_id 로 가는
    # 유일한 링크가 끊겨 아동 얼굴 묘사가 담긴 파생 텍스트가 영원히 남는다.
    job_ids = await collect_book_job_ids(db, book_ids)

    # H1/R1-1: 캐릭터 삭제 전 Series 단방향 FK 해제.
    await detach_series_from_characters(db, character_ids)

    await purge_book_children(db, book_ids)
    if book_ids:
        await db.execute(delete(Book).where(Book.id.in_(book_ids)))
    await purge_job_artifacts(db, job_ids)

    for character in characters:
        await db.delete(character)

    # M8/R1-5: 파기 지시를 삭제와 같은 트랜잭션에 적재(durable). 커밋 후 즉시 실행하고,
    # 실패·중단분은 job_monitor 스윕이 멱등 재실행한다.
    tasks = []
    for book_id in book_ids:
        task = enqueue_purge_prefix(
            db, user_key=user_key, reason=reason, prefix=book_file_prefix(book_id)
        )
        if task is not None:
            tasks.append(task)
        # F2: 인페인트 마스크(masks/{book_id}/…)도 함께 — books/{id}/ prefix 밖.
        mask_task = enqueue_purge_prefix(
            db, user_key=user_key, reason=reason, prefix=mask_file_prefix(book_id)
        )
        if mask_task is not None:
            tasks.append(mask_task)
    for character_id in character_ids:
        task = enqueue_purge_prefix(
            db,
            user_key=user_key,
            reason=reason,
            prefix=character_file_prefix(character_id),
        )
        if task is not None:
            tasks.append(task)
    tasks.extend(
        enqueue_purge_keys(db, user_key=user_key, reason=reason, keys=image_keys)
    )

    await db.commit()

    # 커밋 성공 후에만 실제 파기 — 실패분은 outbox에 pending으로 남는다.
    return await run_purge_tasks(db, tasks)


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

    failed_keys = await purge_photo_derived_data(
        db, user_key, reason="consent_revoke"
    )
    if failed_keys:
        # H8 계약: unknown 파기 결과를 success로 위장하지 않는다. 지시는 outbox에 남아
        # 스윕이 재시도하므로, 여기서는 관측 가능하게 남기고 응답은 철회 성공을 유지한다
        # (동의 철회 의사표시 기록 자체는 커밋 완료 — 재시도해도 500이 되면 안 된다).
        logger.warning(
            "consent revoke storage purge incomplete; queued for retry",
            user_key=user_key[:8] + "...",
            failed_key_count=len(failed_keys),
        )

    return _to_response(None, revoked=True)
