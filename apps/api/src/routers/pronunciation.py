"""
Pronunciation Router
발음 평가(STT 기반 확장용)
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.core.audio_feature import require_audio_supported
from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.core.exceptions import ValidationError
from src.models.db import PronunciationLog
from src.services.stt import stt_service

router = APIRouter()
logger = structlog.get_logger()
_MAX_PRONUNCIATION_AUDIO_BYTES = 15 * 1024 * 1024


class PronunciationEvaluateRequest(BaseModel):
    book_id: Optional[str] = None
    page_number: Optional[int] = Field(default=None, ge=1, le=12)
    transcript: str = Field(min_length=1, max_length=4000)
    expected_text: str = Field(min_length=1, max_length=4000)
    audio_url: Optional[str] = Field(default=None, max_length=500)


def _score_pronunciation(transcript: str, expected: str) -> tuple[float, str]:
    token_pattern = re.compile(r"[0-9A-Za-z가-힣']+")
    expected_tokens = token_pattern.findall(expected.lower())
    transcript_tokens = token_pattern.findall(transcript.lower())
    if not expected_tokens:
        return 0.0, "기준 텍스트가 비어 있습니다."
    if not transcript_tokens:
        return 0.0, "입력된 발화가 비어 있어요. 천천히 다시 읽어볼까요?"

    ordered_matcher = SequenceMatcher(
        a=expected_tokens,
        b=transcript_tokens,
        autojunk=False,
    )
    ordered_match_count = sum(block.size for block in ordered_matcher.get_matching_blocks())
    ordered_ratio = ordered_match_count / len(expected_tokens)

    char_matcher = SequenceMatcher(
        a=" ".join(expected_tokens),
        b=" ".join(transcript_tokens),
        autojunk=False,
    )
    char_ratio = char_matcher.ratio()

    transcript_vocab = set(transcript_tokens)
    missing_words = [token for token in expected_tokens if token not in transcript_vocab]
    coverage_ratio = 1 - (len(missing_words) / len(expected_tokens))

    score = (
        (ordered_ratio * 0.5) +
        (char_ratio * 0.3) +
        (coverage_ratio * 0.2)
    ) * 100
    score = max(0.0, min(100.0, score))

    if score >= 90:
        feedback = "아주 잘했어요! 발음이 또렷해요."
    elif score >= 75:
        feedback = "좋아요! 조금 더 천천히 또박또박 읽어보세요."
    elif score >= 55:
        feedback = "좋은 시도예요! 빠진 단어를 확인하고 다시 읽어보면 더 좋아져요."
    else:
        feedback = "괜찮아요! 문장을 짧게 나눠서 천천히 다시 읽어보면 좋아져요."

    if missing_words:
        dedup_missing = list(dict.fromkeys(missing_words))
        preview = ", ".join(dedup_missing[:4])
        feedback = f"{feedback} 빠진 단어 예시: {preview}"

    return round(score, 2), feedback


@router.post("/evaluate")
async def evaluate_pronunciation(
    request: PronunciationEvaluateRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    score, feedback = _score_pronunciation(request.transcript, request.expected_text)

    log = PronunciationLog(
        user_key=user_key,
        book_id=request.book_id,
        page_number=request.page_number,
        transcript=request.transcript,
        expected_text=request.expected_text,
        score=score,
        feedback=feedback,
        audio_url=request.audio_url,
    )
    db.add(log)
    await db.commit()

    logger.info(
        "Pronunciation evaluated",
        book_id=request.book_id,
        page_number=request.page_number,
        score=score,
    )

    return {
        "score": score,
        "feedback": feedback,
        "status": "success",
    }


@router.post("/evaluate-audio")
async def evaluate_pronunciation_audio(
    expected_text: str = Form(..., min_length=1, max_length=4000),
    audio_file: UploadFile = File(..., description="아이 발화 오디오"),
    book_id: Optional[str] = Form(default=None),
    page_number: Optional[int] = Form(default=None),
    language: str = Form(default="ko"),
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    # H1/G9: STT 비활성 배포에서는 provider 해석 실패 500 대신 명시적 미지원으로 차단.
    require_audio_supported()

    if page_number is not None and not (1 <= page_number <= 12):
        raise ValidationError("page_number는 1~12 범위여야 합니다.")
    # H3: 발음 평가 언어를 스토리 5개 언어로 확장(ja/zh/es 한국어 오전사·저점 채점 제거).
    from src.services.stt import SUPPORTED_STT_LANGUAGES

    if language not in SUPPORTED_STT_LANGUAGES:
        raise ValidationError(
            f"지원하지 않는 언어입니다: {language} "
            f"(지원: {', '.join(SUPPORTED_STT_LANGUAGES)})"
        )
    if not audio_file.content_type or not audio_file.content_type.startswith("audio/"):
        raise ValidationError("오디오 파일만 업로드 가능합니다.")

    audio_bytes = await audio_file.read()
    if not audio_bytes:
        raise ValidationError("빈 오디오 파일은 평가할 수 없습니다.")
    if len(audio_bytes) > _MAX_PRONUNCIATION_AUDIO_BYTES:
        raise ValidationError("발음 평가 오디오는 15MB 이하여야 합니다.")

    transcript = await stt_service.transcribe_audio(
        audio_bytes,
        mime_type=audio_file.content_type or "audio/mp4",
        language=language,
    )
    score, feedback = _score_pronunciation(transcript, expected_text)

    log = PronunciationLog(
        user_key=user_key,
        book_id=book_id,
        page_number=page_number,
        transcript=transcript,
        expected_text=expected_text,
        score=score,
        feedback=feedback,
    )
    db.add(log)
    await db.commit()

    logger.info(
        "Pronunciation evaluated from audio",
        book_id=book_id,
        page_number=page_number,
        language=language,
        score=score,
    )

    return {
        "score": score,
        "feedback": feedback,
        "transcript": transcript,
        "status": "success",
    }
