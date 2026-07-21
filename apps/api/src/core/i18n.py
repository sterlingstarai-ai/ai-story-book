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
    """언어 코드의 표시명. 미지원 코드는 조용한 ko 폴백 대신 ValueError로 시끄럽게 실패한다(L16)
    — enum만 추가하고 이 맵 갱신을 빠뜨리면 신규 언어 책이 전부 한국어로 조용히 생성되는 잠복을
    즉시 드러내기 위함. 정상 호출부는 모두 Language enum.value를 넘기므로 정상 경로 무영향."""
    try:
        return LANGUAGE_DISPLAY_NAMES[code]
    except KeyError as exc:
        raise ValueError(f"Unsupported language code: {code!r}") from exc
