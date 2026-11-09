"""Experimental opt-in OpenAI Realtime speech adapter.

Returns PCM-in-WAV bytes. No provider calls occur on import. Unverified live;
transcript mismatch or incomplete output fails closed and is never cached.
"""
import asyncio
import base64
import io
import json
import re
import unicodedata
import wave

import websockets
from websockets.exceptions import InvalidStatus

from src.core.config import settings
from src.services.narration_style import STYLE_DIRECTIONS

MODEL = 'gpt-realtime-2.1-mini'
MAX_AUDIO_BYTES = 8 * 1024 * 1024
_PCM_RATE = 24000
_SENTENCE_BOUNDARY = re.compile(r'[.!?。！？][”’"」』]?\s+')

DIRECTIONS = {'legacy': 'Use a warm, expressive storytelling voice.', **STYLE_DIRECTIONS}
KOREAN_PRONUNCIATION = (
    '표준 한국어 발음으로 자연스럽게 낭독하세요. 받침과 연음, 문장의 억양을 살리고 '
    '단어 중간에 부자연스러운 강세를 주거나 음절을 끊지 마세요. 대사는 어조와 리듬으로 '
    '구분하되, 등장인물의 감정을 연기할 때도 같은 한국어 발음을 유지하세요. '
    '원문에 없는 말은 덧붙이지 마세요.'
)
VOICES = {'default': 'coral', 'coral': 'coral', 'cedar': 'cedar'}


class RealtimeSynthesisError(ValueError):
    def __init__(self, status_code: int | None = None):
        super().__init__('Realtime narration could not be verified')
        self.status_code = status_code


class RealtimeTranscriptMismatch(RealtimeSynthesisError):
    """A completed response produced speech with a different transcript."""


def _normalize(text):
    return ' '.join(unicodedata.normalize('NFC', text).split())


def split_realtime_script(text: str) -> tuple[str, ...]:
    """Keep every word and use a sentence boundary near the middle."""
    boundaries = [match.end() for match in _SENTENCE_BOUNDARY.finditer(text)
                  if match.end() < len(text.rstrip())]
    if not boundaries:
        return (text,)
    midpoint = min(boundaries, key=lambda index: abs(index - len(text) / 2))
    return text[:midpoint].rstrip(), text[midpoint:].lstrip()


def _pcm_wav(pcm: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, 'wb') as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(_PCM_RATE)
        writer.writeframes(pcm)
    return output.getvalue()


def join_realtime_wav(first: bytes, second: bytes) -> bytes:
    parts = []
    for part in (first, second):
        with wave.open(io.BytesIO(part), 'rb') as reader:
            if (reader.getnchannels(), reader.getsampwidth(), reader.getframerate()) != (1, 2, _PCM_RATE):
                raise RealtimeSynthesisError()
            frames = reader.readframes(reader.getnframes())
            if not frames or len(frames) != 2 * reader.getnframes():
                raise RealtimeSynthesisError()
            parts.append(frames)
    # Keep a short breath between the separately verified sentences.
    pcm = (b'\0\0' * (_PCM_RATE // 5)).join(parts)
    if len(pcm) > MAX_AUDIO_BYTES:
        raise RealtimeSynthesisError()
    return _pcm_wav(pcm)


async def synthesize_realtime(text, voice='default', *, language='ko', style='legacy'):
    if not isinstance(text, str) or not text.strip() or len(text) > 4096:
        raise ValueError('Invalid narration text')
    if voice not in VOICES or style not in DIRECTIONS:
        raise ValueError('Unsupported narration voice or style')
    key = settings.openai_tts_api_key
    if not key:
        raise ValueError('OpenAI TTS key is not configured')
    instructions = ('Read the supplied text exactly as written. Never add or omit words, '
                    'introductions or sound effects. ' + DIRECTIONS[style])
    if language == 'ko':
        instructions += ' ' + KOREAN_PRONUNCIATION
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
                    'audio': {'output': {'format': {'type': 'audio/pcm', 'rate': _PCM_RATE}, 'voice': VOICES[voice]}},
                }}))
                await conn.send(json.dumps({'type': 'response.create', 'response': {
                    'conversation': 'none', 'output_modalities': ['audio'],
                    'instructions': instructions,
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
    except InvalidStatus as error:
        raise RealtimeSynthesisError(error.response.status_code) from None
    except Exception:
        raise RealtimeSynthesisError() from None
    if not pcm or len(pcm) % 2 or not isinstance(transcript, str) or not transcript.strip():
        raise RealtimeSynthesisError()
    if _normalize(transcript) != _normalize(text):
        raise RealtimeTranscriptMismatch()
    return _pcm_wav(pcm)
