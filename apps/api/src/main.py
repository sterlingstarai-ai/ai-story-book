from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from time import perf_counter
import uuid
import structlog

from src.core.config import settings
from src.routers import (
    books,
    branch,
    characters,
    library,
    credits,
    streak,
    growth,
    iap,
    users,
    profiles,
    settings as user_settings,
    rewards,
    pod,
    pronunciation,
    voice_profiles,
    consent,
)
from src.core.database import get_db  # noqa: F401
from src.core.rate_limit import check_rate_limit, rate_limiter
from src.core.exceptions import (
    APIError,
    api_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from src.core.errors import StoryBookError, SafetyError


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assign unique request ID to every request for tracing."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        # Bind to structlog context for all logs in this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # XSS protection (legacy but still useful)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Content Security Policy
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        # Remove server header for security
        if "server" in response.headers:
            del response.headers["server"]
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Emit structured access logs with request correlation and latency."""

    async def dispatch(self, request: Request, call_next):
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((perf_counter() - started) * 1000, 2)
            logger.error(
                "HTTP request failed",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
                error=str(exc),
            )
            raise

        duration_ms = round((perf_counter() - started) * 1000, 2)
        logger.info(
            "HTTP request completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


class RateLimitHeadersMiddleware(BaseHTTPMiddleware):
    """Add rate limit headers to responses for client visibility."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Add rate limit headers if they were set by check_rate_limit
        if hasattr(request.state, "rate_limit_remaining"):
            response.headers["X-RateLimit-Remaining"] = str(
                request.state.rate_limit_remaining
            )
        if hasattr(request.state, "rate_limit_limit"):
            response.headers["X-RateLimit-Limit"] = str(request.state.rate_limit_limit)

        return response


# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting AI Story Book API", version=settings.app_version)

    # Start job monitor (background task for stuck job detection)
    # 테스트 환경에서는 job_monitor 비활성화 (DB 세션 타이밍 이슈 방지)
    from src.services.job_monitor import job_monitor
    from src.services.periodic_credits import periodic_credits

    if not settings.testing:
        await job_monitor.start()
        await periodic_credits.start()

    yield

    # Shutdown - graceful cleanup
    logger.info("Shutting down AI Story Book API - starting graceful cleanup")

    if not settings.testing:
        await job_monitor.stop()
        await periodic_credits.stop()

    # Close rate limiter Redis connection
    await rate_limiter.close()

    # Close database connection pool
    try:
        from src.core.database import async_engine

        await async_engine.dispose()
        logger.info("Database connection pool closed")
    except Exception as e:
        logger.warning("Failed to close database pool", error=str(e))

    logger.info("Graceful shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="""
# AI Story Book API

AI 기반 맞춤형 동화책 생성 API입니다.

## 주요 기능

* **책 생성**: 주제, 연령대, 스타일을 입력하면 AI가 동화책을 생성합니다
* **캐릭터 관리**: 사진에서 캐릭터를 추출하거나 직접 생성할 수 있습니다
* **시리즈 생성**: 같은 캐릭터로 연속된 이야기를 만들 수 있습니다
* **PDF/오디오 내보내기**: 완성된 책을 PDF나 오디오로 내보낼 수 있습니다

## 인증

모든 API는 `X-User-Key` 헤더가 필요합니다.
중복 요청 방지를 위해 `X-Idempotency-Key` 헤더 사용을 권장합니다.

## Rate Limiting

- 기본: 분당 10회 요청 제한
- 초과 시 429 Too Many Requests 응답

## 크레딧 시스템

책 1권 생성에 크레딧 1개가 소모됩니다.
    """,
    lifespan=lifespan,
    openapi_tags=[
        {
            "name": "Books",
            "description": "동화책 생성 및 조회 API",
        },
        {
            "name": "Characters",
            "description": "캐릭터 관리 API",
        },
        {
            "name": "Library",
            "description": "사용자 서재 API",
        },
        {
            "name": "Credits",
            "description": "크레딧 및 구독 관리 API",
        },
        {
            "name": "Streak",
            "description": "오늘의 동화 및 스트릭 API",
        },
    ],
    contact={
        "name": "AI Story Book Team",
        "email": "support@aistorybook.com",
    },
    license_info={
        "name": "MIT",
    },
)

# Request ID middleware (outermost - runs first)
app.add_middleware(RequestIDMiddleware)

# Access logs with request_id bound in middleware above
app.add_middleware(AccessLogMiddleware)

# Security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# Rate limit headers middleware
app.add_middleware(RateLimitHeadersMiddleware)

# CORS - Configurable via CORS_ORIGINS env var
# 프로덕션에서 와일드카드('*') + credentials 조합은 보안 위험
if not settings.cors_origins or settings.cors_origins.strip() == "":
    if settings.debug:
        cors_origins = ["http://localhost:3000", "http://localhost:8080"]
    else:
        cors_origins = []  # 프로덕션에서 미설정 시 CORS 비허용
        logger.warning("CORS_ORIGINS not set in production - no origins allowed")
elif settings.cors_origins == "*":
    if not settings.debug:
        logger.warning("CORS_ORIGINS='*' in production is insecure, restricting to empty")
        cors_origins = []
    else:
        cors_origins = ["*"]
else:
    cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "X-User-Key",
        "X-Profile-Id",
        "X-Idempotency-Key",
        "X-Admin-Key",
        "X-Request-ID",
        "Content-Type",
    ],
)


# API error handler for standardized responses
app.add_exception_handler(APIError, api_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)


# StoryBookError handler - domain errors from orchestrator/services
@app.exception_handler(StoryBookError)
async def storybook_error_handler(request: Request, exc: StoryBookError):
    """Map domain errors to appropriate HTTP responses."""
    status_code = 500
    if isinstance(exc, SafetyError):
        status_code = 422

    logger.warning(
        "Domain error",
        error_code=exc.code.value,
        message=exc.message,
        path=request.url.path,
    )
    content = {
        "detail": exc.message,
        "error": {
            "code": exc.code.value,
            "message": exc.message,
            "details": exc.details or None,
        },
    }
    if hasattr(request.state, "request_id"):
        content["request_id"] = request.state.request_id

    return JSONResponse(
        status_code=status_code,
        content=content,
    )


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", error=str(exc), path=request.url.path)
    message = (
        str(exc) if settings.debug else "서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
    )
    content = {
        "detail": message,
        "error": {
            "code": "INTERNAL_ERROR",
            "message": message,
        },
    }
    if hasattr(request.state, "request_id"):
        content["request_id"] = request.state.request_id

    return JSONResponse(
        status_code=500,
        content=content,
    )


async def _build_readiness_payload(*, include_metrics: bool) -> dict:
    """Build readiness payload with dependency state."""
    from src.services.job_monitor import get_job_metrics

    jobs_status = "healthy"
    try:
        job_metrics = await get_job_metrics()
    except Exception as e:
        logger.error("Failed to get job metrics", error=str(e))
        job_metrics = {"error": str(e)}
        jobs_status = "unhealthy"

    # Check Redis connectivity
    redis_status = "healthy"
    try:
        if not await rate_limiter.ping():
            redis_status = "unhealthy"
    except Exception:
        redis_status = "unhealthy"

    # Check DB connectivity
    db_status = "healthy"
    try:
        from src.core.database import AsyncSessionLocal
        from sqlalchemy import text

        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        db_status = "unhealthy"

    overall_status = (
        "healthy"
        if db_status == "healthy"
        and redis_status == "healthy"
        and jobs_status == "healthy"
        else "degraded"
    )

    payload = {
        "status": overall_status,
        "version": settings.app_version,
        "services": {
            "database": db_status,
            "redis": redis_status,
            "job_monitor": jobs_status,
            "llm_provider": settings.llm_provider,
            "image_provider": settings.image_provider,
        },
    }
    if include_metrics:
        payload["jobs"] = job_metrics
        payload["config"] = {
            "rate_limit_requests": settings.rate_limit_requests,
            "rate_limit_window": settings.rate_limit_window,
            "job_sla_seconds": settings.job_sla_seconds,
            "image_max_concurrent": settings.image_max_concurrent,
        }
    return payload


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": settings.app_version,
    }


@app.get("/health/live")
async def live_health_check():
    return {
        "status": "alive",
        "version": settings.app_version,
    }


@app.get("/health/ready")
async def ready_health_check():
    payload = await _build_readiness_payload(include_metrics=False)
    return JSONResponse(
        status_code=200 if payload["status"] == "healthy" else 503,
        content=payload,
    )


@app.get("/health/detailed")
async def detailed_health_check():
    """Detailed health check with job metrics and external API status"""
    return await _build_readiness_payload(include_metrics=True)


# Include routers with rate limiting
app.include_router(
    books.router,
    prefix="/v1/books",
    tags=["Books"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    characters.router,
    prefix="/v1/characters",
    tags=["Characters"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    library.router,
    prefix="/v1/library",
    tags=["Library"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    credits.router,
    prefix="/v1/credits",
    tags=["Credits"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    streak.router,
    prefix="/v1/streak",
    tags=["Streak"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    growth.router,
    prefix="/v1/growth",
    tags=["Growth"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    iap.router,
    prefix="/v1/iap",
    tags=["IAP"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    users.router,
    prefix="/v1/users",
    tags=["Users"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    profiles.router,
    prefix="/v1/profiles",
    tags=["Profiles"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    user_settings.router,
    prefix="/v1/settings",
    tags=["Settings"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    rewards.router,
    prefix="/v1/rewards",
    tags=["Rewards"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    pod.router,
    prefix="/v1/pod",
    tags=["POD"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    pronunciation.router,
    prefix="/v1/pronunciation",
    tags=["Pronunciation"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    branch.router,
    prefix="/v1/branch",
    tags=["Branch"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    voice_profiles.router,
    prefix="/v1/voice-profiles",
    tags=["VoiceProfiles"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    consent.router,
    prefix="/v1/consent",
    tags=["Consent"],
    dependencies=[Depends(check_rate_limit)],
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
