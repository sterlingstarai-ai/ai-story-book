"""
IAP Router
Apple/Google 영수증 검증 및 웹훅 처리
"""

from datetime import timedelta
import hmac
from typing import Optional, Literal

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.core.config import settings
from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.core.exceptions import AuthorizationError, ValidationError
from src.core.utils import utcnow
from src.models.db import IAPReceipt, IapWebhookEvent, Subscription
from src.services.credits import SUBSCRIPTION_PLANS, credits_service
from src.services.iap_verifier import _strip_google_order_suffix, iap_verifier

router = APIRouter()
logger = structlog.get_logger()


class IAPVerifyRequest(BaseModel):
    platform: Literal["apple", "google"]
    product_id: str = Field(min_length=1, max_length=120)
    transaction_id: str = Field(min_length=1, max_length=200)
    purchase_token: Optional[str] = Field(default=None, max_length=500)
    receipt_data: Optional[str] = Field(default=None, max_length=10000)
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


CREDIT_PACK_PRODUCTS = {
    "credit_pack_1": 1,
    "credit_pack_5": 5,
    "credit_pack_10": 10,
}

SUBSCRIPTION_PRODUCTS = {
    "subscription_basic": "basic",
    "subscription_premium": "premium",
}


def _review_sandbox_allowlist() -> set:
    raw = settings.review_sandbox_allowlist or ""
    return {p.strip() for p in raw.split(",") if p.strip()}


def _subscription_expired(verification) -> bool:
    """스토어 만료 시각이 과거인 구독 영수증인지(MA1). 만료 영수증으로 active 구독을
    재활성하면 periodic_credits가 영구 리필하므로 지급/재활성을 막는다."""
    expires_ms = getattr(verification, "expires_date_ms", None)
    if not expires_ms:
        return False
    return expires_ms < int(utcnow().timestamp() * 1000)


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

    # 빠른 정직-재시도 dedup: 같은 사용자가 같은 transaction_id로 재전송하면 스토어
    # 재호출 없이 즉시 already_processed. (정본 dedup은 아래 store_transaction_id 기준.)
    existing_by_client = (
        await db.execute(
            select(IAPReceipt).where(
                IAPReceipt.platform == request.platform,
                IAPReceipt.transaction_id == transaction_id,
            )
        )
    ).scalar_one_or_none()
    if existing_by_client and existing_by_client.user_key == user_key:
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
    )

    if not verification.verified:
        raise ValidationError("스토어 검증에 실패했습니다.")

    # L10/G8: 운영에서 Sandbox 영수증(Apple 21007 폴백)은 무결제 테스터 영수증이므로 지급
    # 차단한다. 앱스토어 리뷰/TestFlight용 REVIEW_SANDBOX_ALLOWLIST 상품만 예외.
    if (
        not settings.testing
        and verification.environment == "Sandbox"
        and product_id not in _review_sandbox_allowlist()
    ):
        raise ValidationError(
            "샌드박스 영수증은 운영에서 지급되지 않습니다.",
            details={"code": "sandbox_not_allowed"},
        )

    if (
        verification.store_product_id
        and verification.store_product_id != product_id
    ):
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

    def _build_payload(extra: Optional[dict] = None) -> dict:
        base = {
            "receipt_data": receipt_data,
            "is_subscription": resolved_is_subscription,
            "verified_at": utcnow().isoformat(),
            "verification_source": verification.source,
            "verification_environment": verification.environment,
            "verification": verification.raw,
            "client_transaction_id": transaction_id,
        }
        if extra:
            base.update(extra)
        return base

    # with_for_update로 동시 복원을 직렬화(SQLite에선 no-op이라 실질 방어는 M17 부분 유니크).
    existing = (
        await db.execute(
            select(IAPReceipt)
            .where(
                IAPReceipt.platform == request.platform,
                IAPReceipt.store_transaction_id == store_txn,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    if existing:
        if existing.user_key == user_key:
            return IAPVerifyResponse(
                status="already_processed",
                transaction_id=existing.transaction_id,
                product_id=existing.product_id,
                credits_added=0,
                plan=None,
            )
        # F4 복원: 재설치/기기 변경으로 user_key가 새로 발급된 경우. 스토어가 이 영수증의
        # 소유를 방금 검증했으므로(verified=True) 권한을 호출자에게 이전한다. 소비성
        # 크레딧팩은 스토어가 복원해주지 않으므로 재지급하지 않는다(구독만 재활성).
        previous_user_key = existing.user_key
        existing.user_key = user_key
        existing.status = "restored"
        existing.payload = _build_payload({"restored_from_user_key": previous_user_key})
        try:
            if plan:
                # 권한 이전: 이전 소유자의 해당 plan active 구독만 만료(cancelled 잔여기간 보존, G2).
                if previous_user_key != user_key:
                    await credits_service.expire_active_subscription_for_plan(
                        db, previous_user_key, plan, commit=False
                    )
                # 복원은 월간 크레딧을 재지급하지 않는다(G1). 만료 영수증(MA1)은 active 구독을
                # 재활성하지 않는다 — 만료 영수증 1건 restore로 영구 리필되는 무한 수익화 차단.
                if not _subscription_expired(verification):
                    restored_sub = await credits_service.create_subscription(
                        db, user_key, plan, commit=False, grant_credits=False
                    )
                    existing.subscription_id = restored_sub.id  # H5
            await db.commit()
        except IntegrityError:
            # 동시 복원 경쟁 패자 — 현재 상태 재조회 후 멱등 반환.
            await db.rollback()
            active = await credits_service.get_active_subscription(db, user_key)
            return IAPVerifyResponse(
                status="restored",
                transaction_id=transaction_id,
                product_id=product_id,
                credits_added=0,
                plan=active.plan if active else plan,
                verification_source=verification.source,
            )
        # 선도착 환불/취소 웹훅(orphan)을 이 영수증에 sticky 재적용(H4).
        await _reapply_orphan_events(db, existing)
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

    # 이미 같은 플랜이 활성이면 보상 없이 영수증만 기록.
    if plan:
        active_subscription = await credits_service.get_active_subscription(db, user_key)
        if active_subscription and active_subscription.plan == plan:
            receipt = IAPReceipt(
                user_key=user_key,
                platform=request.platform,
                product_id=product_id,
                transaction_id=transaction_id,
                store_transaction_id=store_txn,
                purchase_token=purchase_token,
                status="already_subscribed",
                subscription_id=active_subscription.id,  # H5
                payload=_build_payload(),
            )
            db.add(receipt)
            committed = True
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                committed = False
            if committed:
                await _reapply_orphan_events(db, receipt)
            return IAPVerifyResponse(
                status="already_subscribed",
                transaction_id=transaction_id,
                product_id=product_id,
                credits_added=0,
                plan=plan,
                verification_source=verification.source,
            )

    # 보상 지급 + 영수증 기록을 단일 트랜잭션으로 묶는다(F3: 더블그랜트/고아 방지).
    # 동시 요청 중 패자는 store_transaction_id UNIQUE 위반으로 IntegrityError → 전체
    # 롤백되어 보상도 함께 취소된다.
    try:
        new_sub = None
        if plan:
            # 만료 영수증(MA1)은 active 구독을 만들지 않는다(무한 리필 차단). 영수증만 기록.
            if not _subscription_expired(verification):
                new_sub = await credits_service.create_subscription(
                    db, user_key, plan, commit=False
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
            platform=request.platform,
            product_id=product_id,
            transaction_id=transaction_id,
            store_transaction_id=store_txn,
            purchase_token=purchase_token,
            status="verified",
            # H5: 웹훅이 이 영수증의 구독만 갱신하도록 연결.
            subscription_id=new_sub.id if new_sub else None,
            payload=_build_payload(),
        )
        db.add(receipt)
        await db.commit()
    except IntegrityError:
        # 동시 요청 패자(또는 client transaction_id 충돌) — 보상은 롤백됨.
        await db.rollback()
        logger.info(
            "IAP concurrent duplicate rejected",
            platform=request.platform,
            store_transaction_id=store_txn,
        )
        return IAPVerifyResponse(
            status="already_processed",
            transaction_id=transaction_id,
            product_id=product_id,
            credits_added=0,
            plan=None,
        )

    # 선도착 환불/취소 웹훅(orphan)을 이 영수증에 sticky 재적용(H4).
    await _reapply_orphan_events(db, receipt)

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


# 상태 우선순위(sticky): 터미널(refunded/expired) > cancelled > 그 외. 낮은 순위로 되돌리지
# 않는다 — 환불/만료된 영수증이 이후 active 통지로 뒤집히지 않게 한다(H4).
_STATUS_RANK = {"refunded": 3, "expired": 3, "cancelled": 2}


def _status_rank(status: Optional[str]) -> int:
    return _STATUS_RANK.get(status or "", 1)


async def _apply_status_to_receipt(
    *,
    receipt: IAPReceipt,
    status: str,
    payload: Optional[dict],
    db: AsyncSession,
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
    if receipt.product_id in SUBSCRIPTION_PRODUCTS and status in {
        "cancelled",
        "expired",
        "refunded",
    }:
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
    if status == "refunded" and receipt.product_id in SUBSCRIPTION_PRODUCTS:
        plan = SUBSCRIPTION_PRODUCTS[receipt.product_id]
        clawback_amount = SUBSCRIPTION_PLANS[plan]["credits_per_month"]
        clawback_ref = receipt.store_transaction_id or receipt.transaction_id
        await credits_service.clawback_credits(
            db=db,
            user_key=receipt.user_key,
            amount=clawback_amount,
            reference_id=clawback_ref,
            description="구독 환불 회수",
            commit=False,
        )


async def _reapply_orphan_events(db: AsyncSession, receipt: IAPReceipt) -> None:
    """verify/restore 직후, 이 영수증에 매칭되는 미적용 웹훅 이벤트를 sticky 재적용한다(H4).

    선도착·store 식별자 환불/취소 통지가 유실되지 않고 여기서 반영된다. created_at 순 +
    _apply_status_to_receipt의 sticky 우선순위로 정합.
    """
    events = (
        await db.execute(
            select(IapWebhookEvent)
            .where(
                IapWebhookEvent.platform == receipt.platform,
                IapWebhookEvent.applied.is_(False),
                or_(
                    IapWebhookEvent.transaction_id == receipt.transaction_id,
                    IapWebhookEvent.transaction_id == receipt.store_transaction_id,
                ),
            )
            .order_by(IapWebhookEvent.created_at.asc(), IapWebhookEvent.id.asc())
        )
    ).scalars().all()
    if not events:
        return
    for event in events:
        await _apply_status_to_receipt(
            receipt=receipt, status=event.status, payload=event.payload, db=db
        )
        event.applied = True
    await db.commit()


async def _apply_webhook_status(
    *,
    request: IAPWebhookRequest,
    platform: str,
    db: AsyncSession,
) -> dict:
    # 매칭: 클라이언트 transaction_id 또는 스토어 store_transaction_id 양쪽(Google은
    # order suffix 정규화). 스토어가 store 식별자로만 보내는 환불 통지의 유실을 막는다.
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
        db.add(
            IapWebhookEvent(
                platform=platform,
                transaction_id=request.transaction_id,
                status=request.status,
                payload=request.payload,
                applied=False,
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()  # 중복 웹훅 — 이미 보존됨(멱등)
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


async def _require_webhook_secret(
    token: str = Query(default=""),
    x_webhook_token: Optional[str] = Header(default=None, alias="X-Webhook-Token"),
):
    """IAP 웹훅 인증: iap_webhook_secret이 설정되면 토큰이 일치해야 한다.

    Apple/Google이 호출하는 공개 엔드포인트가 무인증이면 알려진 transaction id로 구독
    상태를 변조(취소성 공격)할 수 있다. 토큰은 X-Webhook-Token 헤더 우선, 미제공 시
    ?token= 쿼리로 폴백(하위호환·쿼리는 로그/리퍼러 노출 위험이라 헤더 권장, L10).
    시크릿 미설정 시 운영(testing=False)에서는 무인증 상태변조를 막기 위해 거부한다
    (fail-closed). dev/test에서만 통과해 기존 동작을 유지한다.
    """
    secret = settings.iap_webhook_secret
    if not secret:
        if not settings.testing:
            raise AuthorizationError("웹훅 인증이 구성되지 않았습니다.")
        return
    provided = x_webhook_token if x_webhook_token is not None else token
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
