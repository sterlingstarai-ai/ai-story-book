"""Shared log privacy boundary for the API and Celery workers."""
from __future__ import annotations

import re
import logging
import traceback

import structlog

_PRIVATE_FIELDS = {
    "user_key", "x_user_key", "authorization", "cookie", "token", "share_token",
    "api_key", "secret", "password", "access_key", "secret_key", "receipt",
    "recovery_code", "new_user_key", "device_key", "credential",
    "error", "message", "exc_info", "exception", "stack", "traceback",
    "prompt", "text", "input", "output", "payload", "body", "response",
    "raw_response", "content", "description", "visual_description",
    "sample_audio_url", "source_image_url", "image_base64", "image_data",
}
_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_UUID = re.compile(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", re.IGNORECASE)
_RECOVERY_SECRET = re.compile(r"(?:ASB-R1-|asb_device_)[A-Za-z0-9_-]{43}")


def _redact_log_text(value: str) -> str:
    value = _RECOVERY_SECRET.sub("[redacted-credential]", value)
    value = _URL.sub("[redacted-url]", value)
    return _UUID.sub("[redacted-id]", value)


def _protect_stdlib_exceptions() -> None:
    # Configure at record creation, before Uvicorn/Celery's own (or later-added)
    # handlers format tracebacks. A root logger filter does not filter children.
    previous = logging.getLogRecordFactory()
    if getattr(previous, "_asb_redacts_exceptions", False):
        return

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        if record.name.split(".", 1)[0] in {"uvicorn", "celery", "sqlalchemy"}:
            record.msg = _redact_log_text(record.getMessage())
            record.args = ()
        if record.exc_info:
            record.exc_text = _redact_log_text("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        if record.stack_info:
            record.stack_info = _redact_log_text(record.stack_info)
        return record

    factory._asb_redacts_exceptions = True
    logging.setLogRecordFactory(factory)


def redact_log_data(_logger, _method, event_dict):
    """Keep operation codes/counts/correlation; drop credentials and raw child/provider data."""
    def clean(value, field=""):
        normalized = str(field).lower().replace("-", "_")
        if (normalized in _PRIVATE_FIELDS or normalized.endswith(("_api_key", "_secret", "_token"))
                or "password" in normalized):
            return "[redacted]"
        if isinstance(value, dict):
            return {key: clean(item, key) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(item, field) for item in value]
        if isinstance(value, str):
            value = _RECOVERY_SECRET.sub("[redacted-credential]", value)
            # URLs may contain S3 signatures, receipt tokens, child names, or legacy credentials.
            value = _URL.sub("[redacted-url]", value)
            if normalized not in {"request_id", "server_request_id", "job_id", "book_id", "event"}:
                value = _UUID.sub("[redacted-id]", value)
            return value
        if isinstance(value, BaseException):
            return type(value).__name__
        return value

    return {key: clean(value, key) for key, value in event_dict.items()}


def configure_logging() -> None:
    _protect_stdlib_exceptions()
    # HTTP client INFO logs include the complete signed URL outside structlog.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            redact_log_data,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
