"""Task-local, code-owned correction context added only to provider requests.

The persisted ImagePrompt remains within its public schema and retains every
character description. Correction instructions must never displace that context.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from src.core.errors import ErrorCode, ImageError
from src.models.dto import ImagePrompt


CORRECTION_INSTRUCTIONS = {
    "printed_instructions": "Remove all printed instructions, labels and typography.",
    "readable_text": "Remove all readable text, letters, numbers and captions; leave signs blank.",
    "duplicate_character": "Draw each named character exactly once; remove clones and extra bystanders.",
    "identity_swap": "Restore each character's own face, hair, outfit and colors; do not exchange identities.",
    "action_mismatch": (
        "The narrative overrides conflicting staging. Show all stated actors, contact, direction, "
        "destination and object state. Show visible pages in an open book; do not invent a state. "
        "Depict planning as talk, not action; objects only on plans stay on paper. "
        "Distinguish ascent from descent. Keep identities, clothes and style. Show each prop only "
        "in its current state and place. No duplicate wearables; keep stated spares. "
        "Shoes and unused skates may coexist."
    ),
}
MAX_CORRECTION_NARRATIVE = 600
MAX_PROVIDER_POSITIVE_PROMPT = 3000


@dataclass(frozen=True)
class ImageCorrection:
    page_text: str
    issues: tuple[str, ...]
    source_image_url: str | None = None


_correction: ContextVar[ImageCorrection | None] = ContextVar("image_correction", default=None)


@contextmanager
def image_correction_scope(*, page_text: str, issues: list[str], source_image_url: str | None = None):
    """Accept finite issue codes, never reviewer-authored repair instructions."""
    if not page_text.strip() or not issues or any(i not in CORRECTION_INSTRUCTIONS for i in issues):
        raise ImageError(ErrorCode.IMAGE_QUALITY_FAILED, "삽화 교정 입력이 유효하지 않습니다.")
    if source_image_url is not None and (not isinstance(source_image_url, str) or not source_image_url.strip()):
        raise ImageError(ErrorCode.IMAGE_QUALITY_FAILED, "삽화 교정 참조가 유효하지 않습니다.")
    token = _correction.set(ImageCorrection(page_text, tuple(dict.fromkeys(issues)), source_image_url))
    try:
        yield
    finally:
        _correction.reset(token)


def correction_scene_reference() -> str | None:
    """A trusted, already ownership-checked page can anchor a local defect edit.

    Identity/cast/action defects still need the caller's approved character reference;
    copying the erroneous character would reinforce that defect. Prompt text or
    reviewer prose cannot choose a source URL or enter this scope.
    """
    context = _correction.get()
    if context is None or set(context.issues) & {"identity_swap", "duplicate_character", "action_mismatch"}:
        return None
    return context.source_image_url


def provider_prompt_with_correction(prompt: ImagePrompt) -> ImagePrompt:
    context = _correction.get()
    if context is None:
        return prompt
    instructions = " ".join(CORRECTION_INSTRUCTIONS[issue] for issue in context.issues)
    positive = (
        f"{prompt.positive_prompt}\n\n"
        f"CORRECTION REQUIREMENTS (preserve all character identities above): {instructions}\n"
        "CURRENT PAGE NARRATIVE (depict this exact moment): "
        f"{context.page_text[:MAX_CORRECTION_NARRATIVE]}"
    )
    if len(positive) > MAX_PROVIDER_POSITIVE_PROMPT:
        raise ImageError(ErrorCode.IMAGE_QUALITY_FAILED, "삽화 교정 요청이 너무 깁니다.")
    # Adapter-private wire value only. Do not persist this expanded prompt or
    # change the public/LLM ImagePrompt schema's 1200-character limit.
    return prompt.model_copy(update={"positive_prompt": positive})
