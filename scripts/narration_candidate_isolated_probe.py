"""Offline-only candidate image probe using invented text and fake provider I/O."""
import asyncio
import base64
import json
import os


if os.environ.get('ASB_NARRATION_ISOLATED_PROBE') != '1':
    raise RuntimeError('This probe must be explicitly run in an isolated container')

import google.auth  # noqa: E402
import httpx  # noqa: E402

from src.core.audio_feature import narration_style_selection_supported  # noqa: E402
from src.main import app  # noqa: E402
from src.services.tts import GeminiCloudTTSProvider  # noqa: E402
from src.worker import celery_app  # noqa: E402


class Credentials:
    token = 'synthetic-token'

    def refresh(self, _request):
        return None


class Response:
    status_code = 200
    is_error = False

    def json(self):
        return {'audioContent': base64.b64encode(b'ID3synthetic-audio').decode()}


class Client:
    calls = []

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def post(self, url, *, json, headers):
        assert url == 'https://texttospeech.googleapis.com/v1/text:synthesize'
        assert headers['Authorization'] == 'Bearer synthetic-token'
        self.calls.append(json)
        return Response()


async def main():
    assert narration_style_selection_supported()
    assert app is not None and celery_app is not None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://fixture') as client:
        response = await client.get('/v1/config/capabilities')
    assert response.status_code == 200
    capabilities = response.json()
    assert capabilities['narration_audio_provider'] == 'google_gemini'
    assert capabilities['narration_style_selection_supported'] is True
    google.auth.default = lambda **_kwargs: (Credentials(), None)
    httpx.AsyncClient = Client
    provider = GeminiCloudTTSProvider()
    for voice in ('Kore', 'Puck'):
        for style in ('natural', 'animated', 'bedtime'):
            audio = await provider.synthesize('토끼가 숲을 걸었어요.', voice, language='ko', style=style)
            assert audio == b'ID3synthetic-audio'
    assert len(Client.calls) == 6
    assert {c['voice']['name'] for c in Client.calls} == {'Kore', 'Puck'}
    assert all(c['voice']['modelName'] == 'gemini-2.5-flash-tts' for c in Client.calls)
    assert all(c['input']['text'] == '토끼가 숲을 걸었어요.' for c in Client.calls)
    for offset in (0, 3):
        assert len({c['input']['prompt'] for c in Client.calls[offset:offset + 3]}) == 3
    print(json.dumps({'status': 'OFFLINE_PROBE_PASSED', 'requests': 6,
                      'real_provider_called': False, 'human_voice_quality_verified': False}))


asyncio.run(main())
