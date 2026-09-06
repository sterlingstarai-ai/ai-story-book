"""Report ownership, data minimization, erasure and actual operator workflow."""

import importlib.util
import json
import stat
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select

from src.core.config import settings
from src.core.exceptions import ValidationError
from src.core.rate_limit import rate_limiter
from src.models.db import Book, ChildProfile, ContentReport, Page
from src.services.content_reports import update_report_status
from tests.factories import make_book_rows

pytestmark = pytest.mark.asyncio


async def seed(db, user_key):
    db.add_all(make_book_rows([("reported-book", user_key)]))
    await db.flush()
    db.add(Page(book_id="reported-book", page_number=1, text="합성 테스트 본문",
                image_url="https://example.invalid/test.png"))
    await db.commit()


async def send(client, headers, **values):
    return await client.post("/v1/books/reported-book/reports", headers=headers,
                             json={"page_number": 1, "reason": "harmful_content", **values})


async def test_report_persists_minimal_metadata_and_deduplicates_version(client, headers, user_key, db_session):
    await seed(db_session, user_key)
    first = await send(client, headers)
    assert first.status_code == 200, first.text
    assert set(first.json()) == {"report_id", "status", "created_at"}
    assert first.json()["status"] == "pending"
    second = await send(client, headers)
    assert second.json() == first.json()
    row = (await db_session.execute(select(ContentReport))).scalar_one()
    assert "합성" not in repr(row.__dict__)
    assert user_key not in repr(row.__dict__)
    assert not {"text", "image_url", "user_key", "profile_id", "email", "contact", "name"}.intersection(ContentReport.__table__.columns.keys())
    page = (await db_session.execute(select(Page))).scalar_one()
    page.text = "교정된 합성 테스트 본문"
    await db_session.commit()
    revised = await send(client, headers)
    assert revised.json()["report_id"] != row.id


async def test_cover_supported_but_nonexistent_page_rejected(client, headers, user_key, db_session):
    await seed(db_session, user_key)
    assert (await send(client, headers, page_number=0)).status_code == 200
    assert (await send(client, headers, page_number=2)).status_code == 404


@pytest.mark.parametrize("values", [
    {"page_number": "1"}, {"page_number": True}, {"page_number": -1}, {"page_number": 65},
    {"reason": "arbitrary"}, {"reason": None}, {"text": "do not store this"}, {"email": "test@example.invalid"},
])
async def test_strict_report_payload(client, headers, values):
    assert (await send(client, headers, **values)).status_code == 422


async def test_report_requires_owner_and_valid_profile(client, headers, user_key, db_session):
    await seed(db_session, user_key)
    db_session.add_all([
        ChildProfile(id="child-a", user_key=user_key, name="합성A"),
        ChildProfile(id="child-b", user_key=user_key, name="합성B"),
        ChildProfile(id="other-child", user_key="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", name="합성C"),
    ])
    book = await db_session.get(Book, "reported-book")
    book.profile_id = "child-a"
    await db_session.commit()
    assert (await send(client, {})).status_code == 422
    assert (await send(client, {"X-User-Key": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"})).status_code == 404
    assert (await send(client, {**headers, "X-Profile-Id": "other-child"})).status_code == 400
    assert (await send(client, {**headers, "X-Profile-Id": "deleted"})).status_code == 400
    assert (await send(client, {**headers, "X-Profile-Id": "child-b"})).status_code == 404
    assert (await send(client, {**headers, "X-Profile-Id": "child-a"})).status_code == 200


async def test_reports_apply_rate_limit_fail_closed(client, headers, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enforce_in_testing", True)
    monkeypatch.setattr(rate_limiter, "is_allowed", AsyncMock(return_value=(False, 0)))
    assert (await send(client, headers)).status_code == 429
    monkeypatch.setattr(rate_limiter, "is_allowed", AsyncMock(side_effect=RuntimeError()))
    assert (await send(client, headers)).status_code == 503


@pytest.mark.parametrize("path", ["/v1/library/reported-book", "/v1/users/me"])
async def test_user_erasure_removes_reports(client, headers, user_key, db_session, path):
    await seed(db_session, user_key)
    assert (await send(client, headers)).status_code == 200
    result = await client.delete(path, headers=headers)
    assert result.status_code == 200, result.text
    assert (await db_session.execute(select(ContentReport))).scalars().all() == []


async def test_database_cascade_removes_reports_without_helper(client, headers, user_key, db_session):
    await seed(db_session, user_key)
    assert (await send(client, headers)).status_code == 200
    await db_session.execute(delete(Page))
    await db_session.execute(delete(Book))
    await db_session.commit()
    assert (await db_session.execute(select(ContentReport))).scalars().all() == []


async def test_operator_review_transitions_require_resolution(client, headers, user_key, db_session):
    await seed(db_session, user_key)
    rid = (await send(client, headers)).json()["report_id"]
    await update_report_status(db_session, rid, "in_review", None)
    assert (await send(client, headers)).json()["status"] == "in_review"
    for status, resolution in [("resolved", None), ("resolved", "no_violation"),
                                ("dismissed", "content_corrected"), ("in_review", "duplicate")]:
        with pytest.raises(ValidationError):
            await update_report_status(db_session, rid, status, resolution)
    row = await update_report_status(db_session, rid, "resolved", "content_corrected")
    assert row.resolution == "content_corrected"
    assert (await send(client, headers)).json()["status"] == "resolved"


async def test_operator_cli_exports_only_requested_content_privately(client, headers, user_key, db_session, monkeypatch, tmp_path, capsys):
    await seed(db_session, user_key)
    rid = (await send(client, headers)).json()["report_id"]
    path = Path(__file__).resolve().parents[3] / "scripts" / "content_reports.py"
    spec = importlib.util.spec_from_file_location("report_cli", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    @asynccontextmanager
    async def session():
        yield db_session

    monkeypatch.setattr("src.core.database.AsyncSessionLocal", session)
    monkeypatch.setattr("src.core.database.async_engine", SimpleNamespace(dispose=AsyncMock()))
    monkeypatch.setattr("src.services.storage.media_url", lambda value: value)
    await cli.run(SimpleNamespace(command="list", status="pending", limit=30))
    output = capsys.readouterr().out
    assert rid in output and "合成" not in output and "합성" not in output and user_key not in output
    target = tmp_path / "report.json"
    args = SimpleNamespace(command="export", report_id=rid, output=target)
    await cli.run(args)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    payload = json.loads(target.read_text())
    assert payload["content"]["text"] == "합성 테스트 본문"
    assert payload["current_content_changed"] is False
    assert "합성" not in capsys.readouterr().out
    with pytest.raises(FileExistsError):
        await cli.run(args)


async def test_report_migration_matches_metadata_and_enforces_erasure():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text

    path = Path(__file__).resolve().parents[1] / "alembic/versions/d5e6f7a8b9c0_content_reports.py"
    spec = importlib.util.spec_from_file_location("content_report_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            connection.execute(text("CREATE TABLE books (id VARCHAR(60) PRIMARY KEY)"))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            inspector = inspect(connection)
            assert {column["name"] for column in inspector.get_columns("content_reports")} == set(ContentReport.__table__.columns.keys())
            foreign_key = inspector.get_foreign_keys("content_reports")[0]
            assert foreign_key["options"]["ondelete"] == "CASCADE"
            assert inspector.get_unique_constraints("content_reports")[0]["name"] == "uq_content_report_version_reason"
            connection.execute(text("INSERT INTO books (id) VALUES ('b')"))
            connection.execute(text("INSERT INTO content_reports (id, book_id, page_number, reason, content_fingerprint, status, created_at, updated_at) VALUES ('r', 'b', 0, 'other', 'fingerprint', 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            connection.execute(text("DELETE FROM books WHERE id = 'b'"))
            assert connection.execute(text("SELECT count(*) FROM content_reports")).scalar() == 0
            migration.downgrade()
            assert "content_reports" not in inspect(connection).get_table_names()
    finally:
        engine.dispose()
