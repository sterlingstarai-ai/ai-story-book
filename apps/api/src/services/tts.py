"""
TTS (Text-to-Speech) Service
책 페이지를 오디오로 변환
"""

import httpx
import structlog
from typing import Optional
from abc import ABC, abstractmethod

from ..core.config import settings

logger = structlog.get_logger()


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

        language_code = "ko-KR" if language == "ko" else "en-US"
        resolved_voice = voice
        if voice in {"default", "ko-KR-Neural2-A"}:
            resolved_voice = "ko-KR-Neural2-A" if language == "ko" else "en-US-Neural2-F"

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

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}?key={self.api_key}",
                json=payload,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "Google TTS API error",
                    status=e.response.status_code,
                    body=e.response.text[:200],
                )
                raise ValueError(
                    f"Google TTS API error: {e.response.status_code}"
                ) from e

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

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.base_url}/{voice_id}",
                json=payload,
                headers={
                    "xi-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "ElevenLabs TTS API error",
                    status=e.response.status_code,
                    body=e.response.text[:200],
                )
                raise ValueError(
                    f"ElevenLabs TTS API error: {e.response.status_code}"
                ) from e
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
        "3-5": 0.65,
        "5-7": 0.80,
        "7-9": 0.90,
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
            "google/elevenlabs/mock만 허용(조용한 Mock 폴백 금지, H1)"
        )

    def _resolve_speed(self, target_age: Optional[str]) -> float:
        if not target_age:
            return 0.9
        return self.AGE_SPEED_MAP.get(target_age, 0.9)

    async def synthesize_page(
        self,
        text: str,
        voice: Optional[str] = None,
        *,
        target_age: Optional[str] = None,
        language: str = "ko",
    ) -> bytes:
        """페이지 텍스트를 오디오로 변환"""
        voice = voice or "default"
        return await self.provider.synthesize(
            text,
            voice,
            language=language,
            speaking_rate=self._resolve_speed(target_age),
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
