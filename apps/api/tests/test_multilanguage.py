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
