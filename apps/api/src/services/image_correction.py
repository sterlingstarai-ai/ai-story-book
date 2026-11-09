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
        "Follow the narrative over conflicting staging or cast counts. Show only its stated actors. "
        "Connect each held prop to the named actor's hand; observers keep hands clear. "
        "Show direct actions without adding tools. Keep each prop's stated count, state and position. "
        "Match contact, scale and flow; keep beside distinct from inside. "
        "Trace water from source to destination. Barrels overflow high, never from the lower tap. "
        "If an action stops, show the stopped state. For stopped water, show wet traces and closed fittings "
        "or crop the fittings out. No fresh stream or drips. "
        "Show visible pages in an open book. "
        "Depict planning as talk, not action; objects only on plans stay on paper. "
        "Distinguish ascent from descent. No duplicate wearables; keep stated spares, including shoes with unused skates."
    ),
}
MAX_CORRECTION_NARRATIVE = 600
MAX_NEIGHBOR_NARRATIVE = 200
MAX_PROVIDER_POSITIVE_PROMPT = 3000
# Allow room for the provider's reference rules and the full negative prompt.
MAX_POSITIVE_PROMPT_WITH_NEIGHBORS = 2940
CAST_LOOKS_PREFIX = "CAST LOOKS: "
CAST_DETAILS_PREFIX = "CAST DETAILS: "
ACTION_FOCUS_PREFIX = "ACTION FOCUS: "
MAX_ACTION_FOCUS = 180
MAX_CAST_DETAILS = 360


@dataclass(frozen=True)
class ImageCorrection:
    page_text: str
    issues: tuple[str, ...]
    source_image_url: str | None = None
    previous_page_text: str = ""
    next_page_text: str = ""
    use_prompt_action_focus: bool = False


_correction: ContextVar[ImageCorrection | None] = ContextVar("image_correction", default=None)


@contextmanager
def image_correction_scope(*, page_text: str, issues: list[str], source_image_url: str | None = None,
                           previous_page_text: str = "", next_page_text: str = "",
                           use_prompt_action_focus: bool = False):
    """Accept finite issue codes, never reviewer-authored repair instructions."""
    if not page_text.strip() or not issues or any(i not in CORRECTION_INSTRUCTIONS for i in issues):
        raise ImageError(ErrorCode.IMAGE_QUALITY_FAILED, "삽화 교정 입력이 유효하지 않습니다.")
    if source_image_url is not None and (not isinstance(source_image_url, str) or not source_image_url.strip()):
        raise ImageError(ErrorCode.IMAGE_QUALITY_FAILED, "삽화 교정 참조가 유효하지 않습니다.")
    token = _correction.set(ImageCorrection(
        page_text, tuple(dict.fromkeys(issues)), source_image_url, previous_page_text, next_page_text,
        use_prompt_action_focus,
    ))
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


def image_correction_active() -> bool:
    return _correction.get() is not None


def _prompt_action_focus(positive_prompt: str) -> str:
    first_line, separator, brief = positive_prompt.partition("\n")
    if not separator or not brief.strip() or not first_line.startswith(ACTION_FOCUS_PREFIX):
        return ""
    focus = first_line.removeprefix(ACTION_FOCUS_PREFIX).strip()
    return focus if 0 < len(focus) <= MAX_ACTION_FOCUS and focus.isprintable() else ""


def _prompt_cast_details(positive_prompt: str) -> str:
    first, _, remaining = positive_prompt.partition("\n")
    line, separator, scene = remaining.partition("\n")
    if not first.startswith(ACTION_FOCUS_PREFIX) or not separator or not scene.strip():
        return ""
    if not line.startswith(CAST_DETAILS_PREFIX):
        return ""
    details = line.removeprefix(CAST_DETAILS_PREFIX).strip()
    return details if 0 < len(details) <= MAX_CAST_DETAILS and details.isprintable() else ""


def provider_prompt_with_correction(prompt: ImagePrompt, *, use_cast_looks: bool = False) -> ImagePrompt:
    context = _correction.get()
    if context is None:
        return prompt
    instructions = " ".join(CORRECTION_INSTRUCTIONS[issue] for issue in context.issues)
    narrative = context.page_text[:MAX_CORRECTION_NARRATIVE]
    if "action_mismatch" in context.issues:
        # The prior brief can itself contain the staging error. New books keep
        # character appearance separately; older saved prompts retain their brief.
        cast_looks = (prompt.guidance_notes or "").strip()
        has_cast_looks = use_cast_looks and cast_looks.startswith(CAST_LOOKS_PREFIX) and cast_looks.isprintable()
        details = _prompt_cast_details(prompt.positive_prompt) if context.use_prompt_action_focus else ""
        if details:
            visual_details = f"CAST DETAILS (fixed appearance of current cast only): {details}"
        else:
            visual_details = cast_looks if has_cast_looks else f"COMPATIBLE BRIEF: {prompt.positive_prompt}"
        focus = _prompt_action_focus(prompt.positive_prompt) if (details or has_cast_looks) and context.use_prompt_action_focus else ""
        focus_line = f"ACTION FOCUS (only if supported by the current narrative): {focus}\n" if focus else ""
        positive = (
            f"CURRENT PAGE NARRATIVE: {narrative}\n"
            f"{focus_line}"
            f"CORRECTION REQUIREMENTS: {instructions}\n"
            f"{visual_details}"
        )
        neighbors = []
        for label, text in (("Previous page", context.previous_page_text), ("Next page", context.next_page_text)):
            if text.strip():
                neighbors.append(f"{label}: {text.strip()[:MAX_NEIGHBOR_NARRATIVE]}")
        if neighbors:
            continuity = (
                "\nNEIGHBORING PAGES (persistent setting and props only; do not show their actions or later states):\n"
                + "\n".join(neighbors)
            )
            if len(positive) + len(continuity) <= MAX_POSITIVE_PROMPT_WITH_NEIGHBORS:
                positive += continuity
    else:
        positive = (
            f"{prompt.positive_prompt}\n\n"
            f"CORRECTION REQUIREMENTS (preserve all character identities above): {instructions}\n"
            f"CURRENT PAGE NARRATIVE (depict this exact moment): {narrative}"
        )
    if len(positive) > MAX_PROVIDER_POSITIVE_PROMPT:
        raise ImageError(ErrorCode.IMAGE_QUALITY_FAILED, "삽화 교정 요청이 너무 깁니다.")
    # Adapter-private wire value only. Do not persist this expanded prompt or
    # change the public/LLM ImagePrompt schema's 1200-character limit.
    return prompt.model_copy(update={"positive_prompt": positive})
