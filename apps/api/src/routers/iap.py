"""
IAP Router
Apple/Google 영수증 검증 및 웹훅 처리
"""

from datetime import timedelta
from typing import Optional, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.core.exceptions import ValidationError
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

    existing_result = await db.execute(
        select(IAPReceipt).where(
            IAPReceipt.platform == request.platform,
            IAPReceipt.transaction_id == transaction_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        logger.info(
            "IAP receipt already processed",
            platform=request.platform,
            transaction_id=transaction_id,
            product_id=existing.product_id,
        )
        return IAPVerifyResponse(
            status="already_processed",
            transaction_id=existing.transaction_id,
            product_id=existing.product_id,
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

    if plan:
        active_subscription = await credits_service.get_active_subscription(db, user_key)
        if active_subscription and active_subscription.plan == plan:
            receipt = IAPReceipt(
                user_key=user_key,
                platform=request.platform,
                product_id=product_id,
                transaction_id=transaction_id,
                purchase_token=purchase_token,
                status="already_subscribed",
                payload={
                    "receipt_data": receipt_data,
                    "is_subscription": resolved_is_subscription,
                    "verified_at": utcnow().isoformat(),
                    "verification_source": verification.source,
                    "verification_environment": verification.environment,
                    "verification": verification.raw,
                },
            )
            db.add(receipt)
            await db.commit()
            logger.info(
                "IAP subscription already active",
                platform=request.platform,
                transaction_id=transaction_id,
                product_id=product_id,
                plan=plan,
            )
            return IAPVerifyResponse(
                status="already_subscribed",
                transaction_id=transaction_id,
                product_id=product_id,
                credits_added=0,
                plan=plan,
                verification_source=verification.source,
            )
        await credits_service.create_subscription(db, user_key, plan)
    elif credits_to_add > 0:
        await credits_service.add_credits(
            db=db,
            user_key=user_key,
            amount=credits_to_add,
            transaction_type="purchase",
            description=f"IAP 크레딧 팩 {credits_to_add}개",
            reference_id=transaction_id,
        )

    receipt = IAPReceipt(
        user_key=user_key,
        platform=request.platform,
        product_id=product_id,
        transaction_id=transaction_id,
        purchase_token=purchase_token,
        status="verified",
        payload={
            "receipt_data": receipt_data,
            "is_subscription": resolved_is_subscription,
            "verified_at": utcnow().isoformat(),
            "verification_source": verification.source,
            "verification_environment": verification.environment,
            "verification": verification.raw,
        },
    )
    db.add(receipt)
    await db.commit()

    logger.info(
        "IAP receipt verified",
        platform=request.platform,
        transaction_id=transaction_id,
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

    # 구독 취소/만료 동기화 (간단 구현)
    if receipt.product_id in SUBSCRIPTION_PRODUCTS and request.status in {
        "cancelled",
        "expired",
    }:
        sub_result = await db.execute(
            select(Subscription)
            .where(Subscription.user_key == receipt.user_key)
            .order_by(Subscription.created_at.desc())
        )
        subscription = sub_result.scalars().first()
        if subscription:
            subscription.status = "cancelled" if request.status == "cancelled" else "expired"
            if request.status == "expired":
                subscription.current_period_end = utcnow() - timedelta(seconds=1)

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


@router.post("/webhook/apple")
async def apple_webhook(
    request: IAPWebhookRequest,
    db: AsyncSession = Depends(get_db),
):
    return await _apply_webhook_status(request=request, platform="apple", db=db)


@router.post("/webhook/google")
async def google_webhook(
    request: IAPWebhookRequest,
    db: AsyncSession = Depends(get_db),
):
    return await _apply_webhook_status(request=request, platform="google", db=db)
