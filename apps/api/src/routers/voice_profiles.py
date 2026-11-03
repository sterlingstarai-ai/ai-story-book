"""
Voice Profiles Router
가족 목소리 프로필 CRUD + 동의 철회
"""

from __future__ import annotations

import uuid
import asyncio
from datetime import timedelta
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.core.database import get_db
from src.core.audio_feature import require_voice_profiles_supported
from src.core.dependencies import get_user_key
from src.core.exceptions import InternalServerError, NotFoundError, ValidationError
from src.core.utils import utcnow
from src.models.db import StoragePurgeTask, VoiceProfile
from src.services.storage import (
    key_from_public_url, storage_service, media_url, canonical_media_url, voice_sample_prefix,
)
from src.services.purge_queue import (UNATTEMPTED_GRACE_SECONDS, cancel_purge_task,
                                      enqueue_purge_keys, run_purge_tasks)
from src.services.privacy_journal_transaction import prepare_transaction_event, publish_committed_event
from src.services.photo_lifecycle import lock_photo_account

router = APIRouter()
logger = structlog.get_logger()
_MAX_SAMPLE_AUDIO_BYTES = 15 * 1024 * 1024
_VOICE_UPLOAD_GUARD = 'voice_sample_upload_guard'


def _consume_upload_result(task):
    try:
        task.exception()
    except BaseException:
        pass


async def _lock_voice_upload_guard(db, *, user_key: str, key: str, uploading=False):
    guard = await db.scalar(select(StoragePurgeTask).where(
        StoragePurgeTask.user_key == user_key,
        StoragePurgeTask.reason == _VOICE_UPLOAD_GUARD,
        StoragePurgeTask.kind == 'keys', StoragePurgeTask.target == key,
    ).order_by(StoragePurgeTask.id.desc()).limit(1).with_for_update())
    expected_status = 'failed' if uploading else 'pending'
    if (guard is None or guard.status != expected_status or guard.attempts != 0
            or guard.created_at is None
            or (uploading and guard.last_error != 'upload_completion_unknown')
            or (not uploading and guard.created_at <= utcnow() - timedelta(seconds=UNATTEMPTED_GRACE_SECONDS))):
        raise ValidationError('음성 샘플이 만료되었습니다. 다시 업로드해주세요.')
    return guard


async def _claim_voice_upload(db, *, user_key: str, url: str):
    key = key_from_public_url(url)
    if key and key.startswith(voice_sample_prefix(user_key)):
        guard = await _lock_voice_upload_guard(db, user_key=user_key, key=key)
        cancel_purge_task(guard)


class VoiceProfileCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    relationship: Optional[str] = Field(default=None, max_length=30)
    sample_audio_url: str = Field(min_length=8, max_length=4096)
    provider_voice_id: Optional[str] = Field(default=None, max_length=120)
    consented: bool = False


class VoiceProfileUpdateRequest(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=40)
    relationship: Optional[str] = Field(default=None, max_length=30)
    sample_audio_url: Optional[str] = Field(default=None, min_length=8, max_length=4096)
    provider_voice_id: Optional[str] = Field(default=None, max_length=120)
    consented: Optional[bool] = None
    active: Optional[bool] = None


def _normalize_required_label(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValidationError("라벨은 공백일 수 없습니다.")
    return normalized


def _normalize_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_required_url(value: str, *, user_key: str) -> str:
    """샘플 오디오 URL 정규화 + **호출자 소유 prefix 소속 검증**(IDOR 봉인).

    이 URL은 나중에 `key_from_public_url`로 역산되어 그대로 삭제 대상이 된다. 소속을
    검증하지 않으면 임의의 우리 버킷 객체(타 사용자의 아동 사진·책 이미지)를 URL로 지정한 뒤
    프로필을 지워 **임의 객체 삭제 프리미티브**를 얻는다. 업로드 엔드포인트가 쓰는
    `voice-samples/{user_key}/` 하위만 허용한다(외부 호스트 URL은 역산 불가라 파기 대상 아님).
    """
    normalized = value.strip()
    if not normalized:
        raise ValidationError("샘플 오디오 URL은 공백일 수 없습니다.")

    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationError("유효한 샘플 오디오 URL이 필요합니다.")

    key = key_from_public_url(normalized)
    if key is not None and not key.startswith((voice_sample_prefix(user_key), f"voice-samples/{user_key}/")):
        raise ValidationError(
            "샘플 오디오 URL은 본인이 업로드한 파일이어야 합니다.",
        )
    return canonical_media_url(key) if key else normalized


def _serialize(profile: VoiceProfile) -> dict:
    sample_url = profile.sample_audio_url
    key = key_from_public_url(sample_url)
    if key and key.startswith(f"voice-samples/{profile.user_key}/"):
        # Legacy paths contain the full account credential. Keep them for deletion,
        # but never issue a new download URL exposing that credential.
        sample_url = ""
    return {
        "id": profile.id,
        "label": profile.label,
        "relationship": profile.relationship,
        "sample_audio_url": media_url(sample_url),
        "provider_voice_id": profile.provider_voice_id,
        "consented": profile.consented,
        "active": profile.active,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def _audio_extension(content_type: Optional[str], filename: Optional[str]) -> str:
    if filename:
        lowered = filename.lower()
        for ext in (".m4a", ".mp3", ".wav", ".aac", ".ogg", ".webm"):
            if lowered.endswith(ext):
                return ext

    mapping = {
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mp4": ".m4a",
        "audio/aac": ".aac",
        "audio/ogg": ".ogg",
        "audio/webm": ".webm",
    }
    if content_type:
        return mapping.get(content_type.lower(), ".m4a")
    return ".m4a"


@router.post("/upload-sample")
async def upload_voice_sample(
    sample: UploadFile = File(..., description="음성 샘플 파일"),
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    require_voice_profiles_supported()
    if not sample.content_type or not sample.content_type.startswith("audio/"):
        raise ValidationError("오디오 파일만 업로드 가능합니다.")

    data = await sample.read(_MAX_SAMPLE_AUDIO_BYTES + 1)
    if not data:
        raise ValidationError("빈 파일은 업로드할 수 없습니다.")
    if len(data) > _MAX_SAMPLE_AUDIO_BYTES:
        raise ValidationError("샘플 오디오는 15MB 이하여야 합니다.")

    ext = _audio_extension(sample.content_type, sample.filename)
    object_key = f"{voice_sample_prefix(user_key)}{utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex}{ext}"

    # The task survives a crash or failure, and remains pending until a voice
    # profile claims the sample in the same transaction that publishes it.
    await lock_photo_account(db, user_key)
    guard = enqueue_purge_keys(db, user_key=user_key, reason=_VOICE_UPLOAD_GUARD, keys=[object_key])[0]
    # If the process or its PUT dies, completion is unknown. Keep this out of
    # the automatic sweep and alert until the outcome is independently known.
    guard.status = 'failed'
    guard.last_error = 'upload_completion_unknown'
    await db.flush()
    await db.commit()
    try:
        # Keep both account and guard row locked while the storage call is in
        # flight; the cleanup sweep skips locked guards on PostgreSQL.
        await lock_photo_account(db, user_key)
        guard = await _lock_voice_upload_guard(db, user_key=user_key, key=object_key, uploading=True)
        upload_task = asyncio.create_task(storage_service.upload_bytes(
            data=data, key=object_key, content_type=sample.content_type or "audio/mp4", bounded_upload=True,
        ))
        try:
            done, _ = await asyncio.wait({upload_task}, timeout=90)
            if not done:
                raise TimeoutError('Voice upload deadline expired')
            url = upload_task.result()
        finally:
            if not upload_task.done():
                # Cancelling a task cannot prove that its S3 thread stopped.
                # The precommitted failed guard continues to alert in that case.
                upload_task.cancel()
                upload_task.add_done_callback(_consume_upload_result)
        if key_from_public_url(url) != object_key:
            raise ValidationError('음성 샘플 저장을 확인하지 못했습니다.')
        # Only a completed, verified response transitions to timed cleanup.
        guard.status = 'pending'
        guard.last_error = None
        await db.commit()
        if guard.created_at <= utcnow() - timedelta(seconds=UNATTEMPTED_GRACE_SECONDS):
            raise ValidationError('음성 샘플이 만료되었습니다. 다시 업로드해주세요.')
    except Exception:
        await db.rollback()
        raise InternalServerError(
            "샘플 오디오 업로드에 실패했습니다. 잠시 후 다시 시도해주세요."
        ) from None

    return {
        "sample_audio_url": media_url(url),
        "content_type": sample.content_type,
        "size_bytes": len(data),
    }


@router.get("")
async def list_voice_profiles(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    result = await db.execute(
        select(VoiceProfile)
        .where(VoiceProfile.user_key == user_key)
        .order_by(VoiceProfile.created_at.desc())
    )
    profiles = result.scalars().all()
    return {
        "profiles": [_serialize(profile) for profile in profiles],
    }


@router.post("")
async def create_voice_profile(
    request: VoiceProfileCreateRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    require_voice_profiles_supported()
    await lock_photo_account(db, user_key)
    count_result = await db.execute(
        select(VoiceProfile.id).where(VoiceProfile.user_key == user_key)
    )
    if len(count_result.all()) >= 5:
        raise ValidationError("음성 프로필은 최대 5개까지 생성할 수 있습니다.")

    if not request.consented:
        raise ValidationError("가족 목소리 등록에는 보호자 동의가 필요합니다.")

    normalized_label = _normalize_required_label(request.label)
    normalized_relationship = _normalize_optional_text(request.relationship)
    normalized_sample_url = _normalize_required_url(
        request.sample_audio_url, user_key=user_key
    )
    normalized_provider_voice_id = _normalize_optional_text(request.provider_voice_id)
    await _claim_voice_upload(db, user_key=user_key, url=normalized_sample_url)

    profile = VoiceProfile(
        id=f"voice_{utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}",
        user_key=user_key,
        label=normalized_label,
        relationship=normalized_relationship,
        sample_audio_url=normalized_sample_url,
        provider_voice_id=normalized_provider_voice_id,
        consented=True,
        active=True,
    )
    journal_event = await prepare_transaction_event(db, user_key=user_key, action='voice_changed', resource_id=profile.id)
    db.add(profile)
    await db.commit()
    await publish_committed_event(db, journal_event)
    await db.refresh(profile)
    logger.info(
        "Voice profile created",
        profile_id=profile.id,
        active=profile.active,
        consented=profile.consented,
    )
    return _serialize(profile)


@router.patch("/{profile_id}")
async def update_voice_profile(
    profile_id: str,
    request: VoiceProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    await lock_photo_account(db, user_key)
    result = await db.execute(
        select(VoiceProfile).where(
            VoiceProfile.id == profile_id,
            VoiceProfile.user_key == user_key,
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise NotFoundError("음성 프로필", profile_id)

    if (request.sample_audio_url is not None or request.provider_voice_id is not None
            or request.active is True or request.consented is True):
        require_voice_profiles_supported()

    # R1-7: 파기 대상은 **변경 적용 전**의 원본이다. 예전에는 setattr 루프 뒤에
    # `profile.sample_audio_url`을 읽어 purge_url을 잡았다 — sample_audio_url 교체와
    # consented=false가 같은 요청에 오면 **방금 올린 새 파일을 지우고 옛 샘플은 남겼다**.
    # 교체만 하는 요청에서도 옛 샘플이 영구 고아로 남았다(가족 음성 = biometric-adjacent PII).
    previous_sample_url = profile.sample_audio_url

    data = request.model_dump(exclude_none=True)
    if "label" in data:
        data["label"] = _normalize_required_label(str(data["label"]))
    if "sample_audio_url" in data:
        data["sample_audio_url"] = _normalize_required_url(
            str(data["sample_audio_url"]), user_key=user_key
        )
        if data['sample_audio_url'] != previous_sample_url and request.consented is not False:
            await _claim_voice_upload(db, user_key=user_key, url=data['sample_audio_url'])
    if "relationship" in data:
        data["relationship"] = _normalize_optional_text(data["relationship"])
    if "provider_voice_id" in data:
        data["provider_voice_id"] = _normalize_optional_text(data["provider_voice_id"])

    if request.active is True:
        consented_after_update = profile.consented
        if "consented" in data:
            consented_after_update = bool(data["consented"])
        if not consented_after_update:
            raise ValidationError("동의가 없는 음성 프로필은 활성화할 수 없습니다.")

    journal_event = None
    if request.consented is False:
        journal_event = await prepare_transaction_event(db, user_key=user_key, action='voice_revoke', resource_id=profile_id)
    elif any(field in data for field in ('sample_audio_url', 'provider_voice_id', 'active', 'consented')):
        # Deliberately omit audio, URLs and provider identifiers from history.
        # Replay must reject an unresolved changed voice rather than guess it.
        journal_event = await prepare_transaction_event(db, user_key=user_key, action='voice_changed', resource_id=profile_id)
    for key, value in data.items():
        setattr(profile, key, value)

    # 동의 철회 시 활성 해제 + 공급자 음성 키 제거
    # S1: 철회 의미는 revoke-consent와 동일하므로 원본 오디오도 같은 계약으로 파기한다.
    if request.consented is False:
        profile.active = False
        profile.provider_voice_id = None
        profile.sample_audio_url = ""

    # 파기 대상 = '더 이상 어떤 행도 참조하지 않게 된' 원본(철회로 비워졌거나 새 URL로 교체됨).
    purge_url: Optional[str] = None
    if previous_sample_url and profile.sample_audio_url != previous_sample_url:
        purge_url = previous_sample_url

    purge_tasks = _enqueue_sample_purge(db, user_key, purge_url)
    await db.commit()
    await publish_committed_event(db, journal_event)
    await db.refresh(profile)

    if purge_url:
        failed_keys = await run_purge_tasks(db, purge_tasks)
        if failed_keys:
            logger.warning(
                "Voice sample purge failures on consent withdrawal",
                profile_id=profile.id,
                failed_key_count=len(failed_keys),
            )
    logger.info(
        "Voice profile updated",
        profile_id=profile.id,
        active=profile.active,
        consented=profile.consented,
    )
    result = _serialize(profile)
    if purge_url:
        result["purge_retry_pending"] = bool(failed_keys)
    return result



def _enqueue_sample_purge(db: AsyncSession, user_key: str, sample_audio_url: Optional[str]):
    """Persist deletion intent in the same transaction that drops the sample reference."""
    key = key_from_public_url(sample_audio_url)
    return enqueue_purge_keys(db, user_key=user_key, reason="voice_sample_removal", keys=[key] if key else [])


@router.post("/{profile_id}/revoke-consent")
async def revoke_voice_profile_consent(
    profile_id: str,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    await lock_photo_account(db, user_key)
    result = await db.execute(
        select(VoiceProfile).where(
            VoiceProfile.id == profile_id,
            VoiceProfile.user_key == user_key,
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise NotFoundError("음성 프로필", profile_id)

    journal_event = await prepare_transaction_event(db, user_key=user_key, action='voice_revoke', resource_id=profile_id)

    # S1: 동의 철회는 삭제보다 강한 파기 트리거다(PIPA 철회-파기 의무). 원본 오디오를
    # 남기면 '철회했는데 목소리는 그대로'가 된다 — 파기 후 행의 참조도 끊는다.
    sample_audio_url = profile.sample_audio_url

    profile.consented = False
    profile.active = False
    profile.provider_voice_id = None
    profile.sample_audio_url = ""
    purge_tasks = _enqueue_sample_purge(db, user_key, sample_audio_url)
    await db.commit()
    await publish_committed_event(db, journal_event)
    await db.refresh(profile)

    failed_keys = await run_purge_tasks(db, purge_tasks)
    if failed_keys:
        logger.warning(
            "Voice sample purge failures on consent revoke",
            profile_id=profile.id,
            failed_key_count=len(failed_keys),
        )

    logger.info(
        "Voice profile consent revoked",
        profile_id=profile.id,
    )

    return {
        "status": "partial" if failed_keys else "success",
        "profile": _serialize(profile),
        "purge_retry_pending": bool(failed_keys),
    }


@router.delete("/{profile_id}")
async def delete_voice_profile(
    profile_id: str,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    await lock_photo_account(db, user_key)
    result = await db.execute(
        select(VoiceProfile).where(
            VoiceProfile.id == profile_id,
            VoiceProfile.user_key == user_key,
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise NotFoundError("음성 프로필", profile_id)

    journal_event = await prepare_transaction_event(db, user_key=user_key, action='voice_delete', resource_id=profile_id)

    # S1: 행을 지우면 sample_audio_url이 사라져 키 역산이 불가능해진다(영구 고아).
    # 계정 삭제·캐릭터 삭제와 동일 순서 — 삭제 전 캡처, 커밋 후 파기.
    sample_audio_url = profile.sample_audio_url

    await db.delete(profile)
    purge_tasks = _enqueue_sample_purge(db, user_key, sample_audio_url)
    await db.commit()
    await publish_committed_event(db, journal_event)

    failed_keys = await run_purge_tasks(db, purge_tasks)
    if failed_keys:
        logger.warning(
            "Voice sample delete failures",
            profile_id=profile_id,
            failed_key_count=len(failed_keys),
        )

    logger.info(
        "Voice profile deleted",
        profile_id=profile_id,
    )

    return {
        "status": "partial" if failed_keys else "success",
        "profile_id": profile_id,
        "purge_retry_pending": bool(failed_keys),
    }
