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
    Page,
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
    BranchStoryNode,
    BranchStoryEdge,
)
from src.services.storage import delete_book_files, storage_service

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

    # FK 순서를 고려해 자식/로그 테이블부터 삭제
    if book_ids:
        await db.execute(delete(BranchStoryEdge).where(BranchStoryEdge.book_id.in_(book_ids)))
        await db.execute(delete(BranchStoryNode).where(BranchStoryNode.book_id.in_(book_ids)))
        await db.execute(delete(Page).where(Page.book_id.in_(book_ids)))
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
    await db.execute(delete(Series).where(Series.user_key == user_key))
    await db.execute(delete(Book).where(Book.user_key == user_key))
    await db.execute(delete(Job).where(Job.user_key == user_key))
    await db.execute(delete(Character).where(Character.user_key == user_key))
    await db.execute(delete(VoiceProfile).where(VoiceProfile.user_key == user_key))

    await db.commit()

    # 스토리지 파일 삭제는 실패해도 응답은 성공 처리
    storage_failures = 0
    for book_id in book_ids:
        try:
            await delete_book_files(book_id)
        except Exception as exc:
            storage_failures += 1
            logger.warning(
                "Failed to delete book files during user deletion",
                user_key=user_key,
                book_id=book_id,
                error=str(exc),
            )
    # 아동 사진/그림 파생 캐릭터 원본 파기(PIPA/GDPR 삭제권 — revoke 경로와 동일)
    for character_id in character_ids:
        try:
            await storage_service.delete_prefix(f"characters/{character_id}/")
        except Exception as exc:
            storage_failures += 1
            logger.warning(
                "Failed to delete character files during user deletion",
                user_key=user_key,
                character_id=character_id,
                error=str(exc),
            )

    return {
        "status": "success",
        "deleted_books": len(book_ids),
        "storage_delete_failures": storage_failures,
        "message": "내 데이터가 삭제되었습니다.",
    }
