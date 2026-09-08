"""Seed historical stored voices without reopening unsupported collection APIs."""
import uuid

from src.models.db import VoiceProfile


async def seed_voice_profile(db, user_key, *, sample_audio_url, **values):
    profile = VoiceProfile(id=f"legacy-{uuid.uuid4().hex}", user_key=user_key,
        sample_audio_url=sample_audio_url, **{
            "label": "Parent", "consented": True, "active": True, **values,
        })
    db.add(profile)
    await db.commit()
    return profile.id
