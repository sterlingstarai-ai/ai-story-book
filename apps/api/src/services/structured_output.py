"""Wire-only schema adaptation; the original Pydantic model remains authoritative.

Story and image-prompt callers opt in explicitly. Schemas contain DTO-owned definitions only,
never user names, prompts, API keys or per-request enum/const substitutions.
Official contracts checked 2026-09-06:
https://platform.claude.com/docs/en/build-with-claude/structured-outputs
https://developers.openai.com/api/docs/guides/structured-outputs
"""

from copy import deepcopy
from typing import Literal

# Explicit verified aliases only. Do not infer support from a family name/date.
ANTHROPIC_SCHEMA_MODELS = frozenset({"claude-sonnet-5", "claude-opus-5"})
_ANTHROPIC_UNSUPPORTED = frozenset({
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "maxItems",
})


def provider_output_schema(schema: dict, *, provider: Literal["anthropic", "openai"]) -> dict:
    """Copy the wire schema without weakening the model used for final validation."""
    result = deepcopy(schema)

    def adapt(node):
        if not isinstance(node, dict):
            return
        if provider == "anthropic":
            for keyword in _ANTHROPIC_UNSUPPORTED:
                node.pop(keyword, None)
            if node.get("minItems", 0) > 1:
                node.pop("minItems")
        else:
            # Strict OpenAI requires each field's presence. Existing optional
            # StoryDraft/ImagePrompts fields retain their anyOf/null alternatives.
            if "properties" in node:
                node["required"] = list(node["properties"])
            # Defaults are local Pydantic behavior, not generation constraints.
            # In particular ImagePrompt's aspect_ratio defaults to "3:4" locally.
            node.pop("default", None)
        if "properties" in node:
            node["additionalProperties"] = False
            for child in node["properties"].values():
                adapt(child)
        for definitions in ("$defs", "definitions"):
            for child in node.get(definitions, {}).values():
                adapt(child)
        adapt(node.get("items"))
        for alternative in ("anyOf", "allOf", "oneOf"):
            for child in node.get(alternative, []):
                adapt(child)

    adapt(result)
    return result
