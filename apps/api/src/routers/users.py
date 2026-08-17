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
from src.services.data_deletion import (
    collect_purgeable_image_keys,
    purge_book_children,
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
    # (계정 삭제는 그 사용자의 책 전부가 대상이라 H6 공유 제외에 걸릴 것이 없다 — 리텔의
    #  원본도 같은 사용자 소유이므로 함께 지워진다.)
    image_keys = await collect_purgeable_image_keys(db, book_ids)
    # M12/R3-5: 잡이 기록한 중간 산출물 키(실패·교체분)도 함께 — 현재 image_url 역산만으론
    # 덮이지 않는다. 계정 삭제는 **책이 없는 실패 잡**까지 대상이므로 job 전수로 읽는다
    # (책 경유 조인은 실패 잡의 고아 이미지를 놓친다).
    job_key_rows = await db.execute(
        select(Job.image_keys).where(Job.user_key == user_key)
    )
    for (raw_keys,) in job_key_rows.all():
        if isinstance(raw_keys, list):
            image_keys.extend(str(k) for k in raw_keys if k)
    image_keys = list(dict.fromkeys(image_keys))

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

    # M8/R1-5: 파기 지시를 **삭제와 같은 트랜잭션**에 적재한다(durable outbox).
    # 예전에는 커밋 후 in-memory 키 리스트만으로 파기했다 — 그 사이 프로세스가 죽거나 S3가
    # 장애면 행이 이미 없어 URL 역산이 불가능하므로 아동 PII가 영구 고아가 되고, 재시도는
    # 지울 행이 없어 200 success로 위장된다(unknown 결과 ≠ 성공).
    reason = "account_deletion"
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
    # 아동 사진/그림 파생 캐릭터 원본 파기(PIPA/GDPR 삭제권 — revoke 경로와 동일)
    for character_id in character_ids:
        task = enqueue_purge_prefix(
            db,
            user_key=user_key,
            reason=reason,
            prefix=character_file_prefix(character_id),
        )
        if task is not None:
            tasks.append(task)
    # 가족 음성 샘플(voice-samples/{user_key}/...)도 파기 — biometric-adjacent PII 잔존 방지.
    voice_task = enqueue_purge_prefix(
        db, user_key=user_key, reason=reason, prefix=f"voice-samples/{user_key}/"
    )
    if voice_task is not None:
        tasks.append(voice_task)
    # N1: books/{id}/ prefix 밖에 저장된 파이프라인 이미지(images/{provider}/{uuid} 등)를
    # image_url 역산 키로 직접 파기 — 아동 사진 파생 일러스트 잔존 방지.
    tasks.extend(
        enqueue_purge_keys(db, user_key=user_key, reason=reason, keys=image_keys)
    )

    await db.commit()

    # H8/G24: 스토리지 파기 실패를 삼키지 않고 표면화한다. 남은 실패는 outbox에 pending으로
    # 남아 job_monitor 스윕이 멱등 재실행하며, 응답은 그동안 success 를 주장하지 않는다.
    failed_keys = await run_purge_tasks(db, tasks)
    if failed_keys:
        logger.warning(
            "Storage purge failures during user deletion",
            user_key=user_key,
            failed_key_count=len(failed_keys),
        )

    storage_failures = len(failed_keys)
    return {
        "status": "partial" if storage_failures else "success",
        "deleted_books": len(book_ids),
        "storage_delete_failures": storage_failures,
        # M8: 미완 파기는 durable 하게 재시도된다는 사실을 응답에 명시(운영·감사 관측점).
        "purge_retry_pending": storage_failures > 0,
        "message": "내 데이터가 삭제되었습니다.",
    }
