"""클라이언트가 기능 가용성을 사전 조회하는 가벼운 capability 엔드포인트."""

from fastapi import APIRouter

from src.core.audio_feature import audio_supported
from src.services.image import supports_inpaint

router = APIRouter()


@router.get("/capabilities")
async def get_capabilities() -> dict:
    """배포 환경 기능 가용성. 클라이언트 UI 게이팅용(예: 부분 재생성 메뉴 노출 여부)."""
    return {
        # image_provider가 replicate/fal일 때만 인페인트(부분 재생성) 가능
        "inpaint_supported": supports_inpaint(),
        # H1/G9: 오디오 기능 플래그 + TTS/STT 라이브 구성일 때만 낭독·발음 제공.
        # 클라이언트는 이 값으로 낭독 버튼/발음 메뉴를 숨긴다(비활성 구성 500 방지).
        "audio_supported": audio_supported(),
    }
