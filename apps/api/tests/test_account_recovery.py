"""Account continuity, one-time rotation, erasure and anonymous attack boundaries."""

import secrets
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select

from src.core.config import settings
from src.core.exceptions import APIError
from src.core.generation_access import generation_identity_hash
from src.core.logging import redact_log_data
from src.core.rate_limit import rate_limiter
from src.core.utils import utcnow
from src.models.db import AccountIdentity, Book, ChildProfile, UserConsent, UserSettings
from src.services.account_recovery import credential_hash, issue_recovery_code, revoke_deleted_account
from src.services.privacy_journal import PrivacyJournal
from tests.factories import make_book_rows
from tests.test_privacy_journal_outbox import FakeStore

pytestmark = pytest.mark.asyncio


def next_device():
    return "asb_device_" + secrets.token_urlsafe(32)


async def enable(client, headers):
    response = await client.post("/v1/account/recovery-code", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["recovery_code"]


async def recover(client, code, device=None):
    device = device or next_device()
    response = await client.post(
        "/v1/account/recover", json={"recovery_code": code, "new_user_key": device}
    )
    return response, {"X-User-Key": device}


async def test_legacy_account_stays_usable_until_explicit_backup(client, headers, db_session):
    response = await client.get("/v1/account/recovery", headers=headers)
    assert response.json() == {"enabled": False, "recovery_code_created_at": None}
    assert (await client.get("/v1/account/session", headers=headers)).json() == {"status": "active"}
    assert (await db_session.execute(select(AccountIdentity))).scalars().all() == []


async def test_recovery_preserves_library_profiles_and_consent_and_revokes_old_device(
    client, headers, user_key, db_session
):
    db_session.add_all(make_book_rows([("saved-book", user_key)]))
    db_session.add(ChildProfile(id="saved-child", user_key=user_key, name="테스트"))
    db_session.add(UserSettings(user_key=user_key, language="ja"))
    db_session.add(UserConsent(user_key=user_key, privacy=True, data_processing=True, granted=True))
    await db_session.commit()
    code = await enable(client, headers)
    identity = await db_session.get(AccountIdentity, user_key, populate_existing=True)
    assert identity.recovery_code_hash == credential_hash(code, kind="recovery")
    assert code not in repr(identity.__dict__)
    response, new_headers = await recover(client, code)
    assert response.status_code == 200, response.text
    assert response.json()["recovery_code"] != code
    assert user_key not in response.text
    assert response.headers["cache-control"] == "private, no-store"

    for path in ("/v1/account/session", "/v1/library", "/v1/profiles", "/v1/consent", "/v1/settings"):
        assert (await client.get(path, headers=headers)).status_code == 401, path
        assert (await client.get(path, headers=new_headers)).status_code == 200, path
    assert (await client.get("/v1/consent", headers=new_headers)).json()["granted"] is True
    assert (await db_session.get(Book, "saved-book")).user_key == user_key
    assert (await db_session.get(ChildProfile, "saved-child")).user_key == user_key
    other_headers = {"X-User-Key": "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"}
    other = await client.get("/v1/library", headers=other_headers)
    assert "saved-book" not in other.text


async def test_backup_rotation_replaces_old_code_without_logging_out(client, headers):
    old_code = await enable(client, headers)
    new_code = await enable(client, headers)
    rejected, _ = await recover(client, old_code)
    assert rejected.status_code == 401
    assert (await client.get("/v1/account/session", headers=headers)).status_code == 200
    accepted, _ = await recover(client, new_code)
    assert accepted.status_code == 200


async def test_lost_response_can_retry_exact_pending_device_but_not_another_device(client, headers):
    code = await enable(client, headers)
    accepted, new_headers = await recover(client, code)
    assert accepted.status_code == 200
    retried, _ = await recover(client, code, new_headers["X-User-Key"])
    assert retried.status_code == 200
    assert retried.json()["recovery_code"] is None
    replayed, _ = await recover(client, code)
    assert replayed.status_code == 401
    replacement = await enable(client, new_headers)
    recovered_again, final_headers = await recover(client, replacement)
    assert recovered_again.status_code == 200
    assert (await client.get("/v1/account/session", headers=new_headers)).status_code == 401
    assert (await client.get("/v1/account/session", headers=final_headers)).status_code == 200


async def test_unknown_modern_device_never_bootstraps_legacy_account(client):
    response = await client.get("/v1/account/session", headers={"X-User-Key": next_device()})
    assert response.status_code == 401


@pytest.mark.parametrize("access_mode", ["invite_only", "open"])
async def test_store_review_pass_claims_only_reserved_private_slots(
    client, headers, user_key, db_session, monkeypatch, access_mode
):
    slots = [str(uuid.uuid4()) for _ in range(3)]
    journal = PrivacyJournal(FakeStore(), b"k" * 32)
    # A configured ordinary account must never become a claimable slot.
    db_session.add(AccountIdentity(user_key=user_key))
    db_session.add_all(make_book_rows([("ordinary-private-book", user_key)]))
    db_session.add_all(
        AccountIdentity(
            user_key=slot,
            device_key_hash=credential_hash(slot, kind="store-review-reservation"),
        ) for slot in slots[:2]
    )
    await db_session.commit()
    passcode = "ASB-R1-" + secrets.token_urlsafe(32)
    monkeypatch.setattr(settings, "generation_access_mode", access_mode)
    monkeypatch.setattr(settings, "free_plan_first_book_trial", True)
    monkeypatch.setattr(settings, "generation_allowed_user_hashes", ",".join(
        generation_identity_hash(key) for key in [user_key, *slots]
    ))
    monkeypatch.setattr(settings, "store_review_account_slots", ",".join([user_key, *slots]))
    monkeypatch.setattr(settings, "store_review_pass_hash", credential_hash(passcode, kind="store-review"))

    assert (await client.get("/v1/account/session", headers={"X-User-Key": slots[0]})).status_code == 401
    assert (await recover(client, passcode))[0].status_code == 401
    db_session.info["privacy_journal"] = journal
    first, first_device = await recover(client, passcode)
    second, second_device = await recover(client, passcode)
    assert first.status_code == second.status_code == 200
    assert first.json()["recovery_code"] != second.json()["recovery_code"]
    for device in (first_device, second_device):
        library = await client.get("/v1/library", headers=device)
        assert library.status_code == 200
        assert "ordinary-private-book" not in library.text
    first_retry, _ = await recover(client, passcode, first_device["X-User-Key"])
    assert first_retry.status_code == 200
    assert first_retry.json()["recovery_code"] is None
    assert (await recover(client, passcode))[0].status_code == 401
    assert (await recover(client, first.json()["recovery_code"]))[0].status_code == 200
    db_session.add(AccountIdentity(
        user_key=slots[-1],
        device_key_hash=credential_hash(slots[-1], kind="store-review-reservation"),
    ))
    await db_session.commit()
    assert (await recover(client, passcode, first_device["X-User-Key"]))[0].status_code == 401
    assert (await client.get("/v1/account/session", headers=second_device)).status_code == 200

    monkeypatch.setattr(settings, "generation_access_mode", "paused")
    assert (await recover(client, passcode, second_device["X-User-Key"]))[0].status_code == 401
    assert (await client.get("/v1/account/session", headers=second_device)).status_code == 200


async def test_previously_authorized_old_device_cannot_rotate_backup_after_recovery(
    client, headers, user_key, db_session
):
    code = await enable(client, headers)
    accepted, _ = await recover(client, code)
    assert accepted.status_code == 200
    with pytest.raises(APIError) as exc:
        await issue_recovery_code(db_session, user_key, user_key)
    assert exc.value.status_code == 401


async def test_recovery_does_not_overwrite_another_accounts_active_device(client, headers):
    other = {"X-User-Key": "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"}
    other_code = await enable(client, other)
    result, other_device = await recover(client, other_code)
    assert result.status_code == 200
    code = await enable(client, headers)
    rejected, _ = await recover(client, code, other_device["X-User-Key"])
    assert rejected.status_code == 401
    assert (await client.get("/v1/account/session", headers=headers)).status_code == 200
    assert (await client.get("/v1/account/session", headers=other_device)).status_code == 200
    accepted, _ = await recover(client, code)
    assert accepted.status_code == 200


async def test_account_erasure_revokes_device_and_backup_and_keeps_canonical_blocked(
    client, headers, user_key, db_session
):
    code = await enable(client, headers)
    result, new_headers = await recover(client, code)
    next_code = result.json()["recovery_code"]
    deleted = await client.delete("/v1/users/me", headers=new_headers)
    assert deleted.status_code == 200, deleted.text
    assert (await client.get("/v1/account/session", headers=headers)).status_code == 401
    assert (await client.get("/v1/account/session", headers=new_headers)).status_code == 401
    assert (await recover(client, next_code))[0].status_code == 401
    identity = await db_session.get(AccountIdentity, user_key, populate_existing=True)
    assert identity.deleted
    assert identity.device_key_hash is not None  # hashed erasure acknowledgement, never auth
    assert identity.recovery_code_hash is None
    assert identity.previous_recovery_code_hash is None


async def test_recovery_does_not_reinstate_revoked_consent(client, headers, user_key, db_session):
    db_session.add(UserConsent(
        user_key=user_key, privacy=True, data_processing=True, photos=True,
        granted=False, revoked_at=utcnow(),
    ))
    await db_session.commit()
    code = await enable(client, headers)
    result, new_headers = await recover(client, code)
    assert result.status_code == 200
    consent = await client.get("/v1/consent", headers=new_headers)
    assert consent.status_code == 200
    assert consent.json()["granted"] is False
    assert consent.json()["revoked"] is True


async def test_optional_today_identity_does_not_bypass_revocation(client, headers, user_key, monkeypatch):
    from src.services.streak import streak_service

    async def today(_db, user_key=None):
        return {
            "date": "2026-09-06", "theme": "courage", "topic": "용기",
            "book_id": "private-today-book" if user_key is not None else None,
        }

    monkeypatch.setattr(streak_service, "get_today_story", today)
    code = await enable(client, headers)
    result, new_headers = await recover(client, code)
    assert result.status_code == 200
    assert (await client.get("/v1/streak/today", headers=headers)).json()["book_id"] is None
    assert (await client.get("/v1/streak/today", headers=new_headers)).json()["book_id"] == "private-today-book"
    assert (await client.get("/v1/streak/today")).json()["book_id"] is None


async def test_previously_authorized_erasure_rolls_back_when_device_was_recovered(
    client, headers, user_key, db_session
):
    db_session.add(UserSettings(user_key=user_key, language="ja"))
    await db_session.commit()
    code = await enable(client, headers)
    result, new_headers = await recover(client, code)
    assert result.status_code == 200
    await db_session.execute(delete(UserSettings).where(UserSettings.user_key == user_key))
    with pytest.raises(APIError) as exc:
        await revoke_deleted_account(db_session, user_key, user_key)
    assert exc.value.status_code == 401
    assert (await db_session.get(UserSettings, user_key)).language == "ja"
    assert (await client.get("/v1/account/session", headers=new_headers)).status_code == 200


async def test_anonymous_recovery_attempts_are_limited_without_user_header(client):
    code = "ASB-R1-" + secrets.token_urlsafe(32)
    for _ in range(10):
        assert (await recover(client, code))[0].status_code == 401
    limited, _ = await recover(client, code)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"


async def test_recovery_fails_closed_when_attempt_counter_unavailable(client, monkeypatch):
    monkeypatch.setattr(rate_limiter, "get_redis", AsyncMock(side_effect=ConnectionError("offline")))
    response, _ = await recover(client, "ASB-R1-" + secrets.token_urlsafe(32))
    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"


async def test_validation_and_logs_do_not_echo_recovery_credentials(client):
    code = "ASB-R1-" + secrets.token_urlsafe(32)
    device = next_device()
    response = await client.post(
        "/v1/account/recover",
        json={"recovery_code": code, "new_user_key": device, "extra": code, code: "extra"},
    )
    assert response.status_code == 422
    assert code not in response.text
    assert device not in response.text
    event = redact_log_data(None, None, {"recovery_code": code, "new_user_key": device, "other": f"{code} {device}"})
    assert code not in str(event)
    assert device not in str(event)
