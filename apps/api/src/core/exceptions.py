"""
Standardized exception handling for consistent API error responses.
"""

from fastapi import HTTPException, Request
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


def api_error_response(error: APIError) -> JSONResponse:
    """Create standardized error response."""
    content = {
        "error": {
            "code": error.error_code,
            "message": error.message,
        }
    }
    if error.details:
        content["error"]["details"] = error.details

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
    return api_error_response(exc)
