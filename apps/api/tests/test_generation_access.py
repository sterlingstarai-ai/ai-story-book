"""Closed beta admission must stop costs without blocking existing data."""

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.core.config import settings
from src.core.exceptions import APIError
from src.core.generation_access import generation_identity_hash, require_generation_access


@pytest.mark.parametrize("mode,hashes,user,allowed", [
    ("open", "", None, True),
    ("paused", "", "invited", False),
    ("invite_only", "", "invited", False),
    ("invite_only", generation_identity_hash("invited"), "invited", True),
    ("invite_only", generation_identity_hash("invited"), "new-account", False),
    ("invite_only", generation_identity_hash("invited"), None, False),
    ("invite_only", generation_identity_hash("invited") + ",broken", "invited", False),
])
def test_admission_is_explicit_and_fail_closed(monkeypatch, mode, hashes, user, allowed):
    monkeypatch.setattr(settings, "generation_access_mode", mode)
    monkeypatch.setattr(settings, "generation_allowed_user_hashes", hashes)
    if allowed:
        require_generation_access(user)
    else:
        with pytest.raises(APIError) as exc:
            require_generation_access(user)
        assert exc.value.status_code == 503


def test_updated_invitation_config_takes_effect_after_a_cached_lookup(monkeypatch):
    monkeypatch.setattr(settings, "generation_access_mode", "invite_only")
    allowed = generation_identity_hash("invited")
    monkeypatch.setattr(settings, "generation_allowed_user_hashes", allowed)
    require_generation_access("invited")
    monkeypatch.setattr(settings, "generation_allowed_user_hashes", allowed + ",broken")
    with pytest.raises(APIError):
        require_generation_access("invited")


@pytest.mark.asyncio
async def test_uninvited_generation_does_not_consume_budget(monkeypatch):
    from src.routers import books
    monkeypatch.setattr(settings, "generation_access_mode", "invite_only")
    monkeypatch.setattr(settings, "generation_allowed_user_hashes", generation_identity_hash("invited"))
    consume = AsyncMock()
    monkeypatch.setattr(books, "consume_daily_generation_budget", consume)
    with pytest.raises(APIError):
        await books.consume_generation_budget(endpoint="books.create", user_key="rotated")
    consume.assert_not_awaited()


@pytest.mark.asyncio
async def test_paused_generation_does_not_block_library(client, headers, monkeypatch):
    monkeypatch.setattr(settings, "generation_access_mode", "paused")
    assert (await client.get("/v1/library", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_uninvited_http_create_cannot_start_a_job(client, headers, valid_book_spec, db_session, monkeypatch):
    from sqlalchemy import func, select
    from src.models.db import Job
    monkeypatch.setattr(settings, "generation_access_mode", "invite_only")
    monkeypatch.setattr(settings, "generation_allowed_user_hashes", generation_identity_hash("another-account"))
    response = await client.post("/v1/books", headers=headers, json=valid_book_spec)
    assert response.status_code == 503, response.text
    assert (await db_session.scalar(select(func.count()).select_from(Job))) == 0


@pytest.mark.asyncio
async def test_invitation_id_is_scoped_to_the_current_beta_account(client, headers, monkeypatch):
    path = "/v1/account/generation-invitation"
    monkeypatch.setattr(settings, "free_plan_first_book_trial", True)
    monkeypatch.setattr(settings, "generation_access_mode", "open")
    assert (await client.get(path, headers=headers)).status_code == 404
    monkeypatch.setattr(settings, "generation_access_mode", "invite_only")
    assert (await client.get("/v1/config/capabilities")).json()["generation_invitation_supported"] is True
    assert (await client.get(path)).status_code == 422
    legacy = {"X-User-Key": "00000000-0000-0000-0000-000000000001"}
    assert (await client.get(path, headers=legacy)).status_code == 404
    response = await client.get(path, headers=headers)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.json() == {"invitation_id": generation_identity_hash(headers["X-User-Key"])}


@pytest.mark.asyncio
async def test_recovered_device_uses_stable_invited_account(client, headers, valid_book_spec, db_session, monkeypatch):
    from src.models.db import AccountIdentity
    from src.services.account_recovery import credential_hash
    owner = headers["X-User-Key"]
    device = "asb_device_" + "x" * 43
    db_session.add(AccountIdentity(user_key=owner, device_key_hash=credential_hash(device, kind="device")))
    await db_session.commit()
    monkeypatch.setattr(settings, "generation_access_mode", "invite_only")
    monkeypatch.setattr(settings, "free_plan_first_book_trial", True)
    monkeypatch.setattr(settings, "generation_allowed_user_hashes", generation_identity_hash(owner))
    invitation = await client.get("/v1/account/generation-invitation", headers={"X-User-Key": device})
    assert invitation.json() == {"invitation_id": generation_identity_hash(owner)}
    response = await client.post("/v1/books", headers={"X-User-Key": device}, json=valid_book_spec)
    assert response.status_code == 200, response.text


def test_all_budget_callers_pass_resolved_account():
    root = Path(__file__).resolve().parents[1] / "src"
    calls = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "consume_generation_budget":
                calls.append(node)
                assert any(k.arg == "user_key" and isinstance(k.value, ast.Name) and k.value.id == "user_key" for k in node.keywords), path
    # Book, series and daily-story creation share one post-credit admission.
    assert len(calls) == 7
