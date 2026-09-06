#!/usr/bin/env python3
"""One explicit paid repair rehearsal of a saved generated-illustration book.

Uses production review/repair/image adapters with an ownership-checked local
byte store. This does not exercise PostgreSQL, Celery, S3, or publication. Source
files are immutable. At most two review and two image HTTP attempts are allowed.
"""

import argparse
import asyncio
import base64
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from PIL import Image

from live_acceptance_guard import JOURNAL_VERSION, install as install_usage_guard
from review_saved_illustrations import ACCEPTANCE, ROOT, load_book, require, validate_request
from run_live_book_acceptance import load_runtime_config, require_ignored_path, save_json
from run_live_quality_matrix import costs

REVIEW_URL = "https://api.openai.com/v1/responses"
IMAGE_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro-image:generateContent"
OWNED_BASE = "https://owned.invalid/books"
REQUEST_LIMITS = {"llm": 2, "image": 2}


def validate_repair_request(url, payload, *, follow_redirects, schema, cover, owned_images,
                            expected_references=None):
    """Independent narrow guard; neither URL nor input-media scope can broaden."""
    require(follow_redirects is False and type(payload) is dict, "REPAIR_REQUEST_REFUSED")
    if str(url) == REVIEW_URL:
        validate_request(url, payload, follow_redirects=follow_redirects)
        require(payload.get("text", {}).get("format") == {
            "type": "json_schema", "name": "book_illustration_review", "strict": True, "schema": schema,
        }, "REPAIR_REVIEW_SCHEMA_REFUSED")
        content = payload.get("input", [])
        images = [part.get("image_url") for message in content if isinstance(message, dict)
                  and isinstance(message.get("content"), list) for part in message["content"]
                  if isinstance(part, dict) and part.get("type") == "input_image"]
        require(5 <= len(images) <= 13 and all(isinstance(value, str) and value in owned_images for value in images),
                "REPAIR_REVIEW_MEDIA_REFUSED")
        return "llm"
    require(str(url) == IMAGE_URL, "REPAIR_ENDPOINT_REFUSED")
    require(set(payload) == {"contents", "generationConfig"}
            and payload["generationConfig"] == {
                "responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": "3:4"},
            }, "REPAIR_IMAGE_OPTIONS_REFUSED")
    contents = payload.get("contents")
    require(type(contents) is list and len(contents) == 1 and type(contents[0]) is dict,
            "REPAIR_IMAGE_CONTENT_REFUSED")
    references = [cover] if expected_references is None else expected_references
    require(type(references) is list and 1 <= len(references) <= 2, "REPAIR_REFERENCE_SCOPE_REFUSED")
    expected_parts = []
    for data, mime in references:
        require(type(data) is bytes and data and mime in {"image/png", "image/jpeg", "image/webp"},
                "REPAIR_REFERENCE_SCOPE_REFUSED")
        encoded = base64.b64encode(data).decode()
        require(f"data:{mime};base64,{encoded}" in owned_images, "REPAIR_REFERENCE_SCOPE_REFUSED")
        expected_parts.append({"inline_data": {"mime_type": mime, "data": encoded}})
    parts = contents[0].get("parts")
    require(type(parts) is list and len(parts) == len(expected_parts) + 2, "REPAIR_IMAGE_CONTENT_REFUSED")
    require(set(parts[0]) == {"text"} and isinstance(parts[0]["text"], str)
            and parts[1:-1] == expected_parts
            and set(parts[-1]) == {"text"} and isinstance(parts[-1]["text"], str),
            "REPAIR_REFERENCE_ORDER_REQUIRED")
    require(len(parts[0]["text"] + "\n" + parts[-1]["text"]) <= 5000,
            "REPAIR_PROMPT_LIMIT")
    return "image"


def inline_images(objects):
    return {f"data:{mime};base64," + base64.b64encode(data).decode() for data, mime in objects.values()}


async def run_repair(inputs, manifest, output, config):
    """The only replaced production seams are local storage reads and persistence."""
    sys.path.insert(0, str(ROOT / "apps/api"))
    from src.core.config import settings
    from src.core.errors import ErrorCode
    from src.models.dto import ImagePrompt
    from src.services import image, image_quality, illustration_quality_pipeline as pipeline, storage
    from src.services.image_correction import correction_scene_reference
    from src.services.image_request_budget import image_request_budget
    from src.services.openai_contract import openai_response_text
    from src.services.structured_output import provider_output_schema

    image_quality._validate_inputs(**inputs, timeout=45.0)
    objects = {f"source/page-{page:02}": value for page, value in inputs["images"].items()}
    urls = {page: f"{OWNED_BASE}/source/page-{page:02}" for page in inputs["images"]}
    cover = inputs["images"][0]
    prompts = {page: ImagePrompt(
        page=page, positive_prompt=(brief if len(brief) >= 10 else "Cover illustration: " + brief),
        negative_prompt="readable text, letters, captions, duplicate characters, identity swaps",
        seed=page + 1, aspect_ratio="3:4",
    ) for page, brief in inputs["image_prompts"].items()}
    schema = provider_output_schema(image_quality.BookIllustrationReview.model_json_schema(), provider="openai")
    deadline = time.monotonic() + 300
    report = {
        "status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
        "source": manifest, "request_limits": REQUEST_LIMITS, "deadline_seconds": 300,
        "providers": {"llm": "openai", "image": "gemini"},
        "models": {"llm": "gpt-5.6-sol", "image": "gemini-3-pro-image"},
        "provider_journal_version": JOURNAL_VERSION, "illustration_quality_enabled": True,
        "generated_illustrations_only": True, "source_photo_used": False,
        "storage": "ownership-checked local byte dictionary", "real_postgres": False,
        "real_celery": False, "real_s3": False, "published": False,
        "requests": [], "reviews": [], "progress": [], "regenerated_files": [],
    }
    report["visual_briefs_before_sha256"] = {
        page: hashlib.sha256(prompt.positive_prompt.encode()).hexdigest() for page, prompt in prompts.items()}
    code_paths = ["scripts/run_saved_illustration_repair.py", "src/services/image_quality.py",
                  "src/services/illustration_quality_pipeline.py", "src/services/image.py",
                  "src/services/image_request_budget.py", "src/services/image_correction.py",
                  "src/services/openai_contract.py"]
    report["code_sha256"] = {path: hashlib.sha256(
        (ROOT / path if path.startswith("scripts/") else ROOT / "apps/api" / path).read_bytes()
    ).hexdigest() for path in code_paths}

    def save():
        save_json(output / "result.json", report)

    async def get_bytes(key):
        require(key in objects, "REPAIR_UNKNOWN_STORAGE_KEY")
        return objects[key]

    active_page = None
    active_references = None

    async def persist(data, mime, provider):
        require(type(active_page) is int and provider == "gemini" and len(report["regenerated_files"]) < 2,
                "REPAIR_PERSISTENCE_REFUSED")
        require(type(data) is bytes and len(data) <= 8 * 1024 * 1024, "REPAIR_IMAGE_SIZE_REFUSED")
        with Image.open(BytesIO(data)) as decoded:
            actual_mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(decoded.format)
            width, height = decoded.size
            decoded.verify()
        require(mime == actual_mime and actual_mime is not None, "REPAIR_IMAGE_FORMAT_REFUSED")
        suffix = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[mime]
        name = f"repaired-page-{active_page:02}.{suffix}"
        path = output / name
        require(not path.exists(), "REPAIR_ALREADY_ATTEMPTED")
        with path.open("xb") as stream:
            stream.write(data)
        path.chmod(0o600)
        key = "repair/" + name
        objects[key] = (data, mime)
        report["regenerated_files"].append({"page_number": active_page, "file": name,
            "sha256": hashlib.sha256(data).hexdigest(), "width": width, "height": height})
        save()
        return f"{OWNED_BASE}/{key}"

    async def regenerate(page, prompt, current_urls):
        nonlocal active_page, active_references
        active_page = page
        try:
            # Local repairs use this generated page first. The pipeline supplies
            # a cover only after QA accepted it; never recover a removed cover
            # from the immutable input dictionary or introduce a source photo.
            cover_url = current_urls.get(0)
            primary_url = correction_scene_reference() or cover_url
            selected = list(dict.fromkeys(url for url in (primary_url, cover_url) if url))
            require(1 <= len(selected) <= 2, "REPAIR_REFERENCE_SCOPE_REFUSED")
            keys = [storage.key_from_public_url(url) for url in selected]
            require(all(key in objects for key in keys), "REPAIR_UNKNOWN_STORAGE_KEY")
            active_references = [objects[key] for key in keys]
            return await image.generate_image(prompt, reference_image_url=cover_url)
        finally:
            active_page = None
            active_references = None

    async def progress(step, value):
        require(step in {"verify_illustrations", "repair_illustrations"} and type(value) is int,
                "REPAIR_PROGRESS_REFUSED")
        report["progress"].append({"step": step, "progress": value})
        save()

    journal = output / "provider-usage.jsonl"
    journal.touch(mode=0o600)
    save()
    original_post = httpx.AsyncClient.post
    with ExitStack() as stack:
        for field, value in {
            **vars(config), "s3_public_url": OWNED_BASE, "s3_legacy_public_urls": "",
            "s3_endpoint": "https://owned.invalid", "s3_download_endpoint": None,
            "s3_bucket": "books", "illustration_quality_enabled": True,
        }.items():
            stack.enter_context(patch.object(settings, field, value))
        stack.enter_context(patch.dict(os.environ, {
            "LLM_PROVIDER": "openai", "LLM_MODEL": "gpt-5.6-sol", "IMAGE_MODEL": "gemini-3-pro-image",
            "ILLUSTRATION_QUALITY_ENABLED": "true", "LIVE_ACCEPTANCE_PAGE_COUNT": "4",
            "LIVE_ACCEPTANCE_JOURNAL": str(journal),
        }))
        stack.enter_context(patch.object(storage, "get_object_bytes", get_bytes))
        stack.enter_context(patch.object(pipeline, "get_object_bytes", get_bytes))
        stack.enter_context(patch.object(image, "_persist_image_bytes", persist))
        install_usage_guard()
        instrumented_post = httpx.AsyncClient.post
        stack.callback(setattr, httpx.AsyncClient, "post", original_post)

        async def outer(client, url, **kwargs):
            require(not kwargs.get("params"), "REPAIR_QUERY_REFUSED")
            role = validate_repair_request(url, kwargs.get("json"),
                follow_redirects=kwargs.get("follow_redirects", client.follow_redirects),
                schema=schema, cover=cover, owned_images=inline_images(objects),
                expected_references=active_references)
            if role == "image":
                wire_text = kwargs["json"]["contents"][0]["parts"][-1]["text"]
                require(active_page in prompts and wire_text.startswith(prompts[active_page].positive_prompt),
                        "REPAIR_VISUAL_BRIEF_TRUNCATED")
            count = sum(event["role"] == role for event in report["requests"])
            require(count < REQUEST_LIMITS[role] and time.monotonic() < deadline, "REPAIR_REQUEST_LIMIT")
            event = {"role": role, "status": "reserved"}
            if role == "image":
                event["full_original_visual_brief_preserved"] = True
            report["requests"].append(event)
            save()
            try:
                response = await instrumented_post(client, url, **kwargs)
                event.update(status="returned", http_status=response.status_code)
                if role == "llm" and response.status_code == 200:
                    try:
                        raw = openai_response_text(response.json(), model="gpt-5.6-sol")
                        reviewed = image_quality.BookIllustrationReview.model_validate_json(raw)
                        report["reviews"].append(reviewed.model_dump(mode="json"))
                    except Exception:
                        event["review_parse_failed"] = True
                return response
            except BaseException as error:
                event.update(status="failed", error_type=type(error).__name__)
                raise
            finally:
                save()

        async def no_get(*_args, **_kwargs):
            raise ValueError("REPAIR_NETWORK_GET_REFUSED")

        stack.enter_context(patch.object(httpx.AsyncClient, "post", outer))
        stack.enter_context(patch.object(httpx.AsyncClient, "get", no_get))
        try:
            with image_request_budget(2, deadline) as budget:
                result = await asyncio.wait_for(pipeline.verify_and_repair_illustrations(
                    title=inputs["title"], page_texts=inputs["page_texts"], image_prompts=prompts,
                    image_urls=urls, deadline=deadline, regenerate=regenerate, on_progress=progress,
                ), timeout=300)
            require(bool(result.repaired_pages), "KNOWN_ERROR_NOT_DETECTED")
            after = [{"page_number": page, "sha256": hashlib.sha256(
                objects[storage.key_from_public_url(url)][0]).hexdigest()}
                for page, url in sorted(result.image_urls.items())]
            before = {item["page_number"]: item["sha256"] for item in manifest["illustrations"]}
            changed = [item["page_number"] for item in after if item["sha256"] != before[item["page_number"]]]
            require(changed == result.repaired_pages, "REPAIR_PAGE_HASH_MISMATCH")
            report.update(status="passed", after=after, changed_pages=changed,
                          repaired_pages=result.repaired_pages, image_budget_used=budget.used)
            report["visual_briefs_after_sha256"] = {
                page: hashlib.sha256(prompt.positive_prompt.encode()).hexdigest()
                for page, prompt in result.image_prompts.items()}
            require(report["visual_briefs_after_sha256"] == report["visual_briefs_before_sha256"],
                    "REPAIR_STORED_VISUAL_BRIEF_CHANGED")
        except BaseException as error:
            report.update(status="failed", error_type=type(error).__name__)
            if isinstance(getattr(error, "code", None), ErrorCode):
                report["error_code"] = error.code.value
    httpx.AsyncClient.post = original_post
    candidate_hashes = {item["page_number"]: item["sha256"] for item in manifest["illustrations"]}
    candidate_hashes.update({item["page_number"]: item["sha256"] for item in report["regenerated_files"]})
    report["candidate_after_not_published"] = [
        {"page_number": page, "sha256": digest} for page, digest in sorted(candidate_hashes.items())]
    try:
        _, after_manifest = load_book(ROOT / manifest["source"])
        require(after_manifest == manifest, "REPAIR_SOURCE_CHANGED")
        report["source_unchanged"] = True
    except Exception:
        report.update(status="failed", source_unchanged=False)
    save()
    try:
        llm_cost, image_cost = costs(output)
        report["estimates_usd"] = {"llm": round(llm_cost, 6), "image": round(image_cost, 6)}
    except Exception:
        report.update(status="failed", cost_evidence_complete=False)
    report["cost_is_invoice"] = False
    save()
    return report


async def execute(args):
    inputs, manifest = load_book(args.book_directory)
    output = args.output_dir.resolve()
    require(not args.output_dir.is_symlink() and not output.exists()
            and output.is_relative_to(ACCEPTANCE.resolve()), "NEW_ACCEPTANCE_DIRECTORY_REQUIRED")
    require_ignored_path(output)
    for name in ("result.json", "provider-usage.jsonl", *(
        f"repaired-page-{page:02}.{suffix}" for page in inputs["images"] for suffix in ("png", "jpg", "webp")
    )):
        require_ignored_path(output / name)
    config = load_runtime_config(SimpleNamespace(env_file=args.env_file, llm_env_file=None,
                                                 llm_model=None, image_model=None))
    require(config.llm_provider == "openai" and config.llm_model == "gpt-5.6-sol"
            and config.image_provider == "gemini" and config.image_model == "gemini-3-pro-image",
            "REPAIR_CONFIG_UNSUPPORTED")
    output.mkdir(parents=True, mode=0o700)
    report = await run_repair(inputs, manifest, output, config)
    print(json.dumps({key: report[key] for key in ("status", "changed_pages", "estimates_usd") if key in report}))
    return 0 if report["status"] == "passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--book-directory", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    previous_umask = os.umask(0o077)
    try:
        return asyncio.run(execute(args))
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        return 1
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":
    raise SystemExit(main())
