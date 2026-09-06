#!/usr/bin/env python3
"""Opt-in, two-request provider-adapter smoke with synthetic data and local artifacts."""

import argparse
import asyncio
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from dotenv import dotenv_values
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE_ROOT = ROOT / "docs" / "acceptance"
TEXT_SYSTEM = (
    '한국어 동화 작가입니다. 실제 사람이나 개인정보 없이 가상의 토끼 이야기만 씁니다. '
    '마크다운 없이 {"title":"제목","text":"이야기"} 형태의 JSON 객체만 반환하세요.'
)
TEXT_PROMPT = "토끼가 숲에서 길을 잃은 반딧불이를 집에 데려다주는 따뜻한 동화를 두 문장,100자 이내로 써 주세요."
IMAGE_PROMPT = (
    "A warm watercolor fairy-tale illustration of a fictional white rabbit wearing a blue vest, "
    "gently guiding a glowing firefly home through a peaceful forest at dusk. "
    "Pastel colors, gentle expressions, picture book art. No people, no lettering, no photographs."
)


class SmokeError(Exception):
    """Only fixed status codes from this script may cross the output boundary."""


def write_json(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def runtime_config(values):
    result = {}
    for role, provider, prefix in (("llm", "anthropic", "claude-"), ("image", "gemini", "gemini-")):
        key = (values.get(f"{role.upper()}_API_KEY") or "").strip()
        model = (values.get(f"{role.upper()}_MODEL") or "").strip()
        if (values.get(f"{role.upper()}_PROVIDER", "").lower() != provider or not key
                or not key.isascii() or any(c.isspace() for c in key)
                or not model.startswith(prefix) or key in model
                or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]{1,127}", model)):
            raise SmokeError("INVALID_CONFIGURATION")
        result.update({f"{role}_provider": provider, f"{role}_api_key": key, f"{role}_model": model})
    result.update(llm_timeout=45, image_timeout=90)
    return SimpleNamespace(**result)


class RequestBudget:
    def __init__(self, settings, transport_factory=None):
        self.settings = settings
        self.transport_factory = transport_factory
        self.metrics = {role: {"requests": 0} for role in ("llm", "image")}
        self.urls = {
            "https://api.anthropic.com/v1/messages": "llm",
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.image_model}:generateContent": "image",
        }

    def client(self, *, timeout):
        budget = self

        class Client:
            async def __aenter__(self):
                self.http = httpx.AsyncClient(
                    timeout=min(float(timeout), 90), follow_redirects=False, trust_env=False,
                    transport=(budget.transport_factory() if budget.transport_factory
                               else httpx.AsyncHTTPTransport(retries=0)),
                )
                await self.http.__aenter__()
                return self

            async def __aexit__(self, *exc):
                return await self.http.__aexit__(*exc)

            async def post(self, url, *, headers, json):
                role = budget.urls.get(url)
                if role is None or budget.metrics[role]["requests"] >= 1:
                    raise SmokeError("REQUEST_LIMIT_OR_HOST_BLOCKED")
                if role == "llm" and json.get("max_tokens") != 384:
                    raise SmokeError("OUTPUT_TOKEN_LIMIT_BLOCKED")
                if role == "image":
                    from src.models.dto import ImagePrompt
                    from src.services.image import gemini_prompt_text
                    expected = gemini_prompt_text(ImagePrompt(
                        page=1, positive_prompt=IMAGE_PROMPT,
                        negative_prompt="No people or personal data", seed=1))
                    if json.get("contents") != [{"parts": [{"text": expected}]}]:
                        raise SmokeError("UNEXPECTED_IMAGE_INPUT_BLOCKED")
                metric = budget.metrics[role]
                metric["requests"] += 1
                started = time.monotonic()
                try:
                    response = await self.http.post(url, headers=headers, json=json)
                    metric["http_status"] = response.status_code
                    try:
                        payload = response.json()
                        usage = payload.get("usage" if role == "llm" else "usageMetadata", {})
                        names = (("input_tokens", "output_tokens") if role == "llm" else
                                 ("promptTokenCount", "candidatesTokenCount", "totalTokenCount"))
                        if isinstance(usage, dict):
                            metric["token_usage"] = {name: usage[name] for name in names
                                                     if type(usage.get(name)) is int and usage[name] >= 0}
                    except (ValueError, AttributeError):
                        pass
                    return response
                finally:
                    metric["latency_seconds"] = round(time.monotonic() - started, 3)

        return Client()


def validate_story(raw, secrets):
    if not isinstance(raw, str) or len(raw) > 4000 or any(secret in raw for secret in secrets):
        raise SmokeError("INVALID_TEXT_OUTPUT")
    try:
        value = json.loads(raw)
    except ValueError:
        raise SmokeError("INVALID_TEXT_OUTPUT") from None
    if (not isinstance(value, dict) or set(value) != {"title", "text"}
            or not all(isinstance(value[k], str) for k in ("title", "text"))
            or not 2 <= len(value["title"]) <= 80 or not 20 <= len(value["text"]) <= 600
            or len(re.findall(r"[가-힣]", value["text"])) < 10 or "토끼" not in value["text"]):
        raise SmokeError("INVALID_TEXT_OUTPUT")
    return value


def failure_status(error):
    if isinstance(error, SmokeError):
        return error.args[0]
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return "TIMEOUT"
    return "NETWORK_ERROR" if isinstance(error, httpx.HTTPError) else "ADAPTER_FAILED"


async def run_smoke(values, output_dir, *, component="both", aspect_ratio="3:4", transport_factory=None):
    """Call real application adapters; the optional transport is for deterministic tests only."""
    settings = runtime_config(values)
    if component not in {"llm", "image", "both"} or aspect_ratio not in {"1:1", "3:4", "4:3", "9:16"}:
        raise SmokeError("INVALID_SMOKE_OPTIONS")
    roles = ("llm", "image") if component == "both" else (component,)
    output_dir = output_dir.resolve()
    if output_dir == ACCEPTANCE_ROOT.resolve() or not output_dir.is_relative_to(ACCEPTANCE_ROOT.resolve()):
        raise SmokeError("OUTPUT_MUST_BE_IN_IGNORED_ACCEPTANCE_DIRECTORY")
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    sys.path.insert(0, str(ROOT / "apps" / "api"))
    from src.services import image, llm
    from src.models.dto import ImagePrompt

    budget = RequestBudget(settings, transport_factory)
    report = {
        "scope": "provider_adapter_smoke", "started_at": datetime.now(timezone.utc).isoformat(),
        "synthetic_data_only": True, "storage": "local_only", "retries": 0,
        "pipeline_verified": False, "s3_verified": False, "launch_ready": False,
        "text_output_token_limit": 384, "requested_aspect_ratio": aspect_ratio, "components": {},
    }
    image_artifact = {}

    async def persist_locally(data, mime, provider):
        if provider != "gemini" or len(data) > 15 * 1024 * 1024 or image_artifact:
            raise SmokeError("INVALID_IMAGE_OUTPUT")
        try:
            with Image.open(BytesIO(data)) as decoded:
                if decoded.width * decoded.height > 16_000_000 or min(decoded.size) < 32:
                    raise SmokeError("INVALID_IMAGE_OUTPUT")
                decoded.verify()
                expected_width, expected_height = map(int, aspect_ratio.split(":"))
                relative_error = abs((decoded.width / decoded.height) / (expected_width / expected_height) - 1)
                image_artifact.update(width=decoded.width, height=decoded.height,
                                      requested_aspect_ratio=aspect_ratio,
                                      actual_aspect_ratio=f"{decoded.width}:{decoded.height}",
                                      relative_ratio_error=round(relative_error, 6))
                if relative_error > 0.02:
                    raise SmokeError("IMAGE_ASPECT_RATIO_MISMATCH")
            with Image.open(BytesIO(data)) as decoded:
                decoded.load()
                normalized = decoded.convert("RGB")
                target = output_dir / "rabbit.png"
                normalized.save(target, format="PNG")
                image_artifact.update(file="rabbit.png", width=normalized.width, height=normalized.height,
                                      sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        except (OSError, ValueError, Image.DecompressionBombError):
            raise SmokeError("INVALID_IMAGE_OUTPUT") from None
        return str(target)

    silent = SimpleNamespace(**{name: lambda *a, **k: None for name in ("info", "warning", "error", "debug")})
    old_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with ExitStack() as stack:
            for module in (llm, image):
                stack.enter_context(patch.object(module, "settings", settings))
                stack.enter_context(patch.object(module, "httpx", SimpleNamespace(AsyncClient=budget.client)))
                stack.enter_context(patch.object(module, "logger", silent))
            stack.enter_context(patch.object(image, "_persist_image_bytes", persist_locally))
            for role in roles:
                result = {"model": getattr(settings, f"{role}_model"), "status": "FAILED"}
                try:
                    if role == "llm":
                        raw = await asyncio.wait_for(
                            llm.call_llm(TEXT_SYSTEM, TEXT_PROMPT, max_tokens=384, temperature=1.0), timeout=50)
                        story = validate_story(raw, (settings.llm_api_key, settings.image_api_key))
                        write_json(output_dir / "story.json", story)
                        result["artifact"] = "story.json"
                        result["korean_json_validated"] = True
                    else:
                        prompt = ImagePrompt(page=1, positive_prompt=IMAGE_PROMPT,
                                             negative_prompt="No people or personal data", seed=1, aspect_ratio=aspect_ratio)
                        await asyncio.wait_for(image.generate_image(prompt, reference_image_url=None), timeout=95)
                        if not image_artifact:
                            raise SmokeError("INVALID_IMAGE_OUTPUT")
                        result["artifact"] = image_artifact
                    result["status"] = "PASSED"
                except Exception as error:
                    result["status"] = failure_status(error)
                    if role == "image" and image_artifact:
                        result["image_validation"] = image_artifact
                result.update(budget.metrics[role])
                report["components"][role] = result
    finally:
        logging.disable(old_logging)
    report["status"] = "PASSED" if all(v["status"] == "PASSED" for v in report["components"].values()) else "FAILED"
    report["request_counts"] = {role: metric["requests"] for role, metric in budget.metrics.items()}
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_json(output_dir / "result.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Authorize one paid request per selected component")
    parser.add_argument("--component", choices=("llm", "image", "both"), default="both")
    parser.add_argument("--aspect-ratio", choices=("1:1", "3:4", "4:3", "9:16"), default="3:4")
    parser.add_argument("--env-file", type=Path, default=ROOT / "apps" / "api" / ".env")
    parser.add_argument("--output-dir", type=Path,
                        default=ACCEPTANCE_ROOT / ("ai-adapter-smoke-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")))
    args = parser.parse_args(argv)
    if not args.live:
        print(json.dumps({"status": "LIVE_OPT_IN_REQUIRED", "generation_requests": 0,
                          "planned_text_requests": int(args.component in {"llm", "both"}),
                          "planned_image_requests": int(args.component in {"image", "both"})}))
        return 0
    logging.getLogger("dotenv.main").disabled = True
    try:
        if not args.env_file.is_file():
            raise SmokeError("ENV_FILE_UNREADABLE")
        values = dict(os.environ)
        values.update({k: v or "" for k, v in dotenv_values(args.env_file, interpolate=False).items()})
        result = asyncio.run(run_smoke(values, args.output_dir, component=args.component, aspect_ratio=args.aspect_ratio))
    except Exception as error:
        result = {"status": failure_status(error), "launch_ready": False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
