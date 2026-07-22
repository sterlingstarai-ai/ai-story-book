"""
Users Router
사용자 데이터 삭제 등 계정 관리
"""

import structlog
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends

from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.models.db import (
    Job,
    StoryDraftDB,
    ImagePromptsDB,
    Book,
    Series,
    Character,
    UserCredits,
    Subscription,
    CreditTransaction,
    DailyStreak,
    ReadingLog,
    ChildProfile,
    UserSettings,
    ScreenTimeLimit,
    UserConsent,
    IAPReceipt,
    AdRewardLog,
    PodOrder,
    VoiceProfile,
    PronunciationLog,
)
from src.services.data_deletion import collect_book_image_keys, purge_book_children
from src.services.storage import delete_book_files, delete_keys, storage_service

router = APIRouter()
logger = structlog.get_logger()


@router.delete("/me")
async def delete_my_data(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """
    내 데이터 전체 삭제.

    삭제 대상:
    - 책/페이지/잡/캐릭터/크레딧/구독/스트릭/설정/프로필/로그
    - 저장소의 책 파일
    """
    # 책 파일 제거를 위해 book ids 먼저 조회
    books_result = await db.execute(select(Book.id).where(Book.user_key == user_key))
    book_ids = [book_id for (book_id,) in books_result.all()]
    jobs_result = await db.execute(select(Job.id).where(Job.user_key == user_key))
    job_ids = [job_id for (job_id,) in jobs_result.all()]
    # 캐릭터 원본 사진/그림(characters/{id}/...)도 파기해야 함 — 행 삭제 전 id 확보
    chars_result = await db.execute(
        select(Character.id).where(Character.user_key == user_key)
    )
    character_ids = [cid for (cid,) in chars_result.all()]
    # N1: 파이프라인 표지·페이지 이미지 키를 image_url에서 역산 — 반드시 행 삭제 전에 수집.
    image_keys = await collect_book_image_keys(db, book_ids)

    # FK 순서를 고려해 자식/로그 테이블부터 삭제. 책-자식(공유 링크/퀴즈응답/오늘의 동화
    # 참조 등)은 공용 헬퍼로 일괄 정리 — 누락 시 Postgres에서 erasure 트랜잭션이 abort된다.
    await purge_book_children(db, book_ids)
    if job_ids:
        await db.execute(delete(StoryDraftDB).where(StoryDraftDB.job_id.in_(job_ids)))
        await db.execute(delete(ImagePromptsDB).where(ImagePromptsDB.job_id.in_(job_ids)))

    await db.execute(delete(PronunciationLog).where(PronunciationLog.user_key == user_key))
    await db.execute(delete(ReadingLog).where(ReadingLog.user_key == user_key))
    await db.execute(delete(PodOrder).where(PodOrder.user_key == user_key))
    await db.execute(delete(AdRewardLog).where(AdRewardLog.user_key == user_key))
    await db.execute(delete(IAPReceipt).where(IAPReceipt.user_key == user_key))
    await db.execute(delete(UserConsent).where(UserConsent.user_key == user_key))
    await db.execute(delete(ScreenTimeLimit).where(ScreenTimeLimit.user_key == user_key))
    await db.execute(delete(UserSettings).where(UserSettings.user_key == user_key))
    await db.execute(delete(ChildProfile).where(ChildProfile.user_key == user_key))
    await db.execute(delete(CreditTransaction).where(CreditTransaction.user_key == user_key))
    await db.execute(delete(Subscription).where(Subscription.user_key == user_key))
    await db.execute(delete(UserCredits).where(UserCredits.user_key == user_key))
    await db.execute(delete(DailyStreak).where(DailyStreak.user_key == user_key))
    # H7: Book(series_id→series.id FK)을 Series보다 먼저 삭제해야 FK 위반이 없다.
    # Series는 여전히 Character(series.character_id→characters.id FK)보다 앞이어야 한다.
    await db.execute(delete(Book).where(Book.user_key == user_key))
    await db.execute(delete(Series).where(Series.user_key == user_key))
    await db.execute(delete(Job).where(Job.user_key == user_key))
    await db.execute(delete(Character).where(Character.user_key == user_key))
    await db.execute(delete(VoiceProfile).where(VoiceProfile.user_key == user_key))

    await db.commit()

    # H8/G24: 스토리지 파기 실패를 삼키지 않고 표면화한다. 헬퍼가 실패키 목록을 반환하며,
    # 실패가 있으면 status='partial' + 식별 가능한 로그(아동 PII 잔존을 관측 가능하게).
    failed_keys: list[str] = []

    async def _purge(coro, **log_ctx):
        try:
            keys = await coro
        except Exception as exc:  # ClientError 외 예외도 실패로 표면화
            logger.warning("Storage purge raised during user deletion",
                           user_key=user_key, error=str(exc), **log_ctx)
            return ["<raised>"]
        if keys:
            logger.warning("Storage purge failures during user deletion",
                           user_key=user_key, failed_keys=keys, **log_ctx)
        return keys or []

    for book_id in book_ids:
        failed_keys.extend(await _purge(delete_book_files(book_id), book_id=book_id))
    # N1: books/{id}/ prefix 밖에 저장된 파이프라인 이미지(images/{provider}/{uuid} 등)를
    # image_url 역산 키로 직접 파기 — 아동 사진 파생 일러스트 잔존 방지(H8 실패 계약과 결합).
    if image_keys:
        failed_keys.extend(await _purge(delete_keys(image_keys)))
    # 아동 사진/그림 파생 캐릭터 원본 파기(PIPA/GDPR 삭제권 — revoke 경로와 동일)
    for character_id in character_ids:
        failed_keys.extend(await _purge(
            storage_service.delete_prefix(f"characters/{character_id}/"),
            character_id=character_id,
        ))
    # 가족 음성 샘플(voice-samples/{user_key}/...)도 파기 — biometric-adjacent PII 잔존 방지.
    failed_keys.extend(await _purge(
        storage_service.delete_prefix(f"voice-samples/{user_key}/")
    ))

    storage_failures = len(failed_keys)
    return {
        "status": "partial" if storage_failures else "success",
        "deleted_books": len(book_ids),
        "storage_delete_failures": storage_failures,
        "message": "내 데이터가 삭제되었습니다.",
    }
