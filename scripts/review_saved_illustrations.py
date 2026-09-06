#!/usr/bin/env python3
"""Explicit paid visual review of one or two saved acceptance books; no regeneration.

Uses the production review service and fixed Responses endpoint. Never loads an
original child photograph, follows a stored URL, changes a book, or logs prompts.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import time

import httpx
from dotenv import dotenv_values
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "docs/acceptance"


def require(condition, code):
    if not condition:
        raise ValueError(code)


def owned_file(directory, name):
    path = directory / name
    require(path.is_file() and not path.is_symlink() and path.resolve().parent == directory,
            "SAVED_ILLUSTRATION_FILE_INVALID")
    return path


def load_book(directory):
    require(directory.is_dir() and not directory.is_symlink()
            and directory.resolve().is_relative_to(ACCEPTANCE.resolve()), "ACCEPTANCE_DIRECTORY_REQUIRED")
    directory = directory.resolve()
    path = owned_file(directory, "book.json")
    require(path.stat().st_size <= 1024 * 1024, "BOOK_CONTEXT_TOO_LARGE")
    book = json.loads(path.read_text())
    pages = book["pages"]
    require(type(pages) is list and 4 <= len(pages) <= 12
            and [p["page_number"] for p in pages] == list(range(1, len(pages) + 1)), "BOOK_PAGES_INVALID")
    title = book["title"]
    texts = {0: title, **{p["page_number"]: p["text"] for p in pages}}
    prompts = {0: title, **{p["page_number"]: p["image_prompt"] for p in pages}}
    images, manifest = {}, []
    for number in range(len(pages) + 1):
        image_path = owned_file(directory, f"page-{number:02}.png")
        require(image_path.stat().st_size <= 8 * 1024 * 1024, "ILLUSTRATION_TOO_LARGE")
        data = image_path.read_bytes()
        # Historical acceptance filenames end in .png even when the provider
        # returned JPEG. Identify bytes; never convert the evidence image.
        with Image.open(BytesIO(data)) as opened:
            mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(opened.format)
        require(mime is not None, "ILLUSTRATION_FORMAT_UNSUPPORTED")
        images[number] = (data, mime)
        manifest.append({"page_number": number, "sha256": hashlib.sha256(data).hexdigest()})
    return dict(title=title, page_texts=texts, image_prompts=prompts, images=images), {
        "source": str(directory.relative_to(ROOT)), "book_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "illustrations": manifest,
    }


def validate_request(url, payload, *, follow_redirects):
    require(str(url) == "https://api.openai.com/v1/responses" and follow_redirects is False,
            "REVIEW_ENDPOINT_REFUSED")
    require(type(payload) is dict and payload.get("model") == "gpt-5.6-sol"
            and payload.get("max_output_tokens") == 6144 and payload.get("store") is False
            and payload.get("text", {}).get("format", {}).get("name") == "book_illustration_review"
            and not payload.get("tools") and not payload.get("background", False)
            and payload.get("service_tier", "default") == "default", "REVIEW_REQUEST_REFUSED")


async def execute(args):
    require(1 <= len(args.book_directory) <= 2, "REVIEW_BOOK_LIMIT")
    books = [load_book(path) for path in args.book_directory]
    output = args.output_dir
    require(not output.exists() and not output.is_symlink()
            and output.resolve().is_relative_to(ACCEPTANCE.resolve()), "NEW_ACCEPTANCE_DIRECTORY_REQUIRED")
    values = dotenv_values(args.env_file)
    require(values.get("LLM_PROVIDER") == "openai" and values.get("LLM_MODEL") == "gpt-5.6-sol"
            and bool(values.get("LLM_API_KEY")), "REVIEW_CONFIG_UNSUPPORTED")
    for key in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY"):
        os.environ[key] = values[key]
    sys.path.insert(0, str(ROOT / "apps/api"))
    from src.services.image_quality import review_book_illustrations, _validate_inputs
    for inputs, _ in books:
        _validate_inputs(**inputs, timeout=45.0)
    output.mkdir(parents=True, mode=0o700)
    report = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
              "model": "gpt-5.6-sol", "request_limit": len(books), "image_generation_requests": 0,
              "generated_illustrations_only": True, "source_photo_used": False, "books": [], "requests": []}
    report["review_source_sha256"] = {
        name: hashlib.sha256((ROOT / "apps/api/src/services" / name).read_bytes()).hexdigest()
        for name in ("image_quality.py", "openai_contract.py")
    }

    def save():
        path = output / "review.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        path.chmod(0o600)

    original = httpx.AsyncClient.post

    async def measured(client, url, **kwargs):
        require(not kwargs.get("params"), "REVIEW_QUERY_REFUSED")
        validate_request(url, kwargs.get("json"), follow_redirects=kwargs.get("follow_redirects", client.follow_redirects))
        require(len(report["requests"]) < len(books), "REVIEW_REQUEST_LIMIT")
        event = {"status": "started"}
        report["requests"].append(event)
        save()  # Reserve before the paid request, including timeout/process-exit cases.
        started = time.monotonic()
        try:
            response = await original(client, url, **kwargs)
            event.update(status="returned", http_status=response.status_code)
            try:
                usage = response.json().get("usage", {})
                event["usage"] = {k: usage[k] for k in ("input_tokens", "output_tokens")
                                  if type(usage.get(k)) is int and usage[k] >= 0}
                if len(event["usage"]) == 2:
                    event["estimate_usd"] = (usage["input_tokens"] * 4 + usage["output_tokens"] * 20) / 1e6
            except (ValueError, AttributeError):
                pass
            return response
        except BaseException as error:
            event.update(status="failed", error_type=type(error).__name__)
            raise
        finally:
            event["seconds"] = round(time.monotonic() - started, 3)
            save()

    httpx.AsyncClient.post = measured
    try:
        for inputs, manifest in books:
            entry = {**manifest, "status": "reviewing"}
            report["books"].append(entry)
            save()
            try:
                result = await review_book_illustrations(**inputs)
                entry.update(status="reviewed", review=result.model_dump(mode="json"),
                             has_issues=result.has_issues)
            except Exception as error:
                entry.update(status="failed", error_type=type(error).__name__)
                raise
            finally:
                save()
        report["status"] = "completed"
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__)
    finally:
        httpx.AsyncClient.post = original
        report["estimated_cost_usd"] = round(sum(r.get("estimate_usd", 0) for r in report["requests"]), 6)
        report["cost_is_invoice"] = False
        save()
    print(json.dumps({"status": report["status"], "requests": len(report["requests"]),
                      "estimated_cost_usd": report["estimated_cost_usd"]}))
    return 0 if report["status"] == "completed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--book-directory", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        return asyncio.run(execute(args))
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
