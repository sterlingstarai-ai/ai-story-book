"""Durable, account-independent store grant deduplication."""

import hashlib

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import IAPPurchaseClaim


async def claim_purchase(db: AsyncSession, platform: str, transaction_id: str) -> bool:
    """Reserve the canonical purchase in the caller's grant/receipt transaction."""
    digest = hashlib.sha256(f"{platform}\0{transaction_id}".encode()).hexdigest()
    dialect = db.get_bind().dialect.name
    if dialect not in {"sqlite", "postgresql"}:
        raise RuntimeError("Unsupported purchase claim database")
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    result = await db.execute(
        insert(IAPPurchaseClaim).values(transaction_digest=digest)
        .on_conflict_do_nothing(index_elements=["transaction_digest"])
    )
    return result.rowcount == 1
