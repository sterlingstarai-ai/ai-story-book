import base64
import io
import json
import wave
from unittest.mock import AsyncMock

import pytest

from src.core.config import settings
from src.services.realtime_tts import synthesize_realtime


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
    assert 'quoted dialogue' in conn.sent[1]['response']['instructions']
    assert 'Never add or omit words' in conn.sent[1]['response']['instructions']


@pytest.mark.asyncio
@pytest.mark.parametrize('server_events', [events(text='잘못된 이야기.'), events(status='failed'), events(pcm=b''), [], [{'type': 'error'}]])
async def test_realtime_failure_never_returns_audio(monkeypatch, server_events):
    monkeypatch.setattr(settings, 'openai_tts_api_key', 'fake-key')
    monkeypatch.setattr('src.services.realtime_tts.websockets.connect', lambda *a, **kw: Connection(server_events))
    with pytest.raises(ValueError):
        await synthesize_realtime('안녕하세요.')


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
    import asyncio
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


def test_realtime_is_explicitly_opt_in_and_exposes_style_only_when_ready(monkeypatch):
    from src.core.audio_feature import narration_style_selection_supported
    from src.services.tts import RealtimeTTSProvider, TTSService
    monkeypatch.setattr(settings, 'tts_provider', 'openai_realtime')
    monkeypatch.setattr('src.core.audio_feature.audio_supported', lambda: True)
    assert isinstance(TTSService().provider, RealtimeTTSProvider)
    assert narration_style_selection_supported()
    monkeypatch.setattr(settings, 'tts_provider', 'google')
    assert not narration_style_selection_supported()
