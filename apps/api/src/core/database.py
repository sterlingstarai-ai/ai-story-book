from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.core.config import settings


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
sync_database_url = make_sync_url(settings.database_url)
engine = create_engine(sync_database_url, echo=settings.debug)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Async engine (for API)
async_database_url = make_async_url(settings.database_url)
async_engine = create_async_engine(async_database_url, echo=settings.debug)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


# Dependency
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
