"""Global purchase claims serialize on real PostgreSQL, including across owners."""
import asyncio
import hashlib
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.models.db import IAPPurchaseClaim, UserCredits
from src.services.purchase_claims import claim_purchase
from tests.test_pg_fk_erasure import PG_URL, pg_schema_at_head  # noqa: F401

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not PG_URL, reason="E2E_PG_DATABASE_URL required")]


@pytest.mark.usefixtures("pg_schema_at_head")
async def test_only_one_owner_can_commit_a_store_grant():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    transaction = 'scan-claim-' + uuid.uuid4().hex
    owners = [str(uuid.uuid4()), str(uuid.uuid4())]
    barrier = asyncio.Barrier(2)
    digest = hashlib.sha256(f'apple\0{transaction}'.encode()).hexdigest()

    async def grant(owner):
        async with maker() as db:
            await barrier.wait()
            first = await claim_purchase(db, 'apple', transaction)
            if first:
                db.add(UserCredits(user_key=owner, credits=5))
            await db.commit()
            return first
    try:
        assert sorted(await asyncio.gather(*(grant(owner) for owner in owners))) == [False, True]
        async with maker() as db:
            assert await db.scalar(select(func.sum(UserCredits.credits)).where(UserCredits.user_key.in_(owners))) == 5
            await db.execute(delete(UserCredits).where(UserCredits.user_key.in_(owners)))
            await db.commit()
        async with maker() as db:
            assert not await claim_purchase(db, 'apple', transaction)
            await db.rollback()
    finally:
        async with maker() as db:
            await db.execute(delete(UserCredits).where(UserCredits.user_key.in_(owners)))
            await db.execute(delete(IAPPurchaseClaim).where(IAPPurchaseClaim.transaction_digest == digest))
            await db.commit()
        await engine.dispose()


@pytest.mark.usefixtures("pg_schema_at_head")
async def test_upgrade_blocks_preexisting_detached_refills_and_repairs_foreign_series():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession
    from src.services.periodic_credits import periodic_credits

    engine = create_async_engine(PG_URL, poolclass=NullPool)
    schema = 'scan_upgrade_' + uuid.uuid4().hex
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(text(f'CREATE SCHEMA {schema}'))
            await connection.execute(text(f'SET LOCAL search_path TO {schema}'))
            for table in ('subscriptions', 'iap_receipts', 'books', 'series'):
                await connection.execute(text(f'CREATE TABLE {table} (LIKE public.{table} INCLUDING DEFAULTS)'))
            await connection.execute(text('ALTER TABLE subscriptions DROP COLUMN calendar_refill_enabled'))
            await connection.execute(text("""INSERT INTO subscriptions
                (id,user_key,plan,status,credits_per_month,current_period_start,current_period_end)
                VALUES (1,'legacy-owner','basic','active',5,now()-interval '32 days',now()-interval '2 days')"""))
            await connection.execute(text("""INSERT INTO iap_receipts
                (user_key,platform,product_id,transaction_id,store_transaction_id,status,subscription_id)
                VALUES ('restored-owner','apple','subscription_basic','legacy-claim','legacy-claim','restored',NULL)"""))
            await connection.execute(text("""INSERT INTO series (id,title,language,target_age,style,user_key)
                VALUES ('victim-series','synthetic','ko','5-7','watercolor','victim')"""))
            await connection.execute(text("""INSERT INTO books
                (id,job_id,title,language,target_age,style,user_key,series_id,series_index)
                VALUES ('foreign-book','synthetic-job','synthetic','ko','5-7','watercolor','attacker','victim-series',2)"""))
            path = Path(__file__).parents[1] / 'alembic/versions/2a8d9e4f610b_security_purchase_claims.py'
            spec = importlib.util.spec_from_file_location('claim_migration', path)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)

            def upgrade(sync_connection):
                with Operations.context(MigrationContext.configure(sync_connection)):
                    migration.upgrade()
            await connection.run_sync(upgrade)
            assert await connection.scalar(text('SELECT calendar_refill_enabled FROM subscriptions')) is False
            assert await connection.scalar(text('SELECT count(*) FROM iap_purchase_claims')) == 1
            assert (await connection.execute(text('SELECT series_id,series_index FROM books'))).one() == (None, None)
            async with AsyncSession(bind=connection) as db:
                assert await periodic_credits.grant_due_refills(db) == 0
        finally:
            await transaction.rollback()  # removes the entire synthetic schema
    await engine.dispose()
