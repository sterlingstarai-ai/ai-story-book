"""durable 스토리지 파기 큐 (M8/R1-5).

계정 삭제·동의 철회는 DB 행을 지운 **뒤** S3 객체를 지운다. 그 사이(커밋 성공 ~ 파기 완료)
프로세스가 죽거나 S3가 장애면, 파기 대상 키는 in-memory 리스트에만 있었으므로 영원히
사라진다 — 행이 없어 URL 역산도 불가능한 **아동 PII 영구 고아**. 재시도해도 삭제할 행이
없으니 200 success로 위장된다(unknown 결과 ≠ 성공).

그래서 파기 의도를 **삭제 트랜잭션과 같은 커밋**으로 DB에 남긴다(outbox). 커밋이 성공하면
파기 지시는 durable하고, 즉시 실행이 실패하거나 프로세스가 죽어도 job_monitor 스윕이
같은 지시를 멱등 재실행한다. 응답은 남은 pending 건수를 partial로 표면화한다(H8 계약).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Iterable, Optional

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.utils import utcnow
from src.models.db import StoragePurgeTask

logger = structlog.get_logger()

KIND_KEYS = "keys"
KIND_PREFIX = "prefix"

# 영구 실패로 스윕을 무한 점유하지 않도록 상한. 초과분은 status='failed'로 남아 관측 가능.
MAX_ATTEMPTS = 10

# '선기록 후 업로드'(H8/R1-3) 가드용 유예. 인라인 실행된 적 없는(attempts=0) 지시는
# 아직 작업이 진행 중일 수 있으므로 이 시간이 지나야 스윕이 손댄다 — 없으면 스윕이
# 방금 업로드된 **살아있는** 사진을 지운다.
UNATTEMPTED_GRACE_SECONDS = 15 * 60


def enqueue_purge_keys(
    db: AsyncSession,
    *,
    user_key: Optional[str],
    reason: str,
    keys: Iterable[str],
) -> list[StoragePurgeTask]:
    """개별 S3 키 파기 지시를 현재 트랜잭션에 적재한다(커밋은 호출부 책임)."""
    tasks: list[StoragePurgeTask] = []
    for key in dict.fromkeys(k for k in keys if k):
        task = StoragePurgeTask(
            user_key=user_key,
            reason=reason,
            kind=KIND_KEYS,
            target=key,
            status="pending",
        )
        db.add(task)
        tasks.append(task)
    return tasks


def enqueue_purge_prefix(
    db: AsyncSession,
    *,
    user_key: Optional[str],
    reason: str,
    prefix: str,
) -> Optional[StoragePurgeTask]:
    """prefix 하위 전체 파기 지시를 현재 트랜잭션에 적재한다(커밋은 호출부 책임)."""
    if not prefix:
        return None
    task = StoragePurgeTask(
        user_key=user_key,
        reason=reason,
        kind=KIND_PREFIX,
        target=prefix,
        status="pending",
    )
    db.add(task)
    return task


def cancel_purge_task(task: Optional[StoragePurgeTask]) -> None:
    """선기록 가드를 무효화한다(H8/R1-3) — 반드시 대상을 살리는 커밋과 **같은 트랜잭션**에서.

    별도 커밋으로 취소하면, 캐릭터 커밋은 성공했는데 취소 커밋이 실패하는 창에서 스윕이
    **살아있는** 아동 사진을 파기한다.
    """
    if task is None:
        return
    task.status = "cancelled"
    task.updated_at = utcnow()


async def _execute_task(task: StoragePurgeTask) -> list[str]:
    """단일 파기 지시를 실행하고 실패한 키 목록을 반환한다(빈 목록 = 완전 성공)."""
    from src.services.storage import delete_keys, storage_service

    if task.kind == KIND_PREFIX:
        return await storage_service.delete_prefix(task.target)
    return await delete_keys([task.target])


async def run_purge_tasks(
    db: AsyncSession, tasks: list[StoragePurgeTask]
) -> list[str]:
    """방금 커밋된 파기 지시들을 즉시 실행하고 **남은 실패 키**를 반환한다.

    성공한 지시는 status='done'으로 종결(스윕 재실행 대상에서 제외), 실패는 pending으로
    남겨 스윕이 재시도한다. 호출부는 반환값이 비어 있지 않으면 success로 응답하지 않는다.
    """
    failed: list[str] = []
    for task in tasks:
        try:
            task_failed = await _execute_task(task)
        except Exception as exc:  # ClientError 외 예외도 '미완'으로 취급
            task.attempts = (task.attempts or 0) + 1
            task.last_error = str(exc)[:300]
            task.updated_at = utcnow()
            failed.append(task.target)
            logger.warning(
                "storage purge task raised", target=task.target, error=str(exc)
            )
            continue
        task.attempts = (task.attempts or 0) + 1
        task.updated_at = utcnow()
        if task_failed:
            task.last_error = f"failed_keys={len(task_failed)}"
            failed.extend(task_failed)
            logger.warning(
                "storage purge task incomplete",
                target=task.target,
                failed_keys=task_failed,
            )
        else:
            task.status = "done"
            task.last_error = None
    await db.commit()
    return failed


async def sweep_pending_purges(limit: int = 100) -> int:
    """중단·실패로 남은 파기 지시를 재실행한다(job_monitor 주기 호출).

    반환: 이번 스윕에서 완결(done)된 지시 수. 멱등 — 이미 없는 객체 삭제는 성공으로 본다.
    """
    from src.core.database import AsyncSessionLocal

    completed = 0
    async with AsyncSessionLocal() as session:
        grace_cutoff = utcnow() - timedelta(seconds=UNATTEMPTED_GRACE_SECONDS)
        rows = await session.execute(
            select(StoragePurgeTask)
            .where(
                StoragePurgeTask.status == "pending",
                StoragePurgeTask.attempts < MAX_ATTEMPTS,
                # 인라인 실행된 적 있는 삭제-경로 지시는 즉시 재시도, 아직 한 번도 실행되지
                # 않은 '선기록 가드'(H8)는 유예가 지난 뒤에만 — 진행 중 업로드 오파기 방지.
                or_(
                    StoragePurgeTask.attempts > 0,
                    StoragePurgeTask.created_at <= grace_cutoff,
                ),
            )
            .order_by(StoragePurgeTask.id.asc())
            .limit(limit)
        )
        tasks = list(rows.scalars().all())
        if not tasks:
            return 0
        for task in tasks:
            task.attempts = (task.attempts or 0) + 1
            task.updated_at = utcnow()
            try:
                task_failed = await _execute_task(task)
            except Exception as exc:
                task.last_error = str(exc)[:300]
                if task.attempts >= MAX_ATTEMPTS:
                    task.status = "failed"
                continue
            if task_failed:
                task.last_error = f"failed_keys={len(task_failed)}"
                if task.attempts >= MAX_ATTEMPTS:
                    task.status = "failed"
                continue
            task.status = "done"
            task.last_error = None
            completed += 1
        await session.commit()

    if completed:
        logger.info("storage purge sweep completed tasks", completed=completed)
    return completed
