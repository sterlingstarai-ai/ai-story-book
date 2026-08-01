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


class PodSubmitUnknown(Exception):
    """외부 제출 결과 미상(타임아웃 등). 확정 실패로 삼키지 않고 submit_unknown으로 남긴다(H6)."""


@dataclass
class PodCreateResult:
    status: str
    provider: str
    provider_order_id: Optional[str]
    tracking_number: Optional[str]
    # provider(Printful) 실비 — 원통화·정수 cents(×환산 금지, H13/G7). 지역 견적은 라우터가
    # total_price/currency로 별도 저장한다(한 행에 단위·통화 혼재 제거).
    provider_total: Optional[int]
    provider_currency: Optional[str]
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
        pdf_url: Optional[str] = None,
    ) -> PodCreateResult:
        mode = self._resolve_mode()

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
                pdf_url=pdf_url,
            )
        except PodSubmitUnknown:
            # 결과 미상(타임아웃 등)은 확정 실패로 폴백하지 않는다 — 실제 draft가 생성됐을 수
            # 있으므로 submit_unknown으로 남겨 대사(reconcile_by_external_id)로 회복한다(H6).
            logger.warning(
                "Printful submit outcome unknown; leaving as submit_unknown",
                local_order_id=local_order_id,
            )
            return PodCreateResult(
                status="submit_unknown",
                provider="printful",
                provider_order_id=None,
                tracking_number=None,
                provider_total=None,
                provider_currency=None,
                sync_source="submit_unknown",
                raw={"reason": "submit_unknown"},
            )
        except ValidationError:
            if mode == "hybrid":
                # H12: 실패를 '접수 성공(created)'으로 위장하지 않는다 — pending_provider로 구분해
                # 사용자·모바일이 이행됐다고 오인하지 않게 한다.
                logger.warning(
                    "Printful order failed in hybrid mode; marking pending_provider",
                    local_order_id=local_order_id,
                )
                return PodCreateResult(
                    status="pending_provider",
                    provider=settings.pod_provider,
                    provider_order_id=None,
                    tracking_number=None,
                    provider_total=None,
                    provider_currency=None,
                    sync_source="local_fallback",
                    raw={"reason": "printful_create_failed"},
                )
            raise

    def _resolve_mode(self) -> str:
        """pod_mode 정규화. 무효값은 조용히 local로 강등하지 않고 경고 후 local(L11)."""
        mode = (settings.pod_mode or "local").strip().lower()
        if mode not in {"local", "hybrid", "strict"}:
            logger.warning("Invalid POD_MODE; defaulting to local", pod_mode=settings.pod_mode)
            return "local"
        return mode

    async def sync_order_status(
        self,
        *,
        provider_order_id: Optional[str],
        current_status: str,
    ) -> PodStatusResult:
        mode = self._resolve_mode()

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
        pdf_url: Optional[str] = None,
    ) -> PodCreateResult:
        recipient = self._build_printful_recipient(shipping_address)
        item: dict = {
            "sync_variant_id": settings.printful_sync_variant_id,
            "quantity": quantity,
            "external_id": local_order_id,
        }
        # G20: 사용자 동화책 PDF를 printfile로 첨부해 전 고객 동일 디자인 인쇄를 막는다.
        # 아트워크(pdf_url) 미첨부 주문은 pending_artwork로 구분 저장(확정불가).
        artwork_attached = bool(pdf_url)
        if artwork_attached:
            item["files"] = [{"type": "default", "url": pdf_url}]

        payload: dict = {
            "external_id": local_order_id,
            "recipient": recipient,
            "items": [item],
            # 결제/확정은 별도 운영 절차에서 수행. 우선 주문 draft 생성.
            "confirm": False,
        }
        store_id = self._store_id_int()
        if store_id is not None:
            payload["store_id"] = store_id

        data = await self._printful_request("POST", "/orders", json=payload)
        result = data.get("result")
        if not isinstance(result, dict):
            raise ValidationError("POD 주문 생성 응답이 올바르지 않습니다.")

        provider_order_id = _as_string(result.get("id"))
        provider_status = _as_string(result.get("status")) or "created"
        # 아트워크 미첨부면 provider 상태와 무관하게 pending_artwork로 구분(G20).
        status = provider_status if artwork_attached else "pending_artwork"
        costs = result.get("costs") if isinstance(result.get("costs"), dict) else {}
        # H13/G7: ×1300 환산 제거. 원통화·정수 cents로 provider 실비 저장.
        provider_total = _amount_to_cents(costs.get("total"))
        provider_currency = _as_string(costs.get("currency"))
        tracking = self._extract_tracking(result)

        return PodCreateResult(
            status=status,
            provider="printful",
            provider_order_id=provider_order_id,
            tracking_number=tracking,
            provider_total=provider_total,
            provider_currency=provider_currency,
            sync_source="printful",
            raw={"status": provider_status, "costs": costs, "artwork_attached": artwork_attached},
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
        except httpx.TimeoutException as exc:
            # 타임아웃은 결과 미상(unknown outcome) — 실제 생성됐을 수 있어 확정 실패로 삼키지
            # 않는다. 호출자가 submit_unknown으로 남기고 대사로 회복한다(H6).
            raise PodSubmitUnknown(str(exc)) from exc
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
        city = _as_string(shipping_address.get("city"))
        state_code = _as_string(shipping_address.get("state"))
        address2 = _as_string(shipping_address.get("line2"))
        postal_code = _as_string(shipping_address.get("postal_code"))
        country = _as_string(shipping_address.get("country"))
        phone = _as_string(shipping_address.get("phone"))

        # H12: Printful Orders API는 recipient.city 필수. US/CA는 state_code 필수.
        if not name or not line1 or not city or not postal_code or not country:
            raise ValidationError(
                "배송지 정보가 올바르지 않습니다.",
                details={
                    "required": ["name", "line1", "city", "postal_code", "country"],
                },
            )
        if country.upper() in {"US", "CA"} and not state_code:
            raise ValidationError(
                "US/CA 주문은 주/State가 필요합니다.",
                details={"required": ["state"], "country": country},
            )

        recipient = {
            "name": name,
            "address1": line1,
            "city": city,
            "zip": postal_code,
            "country_code": country,
            "phone": phone,
        }
        if state_code:
            recipient["state_code"] = state_code
        if address2:
            recipient["address2"] = address2
        return recipient

    def _store_id_int(self) -> Optional[int]:
        """printful_store_id를 안전하게 int로. 무효 값은 500 대신 None으로 무시(L11)."""
        raw = settings.printful_store_id
        if raw in (None, ""):
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            logger.warning("Invalid PRINTFUL_STORE_ID; ignoring", printful_store_id=raw)
            return None

    async def reconcile_by_external_id(self, external_id: str) -> Optional[PodStatusResult]:
        """submit_unknown 주문을 external_id로 Printful에서 조회해 실제 생성 여부 대사(H6).

        Printful은 GET /orders/@{external_id}를 지원. 생성돼 있으면 provider_order_id·status를
        채워 반환, 없으면 None.
        """
        try:
            data = await self._printful_request("GET", f"/orders/@{external_id}")
        except (ValidationError, PodSubmitUnknown):
            return None
        result = data.get("result")
        if not isinstance(result, dict):
            return None
        provider_order_id = _as_string(result.get("id"))
        status = _as_string(result.get("status")) or "created"
        tracking = self._extract_tracking(result)
        return PodStatusResult(
            status=status,
            tracking_number=tracking,
            sync_source="printful_reconciled",
            raw={"provider_order_id": provider_order_id, "status": status},
        )

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
            provider_total=None,
            provider_currency=None,
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


def _amount_to_cents(value: object) -> Optional[int]:
    """금액을 원통화 정수 cents로(예: '25.00' USD → 2500). ×환율 환산 없음(H13/G7)."""
    dec = _as_decimal(value)
    if dec is None:
        return None
    return int((dec * Decimal("100")).to_integral_value())


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

