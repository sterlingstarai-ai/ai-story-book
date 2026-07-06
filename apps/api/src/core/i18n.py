"""다국어(i18n) 기반.

스토리 생성을 언어 파라미터화하기 위한 지원 언어 + 표시명.
**새 언어 추가 = 이 매핑에 한 줄 + dto.Language enum 값 추가 + (선택) 언어별 프롬프트 검토**
만으로 additive 하게 확장된다. 데이터 모델(Book/Page의 _ko/_en, Language enum)은 이미 N-언어 ready.
"""

# code -> LLM에 전달할 언어 표시명(해당 언어로 생성하도록 지시)
LANGUAGE_DISPLAY_NAMES = {
    "ko": "한국어",
    "en": "English",
    "ja": "日本語",
    "zh": "中文",
    "es": "Español",
}

# 현재 지원(활성) 언어 코드 목록
SUPPORTED_LANGUAGES = list(LANGUAGE_DISPLAY_NAMES.keys())

DEFAULT_LANGUAGE = "ko"


def language_display_name(code: str) -> str:
    """언어 코드의 표시명. 미지원 코드는 기본 언어명으로 폴백."""
    return LANGUAGE_DISPLAY_NAMES.get(code, LANGUAGE_DISPLAY_NAMES[DEFAULT_LANGUAGE])
