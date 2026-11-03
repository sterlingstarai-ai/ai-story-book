import json
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from src.core.config import settings
from src.core.rate_limit import rate_limiter
from src.models.db import NarrationVariant
from src.routers.books import get_page_audio
from src.services.storage import storage_service
from src.services.tts import OpenAITTSProvider, tts_service
from tests.test_audio_completion import _narration_book
from tests.test_narration_voices import _LockRedis


@pytest.mark.asyncio
async def test_styles_are_separate_and_legacy_unchanged(db_session, monkeypatch):
    book, page, _ = await _narration_book(db_session)
    page.audio_url = page.audio_url_en = 'https://cdn.example.com/legacy.mp3'
    await db_session.commit()
    monkeypatch.setattr(settings, 'tts_provider', 'openai')
    monkeypatch.setattr(settings, 'openai_tts_api_key', 'test')
    monkeypatch.setattr(settings, 'openai_tts_model', 'gpt-4o-mini-tts')
    monkeypatch.setattr(settings, 'generation_access_mode', 'open')
    monkeypatch.setattr(rate_limiter, 'get_redis', AsyncMock(return_value=_LockRedis()))
    synth = AsyncMock(return_value=b'audio')
    monkeypatch.setattr(tts_service, 'synthesize_page', synth)
    async def upload(_data, key, **kwargs):
        return 'https://cdn.example.com/' + key
    monkeypatch.setattr(storage_service, 'upload_bytes', upload)
    async def get(style):
        return await get_page_audio(book.id, 1, language='en', voice='default', style=style,
                                    db=db_session, user_key=book.user_key, profile_id=None)
    legacy = await get('legacy')
    results = [await get(style) for style in ('natural', 'animated', 'bedtime')]
    assert legacy['audio_url'].endswith('legacy.mp3')
    assert len({r['audio_url'] for r in results}) == 3
    assert await get('animated') == results[1]
    assert synth.await_count == 3
    assert len((await db_session.scalars(select(NarrationVariant))).all()) == 3
    from src.services.audio_assets import variant_url
    assert await variant_url(db_session, page.id, 'en', 'default', 'natural', 'openai_realtime') is None
    db_session.add(NarrationVariant(id='realtime', page_id=page.id, language='en', voice='default', style='natural', provider='openai_realtime', audio_url='https://cdn.example.com/realtime.wav'))
    await db_session.commit()
    assert await variant_url(db_session, page.id, 'en', 'default', 'natural', 'openai') != await variant_url(db_session, page.id, 'en', 'default', 'natural', 'openai_realtime')


@pytest.mark.asyncio
async def test_openai_styles_do_not_change_story_and_are_distinct(monkeypatch):
    monkeypatch.setattr(settings, 'openai_tts_api_key', 'test')
    monkeypatch.setattr(settings, 'openai_tts_model', 'gpt-4o-mini-tts')
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=b'ID3', headers={'content-type': 'audio/mpeg'})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    for style in ('natural', 'animated', 'bedtime'):
        await OpenAITTSProvider().synthesize('숲이 반짝여요.', style=style)
    assert all(r['input'] == '숲이 반짝여요.' for r in requests)
    assert len({r['instructions'] for r in requests}) == 3
    assert all('Do not add introductions' in r['instructions'] for r in requests)


def test_style_capability_only_model_with_instructions(monkeypatch):
    from src.core.audio_feature import narration_style_selection_supported
    monkeypatch.setattr(settings, 'audio_feature_enabled', True)
    monkeypatch.setattr(settings, 'tts_provider', 'openai')
    monkeypatch.setattr(settings, 'openai_tts_api_key', 'test')
    monkeypatch.setattr(settings, 'stt_provider', 'openai')
    monkeypatch.setattr('src.core.audio_feature.audio_supported', lambda: True)
    monkeypatch.setattr(settings, 'openai_tts_model', 'tts-1')
    assert not narration_style_selection_supported()
