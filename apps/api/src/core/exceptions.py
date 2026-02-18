"""
Standardized exception handling for consistent API error responses.
"""

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from typing import Optional, Any
import structlog

logger = structlog.get_logger()


class APIError(HTTPException):
    """Base API error with consistent structure."""

    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        details: Optional[Any] = None,
    ):
        self.error_code = error_code
        self.message = message
        self.details = details
        super().__init__(status_code=status_code, detail=message)


class NotFoundError(APIError):
    """Resource not found error."""

    def __init__(self, resource: str, resource_id: str):
        super().__init__(
            status_code=404,
            error_code="NOT_FOUND",
            message=f"{resource}을(를) 찾을 수 없습니다: {resource_id}",
            details={"resource": resource, "id": resource_id},
        )


class ValidationError(APIError):
    """Input validation error."""

    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(
            status_code=400,
            error_code="VALIDATION_ERROR",
            message=message,
            details=details,
        )


class AuthorizationError(APIError):
    """Authorization/permission error."""

    def __init__(self, message: str = "접근 권한이 없습니다"):
        super().__init__(
            status_code=403,
            error_code="FORBIDDEN",
            message=message,
        )


class PaymentRequiredError(APIError):
    """Payment/credit required error."""

    def __init__(self, message: str = "크레딧이 부족합니다"):
        super().__init__(
            status_code=402,
            error_code="PAYMENT_REQUIRED",
            message=message,
        )


class RateLimitError(APIError):
    """Rate limit exceeded error."""

    def __init__(self, retry_after: int):
        super().__init__(
            status_code=429,
            error_code="RATE_LIMIT_EXCEEDED",
            message=f"요청 한도 초과. {retry_after}초 후 다시 시도해주세요.",
            details={"retry_after": retry_after},
        )


def _get_request_id(request: Request) -> Optional[str]:
    """Read request ID set by middleware, if available."""
    return getattr(getattr(request, "state", None), "request_id", None)


def _http_error_code(status_code: int) -> str:
    """Map HTTP status to stable error code."""
    if status_code == 400:
        return "BAD_REQUEST"
    if status_code == 401:
        return "UNAUTHORIZED"
    if status_code == 403:
        return "FORBIDDEN"
    if status_code == 404:
        return "NOT_FOUND"
    if status_code == 409:
        return "CONFLICT"
    if status_code == 422:
        return "VALIDATION_ERROR"
    if status_code == 429:
        return "RATE_LIMIT_EXCEEDED"
    if status_code == 502:
        return "BAD_GATEWAY"
    if status_code == 503:
        return "SERVICE_UNAVAILABLE"
    if status_code == 504:
        return "GATEWAY_TIMEOUT"
    if 500 <= status_code < 600:
        return "INTERNAL_ERROR"
    return "HTTP_ERROR"


def _normalize_http_detail(detail: Any) -> tuple[str, Optional[Any], Optional[str]]:
    """Normalize HTTPException detail into message/details/optional explicit code."""
    if isinstance(detail, str):
        return detail, None, None

    if isinstance(detail, list):
        return "입력 정보를 확인해주세요.", detail, None

    if isinstance(detail, dict):
        explicit_code = None
        for code_key in ("error_code", "code", "error"):
            code_value = detail.get(code_key)
            if isinstance(code_value, str) and code_value.strip():
                explicit_code = code_value
                break

        msg = detail.get("message") or detail.get("detail")
        if isinstance(msg, str):
            extra = {
                k: v
                for k, v in detail.items()
                if k not in {"message", "detail", "error", "error_code", "code"}
            }
            return msg, extra or detail, explicit_code
        return "요청 처리 중 오류가 발생했습니다.", detail, explicit_code

    if detail is None:
        return "요청 처리 중 오류가 발생했습니다.", None, None

    return str(detail), detail, None


def _build_error_content(
    *,
    code: str,
    message: str,
    details: Optional[Any],
    request_id: Optional[str],
) -> dict:
    safe_details = (
        jsonable_encoder(
            details,
            custom_encoder={
                ValueError: str,
                Exception: str,
            },
        )
        if details is not None
        else None
    )

    content = {
        "detail": message,
        "error": {
            "code": code,
            "message": message,
        },
    }

    if safe_details is not None:
        content["error"]["details"] = safe_details
    if request_id:
        content["request_id"] = request_id

    return content


def api_error_response(
    error: APIError,
    *,
    request_id: Optional[str] = None,
) -> JSONResponse:
    """Create standardized APIError response."""
    content = _build_error_content(
        code=error.error_code,
        message=error.message,
        details=error.details if error.details else None,
        request_id=request_id,
    )

    return JSONResponse(
        status_code=error.status_code,
        content=content,
    )


async def api_exception_handler(request: Request, exc: APIError) -> JSONResponse:
    """Handle APIError exceptions."""
    logger.warning(
        "API error",
        error_code=exc.error_code,
        message=exc.message,
        path=request.url.path,
    )
    return api_error_response(exc, request_id=_get_request_id(request))


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle plain HTTPException with standardized envelope."""
    message, details, explicit_code = _normalize_http_detail(exc.detail)
    code = explicit_code or _http_error_code(exc.status_code)

    logger.warning(
        "HTTP error",
        status_code=exc.status_code,
        error_code=code,
        message=message,
        path=request.url.path,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=_build_error_content(
            code=code,
            message=message,
            details=details,
            request_id=_get_request_id(request),
        ),
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Handle request schema validation errors consistently."""
    details = jsonable_encoder(
        exc.errors(),
        custom_encoder={
            ValueError: str,
            Exception: str,
        },
    )
    message = "입력 정보를 확인해주세요."
    logger.warning(
        "Validation error",
        error_code="VALIDATION_ERROR",
        errors_count=len(details),
        path=request.url.path,
    )

    return JSONResponse(
        status_code=422,
        content=_build_error_content(
            code="VALIDATION_ERROR",
            message=message,
            details=details,
            request_id=_get_request_id(request),
        )
        | {"detail": details},
    )
