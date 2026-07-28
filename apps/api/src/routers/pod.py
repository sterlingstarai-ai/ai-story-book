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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.core.config import settings
from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.core.exceptions import NotFoundError, ValidationError
from src.core.utils import utcnow
from src.models.db import Book, PodOrder
from src.routers.books import get_idempotency_key
from src.services.pod_provider import PodSubmitUnknown, pod_provider_service

# 사용자 표시·조회 시 종결(더 이상 변하지 않는) 상태 — provider 통지로 역행하지 않게 sticky(L6).
# #16: 외부 미제출 상태 — 멱등 재요청을 '접수 성공'으로 위장하지 않고 재제출을 시도한다.
_POD_RESUBMITTABLE_STATUSES = {"pending_submit", "pending_provider"}
_TERMINAL_POD_STATUSES = {"fulfilled", "shipped", "delivered", "canceled", "cancelled", "refunded"}

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


# 지역별 POD 가격 폴백(provider가 가격 미제공 시). 배송 국가 기준으로 서버에서 산출
# — 클라이언트가 보낸 가격을 신뢰하지 않는다. 값: (단가, 배송비, 통화)
_POD_PRICING = {
    "KR": (18000, 3000, "KRW"),
    "US": (20, 5, "USD"),
    "JP": (2500, 500, "JPY"),
}
_POD_PRICING_DEFAULT = (20, 8, "USD")


def _pod_pricing_for(country: str) -> tuple:
    """배송 국가 코드 → (단가, 배송비, 통화). 미지원 국가는 USD 기본."""
    return _POD_PRICING.get((country or "").upper(), _POD_PRICING_DEFAULT)


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

    # H12: Printful은 US/CA 주문에 주/State가 필수. 라우터에서 선검증해 사용자에게 400을
    # 돌려준다(hybrid에서 provider 실패로 조용히 pending_provider가 되는 것을 방지).
    if normalized["country"] in {"US", "CA"} and not normalized.get("state"):
        raise ValidationError(
            "US/CA 주문은 주/State가 필요합니다.",
            details={"required": ["state"], "country": normalized["country"]},
        )

    return normalized


def _order_create_response(order: PodOrder, sync_source: str) -> dict:
    return {
        "order_id": order.id,
        "status": order.status,
        "provider": order.provider,
        "total_price": order.total_price,
        "currency": order.currency,
        "provider_total": order.provider_total,
        "provider_currency": order.provider_currency,
        "provider_order_id": order.provider_order_id,
        "tracking_number": order.tracking_number,
        "sync_source": sync_source,
    }


@router.get("/quote")
async def get_pod_quote(
    country: str,
    quantity: int = 1,
    user_key: str = Depends(get_user_key),
):
    """지역 견적(단가·배송비·통화)을 서버가 산출해 반환(H20). create_pod_order와 동일한
    _pod_pricing_for를 재사용해 표시-청구 통화·금액 일치를 보장한다(클라 가격 미신뢰)."""
    if quantity < 1 or quantity > 10:
        raise ValidationError("수량은 1~10이어야 합니다.", details={"quantity": quantity})
    unit_price, shipping_fee, currency = _pod_pricing_for(country)
    return {
        "unit_price": unit_price,
        "shipping_fee": shipping_fee,
        "total_price": (unit_price * quantity) + shipping_fee,
        "currency": currency,
    }


@router.post("/orders")
async def create_pod_order(
    request: PodOrderCreateRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    idempotency_key: Optional[str] = Depends(get_idempotency_key),
):
    book_result = await db.execute(select(Book).where(Book.id == request.book_id))
    book = book_result.scalar_one_or_none()
    if not book:
        raise NotFoundError("책", request.book_id)
    if book.user_key != user_key:
        raise ValidationError("본인의 책만 주문할 수 있습니다.")

    shipping_address = _normalize_shipping_address(request.shipping_address)

    # 배송 국가 기준 지역 가격(서버 산출 — 클라이언트 가격 미신뢰). 이 값은 사용자 표시·청구
    # 기준(지역 견적)으로 total_price/currency에 저장한다. provider 실비는 별도 컬럼(H13/G7).
    unit_price, shipping_fee, region_currency = _pod_pricing_for(
        shipping_address["country"]
    )
    total_price = (unit_price * request.quantity) + shipping_fee

    # H6: 멱등 — 같은 (user_key, idempotency_key) 주문이 이미 있으면 재요청에 그대로 반환.
    order = None
    order_id = None
    if idempotency_key:
        existing = (
            await db.execute(
                select(PodOrder).where(
                    PodOrder.user_key == user_key,
                    PodOrder.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing:
            # #16: pending_submit/pending_provider는 '외부에 아직 제출되지 않은' 상태다.
            # 이걸 그대로 200으로 돌려주면 사용자는 실물 주문이 접수됐다고 믿지만 provider엔
            # 영원히 제출되지 않는다(재제출·대사 경로 부재 = 영구 미이행 주문). 재요청을
            # 재제출 기회로 삼아 같은 행을 재사용해 외부 제출을 다시 시도한다.
            if existing.status not in _POD_RESUBMITTABLE_STATUSES:
                return _order_create_response(existing, sync_source="idempotent")
            order = existing
            order_id = existing.id

    if order is None:
        order_id = f"pod_{utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"

        # H6: 외부 호출 전에 로컬 fail-closed 레코드를 먼저 commit(orphan draft 방지). 동시
        # 더블탭은 (user_key, idempotency_key) 부분 유니크에서 IntegrityError → 기존 행 재조회.
        order = PodOrder(
            id=order_id,
            user_key=user_key,
            book_id=request.book_id,
            idempotency_key=idempotency_key,
            provider=settings.pod_provider,
            status="pending_submit",
            quantity=request.quantity,
            unit_price=unit_price,
            shipping_fee=shipping_fee,
            total_price=total_price,
            currency=region_currency,
            shipping_address=shipping_address,
            provider_order_id=None,
        )
        db.add(order)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            existing = (
                await db.execute(
                    select(PodOrder).where(
                        PodOrder.user_key == user_key,
                        PodOrder.idempotency_key == idempotency_key,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                return _order_create_response(existing, sync_source="idempotent")
            raise

    # 외부 제출. provider 결과로 같은 행을 갱신(지역 견적 total_price/currency는 유지).
    provider_result = await pod_provider_service.create_order(
        local_order_id=order_id,
        quantity=request.quantity,
        shipping_address=shipping_address,
        pdf_url=book.pdf_url,
    )
    order.status = provider_result.status
    order.provider = provider_result.provider
    order.provider_order_id = provider_result.provider_order_id
    order.tracking_number = provider_result.tracking_number
    order.provider_total = provider_result.provider_total
    order.provider_currency = provider_result.provider_currency
    await db.commit()
    await db.refresh(order)

    logger.info(
        "POD order created",
        order_id=order.id,
        provider=order.provider,
        status=order.status,
        sync_source=provider_result.sync_source,
    )

    return _order_create_response(order, sync_source=provider_result.sync_source)


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

    sync_source = "local"
    new_status: Optional[str] = None
    new_tracking: Optional[str] = None
    new_provider_order_id: Optional[str] = None

    try:
        # H6: submit_unknown(결과 미상)은 external_id로 대사해 실제 생성 여부 확인.
        if order.provider_order_id is None and order.status == "submit_unknown":
            reconciled = await pod_provider_service.reconcile_by_external_id(order.id)
            if reconciled is not None:
                sync_source = reconciled.sync_source
                new_status = reconciled.status
                new_tracking = reconciled.tracking_number
                new_provider_order_id = _coerce_provider_order_id(reconciled.raw)
        else:
            status_result = await pod_provider_service.sync_order_status(
                provider_order_id=order.provider_order_id,
                current_status=order.status,
            )
            sync_source = status_result.sync_source
            new_status = status_result.status
            new_tracking = status_result.tracking_number
    except (ValidationError, PodSubmitUnknown):
        # L6/#15: provider 장애 시 조회를 실패시키지 않고 로컬 스냅샷을 반환한다.
        # 타임아웃은 _printful_request가 GET/POST 구분 없이 PodSubmitUnknown으로 변환하므로
        # ValidationError만 잡으면 상태 조회가 미처리 500이 된다(장애의 최빈 형태).
        sync_source = "local_snapshot"

    # L6: 종결 상태는 sticky(역행 금지). 변경이 있을 때만 커밋(불필요 write 생략).
    changed = False
    if order.status not in _TERMINAL_POD_STATUSES:
        if new_status and new_status != order.status:
            order.status = new_status
            changed = True
    if new_tracking and new_tracking != order.tracking_number:
        order.tracking_number = new_tracking
        changed = True
    if new_provider_order_id and new_provider_order_id != order.provider_order_id:
        order.provider_order_id = new_provider_order_id
        changed = True
    if changed:
        await db.commit()
        await db.refresh(order)

    logger.info(
        "POD order status synced",
        order_id=order.id,
        provider=order.provider,
        status=order.status,
        sync_source=sync_source,
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
        "provider_total": order.provider_total,
        "provider_currency": order.provider_currency,
        "provider_order_id": order.provider_order_id,
        "tracking_number": order.tracking_number,
        "sync_source": sync_source,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }


def _coerce_provider_order_id(raw: dict) -> Optional[str]:
    value = raw.get("provider_order_id") if isinstance(raw, dict) else None
    return value if isinstance(value, str) and value else None
