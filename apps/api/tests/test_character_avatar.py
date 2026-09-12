"""Deterministic portrait lifecycle; no child photos, providers or object store."""

import asyncio
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import APIError, ValidationError
from src.core.utils import utcnow
from src.models.db import Character, StoragePurgeTask
from src.services import character_avatar as avatars
from src.services import image as image_service
from src.services import storage


def source_image(*, exif=False):
    image = Image.new("RGB", (80, 40), "blue")
    output = BytesIO()
    metadata = Image.Exif()
    if exif:
        metadata[274] = 6
        metadata[270] = "private photo metadata"
        metadata[34853] = {1: "N", 2: (1.0, 2.0, 3.0)}
    image.save(output, format="JPEG", exif=metadata)
    return output.getvalue()


def _url(key):
    return f"{settings.s3_public_url.rstrip('/')}/{key}"


@pytest.fixture
def avatar_io(monkeypatch):
    monkeypatch.setattr(settings, "photo_analysis_provider", "mock")
    monkeypatch.setattr(settings, "image_provider", "mock")
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "testing", True)
    objects = {}
    calls = {"analysis": 0, "image": 0, "reference": [], "prompts": [], "conversion_modes": [], "objects": objects}

    async def upload(data, key, content_type="image/jpeg"):
        objects[key] = (data, content_type)
        return _url(key)

    async def get(key):
        return objects[key]

    async def delete(keys):
        for key in keys:
            objects.pop(key, None)
        return []

    async def delete_prefix(prefix):
        return await delete([key for key in objects if key.startswith(prefix)])

    async def analyze(**_kwargs):
        calls["analysis"] += 1
        return {
            "master_description": "A friendly fictional child with short dark hair and a blue shirt.",
            "appearance": {"face": "round face", "hair": "short dark hair", "skin": "warm",
                           "age_visual": "young child", "body": "small", "distinctive_features": ["round glasses"]},
            "clothing": {"top": "blue shirt", "bottom": "yellow trousers", "shoes": "green", "accessories": "none"},
            "personality_traits": ["kind"], "visual_style_notes": "watercolor",
        }

    async def generate(_prompt, reference_image_url=None):
        calls["image"] += 1
        calls["reference"].append(reference_image_url)
        calls["prompts"].append(_prompt)
        calls["conversion_modes"].append(image_service._portrait_conversion.get())
        key = image_service._make_image_key("mock", "png")
        return await upload(source_image(), key, "image/jpeg")

    monkeypatch.setattr(storage.storage_service, "upload_bytes", upload)
    monkeypatch.setattr(storage.storage_service, "delete_prefix", delete_prefix)
    monkeypatch.setattr(storage, "delete_keys", delete)
    monkeypatch.setattr(avatars, "get_object_bytes", get)
    monkeypatch.setattr(avatars, "generate_image", generate)
    monkeypatch.setattr(avatars.photo_character_service, "create_character_from_photo", analyze)
    monkeypatch.setattr(avatars.photo_character_service, "create_character_from_drawing", analyze)
    monkeypatch.setattr(avatars, "media_url", lambda url: f"{url}?signed=1" if url else None)
    return calls


async def _upload(client, headers, *, route="from-photo", key="portrait-attempt", payload=None):
    field = "drawing" if route == "from-drawing" else "photo"
    response = await client.post(
        f"/v1/characters/{route}", headers={**headers, "X-Idempotency-Key": key},
        data={"name": "가상 주인공", "style": "watercolor"},
        files={field: ("source.jpg", payload or source_image(exif=True), "image/jpeg")},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _preview(client, headers, avatar_io, user_key):
    body = await _upload(client, headers)
    assert await avatars.generate_character_avatar(body["character_id"], 1, user_key)
    return body["character_id"]


def test_normalize_applies_orientation_and_removes_metadata():
    clean = avatars.normalize_character_image(source_image(exif=True))
    with Image.open(BytesIO(clean)) as image:
        assert image.format == "JPEG"
        assert image.size == (40, 80)
        assert not image.getexif()
        assert "exif" not in image.info and "icc_profile" not in image.info
    assert b"private photo metadata" not in clean


@pytest.mark.parametrize("style", list(avatars._PORTRAIT_MEDIA))
def test_portrait_prompt_keeps_maximum_identity_and_clothing_without_truncation(style):
    values = {
        "master_description": "I" * 400,
        "appearance": {"age_visual": "A" * 40},
        "clothing": {field: field[0].upper() * 80 for field in ("top", "bottom", "shoes", "accessories")},
    }
    built = avatars.build_avatar_prompt(values, style=style, version=2)
    assert len(built.positive_prompt) <= 1200
    assert values["master_description"] in built.positive_prompt
    assert values["appearance"]["age_visual"] in built.positive_prompt
    for field, value in values["clothing"].items():
        assert f"{field}: {value}" in built.positive_prompt
    assert avatars._PORTRAIT_MEDIA[style] in built.positive_prompt
    assert built.positive_prompt.endswith("Keep garment colors and recognizable hair/face traits.")
    assert "watercolor filter on a photo" in built.negative_prompt
    assert built.seed == 2


@pytest.mark.parametrize("style", ["realistic", "photograph", "invented photo filter style"])
def test_portrait_rendering_is_an_illustration_even_for_incompatible_style(style):
    values = {"master_description": "A fictional child with short black hair.",
              "appearance": {"age_visual": "school-age"},
              "clothing": {field: "blue" for field in ("top", "bottom", "shoes", "accessories")}}
    built = avatars.build_avatar_prompt(values, style=style, version=1)
    assert avatars._PORTRAIT_MEDIA["watercolor"] in built.positive_prompt
    assert style not in built.positive_prompt


@pytest.mark.parametrize(
    "data", [b"", b"not an image", b"\x89PNG\r\n\x1a\n", b"x" * (10 * 1024 * 1024 + 1)],
    ids=["empty", "non-image", "truncated-png", "over-10mb-limit"],
)
def test_normalize_rejects_invalid_input(data):
    with pytest.raises(ValidationError):
        avatars.normalize_character_image(data)


@pytest.mark.parametrize("height,allowed", [(4000, True), (4001, False)])
def test_normalize_dimension_boundary_has_specific_resolution_error(height, allowed):
    source = BytesIO()
    Image.new("L", (4000, height), 128).save(source, format="PNG")
    if allowed:
        with Image.open(BytesIO(avatars.normalize_character_image(source.getvalue()))) as clean:
            assert max(clean.size) <= 1024
    else:
        with pytest.raises(ValidationError) as caught:
            avatars.normalize_character_image(source.getvalue())
        assert caught.value.status_code == 400
        assert caught.value.error_code == "VALIDATION_ERROR"
        assert caught.value.details == {
            "reason": "image_dimensions_exceeded", "max_pixels": 16_000_000
        }
        assert "해상도가 너무 높습니다" in caught.value.message
        assert "읽을 수 없습니다" not in caught.value.message


def test_normalize_downsizes_and_flattens_alpha():
    image = Image.new("RGBA", (2000, 1000), (255, 0, 0, 0))
    output = BytesIO()
    image.save(output, format="PNG")
    with Image.open(BytesIO(avatars.normalize_character_image(output.getvalue()))) as clean:
        assert clean.size == (1024, 512)
        assert clean.mode == "RGB"
        assert clean.getpixel((1, 1)) == (255, 255, 255)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["from-photo", "from-drawing"])
async def test_upload_persists_generating_and_returns_no_source(client, headers, db_session, avatar_io, route):
    body = await _upload(client, headers, route=route)
    assert body["from_photo"] is True
    assert body["avatar_status"] == "generating"
    assert body["avatar_version"] == 1
    assert body["avatar_url"] is None
    assert body["avatar_retry_allowed"] is False
    assert "source_image_url" not in body
    assert avatar_io["analysis"] == avatar_io["image"] == 0
    row = await db_session.get(Character, body["character_id"])
    assert row.avatar_attempts == 1
    assert row.avatar_expires_at > utcnow() + timedelta(hours=23)
    source = avatar_io["objects"][storage.key_from_public_url(row.source_image_url)][0]
    assert b"private photo metadata" not in source


@pytest.mark.asyncio
async def test_duplicate_upload_reuses_committed_version(client, headers, avatar_io):
    first = await _upload(client, headers)
    second = await _upload(client, headers)
    assert first["character_id"] == second["character_id"]
    assert second["avatar_version"] == 1
    assert len(avatar_io["objects"]) == 1
    assert avatar_io["analysis"] == avatar_io["image"] == 0


@pytest.mark.asyncio
async def test_worker_claim_and_redelivery_only_generate_once(client, headers, user_key, db_session, avatar_io):
    body = await _upload(client, headers)
    cid = body["character_id"]
    results = await asyncio.gather(
        avatars.generate_character_avatar(cid, 1, user_key),
        avatars.generate_character_avatar(cid, 1, user_key),
    )
    assert sorted(results) == [False, True]
    assert avatar_io["analysis"] == avatar_io["image"] == 1
    assert avatar_io["conversion_modes"] == [True]
    assert not image_service._portrait_conversion.get()
    assert "clearly illustrated picture-book character" in avatar_io["prompts"][0].positive_prompt
    row = await db_session.get(Character, cid)
    await db_session.refresh(row)
    assert row.avatar_status == "preview"
    assert avatars.avatar_response_fields(row)["avatar_url"].endswith("?signed=1")
    assert avatars.avatar_response_fields(row)["avatar_retry_allowed"] is True
    assert not await avatars.generate_character_avatar(cid, 1, user_key)
    assert avatar_io["image"] == 1


@pytest.mark.asyncio
async def test_approval_purges_source_and_freezes_reference(client, headers, user_key, db_session, avatar_io):
    cid = await _preview(client, headers, avatar_io, user_key)
    first = await client.post(f"/v1/characters/{cid}/avatar/approve", headers=headers, json={"version": 1})
    assert first.status_code == 200, first.text
    assert first.json()["avatar_status"] == "approved"
    assert not first.json()["avatar_retry_allowed"]
    row = await db_session.get(Character, cid)
    await db_session.refresh(row)
    assert row.source_image_url is None
    assert row.avatar_expires_at is None
    assert all(not key.endswith("/photo.jpg") and not key.endswith("/source.jpg") for key in avatar_io["objects"])
    reference = await avatars.approved_avatar_reference([cid], user_key)
    assert reference == row.avatar_url
    assert "/avatars/v1/" in reference
    duplicate = await client.post(f"/v1/characters/{cid}/avatar/approve", headers=headers, json={"version": 1})
    assert duplicate.status_code == 200
    forbidden = await client.post(f"/v1/characters/{cid}/avatar/regenerate", headers=headers, json={"version": 1})
    assert forbidden.status_code == 409
    assert avatar_io["image"] == 1


@pytest.mark.asyncio
async def test_stale_approval_and_regeneration_do_not_replace_preview(client, headers, user_key, avatar_io):
    cid = await _preview(client, headers, avatar_io, user_key)
    for action in ("approve", "regenerate"):
        response = await client.post(f"/v1/characters/{cid}/avatar/{action}", headers=headers, json={"version": 0})
        assert response.status_code == 409
    assert avatar_io["image"] == 1


@pytest.mark.asyncio
async def test_total_attempt_limit_is_three(client, headers, user_key, avatar_io):
    cid = await _preview(client, headers, avatar_io, user_key)
    for version in (1, 2):
        response = await client.post(f"/v1/characters/{cid}/avatar/regenerate", headers=headers, json={"version": version})
        assert response.status_code == 200, response.text
        assert response.json()["avatar_version"] == version + 1
        assert response.json()["avatar_status"] == "generating"
        assert await avatars.generate_character_avatar(cid, version + 1, user_key)
    exhausted = await client.post(f"/v1/characters/{cid}/avatar/regenerate", headers=headers, json={"version": 3})
    assert exhausted.status_code == 409
    assert avatar_io["image"] == 3
    approved = await client.post(f"/v1/characters/{cid}/avatar/approve", headers=headers, json={"version": 3})
    assert approved.status_code == 200


@pytest.mark.asyncio
async def test_unapproved_reference_fails_closed(client, headers, user_key, avatar_io):
    body = await _upload(client, headers)
    with pytest.raises(APIError) as exc:
        await avatars.approved_avatar_reference([body["character_id"]], user_key)
    assert exc.value.error_code == "AVATAR_APPROVAL_REQUIRED"


@pytest.mark.asyncio
async def test_other_owner_cannot_approve_regenerate_or_get_reference(client, headers, user_key, avatar_io):
    cid = await _preview(client, headers, avatar_io, user_key)
    other = {"X-User-Key": "550e8400-e29b-41d4-a716-446655449999"}
    for action in ("approve", "regenerate"):
        response = await client.post(f"/v1/characters/{cid}/avatar/{action}", headers=other, json={"version": 1})
        assert response.status_code == 403
    with pytest.raises(APIError) as exc:
        await avatars.approved_avatar_reference([cid], "550e8400-e29b-41d4-a716-446655449999")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_multiple_photo_references_are_explicitly_rejected(client, headers, user_key, avatar_io):
    first = await _upload(client, headers, key="first")
    second = await _upload(client, headers, key="second")
    with pytest.raises(APIError) as exc:
        await avatars.approved_avatar_reference([first["character_id"], second["character_id"]], user_key)
    assert exc.value.error_code == "AVATAR_MULTIPLE_REFERENCES_UNSUPPORTED"


@pytest.mark.asyncio
async def test_generation_failure_keeps_retry_and_durable_guard(client, headers, user_key, db_session, avatar_io, monkeypatch):
    body = await _upload(client, headers)
    monkeypatch.setattr(avatars, "generate_image", AsyncMock(side_effect=RuntimeError("provider failure")))
    assert not await avatars.generate_character_avatar(body["character_id"], 1, user_key)
    row = await db_session.get(Character, body["character_id"])
    await db_session.refresh(row)
    assert row.avatar_status == "failed"
    assert avatars.avatar_response_fields(row)["avatar_retry_allowed"]
    guard = await db_session.scalar(select(StoragePurgeTask).where(StoragePurgeTask.reason == "avatar_attempt_guard"))
    assert guard.status == "pending"


@pytest.mark.asyncio
async def test_expired_unapproved_source_is_queued_for_deletion(client, headers, db_session, avatar_io):
    body = await _upload(client, headers)
    row = await db_session.get(Character, body["character_id"])
    row.avatar_expires_at = utcnow() - timedelta(seconds=1)
    await db_session.commit()
    assert await avatars.sweep_character_avatars() == 1
    await db_session.refresh(row)
    assert row.avatar_status == "failed"
    assert row.source_image_url is None
    assert not avatars.avatar_response_fields(row)["avatar_retry_allowed"]
    assert await db_session.scalar(select(StoragePurgeTask.id).where(StoragePurgeTask.reason == "avatar_source_expired"))


@pytest.mark.asyncio
async def test_lost_worker_is_failed_without_automatic_paid_retry(client, headers, db_session, avatar_io):
    body = await _upload(client, headers)
    row = await db_session.get(Character, body["character_id"])
    row.avatar_started_at = utcnow() - timedelta(seconds=avatars.AVATAR_TIMEOUT_SECONDS + 60)
    await db_session.commit()
    assert await avatars.sweep_character_avatars() == 1
    await db_session.refresh(row)
    assert row.avatar_status == "failed"
    assert row.avatar_attempts == 1
    assert avatar_io["analysis"] == avatar_io["image"] == 0


@pytest.mark.asyncio
async def test_deleted_during_generation_cannot_publish_late_avatar(client, headers, user_key, db_session, avatar_io, monkeypatch):
    body = await _upload(client, headers)
    original_generate = avatars.generate_image

    async def generate_and_delete(prompt, reference_image_url=None):
        url = await original_generate(prompt, reference_image_url)
        async with avatars.AsyncSessionLocal() as session:
            row = await session.get(Character, body["character_id"])
            await session.delete(row)
            await session.commit()
        return url

    monkeypatch.setattr(avatars, "generate_image", generate_and_delete)
    assert not await avatars.generate_character_avatar(body["character_id"], 1, user_key)
    assert await db_session.scalar(select(Character.id).where(Character.id == body["character_id"])) is None
    guard = await db_session.scalar(select(StoragePurgeTask).where(StoragePurgeTask.reason == "avatar_attempt_guard"))
    assert guard.status == "pending"


@pytest.mark.asyncio
async def test_invalid_photo_rejected_before_storage_or_provider(client, headers, avatar_io):
    response = await client.post("/v1/characters/from-photo", headers=headers,
                                 files={"photo": ("fake.jpg", b"not an image", "image/jpeg")})
    assert response.status_code == 400
    assert not avatar_io["objects"]
    assert avatar_io["analysis"] == avatar_io["image"] == 0


@pytest.mark.asyncio
async def test_photo_consent_is_required_for_approval(client, headers, user_key, avatar_io, monkeypatch):
    cid = await _preview(client, headers, avatar_io, user_key)
    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    response = await client.post(f"/v1/characters/{cid}/avatar/approve", headers=headers, json={"version": 1})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_failed_portrait_quality_never_becomes_preview(client, headers, user_key, db_session, avatar_io, monkeypatch):
    from src.services import avatar_quality

    body = await _upload(client, headers)
    monkeypatch.setattr(avatar_quality, "verify_avatar_illustration", AsyncMock(side_effect=RuntimeError("quality rejected")))
    assert not await avatars.generate_character_avatar(body["character_id"], 1, user_key)
    row = await db_session.get(Character, body["character_id"])
    await db_session.refresh(row)
    assert row.avatar_status == "failed"
    assert row.avatar_url is None
    assert avatar_io["image"] == 1
    assert await db_session.scalar(select(StoragePurgeTask.id).where(
        StoragePurgeTask.reason == "avatar_attempt_guard", StoragePurgeTask.status == "pending",
    ))


@pytest.mark.asyncio
async def test_source_upload_cannot_survive_revoke_and_regrant(client, headers, db_session, avatar_io, monkeypatch):
    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    consent = {"privacy": True, "photos": True, "data_processing": True}
    assert (await client.post("/v1/consent", headers=headers, json=consent)).status_code == 200
    upload = storage.storage_service.upload_bytes

    async def revoke_during_upload(data, key, content_type="image/jpeg"):
        url = await upload(data, key, content_type)
        assert (await client.post("/v1/consent/revoke", headers=headers)).status_code == 200
        assert (await client.post("/v1/consent", headers=headers, json=consent)).status_code == 200
        return url

    monkeypatch.setattr(storage.storage_service, "upload_bytes", revoke_during_upload)
    response = await client.post("/v1/characters/from-photo", headers=headers,
                                 files={"photo": ("source.jpg", source_image(), "image/jpeg")})
    assert response.status_code == 403
    assert await db_session.scalar(select(Character.id)) is None
    assert avatar_io["analysis"] == avatar_io["image"] == 0
    assert await db_session.scalar(select(StoragePurgeTask.id).where(
        StoragePurgeTask.reason == "character_source_upload_guard", StoragePurgeTask.status == "pending",
    ))


@pytest.mark.asyncio
async def test_approval_retains_durable_failed_source_deletion(client, headers, user_key, db_session, avatar_io, monkeypatch):
    cid = await _preview(client, headers, avatar_io, user_key)

    async def fail_delete(keys):
        return keys

    monkeypatch.setattr(storage, "delete_keys", fail_delete)
    response = await client.post(f"/v1/characters/{cid}/avatar/approve", headers=headers, json={"version": 1})
    assert response.status_code == 200
    assert response.json()["avatar_status"] == "approved"
    assert not response.json()["avatar_retry_allowed"]
    row = await db_session.get(Character, cid)
    await db_session.refresh(row)
    assert row.source_image_url is None
    task = await db_session.scalar(select(StoragePurgeTask).where(StoragePurgeTask.reason == "avatar_source_approved"))
    assert task.status == "pending"
    assert task.attempts == 1


@pytest.mark.asyncio
async def test_active_worker_timeout_is_measured_from_claim(client, headers, db_session, avatar_io):
    body = await _upload(client, headers)
    row = await db_session.get(Character, body["character_id"])
    row.avatar_requested_at = utcnow() - timedelta(seconds=avatars.AVATAR_QUEUE_TIMEOUT_SECONDS + 1)
    row.avatar_started_at = utcnow() - timedelta(seconds=10)
    await db_session.commit()
    assert await avatars.sweep_character_avatars() == 0
    await db_session.refresh(row)
    assert row.avatar_status == "generating"


@pytest.mark.asyncio
async def test_sweep_rechecks_claim_after_reading_stale_queue_snapshot(
    client, headers, db_session, avatar_io, monkeypatch,
):
    body = await _upload(client, headers)
    row = await db_session.get(Character, body["character_id"])
    row.avatar_requested_at = utcnow() - timedelta(seconds=avatars.AVATAR_QUEUE_TIMEOUT_SECONDS + 1)
    await db_session.commit()
    original_scalars = AsyncSession.scalars

    async def scalars_then_claim(db, statement, *args, **kwargs):
        result = await original_scalars(db, statement, *args, **kwargs)
        rows = result.all()
        assert rows[0].avatar_started_at is None
        # Deterministically model a claim committed between the sweep SELECT and
        # its conditional UPDATE. Retain the old ORM snapshot intentionally.
        await db.execute(update(Character).where(Character.id == row.id).values(
            avatar_started_at=utcnow(),
        ).execution_options(synchronize_session=False))
        return SimpleNamespace(all=lambda: rows)

    monkeypatch.setattr(AsyncSession, "scalars", scalars_then_claim)
    assert await avatars.sweep_character_avatars() == 0
    await db_session.refresh(row)
    assert row.avatar_status == "generating"
    assert row.avatar_started_at is not None
