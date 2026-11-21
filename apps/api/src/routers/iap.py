"""
IAP Router
Apple/Google 영수증 검증 및 웹훅 처리
"""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from typing import Optional, Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import false, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.core.billing_feature import CREDIT_PACK_PRODUCTS, SUBSCRIPTION_PRODUCTS, review_sandbox_products
from src.core.config import settings
from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.core.exceptions import AuthorizationError, ValidationError
from src.core.utils import utcnow
from src.models.db import (
    AccountIdentity, CreditTransaction, IAPReceipt, IapWebhookEvent, Subscription, UserCredits,
)
from src.services.account_recovery import is_claimed_store_review_slot
from src.services.credits import SUBSCRIPTION_PLANS, credits_service
from src.services.iap_verifier import _strip_google_order_suffix, iap_verifier
from src.services.purchase_claims import claim_purchase
from src.services.store_notifications import (
    StoreEvent,
    decode_apple_notification,
    decode_google_notification,
    verify_google_push_identity,
)

router = APIRouter()
logger = structlog.get_logger()


class IAPVerifyRequest(BaseModel):
    platform: Literal["apple", "google"]
    product_id: str = Field(min_length=1, max_length=120)
    transaction_id: str = Field(min_length=1, max_length=200)
    purchase_token: Optional[str] = Field(default=None, max_length=500)
    receipt_data: Optional[str] = Field(default=None, max_length=32768)
    is_subscription: bool = False


class IAPVerifyResponse(BaseModel):
    status: str
    transaction_id: str
    product_id: str
    credits_added: int = 0
    plan: Optional[str] = None
    verification_source: Optional[str] = None


class IAPWebhookRequest(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=200)
    status: Literal["active", "cancelled", "expired", "refunded"]
    payload: Optional[dict] = None


def _legacy_sandbox_receipt(receipt: IAPReceipt) -> bool:
    payload = receipt.payload or {}
    environment = payload.get("verification_environment") or (payload.get("native_store_event") or {}).get("environment")
    return receipt.platform in {"apple", "google"} and environment == "Sandbox"


def _subscription_expired(verification, *, is_subscription: bool = True) -> bool:
    """스토어 만료 시각이 과거인 구독 영수증인지(MA1). 만료 영수증으로 active 구독을
    재활성하면 periodic_credits가 영구 리필하므로 지급/재활성을 막는다.

    R2-6: 구독 항목에 `expires_date_ms` 가 **없으면** 예전엔 '만료 아님'으로 통과시켰다.
    부재는 '유효함'의 증거가 아니라 unknown이며, 그 fail-open은 만료 판정을 우회하는
    가장 쉬운 경로가 된다(파싱 실패·필드명 변경·조작된 응답 모두 여기로 떨어진다).
    구독은 만료 시각을 **필수**로 강제한다. 비구독(크레딧팩)은 원래 이 필드가 없으므로
    영향 없음.
    """
    expires_ms = getattr(verification, "expires_date_ms", None)
    if not expires_ms:
        return bool(is_subscription)
    return expires_ms < int(utcnow().replace(tzinfo=timezone.utc).timestamp() * 1000)


def _validate_verify_payload(
    *,
    platform: str,
    purchase_token: Optional[str],
    receipt_data: Optional[str],
) -> None:
    if platform == "apple" and not receipt_data:
        raise ValidationError("Apple 영수증(receipt_data)이 필요합니다.")
    if platform == "google" and not purchase_token:
        raise ValidationError("Google purchase_token이 필요합니다.")


def _resolve_reward(product_id: str) -> tuple[int, Optional[str]]:
    if product_id in CREDIT_PACK_PRODUCTS:
        return CREDIT_PACK_PRODUCTS[product_id], None
    if product_id in SUBSCRIPTION_PRODUCTS:
        return 0, SUBSCRIPTION_PRODUCTS[product_id]
    raise ValidationError(
        "지원하지 않는 상품입니다.",
        details={
            "product_id": product_id,
            "supported": [*CREDIT_PACK_PRODUCTS.keys(), *SUBSCRIPTION_PRODUCTS.keys()],
        },
    )


async def _lock_store_settlement(db: AsyncSession, platform: str, *identifiers: Optional[str]) -> None:
    """Serialize receipt and notification writers even before the receipt exists."""
    if db.get_bind().dialect.name == "sqlite":
        # SQLite has one writer. Begin a physical write transaction before either
        # side looks for the other's row, including with legacy sqlite3 handling.
        await db.execute(update(IAPReceipt).where(false()).values(status=IAPReceipt.status))
        return
    # Apple renewals share an original ID. Google order suffixes identify a
    # cycle, while linked purchase tokens can join a replacement to its parent.
    keys = set()
    for identifier in identifiers:
        if identifier:
            family = _strip_google_order_suffix(identifier) if platform in {"google", "google_sandbox"} else identifier
            digest = hashlib.sha256(f"storybook:iap-settle:v1:{platform}:{family}".encode()).digest()
            keys.add(int.from_bytes(digest[:8], "big", signed=True))
    for key in sorted(keys):
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def _store_period(subscription: Subscription, verification) -> None:
    """Store timestamps are authoritative, never a new 30 days on restoration."""
    subscription.calendar_refill_enabled = False
    end = getattr(verification, "expires_date_ms", None)
    if end:
        subscription.current_period_end = datetime.fromtimestamp(end / 1000, timezone.utc).replace(
            tzinfo=None
        )
    start = (getattr(verification, "raw", None) or {}).get("purchase_date_ms")
    if isinstance(start, int) and start > 0:
        subscription.current_period_start = datetime.fromtimestamp(
            start / 1000, timezone.utc
        ).replace(tzinfo=None)


async def _plan_change_credit_grant(
    db: AsyncSession, plan: str, previous: Optional[Subscription], purchase_ms: Optional[int]
) -> tuple[int, int]:
    """An in-period tier change grants the increase, never a second full month."""
    amount = SUBSCRIPTION_PLANS[plan]["credits_per_month"]
    allocation = amount
    if (
        previous
        and isinstance(purchase_ms, int)
        and previous.current_period_end > utcnow().replace(tzinfo=None)
    ):
        previous_end = int(
            previous.current_period_end.replace(tzinfo=timezone.utc).timestamp() * 1000
        )
        if purchase_ms < previous_end:
            previous_allocation = previous.credits_per_month
            payloads = (
                await db.scalars(
                    select(IAPReceipt.payload).where(IAPReceipt.subscription_id == previous.id)
                )
            ).all()
            for payload in payloads:
                if (payload or {}).get("expires_date_ms") == previous_end:
                    previous_allocation = max(
                        previous_allocation, int((payload or {}).get("cycle_allocated_credits", 0))
                    )
            amount = max(0, amount - previous_allocation)
            allocation = max(allocation, previous_allocation)
    return amount, allocation


@router.post("/verify", response_model=IAPVerifyResponse)
async def verify_iap(
    request: IAPVerifyRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """
    결제 영수증 검증 및 보상 지급.
    """
    product_id = request.product_id.strip()
    transaction_id = request.transaction_id.strip()
    purchase_token = request.purchase_token.strip() if request.purchase_token else None
    receipt_data = request.receipt_data.strip() if request.receipt_data else None

    if not product_id:
        raise ValidationError("product_id는 공백일 수 없습니다.")
    if not transaction_id:
        raise ValidationError("transaction_id는 공백일 수 없습니다.")

    _validate_verify_payload(
        platform=request.platform,
        purchase_token=purchase_token,
        receipt_data=receipt_data,
    )
    credits_to_add, plan = _resolve_reward(product_id)
    resolved_is_subscription = plan is not None
    review_slot = await is_claimed_store_review_slot(db, user_key)
    if review_slot and product_id not in review_sandbox_products():
        raise ValidationError("이 상품은 심사 계정에 허용되지 않았습니다.")
    ledger_platform = f"{request.platform}_sandbox" if review_slot else request.platform

    # 빠른 정직-재시도 dedup: 같은 사용자가 같은 transaction_id로 재전송하면 스토어
    # 재호출 없이 즉시 already_processed. (정본 dedup은 아래 store_transaction_id 기준.)
    client_receipt = select(IAPReceipt).where(
        IAPReceipt.platform == ledger_platform, IAPReceipt.transaction_id == transaction_id,
    ).execution_options(populate_existing=True)
    existing_by_client = await db.scalar(client_receipt)
    if (
        existing_by_client
        and existing_by_client.user_key == user_key
        and existing_by_client.product_id == product_id
        and not resolved_is_subscription
        and not _legacy_sandbox_receipt(existing_by_client)
    ):
        await _lock_store_settlement(
            db, ledger_platform, transaction_id, existing_by_client.store_transaction_id,
            (existing_by_client.payload or {}).get("original_transaction_id"),
            existing_by_client.purchase_token,
        )
        await db.refresh(existing_by_client, with_for_update=True)
        await _reapply_orphan_events(db, existing_by_client)
        await db.commit()
        return IAPVerifyResponse(
            status="already_processed",
            transaction_id=existing_by_client.transaction_id,
            product_id=existing_by_client.product_id,
            credits_added=0,
            plan=None,
        )

    verification = await iap_verifier.verify_purchase(
        platform=request.platform,
        product_id=product_id,
        transaction_id=transaction_id,
        purchase_token=purchase_token,
        receipt_data=receipt_data,
        is_subscription=resolved_is_subscription,
        review_sandbox=review_slot,
    )

    if not verification.verified:
        raise ValidationError("스토어 검증에 실패했습니다.")

    environment = (verification.environment or "").lower()
    local_fixture = settings.testing and verification.source.startswith("local_") and not review_slot
    if not local_fixture and environment != ("sandbox" if review_slot else "production"):
        raise ValidationError(
            "샌드박스 영수증은 운영에서 지급되지 않습니다.",
            details={"code": "sandbox_not_allowed"},
        )

    if verification.store_product_id and verification.store_product_id != product_id:
        raise ValidationError(
            "검증된 상품 ID가 요청과 일치하지 않습니다.",
            details={
                "requested_product_id": product_id,
                "verified_product_id": verification.store_product_id,
            },
        )

    # 리플레이 방지의 정본 키: 스토어가 검증해 돌려준 식별자. 클라이언트가 transaction_id를
    # 바꿔가며 같은 영수증을 재제출해도 store_transaction_id는 동일하므로 차단된다.
    store_txn = verification.store_transaction_id or transaction_id
    original_txn = verification.raw.get("original_transaction_id") or (
        _strip_google_order_suffix(store_txn) if request.platform == "google" else store_txn
    )
    await _lock_store_settlement(
        db, ledger_platform, store_txn, original_txn, transaction_id, purchase_token,
    )
    # The first lookup preceded store verification and another receipt may have
    # claimed this client alias in the meantime.
    existing_by_client = await db.scalar(client_receipt)
    if existing_by_client and existing_by_client.store_transaction_id != store_txn:
        # Google restore can reuse the initial client order ID after renewal.
        # Persist the newly verified store order as its own transaction claim.
        transaction_id = store_txn

    def _build_payload(extra: Optional[dict] = None) -> dict:
        base = {
            "credit_grant_user_key": user_key,
            "receipt_data": receipt_data,
            "is_subscription": resolved_is_subscription,
            "verified_at": utcnow().isoformat(),
            "verification_source": verification.source,
            "verification_environment": verification.environment,
            "verification": verification.raw,
            "client_transaction_id": transaction_id,
            "original_transaction_id": original_txn,
            "expires_date_ms": verification.expires_date_ms,
        }
        if extra:
            base.update(extra)
        return base

    # with_for_update로 동시 복원을 직렬화(SQLite에선 no-op이라 실질 방어는 M17 부분 유니크).
    existing = (
        await db.execute(
            select(IAPReceipt)
            .where(
                IAPReceipt.platform == ledger_platform,
                IAPReceipt.store_transaction_id == store_txn,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()

    if existing:
        if _legacy_sandbox_receipt(existing):
            raise ValidationError("기존 구매의 스토어 환경이 다릅니다.")
        # Old releases could commit a grant before applying a queued refund.
        # Settle that historical state even when no new credits are due.
        await _reapply_orphan_events(db, existing)
        entitlement_erased = bool((existing.payload or {}).get("entitlement_erased"))
        if existing.user_key == user_key and not entitlement_erased:
            await db.commit()
            return IAPVerifyResponse(
                status="already_processed",
                transaction_id=existing.transaction_id,
                product_id=existing.product_id,
                credits_added=0,
                plan=None,
            )
        if plan is None:
            # Consumables are not restorable entitlements. Keep the receipt with
            # the account that received its credits so a later refund targets the
            # original grant instead of an unrelated reinstallation account.
            await db.commit()
            return IAPVerifyResponse(
                status="already_processed",
                transaction_id=transaction_id,
                product_id=product_id,
                credits_added=0,
                verification_source=verification.source,
            )
        # F4 복원: 재설치/기기 변경으로 user_key가 새로 발급된 경우. 스토어가 이 영수증의
        # 소유를 방금 검증했으므로(verified=True) 권한을 호출자에게 이전한다. 소비성
        # 크레딧팩은 스토어가 복원해주지 않으므로 재지급하지 않는다(구독만 재활성).
        previous_user_key = existing.user_key
        if existing.status in {"refunded", "expired"}:
            await db.commit()
            raise ValidationError("종료 또는 환불된 결제는 복원할 수 없습니다.")
        # Preserve funding provenance before a receipt moves or loses its FK.
        previous_sub = await db.get(Subscription, existing.subscription_id) if existing.subscription_id else None
        if previous_sub is not None:
            previous_sub.calendar_refill_enabled = False
        # Entitlement ownership may move; the already-issued credit grant does not.
        # Snapshot legacy ledger evidence before replacing the subscription pointer.
        grant_user_key = _credit_grant_user_key(existing)
        granted_credits = await _granted_subscription_credits(db, existing)
        restored_payload = {
            **(existing.payload or {}),
            **_build_payload({"restored_from_user_key": previous_user_key}),
            "credit_grant_user_key": grant_user_key,
            "granted_credits": granted_credits,
        }
        existing.user_key = user_key
        existing.status = "restored"
        existing.payload = restored_payload
        if plan:
            # 만료 영수증(MA1)은 어떤 권한도 이전하지 않는다 — active 구독 재활성 금지로
            # 무한 리필을 막고, 그 연장선에서 부작용 두 가지도 함께 차단한다:
            #  · 이전 소유자의 expire를 건너뛴다. 만료 영수증은 아무것도 이전하지 않는데
            #    expire만 실행되면, 그 사이 새로 결제한 같은 plan 구독까지 소멸한다(#14).
            #  · 이전 소유자 구독을 가리키던 참조를 끊는다. 남겨두면 그 소유자의 계정
            #    삭제가 FK 위반으로 500이 되어 법적 삭제권이 봉쇄된다(#7/H5).
            if _subscription_expired(verification):
                existing.subscription_id = None
            else:
                # Transfer only the receipt's entitlement, including cancelled paid time.
                if previous_user_key != user_key and not entitlement_erased:
                    await credits_service.expire_active_subscription_for_plan(
                        db, previous_user_key, plan, commit=False,
                        subscription_id=existing.subscription_id,
                    )
                # 복원은 월간 크레딧을 재지급하지 않는다(G1).
                restored_sub = await credits_service.create_subscription(
                    db, user_key, plan, commit=False, grant_credits=False
                )
                _store_period(restored_sub, verification)
                existing.subscription_id = restored_sub.id  # H5
                existing.payload = {**existing.payload, "entitlement_erased": False}
        await db.commit()
        logger.info(
            "IAP entitlement restored to new user_key",
            platform=request.platform,
            store_transaction_id=store_txn,
            plan=plan,
        )
        return IAPVerifyResponse(
            status="restored",
            transaction_id=transaction_id,
            product_id=product_id,
            credits_added=0,
            plan=plan,
            verification_source=verification.source,
        )

    if review_slot:
        # Before environment-separated keys, a sandbox purchase could already
        # have issued a grant. Do not issue a second one under its new key.
        legacy = await db.scalar(select(IAPReceipt).where(
            IAPReceipt.platform == request.platform, IAPReceipt.store_transaction_id == store_txn,
        ))
        if legacy and _legacy_sandbox_receipt(legacy):
            return IAPVerifyResponse(status="already_processed", transaction_id=transaction_id,
                                     product_id=product_id, verification_source=verification.source)
    first_grant = await claim_purchase(db, ledger_platform, store_txn)
    if not first_grant and plan is None:
        return IAPVerifyResponse(
            status="already_processed", transaction_id=transaction_id,
            product_id=product_id, credits_added=0, verification_source=verification.source,
        )

    # 이미 같은 플랜이 **active**면 보상 없이 영수증만 기록.
    #
    # H3/R2-1: 예전에는 `get_active_subscription`(status ∈ {active, cancelled})을 그대로 썼다.
    # 그 결과 서버-취소(cancelled, 잔여기간 내) 상태에서 들어온 **새 검증 결제**가
    # already_subscribed로 삼켜져 구독이 생성되지도 갱신되지도 않았다 — 과금은 되고 권한은
    # 미지급, 자가치유 수단 없음. cancelled는 '재활성 가능'한 상태이므로 이 가드에서 제외하고
    # 아래 정상 경로로 흘려보내 create_subscription이 재활성하게 한다.
    if plan:
        active_subscription = await credits_service.get_active_subscription(db, user_key)
        if (
            active_subscription
            and active_subscription.plan == plan
            and active_subscription.status == "active"
        ):
            active_subscription.calendar_refill_enabled = False
            # A verified later billing cycle is a renewal, even if the preceding
            # cycle is still active. The unique store transaction claim and grant
            # are committed together, so client replay cannot refill credits.
            new_expiry = verification.expires_date_ms or 0
            old_expiry = int(
                active_subscription.current_period_end.replace(tzinfo=timezone.utc).timestamp()
                * 1000
            )
            renewal_credits = 0
            purchase_ms = verification.raw.get("purchase_date_ms")
            start_ms = int(
                active_subscription.current_period_start.replace(tzinfo=timezone.utc).timestamp()
                * 1000
            )
            if (
                isinstance(purchase_ms, int)
                and purchase_ms > start_ms
                and new_expiry > old_expiry
                and not _subscription_expired(verification)
                and not verification.source.startswith("local_")
            ):
                _store_period(active_subscription, verification)
                renewal_credits = (
                    active_subscription.credits_per_month
                    or SUBSCRIPTION_PLANS[plan]["credits_per_month"]
                ) if first_grant else 0
                if renewal_credits:
                    await credits_service.add_credits(
                        db,
                        user_key,
                        amount=renewal_credits,
                        transaction_type="subscription",
                        description="스토어에서 확인한 구독 갱신 크레딧",
                        reference_id=f"iap:{ledger_platform}:{store_txn}",
                        commit=False,
                    )
            receipt = IAPReceipt(
                user_key=user_key,
                platform=ledger_platform,
                product_id=product_id,
                transaction_id=transaction_id,
                store_transaction_id=store_txn,
                purchase_token=purchase_token,
                status="already_subscribed",
                subscription_id=active_subscription.id,  # H5
                payload=_build_payload({"granted_credits": renewal_credits}),
            )
            db.add(receipt)
            await _reapply_orphan_events(db, receipt)
            await db.commit()
            return IAPVerifyResponse(
                status="already_subscribed",
                transaction_id=transaction_id,
                product_id=product_id,
                credits_added=0 if receipt.status == "refunded" else renewal_credits,
                plan=plan,
                verification_source=verification.source,
            )

    # 보상 지급 + 영수증 기록을 단일 트랜잭션으로 묶는다(F3: 더블그랜트/고아 방지).
    # 동시 요청 중 패자는 store_transaction_id UNIQUE 위반으로 IntegrityError → 전체
    # 롤백되어 보상도 함께 취소된다.
    new_sub = None
    subscription_grant = 0
    cycle_allocation = 0
    if plan:
        # 만료 영수증(MA1)은 active 구독을 만들지 않는다(무한 리필 차단). 영수증만 기록.
        if not _subscription_expired(verification):
            subscription_grant, cycle_allocation = await _plan_change_credit_grant(
                db, plan, active_subscription, verification.raw.get("purchase_date_ms")
            )
            if not first_grant:
                subscription_grant = 0
            # H3/R2-1: 취소 후 재결제 — 잔여 cancelled 행은 이 결제로 대체(종료)한다.
            await credits_service.supersede_cancelled_subscription_for_plan(db, user_key, plan)
            new_sub = await credits_service.create_subscription(
                db, user_key, plan, commit=False, grant_credits=False
            )
            _store_period(new_sub, verification)
            if subscription_grant:
                await credits_service.add_credits(
                    db,
                    user_key,
                    amount=subscription_grant,
                    transaction_type="subscription",
                    description="스토어에서 확인한 구독 크레딧",
                    reference_id=str(new_sub.id),
                    commit=False,
                )
    elif credits_to_add > 0:
        await credits_service.add_credits(
            db=db,
            user_key=user_key,
            amount=credits_to_add,
            transaction_type="purchase",
            description=f"IAP 크레딧 팩 {credits_to_add}개",
            reference_id=store_txn,
            commit=False,
        )

    receipt = IAPReceipt(
        user_key=user_key,
        platform=ledger_platform,
        product_id=product_id,
        transaction_id=transaction_id,
        store_transaction_id=store_txn,
        purchase_token=purchase_token,
        status="verified",
        # H5: 웹훅이 이 영수증의 구독만 갱신하도록 연결.
        subscription_id=new_sub.id if new_sub else None,
        payload=_build_payload(
            {
                "granted_credits": subscription_grant if new_sub and plan else credits_to_add,
                "cycle_allocated_credits": cycle_allocation,
            }
        ),
    )
    db.add(receipt)
    await _reapply_orphan_events(db, receipt)
    await db.commit()
    if receipt.status == "refunded":
        credits_to_add = 0
    logger.info(
        "IAP receipt verified",
        platform=request.platform,
        transaction_id=transaction_id,
        store_transaction_id=store_txn,
        product_id=product_id,
        credits_added=credits_to_add,
        plan=plan,
        verification_source=verification.source,
    )

    return IAPVerifyResponse(
        status="verified",
        transaction_id=transaction_id,
        product_id=product_id,
        credits_added=credits_to_add,
        plan=plan,
        verification_source=verification.source,
    )


# 상태 우선순위(sticky): **터미널(refunded/expired)만** 되돌릴 수 없다 — 환불/만료된 영수증이
# 이후 active 통지로 뒤집히지 않게 한다(H4).
#
# H3/R2-1: 예전에는 cancelled 도 rank 2 로 sticky였다. 그런데 취소는 터미널이 아니라
# **되돌릴 수 있는** 상태다(사용자가 스토어에서 자동갱신을 다시 켜거나 재결제). sticky면
# 스토어의 'active' 갱신 통지가 조기 반환으로 버려져, 서버는 영원히 cancelled에 갇히고
# 갱신 청구만 계속된다. 복구 수단이 수동 DB 개입뿐이었다.
_STATUS_RANK = {"refunded": 3, "expired": 3}


def _status_rank(status: Optional[str]) -> int:
    return _STATUS_RANK.get(status or "", 1)


def _credit_grant_user_key(receipt: IAPReceipt) -> Optional[str]:
    payload = receipt.payload or {}
    # Old restores discarded the original grant evidence. Do not infer a payer
    # from the current entitlement owner or the last hop of a multi-hop restore.
    return payload.get(
        "credit_grant_user_key",
        None if "restored_from_user_key" in payload else receipt.user_key,
    )


async def _granted_subscription_credits(db: AsyncSession, receipt: IAPReceipt) -> int:
    """이 영수증이 개설한 구독으로 **실제 지급된** 크레딧 합계 (M3/R2-3).

    `create_subscription(grant_credits=True)` 는 `reference_id=str(subscription.id)` 로
    'subscription' 타입 원장을 남긴다. 그 합계가 곧 회수 가능한 상한이다.
    - subscription_id 가 없는 레거시 영수증: 원장을 특정할 수 없으므로 0(회수 안 함) —
      무고한 차감보다 미회수가 낫다(회수 실패는 로그로 관측 가능).
    - 복원 후에는 복원 전에 보존한 지급액을 사용하며, 0 지급도 그대로 보존한다.
    """
    exact_grant = (receipt.payload or {}).get("granted_credits")
    if isinstance(exact_grant, int):
        return max(0, exact_grant)
    grant_user_key = _credit_grant_user_key(receipt)
    if receipt.subscription_id is None or grant_user_key is None:
        return 0
    total = await db.scalar(
        select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
            CreditTransaction.user_key == grant_user_key,
            CreditTransaction.transaction_type == "subscription",
            CreditTransaction.reference_id == str(receipt.subscription_id),
        )
    )
    return max(0, int(total or 0))


async def _apply_status_to_receipt(
    *,
    receipt: IAPReceipt,
    status: str,
    payload: Optional[dict],
    db: AsyncSession,
    sync_subscription: bool = True,
) -> None:
    """웹훅/재적용 상태를 영수증·구독·크레딧에 반영(sticky). 커밋은 호출자 책임."""
    # sticky: 이미 더 높은 우선순위(터미널) 상태면 낮은 상태로 되돌리지 않는다.
    if _status_rank(status) < _status_rank(receipt.status):
        return

    receipt.status = status
    receipt.payload = {
        **(receipt.payload or {}),
        "webhook_status": status,
        "webhook_payload": payload,
        "updated_at": utcnow().isoformat(),
    }

    # 구독 취소/만료/환불 동기화. 'refunded'를 누락하면 환불된 구독이 active로 남아
    # periodic_credits가 매월 영구 리필 → buy→consume→refund 무한 무료 크레딧.
    if (
        sync_subscription
        and not (receipt.payload or {}).get("entitlement_erased")
        and receipt.product_id in SUBSCRIPTION_PRODUCTS
        and status
        in {
            "active",
            "cancelled",
            "expired",
            "refunded",
        }
    ):
        # H5: 이 영수증이 개설한 구독만 갱신한다. subscription_id가 없는 레거시 영수증은
        # '최신 구독' 임의 매칭 대신 product_id의 plan과 일치하는 구독으로 한정한다 —
        # 업그레이드 후 옛 영수증 통지가 방금 결제한 다른 plan 구독을 죽이지 않게.
        subscription = None
        if receipt.subscription_id is not None:
            subscription = await db.get(Subscription, receipt.subscription_id)
        else:
            legacy_plan = SUBSCRIPTION_PRODUCTS.get(receipt.product_id)
            sub_result = await db.execute(
                select(Subscription)
                .where(
                    Subscription.user_key == receipt.user_key,
                    Subscription.plan == legacy_plan,
                )
                .order_by(Subscription.created_at.desc())
            )
            subscription = sub_result.scalars().first()
        if subscription:
            if status == "active":
                # H3/R2-1: 스토어가 '다시 활성'을 통지하면 서버도 복귀한다. 터미널
                # (refunded/expired) 영수증은 위 sticky 가드에서 이미 걸러졌으므로 여기까지
                # 오지 않는다 — 환불 후 부활은 여전히 불가능하다.
                if subscription.status == "cancelled":
                    subscription.status = "active"
            else:
                # cancelled는 기간 만료까지 사용 유지, expired/refunded는 즉시 권한 종료.
                subscription.status = "cancelled" if status == "cancelled" else "expired"
                if status in {"expired", "refunded"}:
                    subscription.current_period_end = utcnow() - timedelta(seconds=1)

    # 소비성 크레딧팩 환불 → 지급했던 크레딧 회수(멱등). add_credits가 사용한 것과 같은
    # reference_id(store_transaction_id 우선)로 회수해 이중 처리하지 않는다.
    if status == "refunded" and receipt.product_id in CREDIT_PACK_PRODUCTS:
        clawback_amount = CREDIT_PACK_PRODUCTS[receipt.product_id]
        clawback_ref = receipt.store_transaction_id or receipt.transaction_id
        await credits_service.clawback_credits(
            db=db,
            user_key=receipt.user_key,
            amount=clawback_amount,
            reference_id=clawback_ref,
            description=f"IAP 크레딧 팩 {clawback_amount}개 환불 회수",
            commit=False,
        )

    # M14: 구독 상품 환불도 지급된 월간 크레딧을 회수(0클램프·멱등). 회수 안 하면
    # buy→30크레딧→refund 사이클마다 무비용 적립된다.
    #
    # M3/R2-3: 회수액은 **이 영수증이 실제로 지급한 액수**여야 한다. 플랜 고정액을 회수하면
    # 0지급 영수증(restored / already_subscribed — 둘 다 grant_credits 없음)의 환불이
    # 아무 잘못 없는 사용자의 크레딧을 차감한다. 원장(credit_transactions)에서 이 구독에
    # 실제 지급된 액수를 읽어 연동하고, 0지급이면 0회수(=no-op)한다.
    if status == "refunded" and receipt.product_id in SUBSCRIPTION_PRODUCTS:
        clawback_amount = await _granted_subscription_credits(db, receipt)
        clawback_ref = receipt.store_transaction_id or receipt.transaction_id
        grant_user_key = _credit_grant_user_key(receipt)
        # Account erasure must not recreate an old beneficiary via get_or_create.
        balance = await db.scalar(
            select(UserCredits).where(UserCredits.user_key == grant_user_key).with_for_update()
        ) if grant_user_key else None
        identity = await db.get(AccountIdentity, grant_user_key) if grant_user_key else None
        if clawback_amount > 0 and balance is not None and not (identity and identity.deleted):
            await credits_service.clawback_credits(
                db=db,
                user_key=grant_user_key,
                amount=clawback_amount,
                reference_id=clawback_ref,
                description="구독 환불 회수",
                commit=False,
            )
        else:
            logger.info(
                "subscription refund clawback skipped (no grant or beneficiary unavailable)",
                transaction_id=receipt.transaction_id,
                receipt_status=receipt.status,
            )


async def _reapply_orphan_events(db: AsyncSession, receipt: IAPReceipt) -> None:
    """verify/restore 직후, 이 영수증에 매칭되는 미적용 웹훅 이벤트를 sticky 재적용한다(H4).

    선도착·store 식별자 환불/취소 통지가 유실되지 않고 여기서 반영된다. created_at 순 +
    _apply_status_to_receipt의 sticky 우선순위로 정합.
    """
    # API sessions disable autoflush. Native reconciliation must see the new
    # receipt and its grant while both still belong to the caller's transaction.
    await db.flush()
    match_clauses = [
        IapWebhookEvent.transaction_id == receipt.transaction_id,
        IapWebhookEvent.transaction_id == receipt.store_transaction_id,
    ]
    original = (receipt.payload or {}).get("original_transaction_id")
    if original:
        match_clauses.append(
            IapWebhookEvent.payload["native_store_event"]["original_transaction_id"].as_string()
            == original
        )
    if receipt.platform in {"google", "google_sandbox"}:
        # H4/#6: Google 갱신 주문 orderId는 base에 '..N' 접미가 붙는다. 접미사가 붙은
        # orderId로 선도착한 환불/취소 웹훅은 base로 verify된 영수증과 원문 등호로는
        # 절대 매칭되지 않아 결정이 영구 유실된다(환불된 구독이 active로 남아 매월 리필).
        # 양방향(이벤트에 접미 / 영수증에 접미)을 모두 정규화해 맞춘다.
        for ident in (receipt.store_transaction_id, receipt.transaction_id):
            if not ident:
                continue
            base = _strip_google_order_suffix(ident)
            escaped = base.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            match_clauses.append(IapWebhookEvent.transaction_id == base)
            match_clauses.append(IapWebhookEvent.transaction_id.like(f"{escaped}..%", escape="\\"))

    events = (
        (
            await db.execute(
                select(IapWebhookEvent)
                .where(
                    IapWebhookEvent.platform == receipt.platform,
                    IapWebhookEvent.applied.is_(False),
                    or_(*match_clauses),
                )
                .order_by(IapWebhookEvent.created_at.asc(), IapWebhookEvent.id.asc())
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for event in events:
        native = (event.payload or {}).get("native_store_event")
        if isinstance(native, dict):
            if native.get("environment") is None and event.platform == "google" and event.status == "refunded":
                # Previous versions omitted the environment on authenticated Google
                # refunds. Bind them only to the exact verified order in this ledger.
                if event.transaction_id != receipt.store_transaction_id or _legacy_sandbox_receipt(receipt):
                    continue
                native = {**native, "environment": "Production"}
            outcome = await _apply_native_event(StoreEvent(**native), db, commit=False)
            if outcome["status"] == "accepted_orphan":
                continue
        else:
            await _apply_status_to_receipt(
                receipt=receipt, status=event.status, payload=event.payload, db=db
            )
        event.applied = True
        await db.flush()


async def _apply_webhook_status(
    *,
    request: IAPWebhookRequest,
    platform: str,
    db: AsyncSession,
) -> dict:
    # 매칭: 클라이언트 transaction_id 또는 스토어 store_transaction_id 양쪽(Google은
    # order suffix 정규화). 스토어가 store 식별자로만 보내는 환불 통지의 유실을 막는다.
    await _lock_store_settlement(db, platform, request.transaction_id)
    normalized = (
        _strip_google_order_suffix(request.transaction_id)
        if platform == "google"
        else request.transaction_id
    )
    result = await db.execute(
        select(IAPReceipt).where(
            IAPReceipt.platform == platform,
            or_(
                IAPReceipt.transaction_id == request.transaction_id,
                IAPReceipt.store_transaction_id == request.transaction_id,
                IAPReceipt.store_transaction_id == normalized,
            ),
        )
    )
    receipt = result.scalars().first()

    if not receipt:
        # 미기록 트랜잭션(선도착·store 식별자): 200 ignored로 재시도를 죽이면 결정이 유실된다.
        # IapWebhookEvent로 적재(멱등)해 결정을 보존하고 verify 시 sticky 재적용한다. 적재
        # 실패(IntegrityError 외)는 재시도 유도 위해 5xx로 전파.
        await _persist_orphan_event(db, platform, request.transaction_id, request.status, request.payload)
        return {
            "status": "accepted_orphan",
            "message": "Persisted for reconciliation at verify time",
            "transaction_id": request.transaction_id,
        }

    await _apply_status_to_receipt(
        receipt=receipt, status=request.status, payload=request.payload, db=db
    )
    await db.commit()

    logger.info(
        "IAP webhook applied",
        platform=platform,
        transaction_id=receipt.transaction_id,
        receipt_status=receipt.status,
    )

    return {
        "status": "ok",
        "transaction_id": receipt.transaction_id,
        "platform": platform,
        "receipt_status": receipt.status,
    }


async def _persist_orphan_event(
    db: AsyncSession, platform: str, transaction_id: str, status: str, payload: Optional[dict],
) -> None:
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
    await db.execute(insert(IapWebhookEvent).values(
        platform=platform, transaction_id=transaction_id, status=status, payload=payload, applied=False,
    ).on_conflict_do_nothing(index_elements=["platform", "transaction_id", "status"]))
    await db.commit()


async def _require_webhook_secret(
    x_webhook_token: Optional[str] = Header(default=None, alias="X-Webhook-Token"),
):
    """IAP 웹훅 인증: iap_webhook_secret이 설정되면 토큰이 일치해야 한다.

    Apple/Google이 호출하는 공개 엔드포인트가 무인증이면 알려진 transaction id로 구독
    상태를 변조(취소성 공격)할 수 있다. 토큰은 **X-Webhook-Token 헤더로만** 받는다.
    이 엔드포인트는 스토어가 직접 호출하지 않고 신뢰된 어댑터가 호출하므로(커스텀 스키마)
    헤더 전달이 가능하다. 과거 ?token= 쿼리 폴백은 nginx 액세스 로그($request)에 시크릿이
    평문 기록되는 유출 경로였다(감사 iap.py:614/L10) — 제거했다. 시크릿 미설정 시
    운영(testing=False)에서는 무인증 상태변조를 막기 위해 거부한다(fail-closed).
    """
    secret = settings.iap_webhook_secret
    if not secret:
        if not settings.testing:
            raise AuthorizationError("웹훅 인증이 구성되지 않았습니다.")
        return
    provided = x_webhook_token if x_webhook_token is not None else ""
    if not hmac.compare_digest(provided, secret):
        raise AuthorizationError("유효하지 않은 웹훅 토큰입니다.")


@router.post("/webhook/apple")
async def apple_webhook(
    request: IAPWebhookRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_webhook_secret),
):
    return await _apply_webhook_status(request=request, platform="apple", db=db)


@router.post("/webhook/google")
async def google_webhook(
    request: IAPWebhookRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_webhook_secret),
):
    return await _apply_webhook_status(request=request, platform="google", db=db)


async def _apply_native_event(event: StoreEvent, db: AsyncSession, *, commit: bool = True) -> dict:
    """Reconcile authenticated native events, with transaction-scoped grants.

    Lock the known subscription receipt before creating renewal receipts. Different
    notifications for one cycle serialize; database uniqueness is the final guard.
    Older refunds may claw back only their own grant, never expire a newer cycle.
    """
    if event.environment not in {"Production", "Sandbox"}:
        raise ValidationError("알림의 스토어 환경을 확인할 수 없습니다.")
    sandbox = event.environment == "Sandbox"
    review_products = review_sandbox_products() if sandbox else set()
    if sandbox and (not settings.store_review_account_slots or not review_products
                    or (event.product_id and event.product_id not in review_products)):
        raise ValidationError("허용되지 않은 샌드박스 알림입니다.")
    ledger_platform = f"{event.platform}_sandbox" if sandbox else event.platform
    if commit:
        # Replayed orphans already run under the receipt writer's transaction.
        await _lock_store_settlement(
            db, ledger_platform, event.transaction_id, event.original_transaction_id,
            event.purchase_token, event.linked_purchase_token,
        )
    exact = await db.scalar(
        select(IAPReceipt)
        .where(
            IAPReceipt.platform == ledger_platform,
            IAPReceipt.store_transaction_id == event.transaction_id,
        )
        .with_for_update()
    )
    anchor = exact
    if anchor is None:
        matches = []
        if event.original_transaction_id:
            matches.extend(
                [
                    IAPReceipt.store_transaction_id == event.original_transaction_id,
                    IAPReceipt.payload["original_transaction_id"].as_string()
                    == event.original_transaction_id,
                ]
            )
        if event.purchase_token:
            matches.append(IAPReceipt.purchase_token == event.purchase_token)
        if event.linked_purchase_token:
            matches.append(IAPReceipt.purchase_token == event.linked_purchase_token)
        if matches:
            anchor = await db.scalar(
                select(IAPReceipt)
                .where(
                    IAPReceipt.platform == ledger_platform,
                    or_(*matches),
                )
                .order_by(IAPReceipt.created_at.desc(), IAPReceipt.id.desc())
                .with_for_update()
            )
    if anchor is None:
        if not commit:
            # A client alias or Google order prefix matched the pending row,
            # but the native event has no verified receipt to apply to yet.
            return {"status": "accepted_orphan"}
        # Persist before ack so notification-before-client-verification is safe.
        await _persist_orphan_event(
            db, ledger_platform, event.transaction_id, event.status, event.persisted_payload(),
        )
        return {"status": "accepted_orphan"}
    product = event.product_id or anchor.product_id
    if sandbox and (product not in review_products or not await is_claimed_store_review_slot(db, anchor.user_key)):
        raise ValidationError("이 심사 계정의 샌드박스 구매를 확인할 수 없습니다.")
    if _legacy_sandbox_receipt(anchor):
        # Historic test receipts could be stored in the commercial namespace.
        raise ValidationError("알림과 기존 구매의 스토어 환경이 다릅니다.")
    plan = SUBSCRIPTION_PRODUCTS.get(product)
    subscription = (
        await db.get(Subscription, anchor.subscription_id) if anchor.subscription_id else None
    )
    if subscription:
        await db.refresh(subscription, with_for_update=True)
        subscription.calendar_refill_enabled = False
    now_ms = int(utcnow().replace(tzinfo=timezone.utc).timestamp() * 1000)
    expiry = event.expires_date_ms or (
        int((exact.payload or {}).get("expires_date_ms") or 0) if exact else 0
    )
    current_end = (
        int(subscription.current_period_end.replace(tzinfo=timezone.utc).timestamp() * 1000)
        if subscription
        else 0
    )
    replacement_grant = None
    replacement_allocation = None
    if product != anchor.product_id:
        if (
            exact is not None
            or not subscription
            or not plan
            or anchor.product_id not in SUBSCRIPTION_PRODUCTS
            or not event.grants_cycle
            or event.status != "active"
            or expiry <= now_ms
        ):
            raise ValidationError("알림 상품이 등록된 결제 상품과 다릅니다.")
        replacement_grant, replacement_allocation = await _plan_change_credit_grant(
            db, plan, subscription, event.purchased_at_ms
        )
        # The signed store transaction proves a paid tier replacement. Preserve
        # the old receipt history; create a new entitlement for the new product.
        subscription = await credits_service.create_subscription(
            db, anchor.user_key, plan, commit=False, grant_credits=False
        )
        subscription.calendar_refill_enabled = False
        subscription.current_period_end = datetime.fromtimestamp(
            expiry / 1000, timezone.utc
        ).replace(tzinfo=None)
        current_end = expiry
    receipt = exact
    if receipt is None:
        receipt = IAPReceipt(
            user_key=anchor.user_key,
            platform=ledger_platform,
            product_id=product,
            transaction_id=event.transaction_id,
            store_transaction_id=event.transaction_id,
            purchase_token=event.purchase_token or anchor.purchase_token,
            subscription_id=subscription.id if subscription else None,
            status="verified",
            payload={
                "original_transaction_id": event.original_transaction_id,
                "verification_environment": event.environment,
                "credit_grant_user_key": anchor.user_key,
                "granted_credits": 0,
            },
        )
        db.add(receipt)
        await db.flush()
    previous_signed = (receipt.payload or {}).get("native_signed_at_ms", 0) or 0
    if event.signed_at_ms and event.signed_at_ms < previous_signed:
        return {"status": "ignored_older_event"}
    terminal = receipt.status in {"refunded", "expired"}
    # Recover a temporarily held/expired same Google transaction when the current
    # Publisher state says active. A revoked/refunded transaction stays terminal.
    if event.platform == "google" and receipt.status == "expired" and expiry > now_ms:
        terminal = False
        receipt.status = "verified"
    granted = int((receipt.payload or {}).get("granted_credits", 0))
    if (
        subscription
        and plan
        and event.status in {"active", "cancelled"}
        and expiry > now_ms
        and not terminal
    ):
        if replacement_grant is not None or (
            event.grants_cycle and expiry > current_end and exact is None
        ):
            first_grant = await claim_purchase(db, ledger_platform, event.transaction_id)
            granted = (
                replacement_grant
                if replacement_grant is not None
                else subscription.credits_per_month or SUBSCRIPTION_PLANS[plan]["credits_per_month"]
            )
            if not first_grant:
                granted = 0
            if granted:
                await credits_service.add_credits(
                    db,
                    anchor.user_key,
                    amount=granted,
                    transaction_type="subscription",
                    description="스토어에서 확인한 구독 갱신 크레딧",
                    reference_id=f"iap:{ledger_platform}:{event.transaction_id}",
                    commit=False,
                )
        if expiry >= current_end:
            subscription.current_period_end = datetime.fromtimestamp(
                expiry / 1000, timezone.utc
            ).replace(tzinfo=None)
            subscription.status = event.status
    receipt.payload = {
        **(receipt.payload or {}),
        **event.persisted_payload(),
        "granted_credits": granted,
        "cycle_allocated_credits": replacement_allocation
        if replacement_allocation is not None
        else (receipt.payload or {}).get(
            "cycle_allocated_credits", subscription.credits_per_month if subscription else granted
        ),
        "native_signed_at_ms": event.signed_at_ms or previous_signed,
        "expires_date_ms": expiry,
    }
    # Receipt refunds still claw back that cycle's grant. Historical events must
    # not overwrite a newer cycle's expiry/cancellation or resurrect its access.
    sync_subscription = bool(expiry and expiry >= current_end)
    if not terminal or event.status == "refunded":
        await _apply_status_to_receipt(
            receipt=receipt,
            status=event.status,
            payload=None,
            db=db,
            sync_subscription=sync_subscription,
        )
    if commit:
        await db.commit()
    return {"status": "ok"}


class AppleNotificationRequest(BaseModel):
    signedPayload: str = Field(min_length=10, max_length=65536)


class GooglePubSubMessage(BaseModel):
    data: str = Field(min_length=1, max_length=32000)
    messageId: str = Field(min_length=1, max_length=200)
    publishTime: Optional[str] = Field(default=None, max_length=100)
    attributes: Optional[dict[str, str]] = None


class GoogleNotificationRequest(BaseModel):
    message: GooglePubSubMessage
    subscription: str = Field(min_length=1, max_length=500)


@router.post("/notifications/apple")
async def apple_native_notification(
    request: AppleNotificationRequest, db: AsyncSession = Depends(get_db)
):
    event = await decode_apple_notification(request.signedPayload)
    if event is None:
        return {"status": "acknowledged"}
    try:
        return await _apply_native_event(event, db)
    except IntegrityError:
        await db.rollback()
        # A concurrent worker may have committed the exact transaction. Replay
        # reconciliation once to preserve a refund that raced with a renewal.
        return await _apply_native_event(event, db)


@router.post("/notifications/google")
async def google_native_notification(
    request: GoogleNotificationRequest,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
):
    await verify_google_push_identity(authorization)

    async def known_order_environment(order_id: str, token: str) -> str | None:
        receipts = (await db.scalars(select(IAPReceipt).where(
            IAPReceipt.platform.in_(("google", "google_sandbox")),
            IAPReceipt.store_transaction_id == order_id, IAPReceipt.purchase_token == token,
        ))).all()
        if len(receipts) != 1:
            return None
        receipt = receipts[0]
        return "Sandbox" if receipt.platform == "google_sandbox" or _legacy_sandbox_receipt(receipt) else "Production"

    event = await decode_google_notification(request.model_dump(), known_order_environment=known_order_environment)
    if event is None:
        return {"status": "acknowledged"}
    try:
        return await _apply_native_event(event, db)
    except IntegrityError:
        await db.rollback()
        return await _apply_native_event(event, db)
