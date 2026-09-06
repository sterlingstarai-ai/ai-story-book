"""Approved character references owned by a book's job, never source photos."""

import uuid

from sqlalchemy import select

from src.core.consent import require_photo_consent
from src.core.database import AsyncSessionLocal
from src.core.exceptions import APIError, AuthorizationError
from src.models.db import Book, Character, Job
from src.services.photo_processing import ensure_photo_processing_ready
from src.services.purge_queue import cancel_purge_task, enqueue_purge_keys
from src.services.storage import copy_object_to_new_key, key_from_public_url


def selected_character_ids(spec) -> list[str]:
    return list(dict.fromkeys(spec.character_ids or ([spec.character_id] if spec.character_id else [])))


async def validate_photo_book_selection(db, user_key: str, character_ids: list[str]):
    """A single photo-derived protagonist; every such selection must be approved."""
    if not character_ids:
        return None
    rows = list((await db.scalars(select(Character).where(
        Character.id.in_(character_ids), Character.user_key == user_key,
    ))).all())
    if len(rows) != len(set(character_ids)):
        raise AuthorizationError("선택한 캐릭터를 확인할 수 없습니다.")
    photos = [c for c in rows if c.from_photo]
    if not photos:
        return None
    await require_photo_consent(db, user_key)
    ensure_photo_processing_ready()
    if len(photos) != 1 or photos[0].id != character_ids[0]:
        raise APIError(400, "PHOTO_CHARACTER_SELECTION_INVALID", "사진 캐릭터 한 명을 주인공으로 선택해주세요.")
    character = photos[0]
    if character.avatar_status != "approved" or not character.avatar_url or character.avatar_version < 1:
        raise APIError(409, "CHARACTER_APPROVAL_REQUIRED", "동화 속 캐릭터의 모습을 먼저 확인해주세요.")
    if not key_from_public_url(character.avatar_url):
        raise APIError(409, "CHARACTER_REFERENCE_UNAVAILABLE", "캐릭터 그림을 불러오지 못했습니다.")
    return character


async def selection_is_photo_derived(db, user_key: str, character_ids: list[str]) -> bool:
    if not character_ids:
        return False
    return bool(await db.scalar(select(Character.id).where(
        Character.id.in_(character_ids), Character.user_key == user_key, Character.from_photo.is_(True),
    ).limit(1)))


async def existing_book_is_photo_derived(db, book) -> bool:
    job = await db.get(Job, book.job_id)
    ids = list(dict.fromkeys([*(book.character_ids or []), *([book.character_id] if book.character_id else [])]))
    return bool(job and job.photo_derived) or await selection_is_photo_derived(db, book.user_key, ids)


async def prepare_job_character_reference(job_id: str, spec, user_key: str) -> str | None:
    if spec.reference_image_base64:
        raise APIError(409, "CHARACTER_APPROVAL_REQUIRED", "사진으로 캐릭터를 만든 뒤 모습을 확인해주세요.")
    ids = selected_character_ids(spec)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if job is None or job.user_key != user_key or job.status not in {"queued", "running"}:
            raise APIError(409, "JOB_UNAVAILABLE", "진행할 수 없는 작업입니다.")
        if job.character_reference_url:
            await require_photo_consent(db, user_key)
            ensure_photo_processing_ready()
            if not key_from_public_url(job.character_reference_url):
                raise APIError(409, "CHARACTER_REFERENCE_UNAVAILABLE", "캐릭터 그림을 불러오지 못했습니다.")
            return job.character_reference_url
        character = await validate_photo_book_selection(db, user_key, ids)
        if character is None:
            if job.photo_derived:
                raise APIError(409, "CHARACTER_REFERENCE_UNAVAILABLE", "캐릭터 그림을 불러오지 못했습니다.")
            return None
        source, version = character.avatar_url, character.avatar_version
        key = f"jobs/{job_id}/character-reference/{uuid.uuid4().hex}.png"
        guards = enqueue_purge_keys(db, user_key=user_key, reason="character_reference_copy_guard", keys=[key])
        job.photo_derived = True
        await db.commit()
    # No transaction is held while object storage is contacted.
    copied = await copy_object_to_new_key(source, key)
    if not copied or key_from_public_url(copied) != key:
        raise APIError(409, "CHARACTER_REFERENCE_UNAVAILABLE", "캐릭터 그림을 불러오지 못했습니다.")
    async with AsyncSessionLocal() as db:
        from src.services.photo_lifecycle import lock_photo_account

        await lock_photo_account(db, user_key)
        job = await db.scalar(select(Job).where(Job.id == job_id, Job.user_key == user_key).with_for_update())
        if job is None or job.status not in {"queued", "running"}:
            raise APIError(409, "JOB_UNAVAILABLE", "진행할 수 없는 작업입니다.")
        await require_photo_consent(db, user_key)
        # Duplicate delivery keeps the first immutable snapshot; loser stays
        # guarded for deletion rather than replacing a reference in flight.
        if job.character_reference_url:
            return job.character_reference_url
        job.character_reference_url = copied
        job.character_reference_version = version
        job.image_keys = list(dict.fromkeys([*(job.image_keys or []), key]))
        from src.models.db import StoragePurgeTask

        for original in guards:
            guard = await db.get(StoragePurgeTask, original.id)
            if guard is not None:
                cancel_purge_task(guard)
        await db.commit()
    return copied


async def reference_for_existing_book(job_id: str, user_key: str) -> str | None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if job is None or job.user_key != user_key:
            raise APIError(409, "JOB_UNAVAILABLE", "책의 생성 정보를 확인할 수 없습니다.")
        book = await db.scalar(select(Book).where(Book.job_id == job_id, Book.user_key == user_key))
        derived = job.photo_derived or (book is not None and await existing_book_is_photo_derived(db, book))
        if not derived:
            return None
        await require_photo_consent(db, user_key)
        ensure_photo_processing_ready()
        if not job.character_reference_url or not key_from_public_url(job.character_reference_url):
            raise APIError(409, "CHARACTER_REFERENCE_UNAVAILABLE", "이 책의 확정 캐릭터 그림이 없습니다. 캐릭터 확인 후 새 책을 만들어주세요.")
        return job.character_reference_url
