"""Receipt, refund and purchase-claim commits must share one settlement boundary."""

import asyncio
import hashlib
import uuid

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.core.exceptions import ValidationError
from src.models.db import CreditTransaction, IAPPurchaseClaim, IAPReceipt, IapWebhookEvent, UserCredits
from src.routers import iap
from src.services.store_notifications import StoreEvent
from tests.test_pg_fk_erasure import PG_URL, pg_schema_at_head  # noqa: F401

pytestmark = pytest.mark.asyncio


def purchase(product="credit_pack_5", txn="fixture-order"):
    return iap.IAPVerifyRequest(platform="apple", product_id=product, transaction_id=txn,
                                receipt_data="test-receipt")


async def settlement_amounts(db, owner):
    return list(await db.scalars(select(CreditTransaction.amount).where(
        CreditTransaction.user_key == owner,
        CreditTransaction.transaction_type.in_(("purchase", "clawback")),
    ).order_by(CreditTransaction.id)))


async def refund(db, request, native):
    if native:
        return await iap._apply_native_event(StoreEvent(
            platform="apple", product_id=request.product_id, transaction_id=request.transaction_id,
            status="refunded", environment="Production",
        ), db)
    return await iap._apply_webhook_status(
        request=iap.IAPWebhookRequest(transaction_id=request.transaction_id, status="refunded"),
        platform="apple", db=db,
    )


@pytest.mark.parametrize("native", [True, False])
async def test_pending_refund_and_grant_retry_as_one_commit(db_session, monkeypatch, user_key, native):
    request = purchase()
    db_session.add(UserCredits(user_key=user_key, credits=3))
    await db_session.commit()
    assert (await refund(db_session, request, native))["status"] == "accepted_orphan"

    async def unavailable(*args, **kwargs):
        raise IntegrityError("synthetic settlement failure", {}, RuntimeError())

    with monkeypatch.context() as patch:
        patch.setattr(iap, "_apply_status_to_receipt", unavailable)
        with pytest.raises(IntegrityError):
            await iap.verify_iap(request, db_session, user_key)
        await db_session.rollback()

    assert await db_session.scalar(select(UserCredits.credits)) == 3
    assert await db_session.scalar(select(func.count()).select_from(IAPReceipt)) == 0
    assert await db_session.scalar(select(func.count()).select_from(IAPPurchaseClaim)) == 0
    assert await db_session.scalar(select(IapWebhookEvent.applied)) is False

    result = await iap.verify_iap(request, db_session, user_key)
    assert result.credits_added == 0
    assert await db_session.scalar(select(UserCredits.credits)) == 3
    assert await db_session.scalar(select(IapWebhookEvent.applied)) is True
    assert await db_session.scalar(select(IAPReceipt.status)) == "refunded"
    assert (await iap.verify_iap(request, db_session, user_key)).credits_added == 0
    assert await settlement_amounts(db_session, user_key) == [5, -5]


@pytest.mark.parametrize("product,cross_account", [
    ("credit_pack_5", False), ("subscription_basic", False), ("subscription_basic", True),
])
async def test_existing_receipt_reconciles_a_legacy_pending_refund(db_session, user_key, product, cross_account):
    request = purchase(product)
    db_session.add(UserCredits(user_key=user_key, credits=3))
    await db_session.commit()
    await iap.verify_iap(request, db_session, user_key)
    db_session.add(IapWebhookEvent(platform="apple", transaction_id=request.transaction_id,
                                   status="refunded", applied=False))
    await db_session.commit()
    if cross_account:
        with pytest.raises(ValidationError):
            await iap.verify_iap(request, db_session, str(uuid.uuid4()))
    else:
        assert (await iap.verify_iap(request, db_session, user_key)).status == "already_processed"
    assert await db_session.scalar(select(UserCredits.credits)) == 3
    assert await db_session.scalar(select(IAPReceipt.status)) == "refunded"
    assert await db_session.scalar(select(IapWebhookEvent.applied)) is True
    if product == "subscription_basic":
        assert await iap.credits_service.get_active_subscription(db_session, user_key) is None


@pytest.mark.skipif(not PG_URL, reason="E2E_PG_DATABASE_URL required for two-connection lock checks")
@pytest.mark.usefixtures("pg_schema_at_head")
@pytest.mark.parametrize("first_is_refund", [True, False])
@pytest.mark.parametrize("native", [True, False])
async def test_concurrent_refund_and_first_receipt_settle_once(
    monkeypatch, first_is_refund, native,
):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    owner = str(uuid.uuid4())
    request = purchase(txn=f"settle-{uuid.uuid4().hex}")
    try:
        async with sessions() as setup:
            setup.add(UserCredits(user_key=owner, credits=3))
            await setup.commit()
        async with sessions() as first, sessions() as second, sessions() as observer:
            holder = await first.scalar(text("SELECT pg_backend_pid()"))
            waiter = await second.scalar(text("SELECT pg_backend_pid()"))
            acquired = asyncio.Event()
            release = asyncio.Event()
            locking = iap._lock_store_settlement

            async def pause_holder(session, *arguments):
                await locking(session, *arguments)
                if session is first:
                    acquired.set()
                    await asyncio.wait_for(release.wait(), 15)

            monkeypatch.setattr(iap, "_lock_store_settlement", pause_holder)

            async def verify_or_refund(session, is_refund):
                if is_refund:
                    return await refund(session, request, native)
                return await iap.verify_iap(request, session, owner)

            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(verify_or_refund(first, first_is_refund))
                await asyncio.wait_for(acquired.wait(), 10)
                tasks.create_task(verify_or_refund(second, not first_is_refund))
                try:
                    async with asyncio.timeout(10):
                        while holder not in await observer.scalar(
                            text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter},
                        ):
                            await asyncio.sleep(0.02)
                finally:
                    release.set()

        async with sessions() as check:
            assert await check.scalar(select(UserCredits.credits).where(UserCredits.user_key == owner)) == 3
            assert await check.scalar(select(IAPReceipt.status).where(IAPReceipt.user_key == owner)) == "refunded"
            assert await settlement_amounts(check, owner) == [5, -5]
            pending = await check.scalar(select(func.count()).select_from(IapWebhookEvent).where(
                IapWebhookEvent.transaction_id == request.transaction_id, IapWebhookEvent.applied.is_(False)))
            assert pending == 0
    finally:
        async with sessions() as cleanup:
            await cleanup.execute(delete(IapWebhookEvent).where(IapWebhookEvent.transaction_id == request.transaction_id))
            for model in (IAPReceipt, CreditTransaction, UserCredits):
                await cleanup.execute(delete(model).where(model.user_key == owner))
            claim = hashlib.sha256(f"apple\0{request.transaction_id}".encode()).hexdigest()
            await cleanup.execute(delete(IAPPurchaseClaim).where(IAPPurchaseClaim.transaction_digest == claim))
            await cleanup.commit()
        await engine.dispose()
