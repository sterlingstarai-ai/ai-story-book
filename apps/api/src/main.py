from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
import structlog

from src.core.config import settings
from src.routers import books, characters, library, credits, streak
from src.core.database import engine, Base
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
        structlog.processors.JSONRenderer()
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
    yield
    # Shutdown
    logger.info("Shutting down AI Story Book API")
    await rate_limiter.close()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI 동화책 생성 API",
    lifespan=lifespan,
)

# Security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# CORS - Configurable via CORS_ORIGINS env var
cors_origins = (
    ["*"] if settings.cors_origins == "*"
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
        }
    )


# Health check
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": settings.app_version,
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
