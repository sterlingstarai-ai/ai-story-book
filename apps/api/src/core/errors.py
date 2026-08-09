from enum import Enum
from typing import Optional


class ErrorCode(str, Enum):
    """에러 코드 정의"""

    SAFETY_INPUT = "SAFETY_INPUT"  # 입력 안전성 위반
    SAFETY_OUTPUT = "SAFETY_OUTPUT"  # 출력 안전성 위반
    LLM_TIMEOUT = "LLM_TIMEOUT"  # LLM 타임아웃
    LLM_JSON_INVALID = "LLM_JSON_INVALID"  # LLM JSON 파싱 실패
    IMAGE_TIMEOUT = "IMAGE_TIMEOUT"  # 이미지 생성 타임아웃
    IMAGE_RATE_LIMIT = "IMAGE_RATE_LIMIT"  # 이미지 API 레이트 리밋
    IMAGE_FAILED = "IMAGE_FAILED"  # 이미지 생성 실패
    STORAGE_UPLOAD_FAILED = "STORAGE_UPLOAD_FAILED"  # 스토리지 업로드 실패
    DB_WRITE_FAILED = "DB_WRITE_FAILED"  # DB 쓰기 실패
    QUEUE_FAILED = "QUEUE_FAILED"  # 큐 등록 실패
    UNKNOWN = "UNKNOWN"  # 알 수 없는 에러


# 재시도 가능 여부
RETRYABLE_ERRORS = {
    ErrorCode.LLM_TIMEOUT,
    ErrorCode.LLM_JSON_INVALID,
    ErrorCode.IMAGE_TIMEOUT,
    ErrorCode.IMAGE_RATE_LIMIT,
    ErrorCode.IMAGE_FAILED,
    ErrorCode.STORAGE_UPLOAD_FAILED,
}

# 재시도 횟수
RETRY_COUNTS = {
    ErrorCode.LLM_TIMEOUT: 2,
    ErrorCode.LLM_JSON_INVALID: 2,
    ErrorCode.IMAGE_TIMEOUT: 3,
    ErrorCode.IMAGE_RATE_LIMIT: 3,
    ErrorCode.IMAGE_FAILED: 3,
    ErrorCode.STORAGE_UPLOAD_FAILED: 2,
    ErrorCode.SAFETY_OUTPUT: 2,
}

# 백오프 (초)
BACKOFF_SECONDS = {
    ErrorCode.LLM_TIMEOUT: [2, 5],
    ErrorCode.LLM_JSON_INVALID: [2, 5],
    ErrorCode.IMAGE_TIMEOUT: [2, 5, 12],
    ErrorCode.IMAGE_RATE_LIMIT: [5, 10, 20],
    ErrorCode.IMAGE_FAILED: [2, 5, 12],
    ErrorCode.STORAGE_UPLOAD_FAILED: [2, 5],
}


class StoryBookError(Exception):
    """기본 예외 클래스"""

    def __init__(self, code: ErrorCode, message: str, details: Optional[dict] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)

    def __str__(self):
        return f"[{self.code.value}] {self.message}"


class SafetyError(StoryBookError):
    """안전성 위반 에러"""

    def __init__(self, message: str, is_input: bool = True, suggestions: list = None):
        code = ErrorCode.SAFETY_INPUT if is_input else ErrorCode.SAFETY_OUTPUT
        super().__init__(
            code=code, message=message, details={"suggestions": suggestions or []}
        )


class LLMError(StoryBookError):
    """LLM 관련 에러"""

    def __init__(self, code: ErrorCode, message: str, raw_output: str = None):
        super().__init__(code=code, message=message, details={"raw_output": raw_output})


class ImageError(StoryBookError):
    """이미지 생성 에러"""

    def __init__(self, code: ErrorCode, message: str, page: int = None):
        super().__init__(code=code, message=message, details={"page": page})


class StorageError(StoryBookError):
    """스토리지 에러"""

    def __init__(self, message: str):
        super().__init__(code=ErrorCode.STORAGE_UPLOAD_FAILED, message=message)


class TransientError(Exception):
    """재시도 가능한 일시적 에러"""

    pass


def is_retryable(error: StoryBookError) -> bool:
    """재시도 가능한 에러인지 확인"""
    return error.code in RETRYABLE_ERRORS


def get_retry_count(error_code: ErrorCode) -> int:
    """재시도 횟수 반환"""
    return RETRY_COUNTS.get(error_code, 0)


def get_backoff(error_code: ErrorCode, attempt: int) -> int:
    """백오프 시간 반환"""
    backoffs = BACKOFF_SECONDS.get(error_code, [2])
    return backoffs[min(attempt, len(backoffs) - 1)]


class PaymentReason:
    """402 PAYMENT_REQUIRED 의 안정 사유 키 — 응답 `error.details.reason` 으로 내려간다.

    클라이언트가 '플랜 업그레이드' 와 '크레딧 충전' 중 어떤 UI 를 띄울지 고르는 근거다.
    M5: 이전에는 모바일이 서버가 준 **한국어 메시지 본문**을 부분 매칭해 분기했다
    (create_screen.dart / viewer_screen.dart). 서버가 402 를 로컬라이즈하거나 문구를
    다듬는 순간 조용히 깨지는 결합이었다 — 안정 키로 대체한다.
    """

    FREE_PLAN_STYLE = "free_plan_style"
    FREE_PLAN_MONTHLY_LIMIT = "free_plan_monthly_limit"
    FREE_PLAN_FEATURE = "free_plan_feature"
    INSUFFICIENT_CREDITS = "insufficient_credits"
    CREDIT_CHARGE_FAILED = "credit_charge_failed"

    #: 플랜 업그레이드로 해소되는 사유(그 외는 크레딧 충전 안내).
    PLAN_UPGRADE = frozenset(
        {FREE_PLAN_STYLE, FREE_PLAN_MONTHLY_LIMIT, FREE_PLAN_FEATURE}
    )


# ---------------------------------------------------------------------------
# 에러 위생 (A1 / A1-R) — 클라이언트로 나가는 도메인 에러의 단일 규칙
# ---------------------------------------------------------------------------
# 도메인 에러의 원문 메시지·details 는 내부 정보를 담는다:
#   - LLM_JSON_INVALID 의 message = pydantic 검증 덤프(내부 스키마명·input_value·
#     errors.pydantic.dev URL). input_value 에는 **모델 응답 원문 조각**이 들어간다.
#   - LLMError.details = {"raw_output": 모델 원문 500자}.
# 실키 환경에서는 미검열 생성물이 그대로 새는 경로가 된다.
#
# A1-R 교훈: 규칙을 예외 핸들러에만 두면 **저장 후 서빙되는 두 번째 경로**가 그대로 샌다
# (워커가 jobs.error_message 에 str(e) 를 저장 → 상태조회가 원문 서빙). 규칙은 여기 하나로
# 두고 예외 핸들러·잡 상태 서빙·잡 실패 저장이 **모두 같은 함수**를 쓴다.

#: 원문 메시지를 그대로 내보내도 되는 코드 — 사용자가 조치 가능한 안내다.
CLIENT_SAFE_ERROR_CODES = frozenset({ErrorCode.SAFETY_INPUT, ErrorCode.SAFETY_OUTPUT})

#: 응답 details 로 내보내도 되는 키. raw_output 같은 내부/원문 키는 절대 불가.
CLIENT_SAFE_DETAIL_KEYS = frozenset({"suggestions", "page", "retry_after", "reason"})

GENERIC_DOMAIN_MESSAGE = "요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요."


def _normalize_error_code(code) -> Optional[ErrorCode]:
    if isinstance(code, ErrorCode):
        return code
    if isinstance(code, str):
        try:
            return ErrorCode(code.strip())
        except ValueError:
            return None
    return None


def client_safe_message(code, raw_message: Optional[str]) -> str:
    """코드별로 클라이언트에 내보낼 메시지를 고른다.

    안전 코드(SAFETY_*)만 원문을 쓰고, 나머지는 일반 문구로 바꾼다. 원문은 **로그로만**.
    저장된 잡 에러(jobs.error_message)에도 같은 규칙을 적용해, 수정 전에 저장된 원문 행이
    서빙되는 것까지 막는다(서빙 시점 방어가 load-bearing).
    """
    normalized = _normalize_error_code(code)
    if normalized in CLIENT_SAFE_ERROR_CODES:
        text = (raw_message or "").strip()
        if text:
            return text
    return GENERIC_DOMAIN_MESSAGE


def client_safe_details(details: Optional[dict]) -> Optional[dict]:
    """화이트리스트 키만 남긴다(값이 비면 제외). 남는 게 없으면 None."""
    if not isinstance(details, dict):
        return None
    safe = {
        key: value
        for key, value in details.items()
        if key in CLIENT_SAFE_DETAIL_KEYS and value not in (None, [], {}, "")
    }
    return safe or None
