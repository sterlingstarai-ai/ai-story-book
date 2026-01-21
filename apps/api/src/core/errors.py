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
