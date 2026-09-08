"""Choose only text that actually exists in the requested language."""


def audio_texts(text: str, text_ko: str | None, text_en: str | None,
                book_language: str) -> dict[str, str]:
    result = {}
    if text and text.strip():
        result[book_language] = text
    if text_ko and text_ko.strip():
        result["ko"] = text_ko
    if text_en and text_en.strip():
        result["en"] = text_en
    return result
