from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from src.core.config import settings
from src.core.database_options import database_options


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
    return database_options(url, asynchronous=False)[0]


def make_async_url(url: str) -> str:
    """Convert database URL to async driver format"""
    return database_options(url, asynchronous=True)[0]


# Sync engine (for Alembic migrations)
database_url = _require_database_url()
_TLS_OPTIONS = {"ssl_mode": settings.database_ssl_mode, "ssl_root_cert": settings.database_ssl_root_cert}
sync_database_url, _ = database_options(database_url, asynchronous=False, **_TLS_OPTIONS)
engine = create_engine(sync_database_url, echo=settings.debug, hide_parameters=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Async engine (for API)
async_database_url, _async_connect_args = database_options(database_url, asynchronous=True, **_TLS_OPTIONS)
_ASYNC_ENGINE_KWARGS = {"echo": settings.debug, "connect_args": _async_connect_args,
                        "hide_parameters": True}
# A suspended provider may close pooled connections.  Check on checkout only;
# unlike a periodic heartbeat this does not keep an idle database active.
if async_database_url.startswith("postgresql+psycopg://"):
    _ASYNC_ENGINE_KWARGS["pool_pre_ping"] = True
async_engine = create_async_engine(async_database_url, **_ASYNC_ENGINE_KWARGS)
# Route sessions can already hold connections while writing media. Reserve
# independent capacity for the write journal so saturated routes can finish.
_media_write_engine = (
    create_async_engine(async_database_url, pool_size=2, max_overflow=0, pool_timeout=10,
                        **_ASYNC_ENGINE_KWARGS)
    if async_database_url.startswith("postgresql+") else None
)


def media_write_engine():
    # Celery task loops cannot share pooled async connections.
    if _media_write_engine is None or isinstance(async_engine.pool, NullPool):
        return async_engine
    return _media_write_engine


async def dispose_async_engines():
    try:
        await async_engine.dispose()
    finally:
        if _media_write_engine is not None:
            await _media_write_engine.dispose()


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


@event.listens_for(Session, 'after_commit')
def _wake_request_maintenance(session):
    # Background sweeps use the unmarked factory: their own commits must never
    # wake themselves in a tight loop. Bulk request DML is covered as well.
    if session.info.get('wake_maintenance_after_commit'):
        from src.core.maintenance_activity import maintenance_activity

        maintenance_activity.notify()


# Dependency
async def get_db():
    async with AsyncSessionLocal() as session:
        session.info['wake_maintenance_after_commit'] = True
        try:
            from src.services.privacy_journal_runtime import configured_journal

            journal = configured_journal()
            if journal is not None:
                session.info['privacy_journal'] = journal
            yield session
        finally:
            await session.close()
