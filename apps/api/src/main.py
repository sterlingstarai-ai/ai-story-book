from typing import Optional

from fastapi import FastAPI, Request, Depends, Header, HTTPException
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
    pod,
    pronunciation,
    voice_profiles,
    consent,
    shares,
    config,
)
from src.core.audio_feature import audio_readiness_issues
from src.core.database import get_db  # noqa: F401
from src.core.rate_limit import check_rate_limit, rate_limiter
from src.core.utils import redact_path
from src.core.exceptions import (
    APIError,
    api_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from src.core.errors import (
    SafetyError,
    StoryBookError,
    client_safe_details,
    client_safe_message,
)


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
        # Content Security Policy — 공개 공유 페이지(/share)는 외부 이미지(S3/CDN)와 인라인
        # 스타일을 쓰므로 img/style만 완화. 그 외 API 응답은 엄격한 default-src 'self' 유지.
        if request.url.path.startswith("/share"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' https: data:; "
                "style-src 'self' 'unsafe-inline'"
            )
        else:
            response.headers["Content-Security-Policy"] = "default-src 'self'"
        # Remove server header for security
        if "server" in response.headers:
            del response.headers["server"]
        return response


# 정본은 `src.core.utils.redact_path` — 예외 핸들러와 **같은 규칙**을 공유해야 한다.
_redact_path = redact_path


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
                path=_redact_path(request.url.path),
                duration_ms=duration_ms,
                error=str(exc),
            )
            raise

        duration_ms = round((perf_counter() - started) * 1000, 2)
        logger.info(
            "HTTP request completed",
            method=request.method,
            path=_redact_path(request.url.path),
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


def sanitize_domain_error(exc: StoryBookError) -> tuple[str, Optional[dict]]:
    """도메인 에러를 클라이언트로 내보낼 (message, details) 로 위생 처리한다(A1).

    규칙 자체는 `core.errors` 에 단일 정의한다 — 잡 상태 서빙 경로(A1-R)와 규칙이
    갈라지지 않게 하기 위함이다(실제로 갈라져서 저장된 원문이 그대로 서빙됐다).
    """
    return (
        client_safe_message(exc.code, exc.message),
        client_safe_details(exc.details),
    )


# StoryBookError handler - domain errors from orchestrator/services
@app.exception_handler(StoryBookError)
async def storybook_error_handler(request: Request, exc: StoryBookError):
    """Map domain errors to appropriate HTTP responses."""
    status_code = 500
    if isinstance(exc, SafetyError):
        status_code = 422

    client_message, client_details = sanitize_domain_error(exc)

    # 원문은 **로그로만** — 진단에 필요한 정보를 잃지 않는다.
    logger.warning(
        "Domain error",
        error_code=exc.code.value,
        message=exc.message,
        detail_keys=sorted((exc.details or {}).keys()),
        path=_redact_path(request.url.path),
    )
    content = {
        "detail": client_message,
        "error": {
            "code": exc.code.value,
            "message": client_message,
            "details": client_details,
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
    logger.error(
        "Unhandled exception", error=str(exc), path=_redact_path(request.url.path)
    )
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


def _iap_readiness_issues() -> list[str]:
    """운영 IAP 설정이 위조 영수증을 통과시킬 수 있는 상태면 사유 목록을 반환한다.

    - strict 모드가 아니면 local/hybrid의 fail-open 경로로 임의 영수증이 통과.
    - Apple/Google 스토어 키가 모두 없으면 실검증 자체가 불가.
    - 웹훅 시크릿 미설정이면 무인증 상태 변조(구독 강등 등)가 가능.
    """
    issues: list[str] = []
    if (settings.iap_verification_mode or "local").strip().lower() != "strict":
        issues.append("iap_mode_not_strict")

    has_apple = bool(settings.apple_iap_shared_secret)
    has_google = bool(
        settings.google_play_package_name
        and (
            settings.google_play_access_token
            or settings.google_play_service_account_json
            or settings.google_play_service_account_file
        )
    )
    if not (has_apple or has_google):
        issues.append("iap_store_credentials_missing")

    if not settings.iap_webhook_secret:
        issues.append("iap_webhook_secret_missing")

    # M5/R2-5: Apple 검증을 쓰면서 기대 bundle_id가 없으면 cross-app 영수증 리플레이가
    # 무검증으로 통과한다(shared secret이 팀 단위일 때). 검증기는 하위호환으로 통과시키므로
    # 여기서 배포를 막는다 — '조용히 검증 안 함'을 남기지 않는다.
    if has_apple and not settings.apple_bundle_id:
        issues.append("apple_bundle_id_missing")

    return issues


async def _build_readiness_payload(
    *, include_metrics: bool, expose_missing_keys: bool = False
) -> dict:
    """Build readiness payload with dependency state.

    M9: 공개 /health/ready는 provider_keys boolean만 노출하고 missing_keys 상세(빠진
    보안설정 목록: iap_webhook_secret_missing 등)는 감춘다(정찰 표면 축소). 상세는
    인증된 /health/detailed(expose_missing_keys=True)에만 노출한다.
    """
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

    # Check S3/storage connectivity + provider key presence (운영에서만 — 테스트는 mock 인프라).
    # 키 누락/S3 오설정이 readiness를 통과해 무관측 배포되는 것을 막는다.
    storage_status = "healthy"
    keys_status = "healthy"
    missing_keys: list[str] = []
    if not settings.testing:
        try:
            from src.services.storage import ensure_bucket_exists

            await ensure_bucket_exists()
        except Exception:
            storage_status = "unhealthy"

        if settings.llm_provider != "mock" and not settings.llm_api_key:
            missing_keys.append("llm")
        if settings.image_provider != "mock" and not settings.image_api_key:
            missing_keys.append("image")

        # IAP 결제 보안: 운영에서 local/hybrid 모드나 스토어 키 누락은 위조 영수증을
        # 통과시키는 fail-open이므로 readiness를 막는다(미관측 출시 차단).
        iap_issues = _iap_readiness_issues()
        missing_keys.extend(iap_issues)

        # 오디오(TTS/STT): 기능이 켜져 있을 때만(G9 기본 비활성) 라이브 구성을 게이트.
        # mock/미지 provider가 무음 오디오·가짜 발음점수를 성공으로 서빙하는 것을 차단(H1).
        if settings.audio_feature_enabled:
            missing_keys.extend(audio_readiness_issues())

        if missing_keys:
            keys_status = "unhealthy"

    # H4/R3-1: 전역 일일 생성 예산이 프로덕션에서 꺼져 있으면(0/미설정) 비용 폭증에 무방비다.
    # 직전 감사가 '출시 최소 조건'으로 승격한 완화책이 배포 산출물 미배선으로 실제로는
    # 꺼져 있었다 — 조용히 넘기지 않고 관측 가능하게 남긴다. (차단이 아니라 **경고**:
    # 값 산정은 오너 결정이고, 미설정만으로 배포를 죽이면 기존 배포가 즉시 멈춘다.)
    warnings: list[str] = []
    if not settings.testing and int(settings.daily_generation_budget or 0) <= 0:
        warnings.append("cost_budget_disabled")
        logger.error(
            "cost budget guardrail NOT CONFIGURED — DAILY_GENERATION_BUDGET<=0 "
            "(전역 비용 상한 없음)",
            daily_generation_budget=settings.daily_generation_budget,
        )

    overall_status = (
        "healthy"
        if db_status == "healthy"
        and redis_status == "healthy"
        and jobs_status == "healthy"
        and storage_status == "healthy"
        and keys_status == "healthy"
        else "degraded"
    )

    payload = {
        "status": overall_status,
        "version": settings.app_version,
        "services": {
            "database": db_status,
            "redis": redis_status,
            "job_monitor": jobs_status,
            "storage": storage_status,
            "provider_keys": keys_status,
            "llm_provider": settings.llm_provider,
            "image_provider": settings.image_provider,
            # H4/R3-1: 비용 가드레일이 켜져 있는지를 공개 payload에서도 boolean으로 노출한다
            # (값·상세는 감추되 '꺼져 있음'은 운영이 프로브만으로 알 수 있어야 한다).
            "cost_budget": (
                "disabled"
                if int(settings.daily_generation_budget or 0) <= 0
                else "configured"
            ),
        },
    }
    # M9: 상세 missing_keys는 인증된 detailed에만. 공개 ready는 provider_keys boolean만.
    if missing_keys and expose_missing_keys:
        payload["missing_keys"] = missing_keys
    if warnings and expose_missing_keys:
        payload["warnings"] = warnings
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
async def detailed_health_check(
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    """Detailed health check with job metrics and external API status.

    M9: 내부 메트릭·config·missing_keys(빠진 보안설정 목록)를 노출하므로 X-Admin-Key
    인증을 요구한다(무인증 정찰 차단). admin_api_key 미설정이면 detailed 미제공(403).
    """
    import hmac

    admin_key = getattr(settings, "admin_api_key", None)
    if not admin_key or not x_admin_key or not hmac.compare_digest(
        x_admin_key, admin_key
    ):
        return JSONResponse(status_code=403, content={"detail": "Forbidden"})
    return await _build_readiness_payload(
        include_metrics=True, expose_missing_keys=True
    )


# Include routers with rate limiting
app.include_router(
    books.router,
    prefix="/v1/books",
    tags=["Books"],
    dependencies=[Depends(check_rate_limit)],
)
app.include_router(
    shares.router,
    prefix="/v1/books",
    tags=["Share"],
    dependencies=[Depends(check_rate_limit)],
)
# 공개 공유 페이지(인증·rate-limit 없음, /share/{token})
app.include_router(shares.public_router, tags=["Share"])
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
    config.router,
    prefix="/v1/config",
    tags=["Config"],
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
