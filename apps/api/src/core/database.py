from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from src.core.config import settings


def _require_database_url() -> str:
    """Fail fast with a clear message when DB URL is missing."""
    url = (settings.database_url or "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is required but not set. Configure DATABASE_URL before starting the API."
        )
    return url


def make_sync_url(url: str) -> str:
    """Convert database URL to sync driver format"""
    if "postgresql+asyncpg://" in url:
        return url.replace("postgresql+asyncpg://", "postgresql://")
    if "sqlite+aiosqlite://" in url:
        return url.replace("sqlite+aiosqlite://", "sqlite://")
    return url


def make_async_url(url: str) -> str:
    """Convert database URL to async driver format"""
    if "postgresql://" in url and "asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://")
    if "sqlite://" in url and "aiosqlite" not in url:
        return url.replace("sqlite://", "sqlite+aiosqlite://")
    return url


# Sync engine (for Alembic migrations)
database_url = _require_database_url()
sync_database_url = make_sync_url(database_url)
engine = create_engine(sync_database_url, echo=settings.debug)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Async engine (for API)
async_database_url = make_async_url(database_url)
_ASYNC_ENGINE_KWARGS = {"echo": settings.debug}
async_engine = create_async_engine(async_database_url, **_ASYNC_ENGINE_KWARGS)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


def configure_for_worker() -> None:
    """Celery 워커 프로세스용으로 async 엔진을 NullPool 로 재구성한다(C1).

    Celery 태스크는 동기 컨텍스트라 `services.tasks.run_async()`가 태스크마다 새 이벤트
    루프를 만들고 닫는다. asyncpg 기본 풀(`AsyncAdaptedQueuePool`)은 커넥션을 캐싱하므로,
    닫힌 루프에 묶인 커넥션이 다음 태스크의 새 루프에서 재사용되어
    `RuntimeError: got Future attached to a different loop`
    → `InterfaceError: cannot perform operation: another operation is in progress`
    로 폭발한다(책 생성 전량 실패). 워커에서는 커넥션을 캐싱하지 않아 이 재사용 자체를
    구조적으로 차단한다.

    **이 NullPool 재구성이 load-bearing이다**(실측 2026-08-09): 태스크당 `run_async`를
    1회로 통합해도, 태스크 #1이 루프를 닫으며 풀에 남긴 커넥션을 태스크 #2의 새 루프가
    재사용하므로 여전히 폭발한다 — 이 재구성을 끄고 실 워커 2연속 테스트를 돌리면
    `test_worker_completes_two_sequential_book_jobs`가 실제로 FAIL한다.
    `run_async` 1회 통합(services/tasks.py)은 그 위의 2차 방어로, 한 태스크 **안에서**
    실패 마킹 경로까지 함께 죽던 문제를 없애고 불변식을 코드에 명시한다.

    SQLite(aiosqlite)는 이미 기본이 NullPool이라 무해하며, 이 클래스를 구조적으로
    재현하지 못한다(그래서 SQLite 게이트만으로는 C1을 못 잡았다).
    """
    global async_engine

    if isinstance(async_engine.pool, NullPool):
        return

    async_engine = create_async_engine(
        async_database_url, poolclass=NullPool, **_ASYNC_ENGINE_KWARGS
    )
    # 세션메이커는 in-place 재바인딩 — 이미 `from ... import AsyncSessionLocal` 로
    # 참조를 잡아둔 모듈들도 새 엔진을 쓰게 된다.
    AsyncSessionLocal.configure(bind=async_engine)

Base = declarative_base()


# Dependency
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
