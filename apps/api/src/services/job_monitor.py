"""
Job Monitor Service: Stuck job detection and recovery

Background service that runs periodically to:
1. Detect jobs stuck in 'running' state
2. Detect jobs that exceeded SLA
3. Auto-recover retryable jobs
4. Mark non-recoverable jobs as failed
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional
import structlog

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.utils import utcnow
from src.models.db import Job
from sqlalchemy import select, and_, func, update

logger = structlog.get_logger()

# Configuration
STUCK_JOB_TIMEOUT_MINUTES = 15  # Jobs running > 15 min are considered stuck
QUEUED_JOB_TIMEOUT_MINUTES = 30  # Jobs queued > 30 min are considered stuck
MAX_JOB_RETRIES = 3
MONITOR_INTERVAL_SECONDS = 60 * 5  # Run every 5 minutes


def _db_timestamp(value: datetime) -> datetime:
    """Normalize datetimes for timestamp-without-time-zone columns."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _db_utcnow() -> datetime:
    """Return UTC now as a naive timestamp for DB comparisons."""
    return _db_timestamp(utcnow())


class JobMonitor:
    """Background service for job health monitoring"""

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the monitor background task"""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Job monitor started", interval_seconds=MONITOR_INTERVAL_SECONDS)

    async def stop(self):
        """Stop the monitor background task"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Job monitor stopped")

    async def _monitor_loop(self):
        """Main monitoring loop"""
        while self._running:
            try:
                await self.check_and_recover_jobs()
            except Exception as e:
                logger.error("Job monitor error", error=str(e))

            # M8/R1-5: 계정삭제·동의철회에서 중단·실패한 아동 PII 파기 지시(outbox)를
            # 멱등 재실행한다. 이 스윕이 없으면 durable 레코드가 '기록만 되고 영원히
            # 실행되지 않는' 장부가 된다.
            try:
                from src.services.purge_queue import sweep_pending_purges

                await sweep_pending_purges()
            except Exception as e:
                logger.error("Storage purge sweep error", error=str(e))

            await asyncio.sleep(MONITOR_INTERVAL_SECONDS)

    async def check_and_recover_jobs(self):
        """Check for stuck jobs and attempt recovery"""
        now = _db_utcnow()

        stuck_running_threshold = now - timedelta(minutes=STUCK_JOB_TIMEOUT_MINUTES)
        stuck_queued_threshold = now - timedelta(minutes=QUEUED_JOB_TIMEOUT_MINUTES)
        sla_threshold = now - timedelta(seconds=settings.job_sla_seconds)

        async with AsyncSessionLocal() as session:
            # Find stuck running jobs
            stuck_running = await session.execute(
                select(Job).where(
                    and_(
                        Job.status == "running",
                        Job.updated_at < stuck_running_threshold,
                    )
                )
            )
            stuck_running_jobs = stuck_running.scalars().all()

            # Find stuck queued jobs
            stuck_queued = await session.execute(
                select(Job).where(
                    and_(
                        Job.status == "queued", Job.updated_at < stuck_queued_threshold
                    )
                )
            )
            stuck_queued_jobs = stuck_queued.scalars().all()

            # Find SLA breach jobs
            sla_breach = await session.execute(
                select(Job).where(
                    and_(
                        Job.status.in_(["queued", "running"]),
                        Job.created_at < sla_threshold,
                    )
                )
            )
            sla_breach_jobs = sla_breach.scalars().all()

            # Process stuck running jobs
            for job in stuck_running_jobs:
                await self._handle_stuck_job(session, job, "STUCK_RUNNING")

            # Process stuck queued jobs
            for job in stuck_queued_jobs:
                await self._handle_stuck_job(session, job, "STUCK_QUEUED")

            # Process SLA breach jobs (mark failed immediately, no retry)
            for job in sla_breach_jobs:
                if job not in stuck_running_jobs and job not in stuck_queued_jobs:
                    await self._mark_job_failed(
                        session,
                        job,
                        "SLA_BREACH",
                        f"Job exceeded SLA of {settings.job_sla_seconds}s",
                    )

            await session.commit()

            # Log summary
            total_processed = (
                len(stuck_running_jobs) + len(stuck_queued_jobs) + len(sla_breach_jobs)
            )
            if total_processed > 0:
                logger.info(
                    "Job monitor cycle complete",
                    stuck_running=len(stuck_running_jobs),
                    stuck_queued=len(stuck_queued_jobs),
                    sla_breach=len(sla_breach_jobs),
                )

    async def _handle_stuck_job(self, session, job: Job, reason: str):
        """스턱 잡 처리 — 즉시 실패+환불(M18).

        기존 '재큐(status=queued)'는 좀비였다: Job 행에 BookSpec이 저장되지 않고 Celery는
        DB 'queued' 행이 아니라 브로커 메시지를 소비하므로 재디스패치가 구조적으로 불가능해
        재시도가 한 번도 일어나지 않았다(거짓 '재시도 중 n/3' UI). 첫 감지 시 즉시 실패 처리해
        멱등 환불(_mark_job_failed)로 크레딧을 방어하고, 복구는 사용자 재생성으로(G14).
        """
        await self._mark_job_failed(
            session, job, reason, "복구 불가 — 즉시 실패 처리"
        )

    async def _mark_job_failed(self, session, job: Job, error_code: str, message: str):
        """Mark a job as failed (크레딧을 소모한 잡이면 1 크레딧 환불 — silent 손실 방지).

        done 잡을 failed로 되돌리지 않는다(H10 fence). 조건부 UPDATE로 전이 성공(rowcount==1)
        시에만 환불해, 워커가 완주해 done이 된 잡을 SLA 틱이 failed+환불로 뒤집는 것을 막는다.
        """
        result = await session.execute(
            update(Job)
            .where(Job.id == job.id, Job.status.in_(["queued", "running"]))
            .values(
                status="failed",
                error_code=error_code,
                error_message=message,
                updated_at=_db_utcnow(),
            )
        )
        if result.rowcount != 1:
            logger.info(
                "SLA fail skipped (job already terminal)", job_id=job.id
            )
            return
        # 세션 내 job 객체도 전이 결과에 맞춘다(호출자 assert·후속 로직 호환).
        job.status = "failed"
        job.error_code = error_code
        job.error_message = message
        job.updated_at = _db_utcnow()

        # 스턱 잡은 요청경로에서 이미 성공 응답을 받았으므로 환불 경로가 없었다 →
        # 여기서 멱등 환불(과금된 잡만·1회만). 실패해도 잡 실패 처리는 막지 않는다.
        try:
            from src.services.credits import credits_service

            refunded = await credits_service.refund_for_job(
                session,
                job.user_key,
                job.id,
                description="생성 실패 환불(자동)",
                commit=False,
            )
            if refunded:
                logger.info("Credit refunded for failed job", job_id=job.id)
        except Exception as refund_error:  # pragma: no cover - 방어적
            logger.warning(
                "Credit refund on job failure failed",
                job_id=job.id,
                error=str(refund_error),
            )

        logger.warning(
            "Job marked as failed by monitor",
            job_id=job.id,
            error_code=error_code,
            message=message,
        )


# Singleton instance
job_monitor = JobMonitor()


async def get_job_metrics() -> dict:
    """Get current job metrics for health check (uses efficient COUNT queries)"""
    async with AsyncSessionLocal() as session:
        now = _db_utcnow()

        # Count by status - use func.count() for efficient counting
        queued_result = await session.execute(
            select(func.count(Job.id)).where(Job.status == "queued")
        )
        queued_count = queued_result.scalar() or 0

        running_result = await session.execute(
            select(func.count(Job.id)).where(Job.status == "running")
        )
        running_count = running_result.scalar() or 0

        # Count stuck jobs
        stuck_threshold = now - timedelta(minutes=STUCK_JOB_TIMEOUT_MINUTES)
        stuck_result = await session.execute(
            select(func.count(Job.id)).where(
                and_(Job.status == "running", Job.updated_at < stuck_threshold)
            )
        )
        stuck_count = stuck_result.scalar() or 0

        # Count jobs in last hour
        hour_ago = now - timedelta(hours=1)
        completed_result = await session.execute(
            select(func.count(Job.id)).where(
                and_(Job.status == "done", Job.updated_at > hour_ago)
            )
        )
        completed_count = completed_result.scalar() or 0

        failed_result = await session.execute(
            select(func.count(Job.id)).where(
                and_(Job.status == "failed", Job.updated_at > hour_ago)
            )
        )
        failed_count = failed_result.scalar() or 0

        return {
            "queued": queued_count,
            "running": running_count,
            "stuck": stuck_count,
            "completed_last_hour": completed_count,
            "failed_last_hour": failed_count,
            "success_rate": (
                completed_count / (completed_count + failed_count) * 100
                if (completed_count + failed_count) > 0
                else 100
            ),
        }
