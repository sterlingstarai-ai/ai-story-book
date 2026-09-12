"""Versioned, bounded photo/drawing portraits with explicit parental approval.

Only a committed Character version may claim provider work. Each attempt owns a
purge guard before producing media; a deleted/revoked/expired version can never
publish its late result. Approval preserves the portrait and queues our temporary
source copy for deletion. Source URLs never leave through the character DTO.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from io import BytesIO
import time
import uuid
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
import structlog
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from src.core.config import settings
from src.core.consent import require_photo_consent
from src.core.database import AsyncSessionLocal
from src.core.exceptions import APIError, AuthorizationError, NotFoundError, ValidationError
from src.core.utils import utcnow
from src.models.db import AccountIdentity, Character, StoragePurgeTask, UserConsent
from src.models.dto import CreateCharacterRequest, ImagePrompt
from src.services.image import generate_image, image_storage_scope, portrait_conversion_scope
from src.services.image_request_budget import image_request_budget
from src.services.photo_character import photo_character_service
from src.services.purge_queue import cancel_purge_task, enqueue_purge_keys, enqueue_purge_prefix, run_purge_tasks
from src.services.storage import get_object_bytes, key_from_public_url, media_url, storage_service

logger = structlog.get_logger()

MAX_AVATAR_ATTEMPTS = 3
AVATAR_SOURCE_TTL_HOURS = 24
AVATAR_TIMEOUT_SECONDS = 300
AVATAR_QUEUE_TIMEOUT_SECONDS = 600
MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_SOURCE_PIXELS = 16_000_000
_local_tasks: set[asyncio.Task] = set()

_PORTRAIT_MEDIA = {
    "watercolor": "Hand-drawn watercolor: pencil contours, flat color washes, textured paper",
    "cartoon": "Hand-drawn cartoon: clean expressive contours, simple flat colors",
    "storybook_crayon": "Hand-drawn crayon: visible wax strokes, playful shapes, textured paper",
    "3d": "Stylized 3D animation: sculpted toy-like shapes, matte colors",
    "pixel": "Pixel art: visible pixel blocks, simple shapes, a limited color palette",
    "oil_painting": "Storybook oil painting: visible brushstrokes, simple painted shapes",
    "claymation": "Clay animation: handmade clay shapes, matte colors, visible craft texture",
}


def build_avatar_prompt(values: dict, *, style: str, version: int) -> ImagePrompt:
    """Build the production portrait prompt without truncating identity or rules.

    ``values`` has already passed CreateCharacterRequest validation. Its bounded
    identity/age/outfit fields and the fixed medium descriptions fit the image
    contract in full; unrelated analysis prose cannot push instructions out.
    A source photo supplies appearance, never the rendering medium.
    """
    medium = _PORTRAIT_MEDIA.get(style.strip().lower(), _PORTRAIT_MEDIA["watercolor"])
    outfit = "; ".join(f"{field}: {values['clothing'][field]}"
                       for field in ("top", "bottom", "shoes", "accessories"))
    return ImagePrompt(
        page=0, seed=version, aspect_ratio="3:4",
        positive_prompt=(
            "Reinterpret the reference as one clearly illustrated picture-book character. "
            f"{medium}. Use simplified face shapes and age-appropriate proportions. "
            "Full body, front three-quarter view, intact hands/feet, blank warm-white background. "
            f"Appearance traits: {values['master_description']} "
            f"Age: {values['appearance']['age_visual']}. "
            f"Fixed outfit: {outfit}. Keep garment colors and recognizable hair/face traits."
        ),
        negative_prompt=(
            "photograph, photorealistic face or body, photo paintover, watercolor filter on a photo, "
            "realistic skin pores, camera lighting, lens blur, copied photo background, "
            "new costume, recolored garments, scene props, text, letters, labels, watermark, logo, "
            "duplicate character, collage, distorted anatomy, unsafe depiction"
        ),
        guidance_notes="parent_approval_portrait",
    )


def _image_dimensions_error() -> ValidationError:
    return ValidationError(
        "사진 해상도가 너무 높습니다. 1,600만 화소 이하로 크기를 줄인 뒤 다시 선택해주세요.",
        details={"reason": "image_dimensions_exceeded", "max_pixels": MAX_SOURCE_PIXELS},
    )


def normalize_character_image(data: bytes) -> bytes:
    """Decode a bounded still image, apply orientation, and emit metadata-free JPEG."""
    if not data or len(data) > MAX_SOURCE_BYTES:
        raise ValidationError("사진은 10MB 이하의 이미지여야 합니다.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"} or getattr(source, "n_frames", 1) != 1:
                    raise ValueError("unsupported still image")
                if source.width * source.height > MAX_SOURCE_PIXELS:
                    raise _image_dimensions_error()
                source.load()
                oriented = ImageOps.exif_transpose(source)
                oriented.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                rgba = oriented.convert("RGBA")
                # A fresh image does not inherit EXIF, XMP, ICC, comments or GPS.
                clean = Image.new("RGB", rgba.size, "white")
                clean.paste(rgba, mask=rgba.getchannel("A"))
                output = BytesIO()
                clean.save(output, format="JPEG", quality=85)
                return output.getvalue()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise _image_dimensions_error() from None
    except (UnidentifiedImageError, OSError, ValueError):
        raise ValidationError("사진 파일을 읽을 수 없습니다. JPEG, PNG, WebP 사진을 다시 선택해주세요.") from None


def avatar_conflict(code: str = "AVATAR_VERSION_CONFLICT") -> APIError:
    return APIError(409, code, "캐릭터의 최신 상태를 확인한 뒤 다시 시도해주세요.")


def _expired(character: Character) -> bool:
    return bool(character.avatar_expires_at and character.avatar_expires_at <= utcnow())


def can_retry_avatar(character: Character) -> bool:
    source_key = key_from_public_url(character.source_image_url)
    return bool(
        character.from_photo and character.avatar_status in {"preview", "failed", "not_required"}
        and (character.avatar_attempts or 0) < MAX_AVATAR_ATTEMPTS
        and source_key and source_key.startswith(f"characters/{character.id}/")
        and "/avatars/" not in source_key
        and character.avatar_expires_at and not _expired(character)
    )


def avatar_response_fields(character: Character) -> dict:
    status = character.avatar_status or "not_required"
    if character.from_photo and status == "not_required":
        status = "failed"  # Legacy photos were never parent-approved.
    if status != "approved" and _expired(character):
        status = "failed"
    url = character.avatar_url if status in {"preview", "approved"} else None
    return {
        "from_photo": bool(character.from_photo),
        "avatar_status": status,
        "avatar_url": media_url(url) if url else None,
        "avatar_version": character.avatar_version or 0,
        "avatar_retry_allowed": can_retry_avatar(character),
    }


async def _owned_character(db, character_id: str, user_key: str, *, lock=False) -> Character:
    query = select(Character).where(Character.id == character_id)
    if lock:
        query = query.with_for_update()
    character = await db.scalar(query)
    if character is None:
        raise NotFoundError("캐릭터", character_id)
    if character.user_key != user_key:
        raise AuthorizationError()
    return character


async def _account_and_consent(db, user_key: str, *, lock=False) -> None:
    if lock:
        from src.services.photo_lifecycle import lock_photo_account

        await lock_photo_account(db, user_key)
    query = select(AccountIdentity.deleted).where(AccountIdentity.user_key == user_key)
    if await db.scalar(query):
        raise AuthorizationError()
    await require_photo_consent(db, user_key)


async def _consent_version(db, user_key: str) -> int | None:
    return await db.scalar(select(UserConsent.id).where(
        UserConsent.user_key == user_key, UserConsent.revoked_at.is_(None),
    ).order_by(UserConsent.created_at.desc(), UserConsent.id.desc()).limit(1))


async def create_image_character(
    db, *, image_data: bytes, name: str | None, style: str,
    source_kind: str, user_key: str, idempotency_key: str | None,
) -> Character:
    from src.services.photo_processing import ensure_photo_processing_ready
    from src.routers.books import consume_generation_budget

    await _account_and_consent(db, user_key)
    consent_version = await _consent_version(db, user_key)
    if idempotency_key:
        existing = await db.scalar(select(Character).where(
            Character.user_key == user_key, Character.idempotency_key == idempotency_key,
        ))
        if existing is not None:
            return existing
    if name is not None and (not name.strip() or len(name.strip()) > 40):
        raise ValidationError("캐릭터 이름은 1~40자로 입력해주세요.")
    if not style.strip() or len(style.strip()) > 40 or source_kind not in {"photo", "drawing"}:
        raise ValidationError("캐릭터 그림 설정을 확인해주세요.")
    clean = await asyncio.to_thread(normalize_character_image, image_data)
    ensure_photo_processing_ready()
    await consume_generation_budget(endpoint=f"characters.from_{source_kind}", user_key=user_key)
    character_id = f"char_{utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
    source_key = f"characters/{character_id}/{source_kind}.jpg"
    guard = enqueue_purge_prefix(db, user_key=user_key, reason="character_source_upload_guard",
                                 prefix=f"characters/{character_id}/")
    await db.commit()
    try:
        source_url = await storage_service.upload_bytes(clean, source_key, "image/jpeg")
        if key_from_public_url(source_url) != source_key:
            raise ValidationError("사진 저장을 완료하지 못했습니다.")
        await _account_and_consent(db, user_key, lock=True)
        if consent_version != await _consent_version(db, user_key):
            raise AuthorizationError("사진 사용 동의가 변경되었습니다. 사진을 다시 선택해주세요.")
        now = utcnow()
        character = Character(
            id=character_id, name=name.strip() if name else "캐릭터",
            master_description="A storybook character portrait is being prepared.",
            appearance={field: "알 수 없음" for field in ("age_visual", "face", "hair", "skin", "body")},
            clothing={field: "없음" for field in ("top", "bottom", "shoes", "accessories")},
            personality_traits=["친절한"], visual_style_notes=f"{style.strip()} illustration",
            user_key=user_key, from_photo=True, source_image_url=source_url,
            idempotency_key=idempotency_key, avatar_status="generating", avatar_version=1,
            avatar_attempts=1, avatar_requested_at=now,
            avatar_expires_at=now + timedelta(hours=AVATAR_SOURCE_TTL_HOURS),
            avatar_style=style.strip(), avatar_source_kind=source_kind,
        )
        db.add(character)
        cancel_purge_task(guard)
        await db.commit()
        await db.refresh(character)
        return character
    except IntegrityError:
        await db.rollback()
        if idempotency_key:
            winner = await db.scalar(select(Character).where(
                Character.user_key == user_key, Character.idempotency_key == idempotency_key,
            ))
            if winner is not None:
                return winner
        raise
    except Exception:
        # The precommitted prefix guard survives a failed publication.
        await db.rollback()
        raise


async def approved_avatar_reference(character_ids: list[str], user_key: str) -> str | None:
    """Return only an owned, approved primary portrait; never an original photo.

    A secondary photo character cannot silently disappear from a one-image
    reference request. Until multi-reference binding exists it is rejected.
    """
    ids = list(dict.fromkeys(cid for cid in character_ids if cid))
    if not ids:
        return None
    async with AsyncSessionLocal() as db:
        characters = list((await db.scalars(select(Character).where(Character.id.in_(ids)))).all())
        by_id = {c.id: c for c in characters}
        if any(cid not in by_id or by_id[cid].user_key != user_key for cid in ids):
            raise AuthorizationError()
        derived = [by_id[cid] for cid in ids if by_id[cid].from_photo]
        if not derived:
            return None
        await _account_and_consent(db, user_key)
        if len(derived) != 1 or derived[0].id != ids[0]:
            raise avatar_conflict("AVATAR_MULTIPLE_REFERENCES_UNSUPPORTED")
        character = derived[0]
        prefix = f"characters/{character.id}/avatars/v{character.avatar_version}/"
        key = key_from_public_url(character.avatar_url)
        if (character.avatar_status != "approved" or not character.avatar_version
                or not key or not key.startswith(prefix)):
            raise avatar_conflict("AVATAR_APPROVAL_REQUIRED")
        return character.avatar_url


async def approve_character_avatar(db, character_id: str, version: int, user_key: str) -> Character:
    await _account_and_consent(db, user_key, lock=True)
    character = await _owned_character(db, character_id, user_key, lock=True)
    if version != character.avatar_version:
        raise avatar_conflict()
    if character.avatar_status == "approved":
        return character  # Same-version double tap is idempotent.
    key = key_from_public_url(character.avatar_url)
    prefix = f"characters/{character.id}/avatars/v{version}/"
    if (not character.from_photo or character.avatar_status != "preview" or _expired(character)
            or not key or not key.startswith(prefix)):
        raise avatar_conflict("AVATAR_NOT_READY")
    source_key = key_from_public_url(character.source_image_url)
    tasks = enqueue_purge_keys(db, user_key=user_key, reason="avatar_source_approved", keys=[source_key])
    result = await db.execute(update(Character).where(
        Character.id == character_id, Character.user_key == user_key,
        Character.avatar_status == "preview", Character.avatar_version == version,
        Character.avatar_expires_at > utcnow(),
    ).values(avatar_status="approved", avatar_approved_at=utcnow(), source_image_url=None,
             avatar_error_code=None, avatar_expires_at=None))
    if result.rowcount != 1:
        await db.rollback()
        raise avatar_conflict()
    await db.commit()
    if tasks:
        await run_purge_tasks(db, tasks)  # Failed deletion remains durable/pending.
    await db.refresh(character)
    return character


async def regenerate_character_avatar(db, character_id: str, version: int, user_key: str) -> Character:
    from src.services.photo_processing import ensure_photo_processing_ready
    from src.routers.books import consume_generation_budget

    await _account_and_consent(db, user_key, lock=True)
    character = await _owned_character(db, character_id, user_key, lock=True)
    if version != character.avatar_version:
        raise avatar_conflict()
    if not can_retry_avatar(character):
        raise avatar_conflict("AVATAR_RETRY_UNAVAILABLE")
    ensure_photo_processing_ready()
    await consume_generation_budget(endpoint="characters.avatar_regenerate", user_key=user_key)
    previous_key = key_from_public_url(character.avatar_url)
    result = await db.execute(update(Character).where(
        Character.id == character_id, Character.user_key == user_key,
        Character.avatar_version == version,
        Character.avatar_status.in_(["preview", "failed", "not_required"]),
        Character.avatar_attempts < MAX_AVATAR_ATTEMPTS,
        Character.avatar_expires_at > utcnow(),
        Character.source_image_url.isnot(None),
    ).values(avatar_status="generating", avatar_url=None, avatar_version=version + 1,
             avatar_attempts=Character.avatar_attempts + 1, avatar_requested_at=utcnow(),
             avatar_started_at=None, avatar_error_code=None))
    if result.rowcount != 1:
        await db.rollback()
        raise avatar_conflict()
    enqueue_purge_keys(db, user_key=user_key, reason="avatar_replaced_preview", keys=[previous_key])
    await db.commit()
    await db.refresh(character)
    return character


def _description_values(data: dict, requested_name: str, style: str) -> dict:
    """Normalize known photo/drawing shape, then enforce the owned character DTO."""
    appearance = data.get("appearance") or {}
    clothing = data.get("clothing") or {}

    def text(value, default="알 수 없음"):
        if isinstance(value, list):
            value = ", ".join(str(v).strip() for v in value if str(v).strip())
        return str(value).strip() if value is not None and str(value).strip() else default

    features = appearance.get("distinctive_features") or []
    normalized = {
        "age_visual": text(appearance.get("age_visual")),
        "face": text(appearance.get("face") or ", ".join(str(v) for v in features[:2])),
        "hair": text(appearance.get("hair") or " ".join(
            text(appearance.get(field), "") for field in ("hair_color", "hair_style"))),
        "skin": text(appearance.get("skin") or appearance.get("skin_tone")),
        "body": text(appearance.get("body") or appearance.get("body_type")),
    }
    request = CreateCharacterRequest(
        name=requested_name, master_description=data.get("master_description"),
        appearance=normalized,
        clothing={field: text(clothing.get(field), "없음") for field in ("top", "bottom", "shoes", "accessories")},
        personality_traits=data.get("personality_traits") or ["친절한"],
        visual_style_notes=data.get("visual_style_notes") or f"{style} illustration",
        distinctive_features=[str(v) for v in features[:10]] or None,
    )
    return request.model_dump()


async def _mark_avatar_failed(character_id: str, version: int, code: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(update(Character).where(
            Character.id == character_id, Character.avatar_version == version,
            Character.avatar_status == "generating",
        ).values(avatar_status="failed", avatar_error_code=code))
        await db.commit()


async def _avatar_attempt(character_id: str, version: int, user_key: str) -> bool:
    from src.services.photo_processing import ensure_photo_processing_ready

    ensure_photo_processing_ready()
    prefix = f"characters/{character_id}/avatars/v{version}/"
    async with AsyncSessionLocal() as db:
        await _account_and_consent(db, user_key, lock=True)
        result = await db.execute(update(Character).where(
            Character.id == character_id, Character.user_key == user_key,
            Character.avatar_version == version, Character.avatar_status == "generating",
            Character.avatar_started_at.is_(None), Character.avatar_expires_at > utcnow(),
        ).values(avatar_started_at=utcnow()))
        if result.rowcount != 1:
            await db.rollback()
            return False
        character = await db.get(Character, character_id)
        source_url, name = character.source_image_url, character.name
        style, kind = character.avatar_style or "watercolor", character.avatar_source_kind or "photo"
        guard = enqueue_purge_prefix(db, user_key=user_key, reason="avatar_attempt_guard", prefix=prefix)
        await db.commit()
        guard_id = guard.id

    key = key_from_public_url(source_url)
    if not key or not key.startswith(f"characters/{character_id}/") or "/avatars/" in key:
        raise avatar_conflict("AVATAR_SOURCE_UNAVAILABLE")
    source, _mime = await get_object_bytes(key)
    clean = normalize_character_image(source)
    # Also normalize legacy sources before any provider sees their bytes.
    normalized_source_key = f"{prefix}source.jpg"
    normalized_source_url = await storage_service.upload_bytes(clean, normalized_source_key, "image/jpeg")
    if key_from_public_url(normalized_source_url) != normalized_source_key:
        raise avatar_conflict("AVATAR_SOURCE_UNAVAILABLE")
    ensure_photo_processing_ready()
    analyzer = (photo_character_service.create_character_from_drawing if kind == "drawing"
                else photo_character_service.create_character_from_photo)
    data = await analyzer(image_data=clean, user_name=name, style=style)
    values = _description_values(data, name, style)
    async with AsyncSessionLocal() as db:
        await _account_and_consent(db, user_key)
        current = await db.get(Character, character_id)
        if (current is None or current.user_key != user_key or current.avatar_version != version
                or current.avatar_status != "generating" or _expired(current)):
            return False
    prompt = build_avatar_prompt(values, style=style, version=version)
    ensure_photo_processing_ready()
    with (image_storage_scope(prefix), portrait_conversion_scope(),
          image_request_budget(1, time.monotonic() + AVATAR_TIMEOUT_SECONDS)):
        url = await generate_image(prompt, reference_image_url=normalized_source_url)
    avatar_key = key_from_public_url(url)
    if not avatar_key or not avatar_key.startswith(prefix) or "placeholder" in url:
        raise avatar_conflict("AVATAR_IMAGE_UNAVAILABLE")
    from src.services.avatar_quality import verify_avatar_illustration

    await verify_avatar_illustration(url)
    async with AsyncSessionLocal() as db:
        await _account_and_consent(db, user_key, lock=True)
        result = await db.execute(update(Character).where(
            Character.id == character_id, Character.user_key == user_key,
            Character.avatar_version == version, Character.avatar_status == "generating",
            Character.avatar_expires_at > utcnow(),
        ).values(**values, avatar_status="preview", avatar_url=url, avatar_error_code=None))
        if result.rowcount != 1:
            await db.rollback()
            return False  # The precommitted guard will delete the late output.
        cancel_purge_task(await db.get(StoragePurgeTask, guard_id))
        source_tasks = enqueue_purge_keys(db, user_key=user_key, reason="avatar_attempt_source_complete", keys=[normalized_source_key])
        await db.commit()
        await run_purge_tasks(db, source_tasks)
    return True


async def generate_character_avatar(character_id: str, version: int, user_key: str) -> bool:
    """One paid image attempt. No hidden retry or replacement of approved media."""
    try:
        return await asyncio.wait_for(_avatar_attempt(character_id, version, user_key), AVATAR_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        await _mark_avatar_failed(character_id, version, "AVATAR_INTERRUPTED")
        raise
    except Exception as exc:
        # Never persist provider payloads, image URLs or descriptions in diagnostics.
        logger.warning("Character avatar attempt failed", character_id=character_id,
                       version=version, error_type=type(exc).__name__)
        await _mark_avatar_failed(character_id, version, "AVATAR_GENERATION_FAILED")
        return False


async def dispatch_character_avatar(character_id: str, version: int, user_key: str) -> None:
    """Dispatch committed work; duplicate queue deliveries cannot duplicate paid work."""
    if settings.testing:
        return
    if settings.use_celery:
        from src.services.tasks import generate_character_avatar_task
        try:
            await asyncio.wait_for(asyncio.to_thread(
                generate_character_avatar_task.delay, character_id, version, user_key,
            ), timeout=10)
        except Exception:
            # Publication can be ambiguous. Keep the version queued; the sweep
            # republishes and the worker CAS prevents a duplicate image charge.
            logger.warning("Character avatar dispatch pending", character_id=character_id, version=version)
        return
    task = asyncio.create_task(generate_character_avatar(character_id, version, user_key))
    _local_tasks.add(task)
    task.add_done_callback(_finish_local_task)


def _finish_local_task(task: asyncio.Task) -> None:
    _local_tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.warning("Local character avatar task failed", error_type=type(task.exception()).__name__)


async def sweep_character_avatars(limit: int = 100) -> int:
    """Recover missed dispatch, fail abandoned attempts, expire unapproved sources."""
    now = utcnow()
    queued = []
    transitioned = 0
    async with AsyncSessionLocal() as db:
        rows = list((await db.scalars(select(Character).where(
            Character.from_photo.is_(True), Character.avatar_status != "approved",
            Character.avatar_expires_at.isnot(None),
            or_(Character.avatar_status == "generating", Character.avatar_expires_at <= now),
        ).order_by(Character.avatar_requested_at.asc()).limit(limit))).all())
        for character in rows:
            if _expired(character):
                result = await db.execute(update(Character).where(
                    Character.id == character.id, Character.avatar_status != "approved",
                    Character.avatar_expires_at <= now,
                ).values(avatar_status="failed", avatar_error_code="AVATAR_SOURCE_EXPIRED",
                         source_image_url=None, avatar_url=None, avatar_expires_at=None))
                if result.rowcount != 1:
                    continue
                enqueue_purge_prefix(db, user_key=character.user_key, reason="avatar_source_expired",
                                     prefix=f"characters/{character.id}/")
                transitioned += 1
            elif character.avatar_status == "generating":
                started = character.avatar_started_at
                requested = character.avatar_requested_at or character.created_at
                if ((started and started <= now - timedelta(seconds=AVATAR_TIMEOUT_SECONDS + 30))
                        or (started is None and requested <= now - timedelta(seconds=AVATAR_QUEUE_TIMEOUT_SECONDS))):
                    result = await db.execute(update(Character).where(
                        Character.id == character.id, Character.avatar_status == "generating",
                        Character.avatar_version == character.avatar_version,
                        # A worker can claim this version after our SELECT.
                        # Recheck its current lease before failing a stale queue row.
                        or_(
                            Character.avatar_started_at <= now - timedelta(seconds=AVATAR_TIMEOUT_SECONDS + 30),
                            and_(
                                Character.avatar_started_at.is_(None),
                                func.coalesce(Character.avatar_requested_at, Character.created_at)
                                <= now - timedelta(seconds=AVATAR_QUEUE_TIMEOUT_SECONDS),
                            ),
                        ),
                    ).values(avatar_status="failed", avatar_error_code="AVATAR_INTERRUPTED"))
                    transitioned += result.rowcount
                elif started is None:
                    queued.append((character.id, character.avatar_version, character.user_key))
        await db.commit()
    for args in queued:
        await dispatch_character_avatar(*args)
    return transitioned
