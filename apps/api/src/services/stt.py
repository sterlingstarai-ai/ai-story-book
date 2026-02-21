"""
STT (Speech-to-Text) Service
발화 오디오를 텍스트로 변환
"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from typing import Optional

import httpx
import structlog

from src.core.config import settings

logger = structlog.get_logger()


class BaseSTTProvider(ABC):
    """STT 제공자 기본 클래스"""

    @abstractmethod
    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str,
        language: str = "ko",
    ) -> str:
        """오디오 바이트를 텍스트로 변환"""
        raise NotImplementedError


class OpenAISTTProvider(BaseSTTProvider):
    """OpenAI Audio Transcription Provider"""

    def __init__(self):
        self.api_key = settings.stt_api_key or settings.llm_api_key
        self.model = settings.stt_model
        self.endpoint = "https://api.openai.com/v1/audio/transcriptions"

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str,
        language: str = "ko",
    ) -> str:
        if not self.api_key:
            raise ValueError("STT API key is not configured for OpenAI provider")

        filename = "speech.m4a"
        if mime_type == "audio/mpeg":
            filename = "speech.mp3"
        elif mime_type in {"audio/wav", "audio/x-wav"}:
            filename = "speech.wav"
        elif mime_type == "audio/webm":
            filename = "speech.webm"

        form = {
            "model": self.model,
        }
        if language in {"ko", "en"}:
            form["language"] = language

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                data=form,
                files={
                    "file": (
                        filename,
                        audio_bytes,
                        mime_type or "application/octet-stream",
                    )
                },
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "OpenAI STT API error",
                    status=exc.response.status_code,
                    body=exc.response.text[:200],
                )
                raise ValueError(
                    f"OpenAI STT API error: {exc.response.status_code}"
                ) from exc

        payload = response.json()
        text = payload.get("text")
        if isinstance(text, str):
            return text.strip()
        raise ValueError("Invalid transcription response from OpenAI STT")


class GoogleSTTProvider(BaseSTTProvider):
    """Google Speech-to-Text Provider (v1 REST)"""

    def __init__(self):
        self.api_key = settings.google_stt_api_key
        self.endpoint = "https://speech.googleapis.com/v1/speech:recognize"

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str,
        language: str = "ko",
    ) -> str:
        if not self.api_key:
            raise ValueError("GOOGLE_STT_API_KEY is not configured")

        language_code = "ko-KR" if language == "ko" else "en-US"
        audio_content = base64.b64encode(audio_bytes).decode("utf-8")
        payload = {
            "config": {
                "languageCode": language_code,
                "enableAutomaticPunctuation": True,
                "model": "latest_short",
            },
            "audio": {
                "content": audio_content,
            },
        }

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.endpoint}?key={self.api_key}",
                json=payload,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "Google STT API error",
                    status=exc.response.status_code,
                    body=exc.response.text[:200],
                )
                raise ValueError(
                    f"Google STT API error: {exc.response.status_code}"
                ) from exc

        data = response.json()
        results = data.get("results")
        if not isinstance(results, list) or not results:
            return ""
        first = results[0]
        alternatives = first.get("alternatives")
        if not isinstance(alternatives, list) or not alternatives:
            return ""
        transcript = alternatives[0].get("transcript")
        if isinstance(transcript, str):
            return transcript.strip()
        return ""


class MockSTTProvider(BaseSTTProvider):
    """테스트/개발용 Mock Provider"""

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str,
        language: str = "ko",
    ) -> str:
        if language == "en":
            return "This is a mock transcript."
        return "이것은 목업 발화 문장입니다."


class STTService:
    def __init__(self):
        self.provider = self._get_provider()

    def _get_provider(self) -> BaseSTTProvider:
        provider_name = settings.stt_provider.lower().strip()
        if provider_name == "openai":
            return OpenAISTTProvider()
        if provider_name == "google":
            return GoogleSTTProvider()
        return MockSTTProvider()

    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str,
        language: str = "ko",
    ) -> str:
        if not isinstance(audio_bytes, (bytes, bytearray)) or len(audio_bytes) == 0:
            return ""
        return await self.provider.transcribe(
            bytes(audio_bytes),
            mime_type=mime_type,
            language=language,
        )


stt_service = STTService()

