"""Explicit operator probe. Run from apps/api; no charge without the opt-in flag.

python scripts/provider_preflight.py --check-only
python scripts/provider_preflight.py --allow-billable-requests

The latter sends generic text and one generic illustration, never child data.
It exercises configured API permissions/credit and records shared observations;
a successful observation is not a promise that balance remains available later.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import settings  # noqa: E402
from src.models.dto import ImagePrompt  # noqa: E402
from src.services.provider_runtime import job_provider_usage, provider_runtime_status  # noqa: E402


async def main(live: bool) -> int:
    failures = []
    if live:
        from src.services.llm import call_llm
        from src.services.openai_contract import request_openai_json
        from src.services.image import generate_image, image_storage_scope
        from src.services.storage import key_from_public_url, delete_keys

        async def text_probe():
            await call_llm('Return only JSON.', 'Return {"ok":true}.', max_tokens=32, temperature=0)

        probes = [("llm", text_probe)]
        if settings.photo_processing_enabled and (
            settings.photo_analysis_api_key != settings.llm_api_key
            or settings.photo_analysis_model != settings.llm_model
        ):
            async def photo_probe():
                await request_openai_json(model=settings.photo_analysis_model,
                    api_key=settings.photo_analysis_api_key, timeout=30,
                    system_prompt='Return only JSON.',
                    user_prompt='Return {"ok":true}.', max_tokens=32)
            probes.append(("photo_analysis", photo_probe))
        # Stop if text/moderation cannot run: an image would be wasted.
        with job_provider_usage("operator-preflight-" + uuid.uuid4().hex):
            for name, probe in probes:
                try:
                    await probe()
                except Exception as exc:
                    failures.append({"component": name, "code": getattr(getattr(exc, "code", None), "value", "PROBE_FAILED")})
            if not failures:
                try:
                    with image_storage_scope("operator-preflight"):
                        url = await generate_image(ImagePrompt(page=0,
                            positive_prompt="A single blue circle on plain white paper, flat illustration.",
                            negative_prompt="letters, numbers, people", seed=1))
                    key = key_from_public_url(url)
                    if key:
                        failed = await delete_keys([key])
                        if failed:
                            failures.append({"component": "cleanup", "code": "CLEANUP_PENDING"})
                except Exception as exc:
                    failures.append({"component": "image", "code": getattr(getattr(exc, "code", None), "value", "PROBE_FAILED")})
    status = await provider_runtime_status()
    from src.core.rate_limit import rate_limiter
    await rate_limiter.close()
    # This output contains no keys, prompts, response bodies or asset URLs.
    print(json.dumps({"provider_runtime": status, "probe_failures": failures,
                      "billable_probe_requested": live}, ensure_ascii=False))
    return 0 if status["status"] == "healthy" and not failures else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check-only", action="store_true")
    group.add_argument("--allow-billable-requests", action="store_true")
    options = parser.parse_args()
    raise SystemExit(asyncio.run(main(options.allow_billable_requests)))
