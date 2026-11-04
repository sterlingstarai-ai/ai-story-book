"""
TTS (Text-to-Speech) Service
책 페이지를 오디오로 변환
"""

import httpx
import re
import structlog
from typing import Optional
from abc import ABC, abstractmethod

from ..core.config import settings
from src.core.cost_budget import require_daily_generation_budget
from src.core.gemini_tts_budget import require_gemini_tts_request_budget
from src.services.provider_runtime import (
    begin_provider_request, observe_invalid_provider_response,
    observe_provider_response, observe_validated_provider_success,
)
from src.services.narration_style import STYLE_DIRECTIONS

logger = structlog.get_logger()

# Based on the approved Korean comparison samples. Directions avoid
# hard-coding that sample's surprise/ending into unrelated stories.
GEMINI_STYLE_DIRECTIONS = {
    "natural": "Read the text exactly, with a warm natural storyteller voice and clear pronunciation. No added words or sound effects.",
    "animated": ("Perform this children's story as a lively professional storyteller for young children. "
                 "Give dialogue a distinctly brighter, playful character voice when the words support it. "
                 "Vary pitch, rhythm and energy noticeably to match the story, without shouting or adding any words or sound effects. "
                 "Read exactly the supplied text."),
    "bedtime": "Read the story exactly, in a gentle calm soothing bedtime voice, soft energy and relaxed natural rhythm. No added words or sound effects.",
}

# H3: 스토리 5개 언어(ko/en/ja/zh/es) → TTS 언어코드·기본 보이스.
# 이전에는 ko/en만 매핑돼 ja/zh/es 책이 한국어(ko-KR) 보이스로 오합성된 오디오를
# audio_url에 영구 캐시했다. 매핑 밖 언어는 무음/오합성 폴백 없이 명시 예외.
TTS_LANGUAGE_CODES = {
    "ko": "ko-KR",
    "en": "en-US",
    "ja": "ja-JP",
    "zh": "cmn-CN",
    "es": "es-ES",
}
TTS_DEFAULT_VOICES = {
    "ko": "ko-KR-Neural2-A",
    "en": "en-US-Neural2-F",
    "ja": "ja-JP-Neural2-B",
    "zh": "cmn-CN-Wavenet-A",
    "es": "es-ES-Neural2-A",
}
# 오디오 표면(생성·조회·발음)이 허용하는 언어 = TTS 매핑 보유 언어.
SUPPORTED_AUDIO_LANGUAGES = tuple(TTS_LANGUAGE_CODES.keys())


_NARRATION_LABEL = re.compile(
    r"\A[ \t\r\n]*(?:"
    r"(?:페이지|ページ|page)[ \t]*[0-9]+[ \t]*(?:[.:：．](?=[ \t\r\n]|$)[ \t]*|\r?\n[ \t]*|$)"
    r"|장면[ \t]*[0-9]+의[ \t]*이야기[ \t]*입니다(?:[.!。](?=[ \t\r\n]|$)[ \t]*|$)"
    r")",
    re.IGNORECASE,
)


def narration_text_without_heading(text: str) -> str:
    """Remove only unmistakable leading production labels, never story dialogue."""
    while True:
        match = _NARRATION_LABEL.match(text)
        if match is None:
            return text
        text = text[match.end():]


def resolve_tts_language(language: str) -> tuple[str, str]:
    """언어 코드 → (TTS languageCode, 기본 보이스명). 미지원 언어는 ValueError(H3).

    무음/오합성 폴백을 금지하기 위해, 호출부(오디오 생성/조회)는 이 예외를
    NOT_SUPPORTED로 명시 처리해야 한다.
    """
    lang = (language or "").lower().strip()
    if lang not in TTS_LANGUAGE_CODES:
        raise ValueError(
            f"TTS가 지원하지 않는 언어입니다: {language!r} "
            f"(지원: {', '.join(SUPPORTED_AUDIO_LANGUAGES)})"
        )
    return TTS_LANGUAGE_CODES[lang], TTS_DEFAULT_VOICES[lang]


class BaseTTSProvider(ABC):
    """TTS 제공자 기본 클래스"""

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: str = "default",
        *,
        language: str = "ko",
        speaking_rate: float = 0.9,
    ) -> bytes:
        """텍스트를 오디오로 변환"""
        pass


class OpenAITTSProvider(BaseTTSProvider):
    """Built-in narration voices only; never clones the child's voice."""

    async def synthesize(
        self,
        text: str,
        voice: str = "default",
        *,
        language: str = "ko",
        speaking_rate: float = 0.9,
        style: str = "legacy",
    ) -> bytes:
        if style not in {"legacy", "natural", "animated", "bedtime"}:
            raise ValueError("Unsupported narration style")
        if style != "legacy" and not settings.openai_tts_model.startswith("gpt-4o-mini-tts"):
            raise ValueError("Narration style unsupported by model")
        resolve_tts_language(language)
        if not text.strip() or len(text) > 4096:
            raise ValueError("TTS text must contain 1 to 4096 characters")
        key = settings.openai_tts_api_key
        if not key:
            raise ValueError("OPENAI_TTS_API_KEY not configured")
        selected = settings.openai_tts_voice if voice == "default" else voice
        if selected not in {
            "alloy",
            "ash",
            "ballad",
            "coral",
            "echo",
            "fable",
            "onyx",
            "nova",
            "sage",
            "shimmer",
            "verse",
            "marin",
            "cedar",
        }:
            raise ValueError("Unsupported built-in narration voice")
        payload = {
            "model": settings.openai_tts_model,
            "input": text,
            "voice": selected,
            "response_format": "mp3",
            "speed": speaking_rate,
        }
        if settings.openai_tts_model.startswith("gpt-4o-mini-tts"):
            payload["instructions"] = (
                "Read the supplied story exactly as written, in its original language. "
                "Tell the story warmly and expressively, with gentle changes in emotion and character "
                "inflection to suit the scene, at a natural conversational pace with natural pauses. "
                "Do not add introductions, sound effects, or additional words."
            )
        if style != "legacy":
            payload["instructions"] += " " + STYLE_DIRECTIONS[style]
        observation = begin_provider_request("openai", settings.openai_tts_model, "tts", key)
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/speech",
                json=payload,
                headers={"Authorization": f"Bearer {key}"},
            )
        if response.is_error:
            await observe_provider_response(observation, response)
            # Provider response bodies may echo the story or credentials.
            raise ValueError(f"OpenAI TTS API error: {response.status_code}")
        if not response.content or not response.headers.get("content-type", "").startswith(
            "audio/"
        ):
            raise ValueError("OpenAI TTS returned no audio")
        await observe_provider_response(observation, response)
        return response.content


class RealtimeTTSProvider(BaseTTSProvider):
    """Opt-in experimental Realtime provider; not a live verification."""

    async def synthesize(self, text, voice="default", *, language="ko", speaking_rate=1.0, style="legacy"):
        resolve_tts_language(language)
        if speaking_rate != 1.0:
            raise ValueError("Realtime provider supports natural speed only")
        from src.services.realtime_tts import MODEL, synthesize_realtime
        observation = begin_provider_request('openai_realtime', MODEL, 'tts', settings.openai_tts_api_key)
        audio = await synthesize_realtime(text, voice, style=style)
        await observe_validated_provider_success(observation)
        return audio


def _validate_gemini_mp3(audio: bytes, text: str) -> None:
    """Reject incomplete or excessively long synthesis before publishing it."""
    # Deliberately generous for pauses, slow bedtime delivery and spoken numbers.
    duration_limit = max(18, 8 + 1.25 * sum(not char.isspace() for char in text))
    offset = 0
    if audio.startswith(b"ID3"):
        if len(audio) < 10 or any(byte & 0x80 for byte in audio[6:10]):
            raise ValueError("Invalid MP3 tag")
        offset = 10 + sum(byte << shift for byte, shift in zip(audio[6:10], (21, 14, 7, 0)))
        if audio[3] == 4 and audio[5] & 0x10:
            offset += 10
    end = len(audio)
    if end - offset >= 128 and audio[-128:-125] == b"TAG":
        end -= 128

    duration = 0.0
    while offset + 4 <= end:
        sync, version_layer, encoding, _ = audio[offset:offset + 4]
        version = (version_layer >> 3) & 3
        bitrate_index = encoding >> 4
        rate_index = (encoding >> 2) & 3
        if (sync != 0xff or version_layer & 0xe6 != 0xe2 or version == 1
                or bitrate_index in (0, 15) or rate_index == 3):
            raise ValueError("Invalid MP3 frame")
        if version == 3:  # MPEG-1 Layer III
            samples = 1152
            bitrates = (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
            sample_rate = (44100, 48000, 32000)[rate_index]
        else:  # MPEG-2 or 2.5 Layer III
            samples = 576
            bitrates = (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
            sample_rate = (22050, 24000, 16000)[rate_index] // (2 if version == 0 else 1)
        bitrate = bitrates[bitrate_index - 1] * 1000
        offset += samples * bitrate // (8 * sample_rate) + ((encoding >> 1) & 1)
        duration += samples / sample_rate
        if duration > duration_limit:
            raise ValueError("Gemini MP3 exceeds narration duration limit")
    if not duration or offset != end:
        raise ValueError("Incomplete MP3")


class GeminiCloudTTSProvider(BaseTTSProvider):
    """Opt-in Gemini TTS via workload ADC; never uses long-lived API keys."""

    async def synthesize(self, text, voice="default", *, language="ko", speaking_rate=1.0, style="legacy"):
        import asyncio
        import base64
        import binascii
        import re

        import google.auth
        from google.auth.transport.requests import Request

        language_code, _ = resolve_tts_language(language)
        if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > 4000:
            raise ValueError("Gemini TTS input must be 1 to 4000 UTF-8 bytes")
        if style not in {"legacy", "natural", "animated", "bedtime"}:
            raise ValueError("Unsupported narration style")
        if speaking_rate != 1.0:
            raise ValueError("Gemini TTS supports natural speed only")
        selected = "Kore" if voice in {"default", "Kore"} else voice
        if selected not in {"Kore", "Puck"}:
            raise ValueError("Unsupported Gemini narration voice")
        project = settings.google_gemini_tts_project or ""
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project):
            raise ValueError("Gemini TTS billing project is invalid")

        def access_token():
            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            credentials.refresh(Request())
            if not credentials.token:
                raise ValueError("Gemini TTS credentials unavailable")
            return credentials.token

        try:
            token = await asyncio.wait_for(asyncio.to_thread(access_token), timeout=20)
        except Exception:
            raise ValueError("Gemini TTS credentials unavailable") from None
        prompt = GEMINI_STYLE_DIRECTIONS["natural" if style == "legacy" else style]
        if language == "ko":
            prompt = prompt.replace("Read the text exactly,", "Read the Korean text exactly,")
            prompt = prompt.replace("with a warm natural storyteller voice and clear pronunciation.",
                                    "with a warm natural storyteller voice and clear Korean pronunciation.")
            prompt = prompt.replace("this children's story", "this Korean children's story")
            prompt = prompt.replace("Read the story exactly,", "Read the Korean story exactly,")
        payload = {"input": {"text": text, "prompt": prompt},
                   "voice": {"languageCode": language_code, "name": selected,
                             "modelName": "gemini-2.5-flash-tts"},
                   "audioConfig": {"audioEncoding": "MP3"}}
        # Each actual provider attempt reserves both durable limits first;
        # failed requests still count and no refund is made on timeout.
        await require_gemini_tts_request_budget()
        observation = begin_provider_request("google_gemini", "gemini-2.5-flash-tts", "tts", project)
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post("https://texttospeech.googleapis.com/v1/text:synthesize",
                    json=payload, headers={"Authorization": f"Bearer {token}", "x-goog-user-project": project})
        except httpx.HTTPError:
            raise ValueError("Gemini TTS request failed") from None
        await observe_provider_response(observation, response, defer_success=True)
        if not response.is_success:
            raise ValueError(f"Gemini TTS request failed: HTTP {response.status_code}")
        try:
            data = response.json()
            encoded = data.get("audioContent") if isinstance(data, dict) else None
            if not isinstance(encoded, str) or len(encoded) > 24_000_000:
                raise ValueError("Gemini TTS returned invalid audio")
            audio = base64.b64decode(encoded, validate=True)
            _validate_gemini_mp3(audio, text)
        except (ValueError, binascii.Error):
            await observe_invalid_provider_response(observation)
            raise ValueError("Gemini TTS returned invalid audio") from None
        await observe_validated_provider_success(observation)
        return audio


class GoogleTTSProvider(BaseTTSProvider):
    """Google Cloud TTS Provider"""

    def __init__(self):
        self.api_key = settings.google_tts_api_key
        self.base_url = "https://texttospeech.googleapis.com/v1/text:synthesize"

    async def synthesize(
        self,
        text: str,
        voice: str = "ko-KR-Neural2-A",
        *,
        language: str = "ko",
        speaking_rate: float = 0.9,
    ) -> bytes:
        """Google Cloud TTS로 오디오 생성"""
        if not self.api_key:
            raise ValueError("GOOGLE_TTS_API_KEY not configured")

        # H3: ko/en 하드코딩 대신 5개 스토리 언어 매핑. 미지원 언어는 raise(무음 폴백 금지).
        language_code, default_voice = resolve_tts_language(language)
        resolved_voice = voice
        if voice in {"default", "ko-KR-Neural2-A"}:
            resolved_voice = default_voice

        payload = {
            "input": {"text": text},
            "voice": {
                "languageCode": language_code,
                "name": resolved_voice,
            },
            "audioConfig": {
                "audioEncoding": "MP3",
                "speakingRate": speaking_rate,
                "pitch": 0.0,
            },
        }

        observation = begin_provider_request("google", "google-tts", "tts", self.api_key)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}?key={self.api_key}",
                json=payload,
            )
            await observe_provider_response(observation, response)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "Google TTS API error",
                    status=e.response.status_code,
                )
                raise ValueError(f"Google TTS API error: {e.response.status_code}") from e

            data = response.json()

            # Base64 디코딩
            import base64

            audio_content = base64.b64decode(data["audioContent"])
            return audio_content


class ElevenLabsProvider(BaseTTSProvider):
    """ElevenLabs TTS Provider"""

    def __init__(self):
        self.api_key = settings.elevenlabs_api_key
        self.base_url = "https://api.elevenlabs.io/v1/text-to-speech"
        # ElevenLabs의 한국어 지원 음성 ID
        self.voice_id = settings.elevenlabs_voice_id

    async def synthesize(
        self,
        text: str,
        voice: str = "default",
        *,
        language: str = "ko",
        speaking_rate: float = 0.9,
    ) -> bytes:
        """ElevenLabs로 오디오 생성"""
        if not self.api_key:
            raise ValueError("ELEVENLABS_API_KEY not configured")

        voice_id = voice if voice != "default" else self.voice_id

        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.5,
                "use_speaker_boost": True,
                "speed": speaking_rate,
            },
        }

        observation = begin_provider_request("elevenlabs", "elevenlabs-tts", "tts", self.api_key)
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.base_url}/{voice_id}",
                json=payload,
                headers={
                    "xi-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
            )
            await observe_provider_response(observation, response)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "ElevenLabs TTS API error",
                    status=e.response.status_code,
                )
                raise ValueError(f"ElevenLabs TTS API error: {e.response.status_code}") from e
            return response.content


class MockTTSProvider(BaseTTSProvider):
    """Mock TTS Provider for testing"""

    async def synthesize(
        self,
        text: str,
        voice: str = "default",
        *,
        language: str = "ko",
        speaking_rate: float = 0.9,
    ) -> bytes:
        """빈 MP3 반환 (테스트용)"""
        # 최소한의 유효한 MP3 헤더
        return bytes(
            [
                0xFF,
                0xFB,
                0x90,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
            ]
        )


class TTSService:
    """TTS 서비스"""

    AGE_SPEED_MAP = {
        "3-5": 1.00,
        "5-7": 1.00,
        "7-9": 1.00,
        "adult": 1.00,
    }

    def __init__(self):
        # H1/핸드오프 B2: provider 해석을 지연(lazy)한다. tts_service는 모듈 임포트
        # 시점 싱글톤이라 생성자에서 raise하면 앱 부팅 전체가 죽는다(결제·생성 포함).
        # 미지/운영-mock provider의 오류는 synthesize 호출(=provider 접근) 시점에만 난다.
        self._provider: Optional[BaseTTSProvider] = None

    @property
    def provider(self) -> BaseTTSProvider:
        if self._provider is None:
            self._provider = self._get_provider()
        return self._provider

    def _get_provider(self) -> BaseTTSProvider:
        """환경 변수에 따라 TTS 제공자 선택.

        H1: 미지 값·운영 mock은 조용한 Mock 폴백(=무음 오디오 서빙) 대신 raise한다.
        mock은 테스트(settings.testing=True)에서만 허용.
        """
        provider_name = settings.tts_provider.lower().strip()

        if provider_name == "openai_realtime":
            return RealtimeTTSProvider()
        if provider_name == "google_gemini":
            return GeminiCloudTTSProvider()
        if provider_name == "openai":
            return OpenAITTSProvider()
        if provider_name == "google":
            return GoogleTTSProvider()
        if provider_name == "elevenlabs":
            return ElevenLabsProvider()
        if provider_name == "mock":
            if settings.testing:
                return MockTTSProvider()
            raise ValueError(
                "TTS_PROVIDER=mock은 운영에서 허용되지 않습니다(무음 오디오 서빙 방지, H1)"
            )
        raise ValueError(
            f"알 수 없는 TTS_PROVIDER={settings.tts_provider!r} — "
            "openai/google/elevenlabs/mock만 허용(조용한 Mock 폴백 금지, H1)"
        )

    def _resolve_speed(self, target_age: Optional[str]) -> float:
        if not target_age:
            return 1.0
        return self.AGE_SPEED_MAP.get(target_age, 1.0)

    async def synthesize_page(
        self,
        text: str,
        voice: Optional[str] = None,
        *,
        target_age: Optional[str] = None,
        language: str = "ko",
        style: str = "legacy",
    ) -> bytes:
        """페이지 텍스트를 오디오로 변환"""
        resolve_tts_language(language)
        if not text.strip() or len(text) > 4096:
            raise ValueError("TTS text must contain 1 to 4096 characters")
        text = narration_text_without_heading(text)
        if not text.strip():
            raise ValueError("TTS text must contain story narration")
        provider = self.provider
        await require_daily_generation_budget("audio.tts")
        voice = voice or "default"
        style_args = {} if style == "legacy" else {"style": style}
        if style != "legacy" and not isinstance(provider, (OpenAITTSProvider, RealtimeTTSProvider, GeminiCloudTTSProvider)):
            raise ValueError("Narration style unsupported by provider")
        return await provider.synthesize(
            text,
            voice,
            language=language,
            speaking_rate=self._resolve_speed(target_age),
            **style_args,
        )

    async def synthesize_book(
        self,
        pages: list[dict],
        voice: Optional[str] = None,
        *,
        target_age: Optional[str] = None,
        language: str = "ko",
    ) -> list[bytes]:
        """
        책 전체 페이지를 오디오로 변환

        Args:
            pages: [{"page_number": 1, "text": "..."}, ...]
            voice: 음성 ID (optional)

        Returns:
            list of audio bytes for each page
        """
        results = []
        for page in pages:
            audio = await self.synthesize_page(
                page["text"],
                voice,
                target_age=target_age,
                language=language,
            )
            results.append(audio)
        return results


# 싱글톤 인스턴스
tts_service = TTSService()
