from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
import structlog

from src.core.config import settings
from src.routers import books, characters, library, credits, streak
from src.core.database import get_db  # noqa: F401
from src.core.rate_limit import check_rate_limit, rate_limiter
from src.core.exceptions import APIError, api_exception_handler


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

    if not settings.testing:
        await job_monitor.start()

    yield

    # Shutdown
    logger.info("Shutting down AI Story Book API")

    if not settings.testing:
        await job_monitor.stop()

    await rate_limiter.close()


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

# Security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# CORS - Configurable via CORS_ORIGINS env var
cors_origins = (
    ["*"]
    if settings.cors_origins == "*"
    else [origin.strip() for origin in settings.cors_origins.split(",")]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["X-User-Key", "X-Idempotency-Key", "Content-Type", "Authorization"],
)


# API error handler for standardized responses
app.add_exception_handler(APIError, api_exception_handler)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", error=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": str(exc) if settings.debug else "Something went wrong",
            }
        },
    )


# Health check
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": settings.app_version,
    }


@app.get("/health/detailed")
async def detailed_health_check():
    """Detailed health check with job metrics and external API status"""
    from src.services.job_monitor import get_job_metrics

    try:
        job_metrics = await get_job_metrics()
    except Exception as e:
        logger.error("Failed to get job metrics", error=str(e))
        job_metrics = {"error": str(e)}

    # Check Redis connectivity
    redis_status = "healthy"
    try:
        await rate_limiter.is_allowed("health_check_probe")
    except Exception:
        redis_status = "unhealthy"

    return {
        "status": "healthy",
        "version": settings.app_version,
        "jobs": job_metrics,
        "services": {
            "redis": redis_status,
            "llm_provider": settings.llm_provider,
            "image_provider": settings.image_provider,
        },
        "config": {
            "rate_limit_requests": settings.rate_limit_requests,
            "rate_limit_window": settings.rate_limit_window,
            "job_sla_seconds": settings.job_sla_seconds,
            "image_max_concurrent": settings.image_max_concurrent,
        },
    }


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
