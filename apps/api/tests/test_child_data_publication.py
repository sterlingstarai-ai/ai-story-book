"""A request already authenticated before erasure cannot save new child data."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.config import settings
from src.core.exceptions import AuthorizationError
from src.models.db import AccountIdentity, Character, ChildProfile, PronunciationLog, UserConsent
from src.routers import characters, profiles, pronunciation
from src.services.account_recovery import revoke_deleted_account


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["erasure", "withdrawal"])
@pytest.mark.parametrize("feature", ["text_character", "audio_pronunciation"])
async def test_provider_result_respects_newer_privacy_decision(
    client, headers, user_key, db_session, valid_character, monkeypatch, decision, feature,
):
    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    db_session.add(UserConsent(user_key=user_key, privacy=True, data_processing=True, granted=True))
    await db_session.commit()
    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def provider(*args, **kwargs):
        async with sessions() as writer:
            if decision == "erasure":
                await revoke_deleted_account(writer, user_key, user_key)
            else:
                writer.add(UserConsent(user_key=user_key, privacy=False, data_processing=False, granted=False))
            await writer.commit()
        return valid_character if feature == "text_character" else "synthetic transcript"

    if feature == "text_character":
        monkeypatch.setattr(characters.photo_character_service, "create_character_from_text", provider)
        response = await client.post("/v1/characters/from-text", headers=headers,
                                     data={"name": "토리", "age": "5", "traits": "토끼"})
        model = Character
    else:
        monkeypatch.setattr(pronunciation, "require_audio_supported", lambda: None)
        monkeypatch.setattr(pronunciation.stt_service, "transcribe_audio", provider)
        response = await client.post("/v1/pronunciation/evaluate-audio", headers=headers,
                                     data={"expected_text": "synthetic"},
                                     files={"audio_file": ("sample.wav", b"sample", "audio/wav")})
        model = PronunciationLog
    assert response.status_code == 403, response.text
    async with sessions() as observer:
        assert await observer.scalar(select(func.count()).select_from(model)) == 0
        if decision == "erasure":
            assert (await observer.get(AccountIdentity, user_key)).deleted


@pytest.mark.asyncio
async def test_profile_write_rechecks_previously_authenticated_account(db_session, user_key):
    await revoke_deleted_account(db_session, user_key, user_key)
    await db_session.commit()
    with pytest.raises(AuthorizationError):
        await profiles.create_profile(profiles.ProfileCreateRequest(name="fixture", age_band="5-7"),
                                      db=db_session, user_key=user_key)
    assert await db_session.scalar(select(func.count()).select_from(ChildProfile)) == 0
