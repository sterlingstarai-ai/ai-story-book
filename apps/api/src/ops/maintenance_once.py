"""Run the existing maintenance work once, without opening a public endpoint.

This is a manual/infrastructure entry point, not a scheduler.  The existing
in-process loops remain enabled.  Do not disable them until an independently
authenticated, monitored scheduler and recovery guarantees are verified.
"""

import asyncio
import json

import structlog


logger = structlog.get_logger()


class UnsettledMaintenance(RuntimeError):
    """A recovery queue still has failed or retryable work after a sweep."""


async def _check_recovery_debt() -> None:
    """Alert on outstanding failures that individual sweepers can swallow.

    Future schedulers must monitor this failure and retry. A clean result is
    not proof that new/grace-period work or bounded avatar batches are empty.
    """
    from sqlalchemy import and_, or_, select

    from src.core.database import AsyncSessionLocal
    from src.models.db import Book, CreditTransaction, IAPReceipt, Job, StoragePurgeTask, Subscription
    from src.services.periodic_credits import _db_utcnow

    charged = select(CreditTransaction.id).where(
        CreditTransaction.reference_id == Job.id,
        CreditTransaction.user_key == Job.user_key,
        CreditTransaction.transaction_type == "usage",
    ).exists()
    refunded = select(CreditTransaction.id).where(
        CreditTransaction.reference_id == Job.id,
        CreditTransaction.transaction_type == "refund",
    ).exists()
    delivered = select(Book.id).where(Book.job_id == Job.id).exists()
    failed_refund = select(Job.id).where(
        Job.status == "failed", charged, ~refunded, ~delivered,
    ).limit(1)
    failed_purge = select(StoragePurgeTask.id).where(or_(
        StoragePurgeTask.status == "failed",
        and_(StoragePurgeTask.status == "pending", StoragePurgeTask.last_error.isnot(None)),
    )).limit(1)
    due_refill = select(Subscription.id).where(
        Subscription.status == "active",
        Subscription.plan != "free",
        Subscription.calendar_refill_enabled.is_(True),
        Subscription.current_period_end <= _db_utcnow(),
        ~select(IAPReceipt.id).where(IAPReceipt.subscription_id == Subscription.id).exists(),
    ).limit(1)
    async with AsyncSessionLocal() as session:
        for statement in (failed_refund, failed_purge, due_refill):
            if await session.scalar(statement) is not None:
                raise UnsettledMaintenance("recovery work remains")


async def run_once() -> dict[str, str]:
    """Invoke each existing routine independently; report invocation failures.

    "ok" means the routine returned without raising. It does not prove that a
    bounded queue is empty or that previously failed items were recovered.
    """
    from src.core.database import AsyncSessionLocal
    from src.services.character_avatar import sweep_character_avatars
    from src.services.job_monitor import job_monitor
    from src.services.periodic_credits import periodic_credits
    from src.services.purge_queue import sweep_pending_purges

    async def refill_credits():
        async with AsyncSessionLocal() as session:
            await periodic_credits.grant_due_refills(session)

    operations = (
        ("jobs_and_refunds", job_monitor.check_and_recover_jobs),
        ("character_avatars", sweep_character_avatars),
        ("storage_purges", sweep_pending_purges),
        ("periodic_credits", refill_credits),
        ("recovery_debt", _check_recovery_debt),
    )
    results: dict[str, str] = {}
    for name, operation in operations:
        try:
            await operation()
            results[name] = "ok"
        except Exception as exc:
            # Provider exceptions can include credentials, user keys, or paths.
            logger.error("Maintenance routine failed", routine=name, error_type=type(exc).__name__)
            results[name] = "failed"
    return results


def main() -> int:
    result = asyncio.run(run_once())
    print(json.dumps(result, sort_keys=True))
    return 1 if "failed" in result.values() else 0


if __name__ == "__main__":
    raise SystemExit(main())
