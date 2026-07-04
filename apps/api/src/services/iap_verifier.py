"""
IAP Verification Service
Apple/Google 스토어 영수증 검증
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Optional

import httpx
import structlog

from src.core.config import settings
from src.core.exceptions import ValidationError
from src.core.utils import utcnow

logger = structlog.get_logger()


@dataclass
class IAPVerificationResult:
    verified: bool
    source: str
    environment: Optional[str]
    store_transaction_id: Optional[str]
    store_product_id: Optional[str]
    raw: dict


class IAPVerifierService:
    async def verify_purchase(
        self,
        *,
        platform: str,
        product_id: str,
        transaction_id: str,
        purchase_token: Optional[str] = None,
        receipt_data: Optional[str] = None,
        is_subscription: bool = False,
    ) -> IAPVerificationResult:
        mode = (settings.iap_verification_mode or "local").strip().lower()
        if mode not in {"local", "hybrid", "strict"}:
            mode = "local"

        if platform == "apple":
            return await self._verify_apple(
                mode=mode,
                product_id=product_id,
                transaction_id=transaction_id,
                receipt_data=receipt_data,
            )
        if platform == "google":
            return await self._verify_google(
                mode=mode,
                product_id=product_id,
                transaction_id=transaction_id,
                purchase_token=purchase_token,
                is_subscription=is_subscription,
            )

        raise ValidationError("지원하지 않는 플랫폼입니다.", details={"platform": platform})

    async def _verify_apple(
        self,
        *,
        mode: str,
        product_id: str,
        transaction_id: str,
        receipt_data: Optional[str],
    ) -> IAPVerificationResult:
        if not receipt_data:
            raise ValidationError("Apple 영수증(receipt_data)이 필요합니다.")

        has_secret = bool(settings.apple_iap_shared_secret)
        if mode == "strict" and not has_secret:
            raise ValidationError(
                "Apple 스토어 검증 설정이 필요합니다.",
                details={"required": ["APPLE_IAP_SHARED_SECRET"]},
            )

        if mode == "local" or (mode == "hybrid" and not has_secret):
            return self._local_success(
                source="local_apple",
                product_id=product_id,
                transaction_id=transaction_id,
                raw={"reason": "apple_store_config_missing"},
            )

        payload = {
            "receipt-data": receipt_data,
            "password": settings.apple_iap_shared_secret,
            "exclude-old-transactions": True,
        }

        try:
            apple_data, environment = await self._post_apple_receipt(
                payload=payload,
                verify_url=settings.apple_iap_verify_url,
                sandbox_url=settings.apple_iap_sandbox_verify_url,
            )
        except ValidationError:
            if mode == "hybrid":
                logger.warning(
                    "Apple verification failed in hybrid mode, falling back to local",
                    product_id=product_id,
                    transaction_id=transaction_id,
                )
                return self._local_success(
                    source="local_apple_hybrid_fallback",
                    product_id=product_id,
                    transaction_id=transaction_id,
                    raw={"reason": "apple_verification_failed"},
                )
            raise

        matched = self._find_apple_transaction(
            data=apple_data,
            expected_product_id=product_id,
            expected_transaction_id=transaction_id,
        )
        if not matched:
            raise ValidationError(
                "Apple 영수증에서 결제 내역을 찾을 수 없습니다.",
                details={
                    "product_id": product_id,
                    "transaction_id": transaction_id,
                },
            )

        return IAPVerificationResult(
            verified=True,
            source="apple_store",
            environment=environment,
            store_transaction_id=_coerce_str(matched.get("transaction_id")),
            store_product_id=_coerce_str(matched.get("product_id")),
            raw={
                "status": apple_data.get("status"),
                "environment": environment,
                "bundle_id": (
                    matched.get("bid")
                    or (apple_data.get("receipt") or {}).get("bundle_id")
                ),
            },
        )

    async def _verify_google(
        self,
        *,
        mode: str,
        product_id: str,
        transaction_id: str,
        purchase_token: Optional[str],
        is_subscription: bool,
    ) -> IAPVerificationResult:
        if not purchase_token:
            raise ValidationError("Google purchase_token이 필요합니다.")

        package_name = settings.google_play_package_name
        access_token = self._resolve_google_access_token()
        has_config = bool(package_name and access_token)

        if mode == "strict" and not has_config:
            raise ValidationError(
                "Google 스토어 검증 설정이 필요합니다.",
                details={
                    "required": [
                        "GOOGLE_PLAY_PACKAGE_NAME",
                        "GOOGLE_PLAY_ACCESS_TOKEN or GOOGLE_PLAY_SERVICE_ACCOUNT_*",
                    ]
                },
            )

        if mode == "local" or (mode == "hybrid" and not has_config):
            return self._local_success(
                source="local_google",
                product_id=product_id,
                transaction_id=transaction_id,
                raw={"reason": "google_store_config_missing"},
            )

        try:
            google_data = await self._fetch_google_purchase(
                package_name=package_name or "",
                product_id=product_id,
                purchase_token=purchase_token,
                access_token=access_token or "",
                is_subscription=is_subscription,
            )
            self._assert_google_purchase_valid(
                google_data=google_data,
                expected_transaction_id=transaction_id,
                is_subscription=is_subscription,
            )
        except ValidationError:
            if mode == "hybrid":
                logger.warning(
                    "Google verification failed in hybrid mode, falling back to local",
                    product_id=product_id,
                    transaction_id=transaction_id,
                )
                return self._local_success(
                    source="local_google_hybrid_fallback",
                    product_id=product_id,
                    transaction_id=transaction_id,
                    raw={"reason": "google_verification_failed"},
                )
            raise

        return IAPVerificationResult(
            verified=True,
            source="google_play",
            environment="production",
            store_transaction_id=_coerce_str(google_data.get("orderId")),
            store_product_id=product_id,
            raw={
                "kind": google_data.get("kind"),
                "purchase_state": google_data.get("purchaseState"),
                "payment_state": google_data.get("paymentState"),
                "acknowledgement_state": google_data.get("acknowledgementState"),
            },
        )

    async def _post_apple_receipt(
        self,
        *,
        payload: dict,
        verify_url: str,
        sandbox_url: str,
    ) -> tuple[dict, str]:
        data = await self._post_json(verify_url, payload)
        status = data.get("status")

        # Production receipt sent to sandbox
        if status == 21007:
            sandbox_data = await self._post_json(sandbox_url, payload)
            sandbox_status = sandbox_data.get("status")
            if sandbox_status != 0:
                raise ValidationError(
                    "Apple sandbox 영수증 검증에 실패했습니다.",
                    details={"status": sandbox_status},
                )
            return sandbox_data, "Sandbox"

        # Sandbox receipt sent to production
        if status == 21008:
            prod_data = await self._post_json(verify_url, payload)
            prod_status = prod_data.get("status")
            if prod_status != 0:
                raise ValidationError(
                    "Apple production 영수증 검증에 실패했습니다.",
                    details={"status": prod_status},
                )
            return prod_data, "Production"

        if status != 0:
            raise ValidationError(
                "Apple 영수증 검증에 실패했습니다.",
                details={"status": status},
            )

        return data, _coerce_str(data.get("environment")) or "Production"

    async def _post_json(self, url: str, payload: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise ValidationError(
                "스토어 검증 서버 통신에 실패했습니다.",
                details={"provider": "apple", "error": str(exc)},
            ) from exc
        except ValueError as exc:
            raise ValidationError(
                "스토어 검증 응답 파싱에 실패했습니다.",
                details={"provider": "apple"},
            ) from exc

        if not isinstance(data, dict):
            raise ValidationError("스토어 검증 응답이 올바르지 않습니다.")
        return data

    def _find_apple_transaction(
        self,
        *,
        data: dict,
        expected_product_id: str,
        expected_transaction_id: str,
    ) -> Optional[dict]:
        receipts: list[dict] = []
        latest = data.get("latest_receipt_info")
        if isinstance(latest, list):
            receipts.extend([item for item in latest if isinstance(item, dict)])

        receipt_obj = data.get("receipt")
        if isinstance(receipt_obj, dict):
            in_app = receipt_obj.get("in_app")
            if isinstance(in_app, list):
                receipts.extend([item for item in in_app if isinstance(item, dict)])

        if not receipts:
            return None

        by_product = [
            item
            for item in receipts
            if _coerce_str(item.get("product_id")) == expected_product_id
        ]
        if not by_product:
            return None

        for item in by_product:
            txid = _coerce_str(item.get("transaction_id"))
            original_txid = _coerce_str(item.get("original_transaction_id"))
            if txid == expected_transaction_id or original_txid == expected_transaction_id:
                return item

        # 보안: product가 일치해도 transaction_id가 영수증의 어떤 거래와도 매칭되지
        # 않으면 거부한다. (예전의 `len(by_product)==1` 폴백은 임의 transaction_id로
        # 같은 영수증을 무한 재사용하는 리플레이를 허용했으므로 제거.)
        return None

    async def _fetch_google_purchase(
        self,
        *,
        package_name: str,
        product_id: str,
        purchase_token: str,
        access_token: str,
        is_subscription: bool,
    ) -> dict:
        base = settings.google_play_verify_base_url.rstrip("/")
        if is_subscription:
            endpoint = (
                f"{base}/androidpublisher/v3/applications/{package_name}/"
                f"purchases/subscriptions/{product_id}/tokens/{purchase_token}"
            )
        else:
            endpoint = (
                f"{base}/androidpublisher/v3/applications/{package_name}/"
                f"purchases/products/{product_id}/tokens/{purchase_token}"
            )

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    endpoint,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if response.status_code in {401, 403}:
                raise ValidationError(
                    "Google 검증 토큰이 유효하지 않습니다.",
                    details={"status_code": response.status_code},
                )
            if response.status_code == 404:
                raise ValidationError("Google 결제 토큰을 찾을 수 없습니다.")

            response.raise_for_status()
            data = response.json()
        except ValidationError:
            raise
        except httpx.HTTPError as exc:
            raise ValidationError(
                "Google 스토어 검증 서버 통신에 실패했습니다.",
                details={"error": str(exc)},
            ) from exc
        except ValueError as exc:
            raise ValidationError("Google 검증 응답 파싱에 실패했습니다.") from exc

        if not isinstance(data, dict):
            raise ValidationError("Google 검증 응답이 올바르지 않습니다.")
        return data

    def _assert_google_purchase_valid(
        self,
        *,
        google_data: dict,
        expected_transaction_id: str,
        is_subscription: bool,
    ) -> None:
        order_id = _coerce_str(google_data.get("orderId"))
        if order_id and not self._is_transaction_match(expected_transaction_id, order_id):
            raise ValidationError(
                "Google 결제 주문번호가 일치하지 않습니다.",
                details={
                    "expected": expected_transaction_id,
                    "actual": order_id,
                },
            )

        if is_subscription:
            payment_state = google_data.get("paymentState")
            if payment_state is not None and payment_state not in {1, 2}:
                raise ValidationError(
                    "Google 구독 결제 상태가 유효하지 않습니다.",
                    details={"payment_state": payment_state},
                )

            expiry_ms = _parse_int(google_data.get("expiryTimeMillis"))
            if expiry_ms is not None:
                now_ms = int(utcnow().timestamp() * 1000)
                if expiry_ms < now_ms:
                    raise ValidationError("Google 구독이 만료되었습니다.")
            return

        purchase_state = google_data.get("purchaseState")
        if purchase_state is not None and purchase_state != 0:
            raise ValidationError(
                "Google 구매 상태가 완료가 아닙니다.",
                details={"purchase_state": purchase_state},
            )

    def _is_transaction_match(self, expected: str, actual: str) -> bool:
        if expected == actual:
            return True
        # Google 구독 갱신 orderId는 base에 `..0`,`..1` 형태의 갱신 접미가 붙는다.
        # 갱신 접미만 제거한 base끼리 '정확히' 비교한다(임의 접두/접미 매칭은 리플레이
        # 표면이므로 허용하지 않는다).
        return _strip_google_order_suffix(expected) == _strip_google_order_suffix(actual)

    def _local_success(
        self,
        *,
        source: str,
        product_id: str,
        transaction_id: str,
        raw: Optional[dict] = None,
    ) -> IAPVerificationResult:
        return IAPVerificationResult(
            verified=True,
            source=source,
            environment=None,
            store_transaction_id=transaction_id,
            store_product_id=product_id,
            raw=raw or {},
        )

    def _resolve_google_access_token(self) -> Optional[str]:
        direct = _coerce_str(settings.google_play_access_token)
        if direct:
            return direct

        service_account_info: Optional[dict] = None
        raw_json = _coerce_str(settings.google_play_service_account_json)
        if raw_json:
            try:
                parsed = json.loads(raw_json)
                if isinstance(parsed, dict):
                    service_account_info = parsed
            except Exception:
                return None

        file_path = _coerce_str(settings.google_play_service_account_file)
        if service_account_info is None and file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    parsed = json.load(f)
                if isinstance(parsed, dict):
                    service_account_info = parsed
            except Exception:
                return None

        if service_account_info is None:
            return None

        try:
            from google.oauth2 import service_account
            from google.auth.transport.requests import Request as GoogleAuthRequest
        except Exception:
            return None

        try:
            credentials = service_account.Credentials.from_service_account_info(
                service_account_info,
                scopes=["https://www.googleapis.com/auth/androidpublisher"],
            )
            credentials.refresh(GoogleAuthRequest())
            return _coerce_str(credentials.token)
        except Exception:
            return None


def _strip_google_order_suffix(order_id: str) -> str:
    """Google 구독 갱신 orderId의 `..N` 갱신 접미를 제거해 base를 반환한다.

    예: 'GPA.1234-5678-9012-34567..0' -> 'GPA.1234-5678-9012-34567'.
    base에 '..'가 없으면 원본을 그대로 반환한다.
    """
    base = order_id.split("..", 1)[0]
    return base


def _parse_int(value: object) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _coerce_str(value: object) -> Optional[str]:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


iap_verifier = IAPVerifierService()
