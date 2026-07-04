"""
IAP Router
Apple/Google 영수증 검증 및 웹훅 처리
"""

from datetime import timedelta
import hmac
from typing import Optional, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.core.config import settings
from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.core.exceptions import AuthorizationError, ValidationError
from src.core.utils import utcnow
from src.models.db import IAPReceipt, Subscription
from src.services.credits import credits_service
from src.services.iap_verifier import iap_verifier

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

    existing = (
        await db.execute(
            select(IAPReceipt).where(
                IAPReceipt.platform == request.platform,
                IAPReceipt.store_transaction_id == store_txn,
            )
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
        if plan:
            await credits_service.create_subscription(db, user_key, plan, commit=False)
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
                payload=_build_payload(),
            )
            db.add(receipt)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
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
        if plan:
            await credits_service.create_subscription(db, user_key, plan, commit=False)
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


async def _apply_webhook_status(
    *,
    request: IAPWebhookRequest,
    platform: str,
    db: AsyncSession,
) -> dict:
    result = await db.execute(
        select(IAPReceipt).where(
            IAPReceipt.platform == platform,
            IAPReceipt.transaction_id == request.transaction_id,
        )
    )
    receipt = result.scalar_one_or_none()

    if not receipt:
        return {
            "status": "ignored",
            "message": "Unknown transaction",
            "transaction_id": request.transaction_id,
        }

    receipt.status = request.status
    receipt.payload = {
        **(receipt.payload or {}),
        "webhook_status": request.status,
        "webhook_payload": request.payload,
        "updated_at": utcnow().isoformat(),
    }

    # 구독 취소/만료/환불 동기화. 'refunded'를 누락하면 환불된 구독이 active로 남아
    # periodic_credits가 매월 영구 리필 → buy→consume→refund 무한 무료 크레딧.
    if receipt.product_id in SUBSCRIPTION_PRODUCTS and request.status in {
        "cancelled",
        "expired",
        "refunded",
    }:
        sub_result = await db.execute(
            select(Subscription)
            .where(Subscription.user_key == receipt.user_key)
            .order_by(Subscription.created_at.desc())
        )
        subscription = sub_result.scalars().first()
        if subscription:
            # cancelled는 기간 만료까지 사용 유지, expired/refunded는 즉시 권한 종료.
            subscription.status = "cancelled" if request.status == "cancelled" else "expired"
            if request.status in {"expired", "refunded"}:
                subscription.current_period_end = utcnow() - timedelta(seconds=1)

    # 소비성 크레딧팩 환불 → 지급했던 크레딧 회수(멱등). add_credits가 사용한 것과 같은
    # reference_id(store_transaction_id 우선)로 회수해 이중 처리하지 않는다.
    if request.status == "refunded" and receipt.product_id in CREDIT_PACK_PRODUCTS:
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


async def _require_webhook_secret(token: str = Query(default="")):
    """IAP 웹훅 인증: iap_webhook_secret이 설정되면 ?token=과 일치해야 한다.

    Apple/Google이 호출하는 공개 엔드포인트가 무인증이면 알려진 transaction id로 구독
    상태를 변조(취소성 공격)할 수 있다. 운영에선 시크릿을 설정하고 웹훅 URL에 토큰을 담는다.
    미설정 시(dev/test)는 통과해 기존 동작을 유지하나, 운영 배포 시 필수.
    """
    secret = settings.iap_webhook_secret
    if secret and not hmac.compare_digest(token, secret):
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
