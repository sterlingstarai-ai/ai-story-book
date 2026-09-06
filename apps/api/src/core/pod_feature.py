"""POD ordering is opt-in after fulfillment validation; existing orders remain readable."""
from fastapi import HTTPException
from src.core.config import settings


def pod_ordering_supported() -> bool:
    return settings.pod_ordering_enabled


def require_pod_ordering() -> None:
    if not pod_ordering_supported():
        raise HTTPException(status_code=409, detail={
            "code": "POD_NOT_SUPPORTED",
            "message": "이 배포에서는 실물책 주문을 제공하지 않습니다.",
        })
