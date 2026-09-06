"""Synthetic acceptance-only HTTP budget/usage instrumentation, injected in a source copy.

Never imported by the application or used in production. No prompts, URLs, headers,
provider bodies, or credentials enter the journal. Reservations survive process exits.
"""

import base64
import binascii
import fcntl
from io import BytesIO
import json
import os
from pathlib import Path
import time

import httpx
from PIL import Image, UnidentifiedImageError

LLM_MODELS = {
    "claude-sonnet-5": "anthropic", "claude-opus-5": "anthropic",
    "gpt-6-astra": "openai", "gpt-5.6-sol": "openai",
}
IMAGE_MODELS = frozenset({"gemini-3-pro-image", "gemini-3.1-flash-image"})
LLM_TOKEN_LIMITS = {"anthropic": 8000, "openai": 16000}
ACCEPTANCE_PAGE_COUNTS = (4, 8)
JOURNAL_VERSION = 2


def request_limits(page_count, quality_enabled):
    """No caller-controlled numeric limit: only a supported book size and gate flag."""
    if (type(page_count) is not int or page_count not in ACCEPTANCE_PAGE_COUNTS
            or type(quality_enabled) is not bool):
        raise RuntimeError("LIVE_ACCEPTANCE_INVALID_BOOK_SELECTION")
    return {"llm": 16, "image": page_count + 1 + (2 if quality_enabled else 0)}


def image_dimensions(body):
    """Inspect every returned image, including candidates later replaced or discarded.

    Return only dimensions plus completeness. A malformed image must make cost
    estimation unavailable, not fall back to a different final book image.
    """
    dimensions = []
    if not isinstance(body, dict):
        return dimensions, False
    candidates = body.get("candidates", [])
    if not isinstance(candidates, list):
        return dimensions, False
    try:
        for candidate in candidates:
            parts = candidate.get("content", {}).get("parts", [])
            if not isinstance(parts, list):
                return dimensions, False
            for part in parts:
                inline = part.get("inlineData", part.get("inline_data"))
                if inline is None:
                    continue
                mime = inline.get("mimeType", inline.get("mime_type"))
                data = inline.get("data")
                formats = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
                if (mime not in formats or not isinstance(data, str) or not data
                        or len(data) > 32 * 1024 * 1024):
                    return dimensions, False
                raw = base64.b64decode(data, validate=True)
                with Image.open(BytesIO(raw)) as image:
                    if (image.format != formats[mime] or getattr(image, "is_animated", False)
                            or min(image.size) < 1 or max(image.size) > 8192
                            or image.width * image.height > 16_777_216):
                        return dimensions, False
                    size = {"width": image.width, "height": image.height}
                    image.verify()
                dimensions.append(size)
        return dimensions, True
    except (AttributeError, TypeError, ValueError, binascii.Error, UnidentifiedImageError,
            OSError, SyntaxError, Image.DecompressionBombError):
        return dimensions, False


def validate_selection(provider, llm_model, image_model):
    if LLM_MODELS.get(llm_model) != provider or image_model not in IMAGE_MODELS:
        raise RuntimeError("LIVE_ACCEPTANCE_INVALID_MODEL_SELECTION")


def append_event(path, event, *, limit=None):
    with open(path, "a+", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        if limit is not None:
            stream.seek(0)
            count = sum(json.loads(line).get("kind") == "request"
                        and json.loads(line).get("role") == event["role"] for line in stream)
            if count >= limit:
                raise RuntimeError("LIVE_ACCEPTANCE_REQUEST_LIMIT")
        stream.write(json.dumps(event) + "\n")
        stream.flush()


def install():
    journal = Path(os.environ["LIVE_ACCEPTANCE_JOURNAL"])
    provider = os.environ.get("LLM_PROVIDER")
    llm_model = os.environ.get("LLM_MODEL")
    image_model = os.environ.get("IMAGE_MODEL")
    validate_selection(provider, llm_model, image_model)
    page_count = os.environ.get("LIVE_ACCEPTANCE_PAGE_COUNT", "8")
    enabled = os.environ.get("ILLUSTRATION_QUALITY_ENABLED", "false")
    if page_count not in {str(count) for count in ACCEPTANCE_PAGE_COUNTS} or enabled not in {"true", "false"}:
        raise RuntimeError("LIVE_ACCEPTANCE_INVALID_BOOK_SELECTION")
    if enabled == "true" and provider != "openai":
        raise RuntimeError("LIVE_ACCEPTANCE_UNSUPPORTED_QUALITY_PROVIDER")
    limits = request_limits(int(page_count), enabled == "true")
    original = httpx.AsyncClient.post
    urls = {
        ("https://api.openai.com/v1/responses" if provider == "openai"
         else "https://api.anthropic.com/v1/messages"): ("llm", limits["llm"]),
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + image_model + ":generateContent": ("image", limits["image"]),
    }

    async def measured(self, url, **kwargs):
        if (str(url) not in urls or kwargs.get("params")
                or kwargs.get("follow_redirects", self.follow_redirects) is not False):
            raise RuntimeError("LIVE_ACCEPTANCE_UNEXPECTED_POST")
        role, limit = urls[str(url)]
        payload = kwargs.get("json", {})
        if not isinstance(payload, dict):
            raise RuntimeError("LIVE_ACCEPTANCE_INVALID_PAYLOAD")
        if role == "llm":
            if payload.get("model") != llm_model:
                raise RuntimeError("LIVE_ACCEPTANCE_MODEL_MISMATCH")
            field = "max_output_tokens" if provider == "openai" else "max_tokens"
            tokens = payload.get(field)
            if type(tokens) is not int or not 1 <= tokens <= LLM_TOKEN_LIMITS[provider]:
                raise RuntimeError("LIVE_ACCEPTANCE_TOKEN_LIMIT")
            if provider == "openai" and (
                payload.get("store") is not False
                or payload.get("service_tier", "default") != "default"
                or payload.get("background", False) is not False
                or payload.get("tools")
            ):
                raise RuntimeError("LIVE_ACCEPTANCE_OPENAI_OPTIONS")
        # No image request fields are rewritten: retain the verified live shape.
        identity = {"role": role, "provider": provider if role == "llm" else "gemini",
                    "model": llm_model if role == "llm" else image_model}
        append_event(journal, {"kind": "request", **identity}, limit=limit)
        started = time.monotonic()
        event = {"kind": "response", "journal_version": JOURNAL_VERSION, **identity}
        if role == "image":
            event.update(image_dimensions=[], image_dimensions_complete=False)
        try:
            response = await original(self, url, **kwargs)
            event["http_status"] = response.status_code
            try:
                body = response.json()
                if role == "image":
                    sizes, complete = image_dimensions(body)
                    event.update(image_dimensions=sizes, image_dimensions_complete=complete)
                usage = body.get("usage" if role == "llm" else "usageMetadata", {})
                names = ("input_tokens", "output_tokens") if role == "llm" else (
                    "promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount", "totalTokenCount")
                event["usage"] = {key: usage[key] for key in names
                                  if type(usage.get(key)) is int and usage[key] >= 0}
            except (ValueError, AttributeError):
                pass
            return response
        except Exception as error:
            event["failure"] = type(error).__name__
            raise
        finally:
            event["seconds"] = round(time.monotonic() - started, 3)
            append_event(journal, event)

    httpx.AsyncClient.post = measured
