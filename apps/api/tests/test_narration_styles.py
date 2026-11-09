import json
from unittest.mock import AsyncMock
import uuid

import httpx
import pytest
from sqlalchemy import event, select

from src.core.config import settings
from src.core.rate_limit import rate_limiter
from src.models.db import ChildProfile, NarrationVariant
from src.routers.books import get_page_audio
from src.services.storage import storage_service
from src.services.tts import OpenAITTSProvider, tts_service
from tests.test_audio_completion import _narration_book
from tests.test_narration_voices import _LockRedis


@pytest.mark.asyncio
async def test_cached_narration_never_synthesizes_or_bypasses_consent(client, db_session, monkeypatch, user_key):
    book, page, consent = await _narration_book(db_session, user_key=user_key)
    monkeypatch.setattr(settings, 'tts_provider', 'openai')
    monkeypatch.setattr(settings, 'openai_tts_api_key', 'test')
    monkeypatch.setattr(settings, 'openai_tts_model', 'gpt-4o-mini-tts')
    monkeypatch.setattr(settings, 'require_parental_consent_in_testing', True)
    synth = AsyncMock(side_effect=AssertionError('Cached narration must never synthesize'))
    monkeypatch.setattr(tts_service, 'synthesize_page', synth)
    url = f'/v1/books/{book.id}/pages/1/audio/cached'
    headers = {'X-User-Key': book.user_key}
    params = {'language': 'en', 'voice': 'deep', 'style': 'animated'}

    missing = await client.get(url, params=params, headers=headers)
    assert missing.status_code == 200 and missing.json() == {'audio_url': None}
    db_session.add(NarrationVariant(id='cached-only', page_id=page.id, language='en', voice='deep',
                                   style='animated', provider='openai', audio_url='https://cdn.example.com/cached.mp3'))
    await db_session.commit()
    saved = await client.get(url, params=params, headers=headers)
    assert saved.status_code == 200 and saved.json()['audio_url'].endswith('/cached.mp3')
    foreign = {'X-User-Key': str(uuid.uuid4())}
    assert (await client.get(url, params=params, headers=foreign)).status_code == 403

    consent.granted = False
    await db_session.commit()
    assert (await client.get(url, params=params, headers=headers)).status_code == 403
    synth.assert_not_awaited()


@pytest.mark.asyncio
async def test_cached_narration_reads_book_and_page_together_with_profile_scope(client, db_session, user_key):
    book, page, _ = await _narration_book(db_session, user_key=user_key)
    db_session.add_all([
        ChildProfile(id='audio-owner', user_key=user_key, name='Owner'),
        ChildProfile(id='audio-sibling', user_key=user_key, name='Sibling'),
    ])
    await db_session.flush()
    book.profile_id = 'audio-owner'
    page.audio_url_en = 'https://cdn.example.com/cached.mp3'
    await db_session.commit()
    params = {'language': 'en'}
    owner = {'X-User-Key': user_key, 'X-Profile-Id': 'audio-owner'}
    sibling = {**owner, 'X-Profile-Id': 'audio-sibling'}
    url = f'/v1/books/{book.id}/pages'
    reads = []

    def observe(_conn, _cursor, statement, _params, _context, _executemany):
        sql = ' '.join(statement.lower().split())
        if ' from books ' in sql or ' from pages ' in sql:
            reads.append(sql)

    engine = db_session.bind.sync_engine
    event.listen(engine, 'before_cursor_execute', observe)
    try:
        saved = await client.get(f'{url}/1/audio/cached', params=params, headers=owner)
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert saved.status_code == 200 and saved.json()['audio_url'].endswith('/cached.mp3')
    assert len(reads) == 1 and 'left outer join pages' in reads[0]
    assert (await client.get(f'{url}/2/audio/cached', params=params, headers=owner)).status_code == 404
    for page_number in (1, 2):
        assert (await client.get(
            f'{url}/{page_number}/audio/cached', params=params, headers=sibling,
        )).status_code == 403

    book.profile_id = None
    await db_session.commit()
    assert (await client.get(f'{url}/1/audio/cached', params=params, headers=sibling)).status_code == 200


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
