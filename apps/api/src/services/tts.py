"""
TTS (Text-to-Speech) Service
책 페이지를 오디오로 변환
"""
import io
import httpx
from typing import Optional
from abc import ABC, abstractmethod
import os

from ..core.config import settings


class BaseTTSProvider(ABC):
    """TTS 제공자 기본 클래스"""

    @abstractmethod
    async def synthesize(self, text: str, voice: str = "default") -> bytes:
        """텍스트를 오디오로 변환"""
        pass


class GoogleTTSProvider(BaseTTSProvider):
    """Google Cloud TTS Provider"""

    def __init__(self):
        self.api_key = os.getenv("GOOGLE_TTS_API_KEY")
        self.base_url = "https://texttospeech.googleapis.com/v1/text:synthesize"

    async def synthesize(self, text: str, voice: str = "ko-KR-Neural2-A") -> bytes:
        """Google Cloud TTS로 오디오 생성"""
        if not self.api_key:
            raise ValueError("GOOGLE_TTS_API_KEY not configured")

        payload = {
            "input": {"text": text},
            "voice": {
                "languageCode": "ko-KR",
                "name": voice,
            },
            "audioConfig": {
                "audioEncoding": "MP3",
                "speakingRate": 0.9,  # 아이들을 위해 약간 느리게
                "pitch": 0.0,
            },
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}?key={self.api_key}",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            # Base64 디코딩
            import base64
            audio_content = base64.b64decode(data["audioContent"])
            return audio_content


class ElevenLabsProvider(BaseTTSProvider):
    """ElevenLabs TTS Provider"""

    def __init__(self):
        self.api_key = os.getenv("ELEVENLABS_API_KEY")
        self.base_url = "https://api.elevenlabs.io/v1/text-to-speech"
        # ElevenLabs의 한국어 지원 음성 ID
        self.voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

    async def synthesize(self, text: str, voice: str = "default") -> bytes:
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
            response.raise_for_status()
            return response.content


class MockTTSProvider(BaseTTSProvider):
    """Mock TTS Provider for testing"""

    async def synthesize(self, text: str, voice: str = "default") -> bytes:
        """빈 MP3 반환 (테스트용)"""
        # 최소한의 유효한 MP3 헤더
        return bytes([
            0xFF, 0xFB, 0x90, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        ])


class TTSService:
    """TTS 서비스"""

    def __init__(self):
        self.provider = self._get_provider()

    def _get_provider(self) -> BaseTTSProvider:
        """환경 변수에 따라 TTS 제공자 선택"""
        provider_name = os.getenv("TTS_PROVIDER", "mock").lower()

        if provider_name == "google":
            return GoogleTTSProvider()
        elif provider_name == "elevenlabs":
            return ElevenLabsProvider()
        else:
            return MockTTSProvider()

    async def synthesize_page(self, text: str, voice: Optional[str] = None) -> bytes:
        """페이지 텍스트를 오디오로 변환"""
        voice = voice or "default"
        return await self.provider.synthesize(text, voice)

    async def synthesize_book(
        self,
        pages: list[dict],
        voice: Optional[str] = None,
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
            audio = await self.synthesize_page(page["text"], voice)
            results.append(audio)
        return results


# 싱글톤 인스턴스
tts_service = TTSService()
