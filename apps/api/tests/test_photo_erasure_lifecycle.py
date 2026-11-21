"""Photo erasure across independent requests, removed characters and late uploads.

Storage is an in-memory fake; the ordinary suite must not access child media or
provider services. Fresh sessions intentionally avoid the shared client fixture
masking missing commits.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.consent import _has_active_photo_consent
from src.core.utils import utcnow
from src.models.db import (
    Book,
    BookShare,
    Character,
    CreditTransaction,
    ImagePromptsDB,
    Job,
    Page,
    StoragePurgeTask,
    StoryDraftDB,
    UserConsent,
    UserCredits,
)
from src.routers.consent import ConsentGrantRequest, grant_consent, revoke_consent
from src.services import purge_queue
from src.services.data_deletion import prepare_character_deletion

OWNER = "550e8400-e29b-41d4-a716-446655440000"
OTHER = "660e8400-e29b-41d4-a716-446655440000"


def _sessions(db):
    return async_sessionmaker(bind=db.bind, expire_on_commit=False, autoflush=False)


def _character(identifier="photo-character", *, owner=OWNER, status="approved"):
    return Character(
        id=identifier,
        user_key=owner,
        name="합성 캐릭터",
        master_description="synthetic illustrated character",
        appearance={},
        clothing={},
        personality_traits=[],
        from_photo=True,
        avatar_status=status,
    )


def _grant(db, *, owner=OWNER):
    db.add(UserConsent(
        user_key=owner, privacy=True, photos=True,
        data_processing=True, granted=True,
    ))


async def _book(db, identifier, *, owner=OWNER, character=None, multi=False,
                photo_derived=False):
    job = Job(id=f"job-{identifier}", user_key=owner, status="done",
              photo_derived=photo_derived)
    db.add(job)
    await db.flush()
    book = Book(
        id=identifier, job_id=job.id, title="합성 동화", language="ko",
        target_age="8-10", style="watercolor", user_key=owner,
        character_id=character if not multi else None,
        character_ids=[character] if character and multi else None,
    )
    db.add(book)
    await db.flush()
    return book, job


@pytest.fixture
def fake_storage(monkeypatch):
    """Exercise actual prefix/key routing, but only against synthetic byte names."""
    from src.services import storage

    state = {"objects": set(), "calls": [], "fail": False}

    async def delete_prefix(prefix):
        state["calls"].append(("prefix", prefix))
        matches = {key for key in state["objects"] if key.startswith(prefix)}
        if state["fail"]:
            return list(matches) or [prefix + "*"]
        state["objects"].difference_update(matches)
        return []

    async def delete_keys(keys):
        state["calls"].extend(("key", key) for key in keys)
        if state["fail"]:
            return list(keys)
        state["objects"].difference_update(keys)
        return []

    monkeypatch.setattr(storage.storage_service, "delete_prefix", delete_prefix)
    monkeypatch.setattr(storage, "delete_keys", delete_keys)
    return state


@pytest.mark.asyncio
async def test_empty_photo_account_withdrawal_survives_request_close(db_session):
    _grant(db_session)
    await db_session.commit()
    sessions = _sessions(db_session)

    async with sessions() as request:
        response = await revoke_consent(db=request, user_key=OWNER)
        assert response.revoked is True

    async with sessions() as verification:
        assert await _has_active_photo_consent(verification, OWNER) is False
        consent = (await verification.execute(select(UserConsent))).scalar_one()
        assert consent.revoked_at is not None
        assert consent.granted is False


@pytest.mark.asyncio
async def test_photos_off_and_erasure_plan_are_one_transaction(db_session, monkeypatch):
    from src.routers import consent as consent_module

    _grant(db_session)
    db_session.add(_character())
    await db_session.commit()
    sessions = _sessions(db_session)

    async def cannot_prepare(*_args, **_kwargs):
        raise RuntimeError("synthetic interruption before erasure plan")

    monkeypatch.setattr(consent_module, "preserve_photo_derived_jobs", cannot_prepare)
    async with sessions() as request:
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            await grant_consent(
                request=ConsentGrantRequest(privacy=True, photos=False, data_processing=True),
                db=request, user_key=OWNER,
            )

    async with sessions() as verification:
        assert await _has_active_photo_consent(verification, OWNER) is True
        assert await verification.get(Character, "photo-character") is not None
        active = list((await verification.execute(
            select(UserConsent).where(UserConsent.revoked_at.is_(None))
        )).scalars())
        assert len(active) == 1 and active[0].photos is True


@pytest.mark.asyncio
@pytest.mark.parametrize("multi", [False, True])
async def test_character_removal_preserves_book_erasure_provenance(
    db_session, fake_storage, multi,
):
    from src.services.storage import canonical_media_url

    _grant(db_session)
    db_session.add(_character())
    await db_session.flush()
    book, job = await _book(db_session, "kept-book", character="photo-character", multi=multi)
    book.cover_image_url = canonical_media_url("jobs/job-kept-book/cover.png")
    db_session.add(Page(book_id=book.id, page_number=1, text="합성 본문",
                        image_url=canonical_media_url("jobs/job-kept-book/page.png")))
    db_session.add(BookShare(id="synthetic-share", book_id=book.id, user_key=OWNER))
    await db_session.commit()
    fake_storage["objects"].update({
        "characters/photo-character/photo.jpg",
        "characters/photo-character/avatars/v1/avatar.jpg",
        "jobs/job-kept-book/character-reference/avatar.jpg",
        "jobs/job-kept-book/cover.png", "jobs/job-kept-book/page.png",
    })
    sessions = _sessions(db_session)

    async with sessions() as request:
        character = await request.get(Character, "photo-character")
        tasks = await prepare_character_deletion(request, character)
        await request.commit()
        assert await purge_queue.run_purge_tasks(request, tasks) == []

    async with sessions() as verification:
        assert await verification.get(Character, "photo-character") is None
        assert await verification.get(Book, book.id) is not None
        assert (await verification.get(Job, job.id)).photo_derived is True
    assert not any(key.startswith("characters/") for key in fake_storage["objects"])
    assert "jobs/job-kept-book/character-reference/avatar.jpg" in fake_storage["objects"]

    async with sessions() as request:
        await revoke_consent(db=request, user_key=OWNER)
    async with sessions() as verification:
        assert await verification.get(Book, book.id) is None
        assert await verification.get(Job, job.id) is None
        assert await verification.get(BookShare, "synthetic-share") is None
    assert fake_storage["objects"] == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("remove_character", [False, True])
async def test_verified_retell_uses_current_character_link_and_keeps_approved_reference(
    db_session, fake_storage, monkeypatch, remove_character,
):
    """Deletion during review detaches the live FK without discarding a book's avatar."""
    from src.core.config import settings
    from src.models.dto import RetoldStory
    from src.routers.characters import delete_character
    from src.services import illustration_quality_edits as edits, photo_book_references
    from src.services.storage import canonical_media_url, key_from_public_url

    sessions = _sessions(db_session)
    monkeypatch.setattr(edits, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(photo_book_references, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(settings, "require_parental_consent_enabled", True)
    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    _grant(db_session)
    db_session.add(_character())
    await db_session.flush()
    book, job = await _book(
        db_session, "retell-source", character="photo-character", photo_derived=True,
    )
    reference_key = f"jobs/{job.id}/character-reference/avatar.png"
    cover_key, page_key = f"jobs/{job.id}/cover.png", f"jobs/{job.id}/page.png"
    job.character_reference_url = canonical_media_url(reference_key)
    job.character_reference_version = 1
    job.image_keys = [reference_key]
    book.cover_image_url = canonical_media_url(cover_key)
    db_session.add(Page(book_id=book.id, page_number=1, text="합성 본문",
                        image_url=canonical_media_url(page_key)))
    await db_session.commit()
    fake_storage["objects"].update({reference_key, cover_key, page_key,
                                    "characters/photo-character/avatars/v1/avatar.png"})

    async def review(**kwargs):
        # The retell has already captured its old BookSnapshot and approved avatar.
        if remove_character:
            async with sessions() as request:
                response = await delete_character("photo-character", db=request, user_key=OWNER)
                assert response["status"] == "deleted"
            async with sessions() as verification:
                assert (await verification.get(Book, book.id)).character_id is None
        return SimpleNamespace(image_urls=kwargs["image_urls"],
                               image_prompts=kwargs["image_prompts"])

    async def copy(source, key):
        assert key_from_public_url(source) in fake_storage["objects"]
        fake_storage["objects"].add(key)
        return canonical_media_url(key)

    monkeypatch.setattr(edits, "verify_and_repair_illustrations", review)
    monkeypatch.setattr(edits, "copy_object_to_new_key", copy)
    new_id = await edits.publish_verified_retell(
        source_book_id=book.id, user_key=OWNER,
        retold=RetoldStory(title="다시 쓴 합성 이야기", pages=["새 합성 본문"]),
        target_age="5-7", idempotency_key="retell-during-character-removal",
    )
    async with sessions() as verification:
        retell = await verification.get(Book, new_id)
        assert retell.character_id == (None if remove_character else "photo-character")
        assert retell.retelling_source_book_id == book.id
        retell_job = await verification.get(Job, retell.job_id)
        assert retell_job.photo_derived is True
        assert retell_job.character_reference_version == 1
        copied_key = key_from_public_url(retell_job.character_reference_url)
        assert copied_key == f"images/retell/{new_id}/character-reference.png"
        assert copied_key in retell_job.image_keys
        assert copied_key in fake_storage["objects"]
        assert (await verification.get(Job, job.id)).character_reference_url == canonical_media_url(reference_key)

    # Both books remain discoverable for erasure even if the reusable character is gone.
    async with sessions() as request:
        await revoke_consent(db=request, user_key=OWNER)
    async with sessions() as verification:
        assert await verification.get(Book, new_id) is None
        assert await verification.get(Book, book.id) is None
    assert fake_storage["objects"] == set()


@pytest.mark.asyncio
async def test_character_delete_storage_failure_is_durable_and_retryable(
    db_session, fake_storage,
):
    db_session.add(_character())
    await db_session.commit()
    fake_storage["objects"].add("characters/photo-character/photo.jpg")
    fake_storage["fail"] = True
    sessions = _sessions(db_session)

    async with sessions() as request:
        tasks = await prepare_character_deletion(
            request, await request.get(Character, "photo-character")
        )
        await request.commit()
        assert await purge_queue.run_purge_tasks(request, tasks)

    fake_storage["fail"] = False
    async with sessions() as retry:
        assert await retry.get(Character, "photo-character") is None
        pending = list((await retry.execute(select(StoragePurgeTask))).scalars())
        assert len(pending) == 1 and pending[0].status == "pending"
        assert await purge_queue.run_purge_tasks(retry, pending) == []
        assert pending[0].status == "done"
    assert fake_storage["objects"] == set()


@pytest.mark.asyncio
async def test_character_delete_rollback_preserves_provenance_and_bytes(
    db_session, fake_storage,
):
    db_session.add(_character())
    await db_session.flush()
    book, job = await _book(db_session, "rollback-book", character="photo-character")
    await db_session.commit()
    fake_storage["objects"].add("characters/photo-character/photo.jpg")
    sessions = _sessions(db_session)
    async with sessions() as request:
        await prepare_character_deletion(
            request, await request.get(Character, "photo-character")
        )
        await request.rollback()
    async with sessions() as verification:
        assert await verification.get(Character, "photo-character") is not None
        assert (await verification.get(Book, book.id)).character_id == "photo-character"
        assert (await verification.get(Job, job.id)).photo_derived is False
        assert list((await verification.execute(select(StoragePurgeTask))).scalars()) == []
    assert fake_storage["calls"] == []


@pytest.mark.asyncio
async def test_withdrawal_erases_flagged_failed_jobs_without_characters(
    db_session, fake_storage,
):
    _grant(db_session)
    db_session.add(Job(id="failed-photo-job", user_key=OWNER, status="failed",
                       photo_derived=True, image_keys=["images/legacy/failed.png"]))
    db_session.add(Job(id="text-job", user_key=OWNER, status="failed", photo_derived=False))
    db_session.add(Job(id="other-photo-job", user_key=OTHER, status="failed", photo_derived=True))
    db_session.add(UserCredits(user_key=OWNER, credits=0, total_used=1))
    db_session.add(CreditTransaction(user_key=OWNER, amount=-1, balance_after=0, transaction_type="usage",
                                     reference_id="failed-photo-job", description="synthetic"))
    await db_session.flush()
    db_session.add(StoryDraftDB(job_id="failed-photo-job", draft={"synthetic": True}))
    db_session.add(ImagePromptsDB(job_id="failed-photo-job", prompts={"synthetic": True}))
    await db_session.commit()
    fake_storage["objects"].update({
        "jobs/failed-photo-job/character-reference/avatar.jpg", "images/legacy/failed.png",
        "jobs/text-job/image.jpg", "jobs/other-photo-job/image.jpg",
    })
    sessions = _sessions(db_session)
    async with sessions() as request:
        await revoke_consent(db=request, user_key=OWNER)
    async with sessions() as verification:
        assert await verification.scalar(select(CreditTransaction.amount).where(
            CreditTransaction.reference_id == "failed-photo-job", CreditTransaction.transaction_type == "refund",
        )) == 1
        assert await verification.get(Job, "failed-photo-job") is None
        assert await verification.get(Job, "text-job") is not None
        assert await verification.get(Job, "other-photo-job") is not None
        assert list((await verification.execute(select(StoryDraftDB))).scalars()) == []
        assert list((await verification.execute(select(ImagePromptsDB))).scalars()) == []
    assert fake_storage["objects"] == {"jobs/text-job/image.jpg", "jobs/other-photo-job/image.jpg"}


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["avatar", "book"])
async def test_late_upload_after_withdrawal_is_removed_by_deferred_guard(
    db_session, fake_storage, monkeypatch, target,
):
    from src.core import database

    _grant(db_session)
    if target == "avatar":
        db_session.add(_character(status="generating"))
        prefix = "characters/photo-character/"
    else:
        db_session.add(Job(id="running-photo-job", user_key=OWNER, status="running",
                           photo_derived=True))
        prefix = "jobs/running-photo-job/"
    await db_session.commit()
    sessions = _sessions(db_session)
    monkeypatch.setattr(database, "AsyncSessionLocal", sessions)

    async with sessions() as request:
        await revoke_consent(db=request, user_key=OWNER)
    async with sessions() as verification:
        pending = list((await verification.execute(
            select(StoragePurgeTask).where(StoragePurgeTask.status == "pending")
        )).scalars())
        assert len(pending) == 1
        assert pending[0].target == prefix
        assert pending[0].attempts == 0
        pending[0].created_at = utcnow() - timedelta(minutes=16)
        await verification.commit()

    fake_storage["objects"].add(prefix + "synthetic-late-upload.jpg")
    assert await purge_queue.sweep_pending_purges() == 1
    assert fake_storage["objects"] == set()


@pytest.mark.asyncio
async def test_account_deletion_keeps_a_guard_for_inflight_avatar(
    db_session, fake_storage, monkeypatch,
):
    from src.core import database
    from src.routers.users import delete_my_data

    _grant(db_session)
    db_session.add(_character(status="generating"))
    await db_session.commit()
    sessions = _sessions(db_session)
    monkeypatch.setattr(database, "AsyncSessionLocal", sessions)
    fake_storage["objects"].add("characters/photo-character/photo.jpg")

    async with sessions() as request:
        response = await delete_my_data(db=request, user_key=OWNER, x_user_key=OWNER)
        assert response["status"] == "partial"
        assert response["purge_retry_pending"] is True
    assert fake_storage["objects"] == set()

    async with sessions() as verification:
        assert await verification.get(Character, "photo-character") is None
        pending = list((await verification.execute(
            select(StoragePurgeTask).where(StoragePurgeTask.status == "pending")
        )).scalars())
        assert len(pending) == 1
        assert pending[0].target == "characters/photo-character/"
        assert pending[0].attempts == 0
        pending[0].created_at = utcnow() - timedelta(minutes=16)
        await verification.commit()

    fake_storage["objects"].add("characters/photo-character/avatars/v1/late.jpg")
    assert await purge_queue.sweep_pending_purges() == 1
    assert fake_storage["objects"] == set()


@pytest.mark.asyncio
@pytest.mark.parametrize('flags', [
    dict(privacy=False, data_processing=True, photos=True),
    dict(privacy=True, data_processing=False, photos=True),
    dict(privacy=False, data_processing=False, photos=True),
])
@pytest.mark.parametrize('already_ineffective', [False, True])
async def test_mandatory_withdrawal_erases_shared_photo_assets(
    db_session, fake_storage, flags, already_ineffective,
):
    _grant(db_session)
    if already_ineffective:
        await db_session.flush()
        consent = await db_session.scalar(select(UserConsent).where(UserConsent.user_key == OWNER))
        consent.granted = False
        consent.privacy = False
    db_session.add(_character())
    await db_session.flush()
    book, _ = await _book(db_session, 'mandatory-withdrawal', character='photo-character', photo_derived=True)
    db_session.add(BookShare(id='withdrawn-share', book_id=book.id, user_key=OWNER))
    await db_session.commit()
    await grant_consent(ConsentGrantRequest(**flags), db=db_session, user_key=OWNER)
    assert await db_session.get(Book, 'mandatory-withdrawal') is None
    assert await db_session.get(BookShare, 'withdrawn-share') is None
    assert await db_session.get(Character, 'photo-character') is None
    assert await _has_active_photo_consent(db_session, OWNER) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("withdrawal", ["revoke", "mandatory_off", "photos_only"])
async def test_pending_text_book_consent_is_checked_after_regrant(
    db_session, fake_storage, monkeypatch, withdrawal,
):
    from unittest.mock import AsyncMock

    from src.core.config import settings
    from src.core.exceptions import AuthorizationError
    from src.services import orchestrator
    from src.services.generation_consent import post_with_consent, provider_consent_scope, require_active_book_job

    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    _grant(db_session)
    job = Job(id="job_consent_regression", user_key=OWNER, status="queued")
    db_session.add_all([job, UserCredits(user_key=OWNER, credits=2, total_used=1),
                        CreditTransaction(user_key=OWNER, amount=-1, balance_after=2, transaction_type="usage",
                                          reference_id=job.id, description="synthetic")])
    await db_session.commit()
    sessions = _sessions(db_session)
    async with sessions() as request:
        if withdrawal == "revoke":
            await revoke_consent(db=request, user_key=OWNER)
        else:
            await grant_consent(ConsentGrantRequest(
                privacy=True, photos=False, data_processing=withdrawal == "photos_only",
            ), db=request, user_key=OWNER)
    async with sessions() as request:
        await grant_consent(ConsentGrantRequest(privacy=True, photos=True, data_processing=True),
                            db=request, user_key=OWNER)

    async def authorize(db):
        await require_active_book_job(db, job.id, OWNER)

    async with sessions() as verification:
        refunds = (await verification.scalars(select(CreditTransaction.id).where(
            CreditTransaction.reference_id == job.id, CreditTransaction.transaction_type == "refund",
        ))).all()
        assert len(refunds) == (0 if withdrawal == "photos_only" else 1)

    transport = AsyncMock()
    with provider_consent_scope(authorize):
        if withdrawal == "photos_only":
            await post_with_consent(transport, "https://example.invalid/")
            transport.post.assert_awaited_once()
        else:
            with pytest.raises(AuthorizationError):
                await post_with_consent(transport, "https://example.invalid/")
            transport.post.assert_not_awaited()
            moderate = AsyncMock()
            monkeypatch.setattr(orchestrator, "moderate_input", moderate)
            await orchestrator.start_book_generation(job.id, None, OWNER)
            moderate.assert_not_awaited()
