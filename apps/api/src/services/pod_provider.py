"""
POD Provider Service
Printful 연동(local/hybrid/strict)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import httpx
import structlog

from src.core.config import settings
from src.core.exceptions import ValidationError

logger = structlog.get_logger()


@dataclass
class PodCreateResult:
    status: str
    provider: str
    provider_order_id: Optional[str]
    tracking_number: Optional[str]
    total_price: Optional[int]
    currency: Optional[str]
    sync_source: str
    raw: dict


@dataclass
class PodStatusResult:
    status: str
    tracking_number: Optional[str]
    sync_source: str
    raw: dict


class PodProviderService:
    async def create_order(
        self,
        *,
        local_order_id: str,
        quantity: int,
        shipping_address: dict,
    ) -> PodCreateResult:
        mode = (settings.pod_mode or "local").strip().lower()
        if mode not in {"local", "hybrid", "strict"}:
            mode = "local"

        if mode == "local":
            return self._local_create(reason="pod_mode_local")

        config_error = self._validate_printful_config()
        if config_error:
            if mode == "strict":
                raise config_error
            return self._local_create(reason="printful_config_missing")

        try:
            return await self._create_printful_order(
                local_order_id=local_order_id,
                quantity=quantity,
                shipping_address=shipping_address,
            )
        except ValidationError:
            if mode == "hybrid":
                logger.warning(
                    "Printful order sync failed in hybrid mode; fallback to local",
                    local_order_id=local_order_id,
                )
                return self._local_create(reason="printful_create_failed")
            raise

    async def sync_order_status(
        self,
        *,
        provider_order_id: Optional[str],
        current_status: str,
    ) -> PodStatusResult:
        mode = (settings.pod_mode or "local").strip().lower()
        if mode not in {"local", "hybrid", "strict"}:
            mode = "local"

        if mode == "local" or not provider_order_id:
            return PodStatusResult(
                status=current_status,
                tracking_number=None,
                sync_source="local",
                raw={},
            )

        config_error = self._validate_printful_config()
        if config_error:
            if mode == "strict":
                raise config_error
            return PodStatusResult(
                status=current_status,
                tracking_number=None,
                sync_source="local_fallback",
                raw={"reason": "printful_config_missing"},
            )

        try:
            return await self._fetch_printful_order(provider_order_id=provider_order_id)
        except ValidationError:
            if mode == "hybrid":
                logger.warning(
                    "Printful status sync failed in hybrid mode; fallback to local",
                    provider_order_id=provider_order_id,
                )
                return PodStatusResult(
                    status=current_status,
                    tracking_number=None,
                    sync_source="local_fallback",
                    raw={"reason": "printful_fetch_failed"},
                )
            raise

    def _validate_printful_config(self) -> Optional[ValidationError]:
        missing: list[str] = []
        if not settings.printful_api_key:
            missing.append("PRINTFUL_API_KEY")
        if settings.printful_sync_variant_id is None:
            missing.append("PRINTFUL_SYNC_VARIANT_ID")

        if missing:
            return ValidationError(
                "POD 연동 설정이 필요합니다.",
                details={"required": missing},
            )
        return None

    async def _create_printful_order(
        self,
        *,
        local_order_id: str,
        quantity: int,
        shipping_address: dict,
    ) -> PodCreateResult:
        recipient = self._build_printful_recipient(shipping_address)
        payload: dict = {
            "external_id": local_order_id,
            "recipient": recipient,
            "items": [
                {
                    "sync_variant_id": settings.printful_sync_variant_id,
                    "quantity": quantity,
                }
            ],
            # 결제/확정은 별도 운영 절차에서 수행. 우선 주문 draft 생성.
            "confirm": False,
        }
        if settings.printful_store_id:
            payload["store_id"] = int(settings.printful_store_id)

        data = await self._printful_request("POST", "/orders", json=payload)
        result = data.get("result")
        if not isinstance(result, dict):
            raise ValidationError("POD 주문 생성 응답이 올바르지 않습니다.")

        provider_order_id = _as_string(result.get("id"))
        status = _as_string(result.get("status")) or "created"
        costs = result.get("costs") if isinstance(result.get("costs"), dict) else {}
        total_price = self._cost_to_krw(costs.get("total"))
        currency = _as_string(costs.get("currency")) or "USD"
        tracking = self._extract_tracking(result)

        return PodCreateResult(
            status=status,
            provider="printful",
            provider_order_id=provider_order_id,
            tracking_number=tracking,
            total_price=total_price,
            currency=currency,
            sync_source="printful",
            raw={"status": status, "costs": costs},
        )

    async def _fetch_printful_order(
        self,
        *,
        provider_order_id: str,
    ) -> PodStatusResult:
        data = await self._printful_request("GET", f"/orders/{provider_order_id}")
        result = data.get("result")
        if not isinstance(result, dict):
            raise ValidationError("POD 주문 조회 응답이 올바르지 않습니다.")

        status = _as_string(result.get("status")) or "created"
        tracking = self._extract_tracking(result)
        return PodStatusResult(
            status=status,
            tracking_number=tracking,
            sync_source="printful",
            raw={"status": status},
        )

    async def _printful_request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[dict] = None,
    ) -> dict:
        base = settings.printful_base_url.rstrip("/")
        url = f"{base}{path}"
        headers = {
            "Authorization": f"Bearer {settings.printful_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json,
                )
            if response.status_code >= 400:
                raise ValidationError(
                    "POD 제공자 요청에 실패했습니다.",
                    details={
                        "status_code": response.status_code,
                        "path": path,
                        "body": response.text[:500],
                    },
                )
            data = response.json()
        except ValidationError:
            raise
        except httpx.HTTPError as exc:
            raise ValidationError(
                "POD 제공자 서버 통신에 실패했습니다.",
                details={"path": path, "error": str(exc)},
            ) from exc
        except ValueError as exc:
            raise ValidationError("POD 제공자 응답 파싱에 실패했습니다.") from exc

        if not isinstance(data, dict):
            raise ValidationError("POD 제공자 응답이 올바르지 않습니다.")
        return data

    def _build_printful_recipient(self, shipping_address: dict) -> dict:
        name = _as_string(shipping_address.get("name"))
        line1 = _as_string(shipping_address.get("line1"))
        postal_code = _as_string(shipping_address.get("postal_code"))
        country = _as_string(shipping_address.get("country"))
        phone = _as_string(shipping_address.get("phone"))

        if not name or not line1 or not postal_code or not country:
            raise ValidationError(
                "배송지 정보가 올바르지 않습니다.",
                details={
                    "required": ["name", "line1", "postal_code", "country"],
                },
            )

        return {
            "name": name,
            "address1": line1,
            "zip": postal_code,
            "country_code": country,
            "phone": phone,
        }

    def _cost_to_krw(self, cost: object) -> Optional[int]:
        value = _as_decimal(cost)
        if value is None:
            return None
        # 운영 환율은 추후 분리 가능. 현재는 보수적으로 1 USD=1300 KRW 사용.
        return int((value * Decimal("1300")).to_integral_value())

    def _extract_tracking(self, result: dict) -> Optional[str]:
        direct = _as_string(result.get("tracking_number"))
        if direct:
            return direct

        shipments = result.get("shipments")
        if isinstance(shipments, list):
            for shipment in shipments:
                if isinstance(shipment, dict):
                    candidate = _as_string(
                        shipment.get("tracking_number") or shipment.get("tracking")
                    )
                    if candidate:
                        return candidate
        return None

    def _local_create(self, *, reason: str) -> PodCreateResult:
        return PodCreateResult(
            status="created",
            provider=settings.pod_provider,
            provider_order_id=None,
            tracking_number=None,
            total_price=None,
            currency=None,
            sync_source="local",
            raw={"reason": reason},
        )


def _as_string(value: object) -> Optional[str]:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _as_decimal(value: object) -> Optional[Decimal]:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:
            return None
    return None


pod_provider_service = PodProviderService()

