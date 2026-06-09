"""
Periodic Credits Service: 월간 구독 크레딧 리필.

활성(active) 구독의 결제 주기가 경과하면 다음 주기로 갱신하고 월간 크레딧을 1회 지급한다.
이것이 없으면 베이직 구독자가 2개월차에 크레딧 0이 되어 즉시 이탈(매출 누수)한다.
job_monitor 와 동일한 백그라운드 async-loop 패턴을 따른다 (USE_CELERY 무관 동작).
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import AsyncSessionLocal
from src.core.utils import utcnow
from src.models.db import Subscription
from src.services.credits import SUBSCRIPTION_PLANS, credits_service

logger = structlog.get_logger()

# 멱등하므로 점검 빈도는 무관 — 1시간마다 점검(놓친 주기를 빠르게 따라잡음)
REFILL_INTERVAL_SECONDS = 60 * 60
PERIOD_DAYS = 30


def _db_timestamp(value: datetime) -> datetime:
    """timezone-naive 타임스탬프 컬럼과 비교하기 위한 정규화."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _db_utcnow() -> datetime:
    return _db_timestamp(utcnow())


class PeriodicCredits:
    """월간 구독 크레딧 리필 백그라운드 서비스."""

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Periodic credits started", interval_seconds=REFILL_INTERVAL_SECONDS)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Periodic credits stopped")

    async def _loop(self):
        while self._running:
            try:
                async with AsyncSessionLocal() as session:
                    await self.grant_due_refills(session)
            except Exception as e:  # pragma: no cover - 방어적
                logger.error("Periodic credits error", error=str(e))
            await asyncio.sleep(REFILL_INTERVAL_SECONDS)

    async def grant_due_refills(self, session: AsyncSession) -> int:
        """결제 주기가 경과한 active 구독을 갱신하고 월간 크레딧을 지급한다.

        멱등성: 지급 시 결제 주기를 now 이후로 전진시키므로 같은 주기에 재지급되지 않는다.
        cancelled 구독은 갱신하지 않고 만료되도록 둔다.
        장기 미접속으로 여러 주기가 밀렸어도 크레딧은 1회만 지급한다(오프라인 보상 방지).

        Returns: 리필된 구독 수.
        """
        now = _db_utcnow()
        result = await session.execute(
            select(Subscription).where(
                Subscription.status == "active",
                Subscription.current_period_end <= now,
            )
        )
        due = list(result.scalars().all())

        refilled = 0
        for sub in due:
            try:
                plan_info = SUBSCRIPTION_PLANS.get(sub.plan)
                if not plan_info:
                    continue

                # 결제 주기를 now 이후로 전진
                new_start = sub.current_period_start
                new_end = sub.current_period_end
                while new_end <= now:
                    new_start = new_end
                    new_end = new_end + timedelta(days=PERIOD_DAYS)

                amount = sub.credits_per_month or plan_info["credits_per_month"]

                # 원자적 claim: 조건부 UPDATE로 주기를 전진. 다중 복제본/동시 실행에서 같은
                # 구독을 둘이 동시에 처리해도 WHERE(current_period_end <= now)에 매칭되는
                # 프로세스는 하나뿐(나머지는 행 잠금 해제 후 재평가에서 미매칭) → 이중 지급 방지.
                claim = await session.execute(
                    update(Subscription)
                    .where(
                        Subscription.id == sub.id,
                        Subscription.status == "active",
                        Subscription.current_period_end <= now,
                    )
                    .values(
                        current_period_start=new_start,
                        current_period_end=new_end,
                    )
                )
                if (claim.rowcount or 0) != 1:
                    # 다른 프로세스가 이미 이 주기를 전진·지급함 → 크레딧 지급 스킵
                    await session.commit()
                    continue

                await credits_service.add_credits(
                    db=session,
                    user_key=sub.user_key,
                    amount=amount,
                    transaction_type="subscription",
                    description=f"{plan_info['name']} 월간 구독 크레딧",
                    reference_id=f"{sub.id}:{_db_timestamp(new_start).isoformat()}",
                    commit=False,
                )
                await session.commit()
                refilled += 1
            except Exception as e:
                await session.rollback()
                logger.error(
                    "Refill failed",
                    subscription_id=getattr(sub, "id", None),
                    error=str(e),
                )
                continue

        if refilled:
            logger.info("Monthly credits refilled", count=refilled)
        return refilled


# 싱글톤 인스턴스
periodic_credits = PeriodicCredits()
