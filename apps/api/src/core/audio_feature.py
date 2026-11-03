"""오디오(TTS/STT) 기능 가용성 판정 — readiness·capabilities·엔드포인트 게이트 공용 정본.

H1/G9: 오디오는 GA에서 기본 비활성(audio_feature_enabled=False)이다. 이 판정이 readiness에만
배선돼 있으면 비활성 구성에서 낭독/발음 요청이 provider 해석 실패로 500이 된다(기능이
'명시적으로 비활성'이 아니라 '전면 에러'). 여기서 단일 정본을 제공해 readiness, 클라이언트
게이팅용 /v1/config/capabilities, 오디오 엔드포인트 가드가 같은 기준을 쓰게 한다.
"""

from fastapi import HTTPException
import re

from src.core.config import settings

# 이 코드로 클라이언트는 '일시 장애'가 아닌 '이 배포에서 미지원'을 구분한다(인페인트 패턴 동일).
AUDIO_NOT_SUPPORTED_CODE = "AUDIO_NOT_SUPPORTED"


def tts_readiness_issues() -> list[str]:
    """오디오 기능 ON 상태에서 TTS/STT가 라이브 미구성이면 사유 목록을 반환한다(H1).

    mock/미지 provider는 무음 오디오·가짜 발음 점수를 성공으로 서빙하므로 readiness를 막는다.
    """
    issues: list[str] = []

    tts = (settings.tts_provider or "").strip().lower()
    if tts in {"openai", "openai_realtime"}:
        if not settings.openai_tts_api_key:
            issues.append("tts_key")
    elif tts == "google":
        if not settings.google_tts_api_key:
            issues.append("tts_key")
    elif tts == "google_gemini":
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", settings.google_gemini_tts_project or ""):
            issues.append("tts_project")
        if settings.google_gemini_tts_daily_request_limit <= 0 or settings.google_gemini_tts_monthly_request_limit <= 0:
            issues.append("tts_request_budget")
    elif tts == "elevenlabs":
        if not settings.elevenlabs_api_key:
            issues.append("tts_key")
    else:
        issues.append("tts_provider_not_live")

    return issues


def stt_readiness_issues() -> list[str]:
    issues: list[str] = []
    stt = (settings.stt_provider or "").strip().lower()
    if stt == "openai":
        if not (settings.stt_api_key or (
            settings.llm_api_key if settings.llm_provider == "openai" else None
        )):
            issues.append("stt_key")
    elif stt == "google":
        if not settings.google_stt_api_key:
            issues.append("stt_key")
    else:
        issues.append("stt_provider_not_live")

    return issues


def audio_readiness_issues() -> list[str]:
    issues = tts_readiness_issues()
    if not settings.audio_narration_only_enabled:
        issues += stt_readiness_issues()
    return issues


def audio_supported() -> bool:
    """이 배포에서 오디오·발음 기능을 실제로 제공할 수 있는가.

    기능 플래그가 켜져 있고 TTS/STT가 라이브 구성일 때만 True. 플래그만 켜고 provider가
    mock이면 무음 오디오를 성공으로 서빙하게 되므로 '지원'으로 광고하지 않는다.
    """
    if not settings.audio_feature_enabled:
        return False
    return not (tts_readiness_issues() or stt_readiness_issues())


def narration_supported() -> bool:
    if not settings.audio_feature_enabled:
        return False
    if not settings.audio_narration_only_enabled:
        return audio_supported()
    return not tts_readiness_issues()


def narration_voice_selection_supported() -> bool:
    """Only expose choices whose built-in voice mapping is implemented."""
    return narration_supported() and (settings.tts_provider or "").strip().lower() in {"openai", "openai_realtime", "google_gemini"}


def narration_style_selection_supported() -> bool:
    """Expressive style instructions require the OpenAI mini TTS model."""
    return narration_voice_selection_supported() and ((settings.tts_provider or "").strip().lower() in {"openai_realtime", "google_gemini"} or (settings.openai_tts_model or "").startswith("gpt-4o-mini-tts"))


def require_audio_supported() -> None:
    """오디오 미지원 배포에서 명시적 4xx로 차단(500 대신). 인페인트 409 패턴과 동일."""
    if audio_supported():
        return
    raise HTTPException(
        status_code=409,
        detail={
            "code": AUDIO_NOT_SUPPORTED_CODE,
            "message": "이 배포에서는 오디오 기능을 사용할 수 없습니다.",
        },
    )


def require_narration_supported() -> None:
    if narration_supported():
        return
    raise HTTPException(status_code=409, detail={
        "code": AUDIO_NOT_SUPPORTED_CODE,
        "message": "이 배포에서는 오디오 기능을 사용할 수 없습니다.",
    })


def voice_profiles_supported() -> bool:
    """Narration providers do not consume family-voice samples in this release."""
    return False


def require_voice_profiles_supported() -> None:
    if voice_profiles_supported():
        return
    raise HTTPException(status_code=409, detail={
        "code": "VOICE_PROFILE_NOT_SUPPORTED",
        "message": "가족 목소리 등록은 지원하지 않습니다. 저장된 음성 삭제와 동의 철회는 이용할 수 있습니다.",
    })
