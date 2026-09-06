from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.config import settings
from src.core.exceptions import APIError, AuthorizationError
from src.models.db import Book, Character, Job, StoragePurgeTask, UserConsent
from src.models.dto import BookSpec
from src.services import photo_book_references as references


async def setup_photo(db, monkeypatch, valid_character, user_key, *, status="approved"):
    monkeypatch.setattr(references, "AsyncSessionLocal", async_sessionmaker(db.bind, expire_on_commit=False))
    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    c = Character(id="approved-character", user_key=user_key, from_photo=True,
                  source_image_url=None, avatar_status=status, avatar_version=1,
                  avatar_url=settings.s3_public_url + "/characters/approved-character/avatars/v1/portrait.png",
                  **valid_character)
    db.add_all([c, Job(id="photo-book-job", user_key=user_key, status="queued", photo_derived=True),
                UserConsent(user_key=user_key, privacy=True, data_processing=True, granted=True, photos=True)])
    await db.commit()
    return c


@pytest.mark.asyncio
async def test_pending_portrait_cannot_start_or_charge_for_book(client, db_session, monkeypatch, valid_character, valid_book_spec, user_key, headers):
    await setup_photo(db_session, monkeypatch, valid_character, user_key, status="preview")
    from src.routers import books

    budget = AsyncMock()
    monkeypatch.setattr(books, "consume_generation_budget", budget)
    response = await client.post("/v1/books", headers=headers, json={**valid_book_spec, "character_id": "approved-character"})
    assert response.status_code == 409
    assert "CHARACTER_APPROVAL_REQUIRED" in response.text
    budget.assert_not_awaited()


@pytest.mark.asyncio
async def test_book_job_is_photo_derived_at_enqueue(client, db_session, monkeypatch, valid_character, valid_book_spec, user_key, headers):
    await setup_photo(db_session, monkeypatch, valid_character, user_key)
    response = await client.post("/v1/books", headers=headers, json={**valid_book_spec, "character_id": "approved-character"})
    assert response.status_code == 200, response.text
    job = await db_session.get(Job, response.json()["job_id"])
    assert job.photo_derived is True


@pytest.mark.asyncio
async def test_same_approved_portrait_is_copied_once_and_survives_character_removal(db_session, monkeypatch, valid_character, valid_book_spec, user_key):
    c = await setup_photo(db_session, monkeypatch, valid_character, user_key)
    source_url = c.avatar_url
    copied = []

    async def copy(source, key):
        copied.append((source, key))
        return settings.s3_public_url + "/" + key

    monkeypatch.setattr(references, "copy_object_to_new_key", copy)
    spec = BookSpec(**valid_book_spec, character_id=c.id)
    first = await references.prepare_job_character_reference("photo-book-job", spec, user_key)
    assert await references.prepare_job_character_reference("photo-book-job", spec, user_key) == first
    assert len(copied) == 1 and copied[0][0] == source_url
    assert "/jobs/photo-book-job/character-reference/" in first
    await db_session.execute(delete(Character).where(Character.id == c.id))
    job = await db_session.get(Job, "photo-book-job", populate_existing=True)
    assert job.character_reference_version == 1 and job.photo_derived
    job.status = "done"
    db_session.add(Book(id="photo-book", job_id=job.id, user_key=user_key, title="합성 동화", language="ko", target_age="5-7", style="watercolor"))
    await db_session.commit()
    assert await references.reference_for_existing_book(job.id, user_key) == first
    assert set((await db_session.scalars(select(StoragePurgeTask.status))).all()) == {"cancelled"}


@pytest.mark.asyncio
async def test_deleted_job_cannot_publish_reference_and_copy_remains_guarded(db_session, monkeypatch, valid_character, valid_book_spec, user_key):
    c = await setup_photo(db_session, monkeypatch, valid_character, user_key)

    async def copy_then_delete(source, key):
        await db_session.execute(delete(Job).where(Job.id == "photo-book-job"))
        await db_session.commit()
        return settings.s3_public_url + "/" + key

    monkeypatch.setattr(references, "copy_object_to_new_key", copy_then_delete)
    with pytest.raises(APIError):
        await references.prepare_job_character_reference("photo-book-job", BookSpec(**valid_book_spec, character_id=c.id), user_key)
    guards = list((await db_session.scalars(select(StoragePurgeTask))).all())
    assert len(guards) == 1 and guards[0].status == "pending"


@pytest.mark.asyncio
async def test_legacy_photo_book_never_falls_back_to_source_photo(db_session, monkeypatch, valid_character, user_key):
    c = await setup_photo(db_session, monkeypatch, valid_character, user_key)
    job = await db_session.get(Job, "photo-book-job")
    job.status = "done"
    job.photo_derived = False  # Legacy job, still linked to a photo character.
    db_session.add(Book(id="legacy-photo-book", job_id=job.id, user_key=user_key, character_id=c.id,
                        title="합성 동화", language="ko", target_age="5-7", style="watercolor"))
    await db_session.commit()
    with pytest.raises(APIError) as caught:
        await references.reference_for_existing_book(job.id, user_key)
    assert caught.value.error_code == "CHARACTER_REFERENCE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_reference_lookup_enforces_owner_and_current_consent(db_session, monkeypatch, valid_character, user_key):
    c = await setup_photo(db_session, monkeypatch, valid_character, user_key)
    with pytest.raises(AuthorizationError):
        await references.validate_photo_book_selection(db_session, "another-owner", [c.id])
    await db_session.execute(delete(UserConsent).where(UserConsent.user_key == user_key))
    await db_session.commit()
    with pytest.raises(AuthorizationError):
        await references.validate_photo_book_selection(db_session, user_key, [c.id])
