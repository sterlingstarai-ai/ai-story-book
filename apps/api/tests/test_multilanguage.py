"""P2-17: 새 언어(zh, es)가 Language enum/i18n/스토리 프롬프트에 additive하게 추가되는지."""

from src.core.i18n import SUPPORTED_LANGUAGES, language_display_name
from src.models.dto import BookSpec, Language
from src.services.llm import render_prompt


def test_language_enum_includes_new_languages():
    assert Language("zh") == Language.zh
    assert Language("es") == Language.es


def test_supported_languages_and_display_names():
    assert "zh" in SUPPORTED_LANGUAGES
    assert "es" in SUPPORTED_LANGUAGES
    assert language_display_name("zh") == "中文"
    assert language_display_name("es") == "Español"


def test_book_spec_accepts_new_language():
    spec = BookSpec(
        topic="una aventura en el bosque",
        language="es",
        target_age="5-7",
        style="watercolor",
    )
    assert spec.language == Language.es


def test_story_system_prompt_renders_new_language_name():
    prompt = render_prompt(
        "generate_story.system.jinja2",
        page_count=8,
        language="es",
        language_name=language_display_name("es"),
    )
    assert "Español" in prompt


# ---- H3: 오디오 언어 표면 ko/en → 5개 스토리 언어 ----


def test_resolve_tts_language_covers_all_story_languages():
    """H3: ko/en/ja/zh/es 전부 고유 언어코드로 매핑(ja→ja-JP, 한국어 보이스 오합성 방지)."""
    from src.services.tts import resolve_tts_language

    assert resolve_tts_language("ko")[0] == "ko-KR"
    assert resolve_tts_language("en")[0] == "en-US"
    assert resolve_tts_language("ja")[0] == "ja-JP"
    assert resolve_tts_language("zh")[0] == "cmn-CN"
    assert resolve_tts_language("es")[0] == "es-ES"
    # 각 언어 기본 보이스가 존재
    for code in ("ko", "en", "ja", "zh", "es"):
        _lc, voice = resolve_tts_language(code)
        assert isinstance(voice, str) and voice


def test_resolve_tts_language_rejects_unsupported():
    """H3: 매핑 밖 언어는 무음/오합성 폴백 금지 — 명시 예외."""
    import pytest as _pytest

    from src.services.tts import resolve_tts_language

    with _pytest.raises(ValueError):
        resolve_tts_language("fr")


def test_stt_language_codes_cover_story_languages():
    """H3: STT도 5개 스토리 언어를 매핑(발음 평가 한국어 오전사 제거)."""
    from src.services.stt import STT_LANGUAGE_CODES, SUPPORTED_STT_LANGUAGES

    assert set(SUPPORTED_STT_LANGUAGES) == {"ko", "en", "ja", "zh", "es"}
    for code in ("ko", "en", "ja", "zh", "es"):
        assert STT_LANGUAGE_CODES[code]
