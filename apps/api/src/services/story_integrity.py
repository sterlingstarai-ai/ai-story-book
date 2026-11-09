"""Deterministic generated-text checks; this is not a semantic quality assessment.

Never repair model prose or log rejected text. Korean narrative allows caller-supplied
Latin spellings and English-only quotations in an explicitly requested English lesson.
Translation/learning fields are separate models and retain their selected language.
"""

from collections.abc import Iterable
import re
import unicodedata

from pydantic import BaseModel
import structlog

from src.core.errors import ErrorCode, LLMError
from src.models import dto
from src.models.dto import BookSpec, Language, StoryDraft, TargetAge

logger = structlog.get_logger()

# Newlines/tabs are intentional layout; joiners can be meaningful in names/emoji.
_ALLOWED_CONTROLS = frozenset("\n\r\t\u200c\u200d")
_QUOTED_PHRASES = re.compile(r'"([^"\n]+)"|“([^”\n]+)”|‘([^’\n]+)’|\'([^\'\n]+)\'|「([^」\n]+)」')
_ENGLISH_SUBJECT = re.compile(r"영어|영단어|알파벳|\benglish\b", re.IGNORECASE)
_LEARNING_INTENT = re.compile(r"배우|배움|학습|공부|연습|단어|인사|노래|놀이|가르|읽기|\blearn(?:ing)?\b|\blesson\b", re.IGNORECASE)

MIN_LONG_STORY_PAGE_WORDS = 40
MIN_LONG_STORY_PAGES = 9


def requires_long_korean_story(spec: BookSpec) -> bool:
    return spec.language == Language.ko and spec.target_age == TargetAge.a7_9 and spec.page_count == 12


def count_story_words(text: str) -> int:
    """Count whitespace-delimited eojeol and ignore standalone punctuation."""
    return sum(any(character.isalnum() for character in word) for word in text.split())


def _is_latin_letter(character: str) -> bool:
    return character.isalpha() and "LATIN" in unicodedata.name(character, "")


def _latin_tokens(text: str):
    """Unicode Latin tokens with original spans, retaining accents and identifiers."""
    start = None
    for position, character in enumerate(text):
        latin = _is_latin_letter(character)
        continuation = start is not None and (
            character.isdecimal() or unicodedata.category(character).startswith("M")
        )
        if latin or continuation:
            if start is None:
                start = position
        elif start is not None:
            yield start, position, unicodedata.normalize("NFC", text[start:position]).casefold()
            start = None
    if start is not None:
        yield start, len(text), unicodedata.normalize("NFC", text[start:]).casefold()


def _model_strings(value, path=""):
    # Iterate declared schema fields, never provider-controlled dictionary keys.
    if isinstance(value, BaseModel):
        model_type = type(value)
        owned = model_type.__module__ == dto.__name__ and getattr(dto, model_type.__name__, None) is model_type
        for field in type(value).model_fields:
            field_path = (f"{path}.{field}" if path else field) if owned else (path or "$")
            yield from _model_strings(getattr(value, field), field_path)
    elif isinstance(value, list):
        for item in value:
            yield from _model_strings(item, path + "[]")
    elif isinstance(value, str):
        yield path, value


def _invalid_unicode(text: str) -> bool:
    for character in text:
        point = ord(character)
        if character == "\ufffd" or unicodedata.category(character) == "Cs":
            return True
        if 0xFDD0 <= point <= 0xFDEF or (point & 0xFFFF) in {0xFFFE, 0xFFFF}:
            return True
        if unicodedata.category(character) in {"Cc", "Cf"} and character not in _ALLOWED_CONTROLS:
            return True
    return False


def _reject(issues: list[dict[str, str]]):
    if not issues:
        return
    # Values are fixed policy names and model-owned paths, never token/snippet/offset data.
    distinct = sorted({(issue["field_path"], issue["rule"]) for issue in issues})
    logger.warning(
        "Generated text integrity check failed",
        integrity_issue_count=len(issues),
        integrity_diagnostics=[{"field_path": path, "rule": rule} for path, rule in distinct[:12]],
    )
    raise LLMError(ErrorCode.LLM_JSON_INVALID, "생성된 글이 문자·언어 형식 검사를 통과하지 못했습니다.")


def validate_generated_text_unicode(model: BaseModel) -> None:
    """Apply Unicode hygiene without restricting translation/learning languages."""
    _reject([
        {"field_path": path, "rule": "invalid_unicode"}
        for path, text in _model_strings(model) if _invalid_unicode(text)
    ])


def _english_lesson_spans(text: str, requested: bool):
    if not requested:
        return []
    spans = []
    for match in _QUOTED_PHRASES.finditer(text):
        phrase = next(value for value in match.groups() if value is not None)
        # A quoted Korean sentence containing a stray Latin adverb is not a lesson phrase.
        if any(character.isalpha() and not _is_latin_letter(character) for character in phrase):
            continue
        if any(_is_latin_letter(character) for character in phrase):
            spans.append(match.span())
    return spans


def validate_story_integrity(
    story: StoryDraft, spec: BookSpec, *, supplied_character_names: Iterable[str] = ()
) -> None:
    """Reject malformed text before the story proceeds to character/image generation."""
    validate_generated_text_unicode(story)
    if story.language != spec.language:
        _reject([{"field_path": "language", "rule": "requested_language_mismatch"}])
    if spec.language != Language.ko:
        return

    supplied = [spec.topic, spec.protagonist_name or "", *supplied_character_names]
    if spec.character:
        supplied.append(spec.character.name)
    allowed_tokens = {token for text in supplied for _, _, token in _latin_tokens(text)}
    english_lesson = bool(_ENGLISH_SUBJECT.search(spec.topic) and _LEARNING_INTENT.search(spec.topic))
    narrative = [("title", story.title), ("moral", story.moral), ("cover.cover_text", story.cover.cover_text)]
    for page in story.pages:
        narrative.extend((f"pages[].{field}", getattr(page, field) or "")
                         for field in ("text", "learning_point", "series_hook"))
    issues = []
    for path, text in narrative:
        lesson_spans = _english_lesson_spans(text, english_lesson)
        for start, end, token in _latin_tokens(text):
            if token in allowed_tokens or any(left <= start and end <= right for left, right in lesson_spans):
                continue
            issues.append({"field_path": path, "rule": "unexpected_latin_in_korean_narrative"})
            break
    _reject(issues)
