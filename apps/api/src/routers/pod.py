"""
POD Router
실물 동화책 주문
"""

import uuid
import re
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.core.exceptions import NotFoundError, ValidationError
from src.core.utils import utcnow
from src.models.db import Book, PodOrder
from src.services.pod_provider import pod_provider_service

router = APIRouter()
logger = structlog.get_logger()


class ShippingAddressInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    line1: str = Field(min_length=1, max_length=200)
    line2: Optional[str] = Field(default=None, max_length=200)
    city: Optional[str] = Field(default=None, max_length=120)
    state: Optional[str] = Field(default=None, max_length=120)
    postal_code: str = Field(min_length=1, max_length=40)
    country: str = Field(min_length=2, max_length=2)
    phone: Optional[str] = Field(default=None, max_length=40)


class PodOrderCreateRequest(BaseModel):
    book_id: str
    quantity: int = Field(default=1, ge=1, le=10)
    shipping_address: ShippingAddressInput


_COUNTRY_CODE_PATTERN = re.compile(r"^[A-Za-z]{2}$")


def _normalize_shipping_address(payload: ShippingAddressInput) -> dict:
    data = payload.model_dump(exclude_none=True)
    normalized: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, str):
            normalized[key] = value.strip()

    required = ("name", "line1", "postal_code", "country")
    for field_name in required:
        if not normalized.get(field_name):
            raise ValidationError(
                "배송지 정보가 올바르지 않습니다.",
                details={"required": list(required)},
            )

    country = normalized["country"]
    if not _COUNTRY_CODE_PATTERN.fullmatch(country):
        raise ValidationError(
            "country는 2자리 국가 코드여야 합니다.",
            details={"country": country},
        )

    normalized["country"] = country.upper()
    return normalized


@router.post("/orders")
async def create_pod_order(
    request: PodOrderCreateRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    book_result = await db.execute(select(Book).where(Book.id == request.book_id))
    book = book_result.scalar_one_or_none()
    if not book:
        raise NotFoundError("책", request.book_id)
    if book.user_key != user_key:
        raise ValidationError("본인의 책만 주문할 수 있습니다.")

    shipping_address = _normalize_shipping_address(request.shipping_address)

    unit_price = 18000
    shipping_fee = 3000
    total_price = (unit_price * request.quantity) + shipping_fee
    order_id = f"pod_{utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"

    provider_result = await pod_provider_service.create_order(
        local_order_id=order_id,
        quantity=request.quantity,
        shipping_address=shipping_address,
    )
    effective_total = provider_result.total_price or total_price
    effective_currency = provider_result.currency or "KRW"

    order = PodOrder(
        id=order_id,
        user_key=user_key,
        book_id=request.book_id,
        provider=provider_result.provider,
        status=provider_result.status,
        quantity=request.quantity,
        unit_price=unit_price,
        shipping_fee=shipping_fee,
        total_price=effective_total,
        currency=effective_currency,
        shipping_address=shipping_address,
        provider_order_id=provider_result.provider_order_id,
        tracking_number=provider_result.tracking_number,
    )

    db.add(order)
    await db.commit()
    await db.refresh(order)

    logger.info(
        "POD order created",
        order_id=order.id,
        provider=order.provider,
        status=order.status,
        sync_source=provider_result.sync_source,
    )

    return {
        "order_id": order.id,
        "status": order.status,
        "provider": order.provider,
        "total_price": order.total_price,
        "currency": order.currency,
        "provider_order_id": order.provider_order_id,
        "tracking_number": order.tracking_number,
        "sync_source": provider_result.sync_source,
    }


@router.get("/orders/{order_id}")
async def get_pod_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    result = await db.execute(
        select(PodOrder).where(
            PodOrder.id == order_id,
            PodOrder.user_key == user_key,
        )
    )
    order = result.scalar_one_or_none()
    if not order:
        raise NotFoundError("주문", order_id)

    status_result = await pod_provider_service.sync_order_status(
        provider_order_id=order.provider_order_id,
        current_status=order.status,
    )
    if status_result.status and status_result.status != order.status:
        order.status = status_result.status
    if status_result.tracking_number and status_result.tracking_number != order.tracking_number:
        order.tracking_number = status_result.tracking_number
    await db.commit()
    await db.refresh(order)

    logger.info(
        "POD order status synced",
        order_id=order.id,
        provider=order.provider,
        status=order.status,
        sync_source=status_result.sync_source,
    )

    return {
        "order_id": order.id,
        "book_id": order.book_id,
        "provider": order.provider,
        "status": order.status,
        "quantity": order.quantity,
        "unit_price": order.unit_price,
        "shipping_fee": order.shipping_fee,
        "total_price": order.total_price,
        "currency": order.currency,
        "provider_order_id": order.provider_order_id,
        "tracking_number": order.tracking_number,
        "sync_source": status_result.sync_source,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }
