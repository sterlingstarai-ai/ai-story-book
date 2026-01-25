"""
Job Monitor Service: Stuck job detection and recovery

Background service that runs periodically to:
1. Detect jobs stuck in 'running' state
2. Detect jobs that exceeded SLA
3. Auto-recover retryable jobs
4. Mark non-recoverable jobs as failed
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional
import structlog

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.models.db import Job
from sqlalchemy import select, and_, func

logger = structlog.get_logger()

# Configuration
STUCK_JOB_TIMEOUT_MINUTES = 15  # Jobs running > 15 min are considered stuck
QUEUED_JOB_TIMEOUT_MINUTES = 30  # Jobs queued > 30 min are considered stuck
MAX_JOB_RETRIES = 3
MONITOR_INTERVAL_SECONDS = 60 * 5  # Run every 5 minutes


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

            await asyncio.sleep(MONITOR_INTERVAL_SECONDS)

    async def check_and_recover_jobs(self):
        """Check for stuck jobs and attempt recovery"""
        now = datetime.utcnow()

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
        """Handle a stuck job - retry or fail"""
        retry_count = job.retry_count or 0

        if retry_count < MAX_JOB_RETRIES:
            # Retry the job
            job.status = "queued"
            job.retry_count = retry_count + 1
            job.last_retry_at = datetime.utcnow()
            job.current_step = f"재시도 중... ({job.retry_count}/{MAX_JOB_RETRIES})"
            job.updated_at = datetime.utcnow()

            logger.info(
                "Job requeued for retry",
                job_id=job.id,
                retry_count=job.retry_count,
                reason=reason,
            )
        else:
            # Max retries exceeded, mark as failed
            await self._mark_job_failed(
                session, job, reason, f"Max retries ({MAX_JOB_RETRIES}) exceeded"
            )

    async def _mark_job_failed(self, session, job: Job, error_code: str, message: str):
        """Mark a job as failed"""
        job.status = "failed"
        job.error_code = error_code
        job.error_message = message
        job.updated_at = datetime.utcnow()

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
        now = datetime.utcnow()

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
