"""Experimental opt-in OpenAI Realtime speech adapter.

Returns PCM-in-WAV bytes. No provider calls occur on import. Unverified live;
transcript mismatch or incomplete output fails closed and is never cached.
"""
import asyncio
import base64
import io
import json
import unicodedata
import wave

import websockets

from src.core.config import settings
from src.services.narration_style import STYLE_DIRECTIONS

MODEL = 'gpt-realtime-2.1-mini'
MAX_AUDIO_BYTES = 8 * 1024 * 1024

DIRECTIONS = {'legacy': 'Use a warm, expressive storytelling voice.', **STYLE_DIRECTIONS}
VOICES = {'default': 'coral', 'coral': 'coral', 'cedar': 'cedar'}


def _normalize(text):
    return ' '.join(unicodedata.normalize('NFC', text).split())


async def synthesize_realtime(text, voice='default', *, style='legacy'):
    if not isinstance(text, str) or not text.strip() or len(text) > 4096:
        raise ValueError('Invalid narration text')
    if voice not in VOICES or style not in DIRECTIONS:
        raise ValueError('Unsupported narration voice or style')
    key = settings.openai_tts_api_key
    if not key:
        raise ValueError('OpenAI TTS key is not configured')
    pcm = bytearray()
    transcript = None
    try:
        async with asyncio.timeout(60):
            async with websockets.connect(
                f'wss://api.openai.com/v1/realtime?model={MODEL}',
                additional_headers={'Authorization': f'Bearer {key}'},
                open_timeout=10, close_timeout=3, max_size=2 * 1024 * 1024,
            ) as conn:
                await conn.send(json.dumps({'type': 'session.update', 'session': {
                    'type': 'realtime', 'output_modalities': ['audio'],
                    'audio': {'output': {'format': {'type': 'audio/pcm', 'rate': 24000}, 'voice': VOICES[voice]}},
                }}))
                await conn.send(json.dumps({'type': 'response.create', 'response': {
                    'conversation': 'none', 'output_modalities': ['audio'],
                    'instructions': ('Read the supplied text exactly as written. Never add or omit words, '
                                     'introductions or sound effects. ' + DIRECTIONS[style]),
                    'input': [{'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': text}]}],
                }}))
                async for raw in conn:
                    event = json.loads(raw)
                    kind = event.get('type')
                    if kind == 'error':
                        raise ValueError('Realtime provider returned an error')
                    if kind == 'response.output_audio.delta':
                        pcm.extend(base64.b64decode(event['delta'], validate=True))
                        if len(pcm) > MAX_AUDIO_BYTES:
                            raise ValueError('Realtime audio exceeds size limit')
                    elif kind == 'response.output_audio_transcript.done':
                        if transcript is not None:
                            raise ValueError('Multiple narration transcripts')
                        transcript = event.get('transcript')
                    elif kind == 'response.done':
                        if event.get('response', {}).get('status') != 'completed':
                            raise ValueError('Realtime response incomplete')
                        break
                else:
                    raise ValueError('Realtime connection closed before completion')
    except asyncio.CancelledError:
        raise
    except Exception:
        raise ValueError('Realtime narration could not be verified') from None
    if not pcm or len(pcm) % 2 or not isinstance(transcript, str) or _normalize(transcript) != _normalize(text):
        raise ValueError('Realtime narration transcript or audio mismatch')
    output = io.BytesIO()
    with wave.open(output, 'wb') as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(24000)
        writer.writeframes(pcm)
    return output.getvalue()
