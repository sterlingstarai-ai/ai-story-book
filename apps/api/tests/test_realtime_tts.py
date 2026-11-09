import asyncio
import base64
import io
import json
import wave
from unittest.mock import AsyncMock

import pytest
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response

from src.core.config import settings
from src.services.realtime_tts import (
    RealtimeSynthesisError, RealtimeTranscriptMismatch, synthesize_realtime,
)


class Connection:
    def __init__(self, events):
        self.events = [json.dumps(e) for e in events]
        self.sent = []
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False
    async def send(self, value): self.sent.append(json.loads(value))
    def __aiter__(self):
        self._iter = iter(self.events)
        return self
    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration from None


def events(text='안녕하세요.', status='completed', pcm=b'\0\0\x01\0'):
    return [
        {'type': 'response.output_audio.delta', 'delta': base64.b64encode(pcm).decode()},
        {'type': 'response.output_audio_transcript.done', 'transcript': text},
        {'type': 'response.done', 'response': {'status': status}},
    ]


@pytest.mark.asyncio
async def test_realtime_audio_is_wav_and_exact_transcript(monkeypatch):
    monkeypatch.setattr(settings, 'openai_tts_api_key', 'fake-key')
    conn = Connection(events())
    monkeypatch.setattr('src.services.realtime_tts.websockets.connect', lambda *a, **kw: conn)
    result = await synthesize_realtime('안녕하세요.', voice='cedar', style='animated')
    with wave.open(io.BytesIO(result)) as audio:
        assert audio.getframerate() == 24000 and audio.getnchannels() == 1
        assert audio.readframes(2) == b'\0\0\x01\0'
    assert conn.sent[0]['session']['audio']['output']['voice'] == 'cedar'
    assert conn.sent[1]['response']['input'][0]['content'][0]['text'] == '안녕하세요.'
    assert '억양과 강약을 생생하게' in conn.sent[1]['response']['instructions']
    assert '표현은 목소리의 변화로만' in conn.sent[1]['response']['instructions']
    assert '역할 이름, 웃음이나 효과음, 뒷이야기를 덧붙이지 마세요' in conn.sent[1]['response']['instructions']
    assert '원문의 말과 순서' in conn.sent[1]['response']['instructions']
    assert '표준 한국어 발음' in conn.sent[1]['response']['instructions']


@pytest.mark.asyncio
async def test_realtime_korean_pronunciation_does_not_apply_to_english(monkeypatch):
    monkeypatch.setattr(settings, 'openai_tts_api_key', 'fake-key')
    conn = Connection(events(text='Hello, little fox.'))
    monkeypatch.setattr('src.services.realtime_tts.websockets.connect', lambda *a, **kw: conn)
    await synthesize_realtime('Hello, little fox.', language='en', style='animated')
    assert '표준 한국어 발음' not in conn.sent[1]['response']['instructions']
    assert 'quoted dialogue' in conn.sent[1]['response']['instructions']


@pytest.mark.asyncio
@pytest.mark.parametrize('server_events', [events(text='잘못된 이야기.'), events(status='failed'), events(pcm=b''), [], [{'type': 'error'}]])
async def test_realtime_failure_never_returns_audio(monkeypatch, server_events):
    monkeypatch.setattr(settings, 'openai_tts_api_key', 'fake-key')
    monkeypatch.setattr('src.services.realtime_tts.websockets.connect', lambda *a, **kw: Connection(server_events))
    with pytest.raises(ValueError):
        await synthesize_realtime('안녕하세요.')


@pytest.mark.asyncio
@pytest.mark.parametrize('transcript', [
    '다른 이야기를 읽었어요.',
    '해설: 안녕하세요.',
    '안녕하세요. (웃음)',
    '안녕하세요. 두 친구는 행복했어요.',
])
async def test_completed_realtime_response_reports_changed_words(monkeypatch, transcript):
    monkeypatch.setattr(settings, 'openai_tts_api_key', 'fake-key')
    connection = Connection(events(text=transcript))
    monkeypatch.setattr('src.services.realtime_tts.websockets.connect', lambda *a, **kw: connection)
    with pytest.raises(RealtimeTranscriptMismatch):
        await synthesize_realtime('안녕하세요.')


@pytest.mark.asyncio
@pytest.mark.parametrize(('outcomes', 'calls', 'error'), [
    ([RealtimeTranscriptMismatch(), b'validated audio'], 2, None),
    ([RealtimeTranscriptMismatch(), RealtimeTranscriptMismatch()], 2, RealtimeTranscriptMismatch),
    ([RealtimeSynthesisError(403)], 1, RealtimeSynthesisError),
    ([RealtimeSynthesisError()], 1, RealtimeSynthesisError),
])
async def test_page_retries_only_completed_transcript_mismatch(monkeypatch, outcomes, calls, error):
    from src.services.tts import RealtimeTTSProvider, TTSService
    monkeypatch.setattr(settings, 'tts_provider', 'openai_realtime')
    synthesis = AsyncMock(side_effect=outcomes)
    budget = AsyncMock()
    monkeypatch.setattr(RealtimeTTSProvider, 'synthesize', synthesis)
    monkeypatch.setattr('src.services.tts.require_daily_generation_budget', budget)
    service = TTSService()
    if error is None:
        assert await service.synthesize_page('안녕하세요.', 'cedar', style='animated') == b'validated audio'
    else:
        with pytest.raises(error):
            await service.synthesize_page('안녕하세요.', 'cedar', style='animated')
    assert synthesis.await_count == budget.await_count == calls


@pytest.mark.asyncio
async def test_realtime_retry_requires_an_available_second_budget_slot(monkeypatch):
    from src.core.exceptions import APIError
    from src.services.tts import RealtimeTTSProvider, TTSService
    monkeypatch.setattr(settings, 'tts_provider', 'openai_realtime')
    synthesis = AsyncMock(side_effect=RealtimeTranscriptMismatch())
    budget = AsyncMock(side_effect=[None, APIError(429, 'RATE_LIMIT', 'Fixture budget exhausted')])
    monkeypatch.setattr(RealtimeTTSProvider, 'synthesize', synthesis)
    monkeypatch.setattr('src.services.tts.require_daily_generation_budget', budget)
    with pytest.raises(APIError) as error:
        await TTSService().synthesize_page('안녕하세요.', style='animated')
    assert error.value.status_code == 429
    assert budget.await_count == 2
    synthesis.assert_awaited_once()


@pytest.mark.asyncio
async def test_realtime_recovers_a_long_page_in_two_verified_parts(monkeypatch):
    from src.services.tts import RealtimeTTSProvider, TTSService

    def clip(pcm):
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as audio:
            audio.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
            audio.writeframes(pcm)
        return stream.getvalue()

    first = '작은 토끼가 숲에서 친구를 만났어요.'
    second = '“우리 함께 꽃을 찾아볼까?” 토끼가 물었어요.'
    text = f'{first} {second}'
    synthesis = AsyncMock(side_effect=[RealtimeTranscriptMismatch(), clip(b'\x01\0'), clip(b'\x02\0')])
    budget = AsyncMock()
    monkeypatch.setattr(settings, 'tts_provider', 'openai_realtime')
    monkeypatch.setattr(RealtimeTTSProvider, 'synthesize', synthesis)
    monkeypatch.setattr('src.services.tts.require_daily_generation_budget', budget)

    recovered = await TTSService().synthesize_page(text, 'cedar', style='animated')
    assert [call.args for call in synthesis.await_args_list] == [(text, 'cedar'), (first, 'cedar'), (second, 'cedar')]
    assert all(call.kwargs['style'] == 'animated' for call in synthesis.await_args_list)
    assert budget.await_count == 3
    with wave.open(io.BytesIO(recovered)) as audio:
        assert audio.getframerate() == 24000
        assert audio.readframes(audio.getnframes()) == b'\x01\0' + b'\0\0' * 4800 + b'\x02\0'


@pytest.mark.asyncio
async def test_realtime_recovery_deadline_cancels_the_slow_fragment(monkeypatch):
    from src.services import tts

    first = '작은 토끼가 숲에서 친구를 만났어요.'
    text = f'{first} 함께 꽃을 찾았어요.'
    attempts = []

    async def synthesize(_provider, script, _voice, **_kwargs):
        attempts.append(script)
        if script == text:
            raise RealtimeTranscriptMismatch()
        await asyncio.Event().wait()

    budget = AsyncMock()
    monkeypatch.setattr(settings, 'tts_provider', 'openai_realtime')
    monkeypatch.setattr(tts, '_REALTIME_RECOVERY_TIMEOUT', 0)
    monkeypatch.setattr(tts.RealtimeTTSProvider, 'synthesize', synthesize)
    monkeypatch.setattr(tts, 'require_daily_generation_budget', budget)
    with pytest.raises(TimeoutError):
        await tts.TTSService().synthesize_page(text, style='animated')
    assert attempts == [text, first]
    assert budget.await_count == 2


@pytest.mark.asyncio
async def test_store_wav_uses_matching_content_type(db_session, monkeypatch):
    from src.services.audio_assets import store_narration
    from src.services.storage import storage_service
    upload = AsyncMock(return_value='https://cdn.example.com/wav')
    monkeypatch.setattr(storage_service, 'upload_bytes', upload)
    await store_narration(db_session, 'synthetic', 1, 'ko', b'RIFF\0\0\0\0WAVEdata', user_key='test')
    assert upload.await_args.kwargs['content_type'] == 'audio/wav'
    assert upload.await_args.args[1].endswith('.wav')


@pytest.mark.asyncio
async def test_realtime_timeout_fails_safely(monkeypatch):
    class TimeoutConnection:
        async def __aenter__(self):
            raise asyncio.TimeoutError('sensitive response')
        async def __aexit__(self, *args):
            return False
    monkeypatch.setattr(settings, 'openai_tts_api_key', 'fake-key')
    monkeypatch.setattr('src.services.realtime_tts.websockets.connect', lambda *a, **kw: TimeoutConnection())
    with pytest.raises(ValueError) as error:
        await synthesize_realtime('안녕하세요.')
    assert 'sensitive response' not in str(error.value)


@pytest.mark.asyncio
async def test_realtime_upgrade_rejection_exposes_only_the_status(monkeypatch):
    class RejectedConnection:
        async def __aenter__(self):
            raise InvalidStatus(Response(403, 'Forbidden', Headers(), b'sensitive response'))
        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(settings, 'openai_tts_api_key', 'fake-key')
    monkeypatch.setattr('src.services.realtime_tts.websockets.connect', lambda *a, **kw: RejectedConnection())
    with pytest.raises(RealtimeSynthesisError) as error:
        await synthesize_realtime('안녕하세요.')
    assert error.value.status_code == 403
    assert 'sensitive response' not in str(error.value)


def test_realtime_is_explicitly_opt_in_and_exposes_style_only_when_ready(monkeypatch):
    from src.core.audio_feature import narration_style_selection_supported
    from src.services.tts import RealtimeTTSProvider, TTSService
    monkeypatch.setattr(settings, 'tts_provider', 'openai_realtime')
    monkeypatch.setattr('src.core.audio_feature.audio_supported', lambda: True)
    assert isinstance(TTSService().provider, RealtimeTTSProvider)
    assert narration_style_selection_supported()
    monkeypatch.setattr(settings, 'tts_provider', 'google')
    assert not narration_style_selection_supported()
