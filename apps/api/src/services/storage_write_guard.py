"""Track in-flight media writes across worker crashes and DB disconnects."""

from contextlib import asynccontextmanager
from uuid import uuid4

from sqlalchemy import text

from src.core.errors import StorageError

# The backup runner takes this same lock exclusively before locking tables.
MEDIA_WRITE_LOCK = 0x4153424D45444941


@asynccontextmanager
async def guarded_media_write():
    from src.core.database import media_write_engine

    async with media_write_engine().connect() as connection:
        operation_id = uuid4().hex
        # Publish the intent before competing for the write lock. A backup
        # winning the gap between transactions sees the intent and aborts.
        async with connection.begin():
            await connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            await connection.execute(
                text("INSERT INTO public.media_write_intents (id) VALUES (:id)"),
                {"id": operation_id},
            )
        # A transaction-scoped lock stays on the backend handling S3 I/O
        # and releases automatically, including with transaction pooling.
        async with connection.begin():
            await connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            await connection.execute(text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": MEDIA_WRITE_LOCK})
            yield
            deleted = await connection.execute(
                text("DELETE FROM public.media_write_intents WHERE id = :id"),
                {"id": operation_id},
            )
            if deleted.rowcount != 1:
                raise StorageError("Media write intent could not be cleared")
