#!/usr/bin/env python3
"""Review one retained fictional 13-page candidate once; never generate images.

Requires a new private output directory, explicit live opt-in, selected credentials
and the same operator-verified budget policy as photo acceptance. The source copy
has no .env; credentials travel only in the child environment. The original
candidate and review remain immutable, so a recheck cannot erase failure evidence.
"""

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


async def review_once(capture_dir, output_dir, repository_root):
    import httpx
    from fictional_review_capture import load_review_input
    from src.core.errors import ErrorCode
    from src.core.logging import configure_logging
    from src.services.image_quality import review_book_illustrations

    logging.basicConfig(level=logging.WARNING)
    configure_logging()
    result = {"status": "failed", "source_classification": "fictional_image", "real_child_data": False,
              "new_images": 0, "max_provider_calls": 1, "book_publication_performed": False,
              "release_approved": False, "prior_failure_evidence_changed": False}
    original_post = httpx.AsyncClient.post
    count = 0

    async def single_review(client, url, **kwargs):
        nonlocal count
        if str(url) != "https://api.openai.com/v1/responses" or count != 0:
            raise RuntimeError("ONE_REVIEW_REQUEST_ONLY")
        count += 1
        return await original_post(client, url, **kwargs)

    httpx.AsyncClient.post = single_review
    try:
        inputs = load_review_input(capture_dir, repository_root=repository_root)
        reviewed = await review_book_illustrations(**inputs, timeout=45.0)
        result.update(status="validated_response", review=reviewed.model_dump(mode="json"))
    except Exception as exc:
        code = getattr(exc, "code", None)
        result["error_code"] = code.value if isinstance(code, ErrorCode) else "UNKNOWN"
    finally:
        httpx.AsyncClient.post = original_post
    result["provider_calls"] = count
    path = output_dir / "result.json"
    with path.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, separators=(",", ":"))
    path.chmod(0o600)
    print(json.dumps({key: result[key] for key in ("status", "provider_calls", "new_images")}))
    return 0 if result["status"] == "validated_response" else 1


def run(args):
    from dotenv import dotenv_values
    from run_live_book_acceptance import ROOT, require_ignored_path, write_guarded_entry
    from run_live_photo_acceptance import private_json, verified_policy, runtime_config
    from run_runtime_e2e import clean_environment, require

    require(args.live is True, "EXPLICIT_LIVE_OPT_IN_REQUIRED")
    # Classification must be checked before reading credentials or starting a worker.
    # The larger book context is validated inside the isolated worker. Read only
    # a bounded object here; never copy it or echo malformed input in an exception.
    from run_live_photo_acceptance import private_bytes
    try:
        record = json.loads(private_bytes(args.capture_dir / "input.json", 512 * 1024))
    except (ValueError, UnicodeError):
        require(False, "FICTIONAL_REPLAY_INPUT_INVALID")
    require(type(record) is dict and record.get("classification") == "fictional_image"
            and record.get("real_child_data") is False and record.get("source_photos_retained") is False,
            "REAL_CHILD_REVIEW_CAPTURE_FORBIDDEN")
    policy = verified_policy(private_json(args.policy_file), "fictional_image")
    config = runtime_config(dotenv_values(args.env_file, interpolate=False), policy)
    directory = args.output_dir.resolve()
    require_ignored_path(directory)
    require(not directory.exists() and directory != args.capture_dir.resolve(), "NEW_REPLAY_OUTPUT_REQUIRED")
    directory.mkdir(mode=0o700)
    journal = directory / "provider-usage.jsonl"
    journal.touch(mode=0o600)
    with tempfile.TemporaryDirectory(prefix="storybook-review-replay-") as scratch:
        api = Path(scratch) / "api"
        shutil.copytree(ROOT / "apps/api/src", api / "src",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env*"))
        for name in ("photo_acceptance_guard.py", "live_acceptance_guard.py", "fictional_review_capture.py",
                     "replay_fictional_review.py"):
            shutil.copy2(ROOT / "scripts" / name, api / name)
        entry = write_guarded_entry(api, "photo_acceptance_guard")
        runtime = {**clean_environment(), **{key.upper(): str(value) for key, value in vars(config).items()},
                   "PYTHONPATH": str(api), "DATABASE_URL": "sqlite+aiosqlite:///:memory:", "TESTING": "true",
                   # Required by the existing guard profile in this isolated,
                   # fictional-only child; no photo service is invoked here.
                   "PHOTO_PROCESSING_ENABLED": "true", "ILLUSTRATION_QUALITY_ENABLED": "true",
                   "OPENAI_IMAGE_QUALITY": "medium", "LIVE_ACCEPTANCE_JOURNAL": str(journal),
                   "LIVE_PHOTO_POLICY_FILE": str(args.policy_file.resolve()),
                   "LIVE_ACCEPTANCE_PAGE_COUNT": "12", "AWS_EC2_METADATA_DISABLED": "true"}
        fd = os.open(directory / "replay.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as log:
            process = subprocess.run(
                [sys.executable, str(entry), "replay_fictional_review", "--worker",
                 "--capture-dir", str(args.capture_dir.resolve()), "--output-dir", str(directory),
                 "--repository-root", str(ROOT.resolve())],
                env=runtime, cwd=api, stdout=log, stderr=subprocess.STDOUT, timeout=75, check=False,
            )
        return process.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--policy-file", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--repository-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    old_umask = os.umask(0o077)
    try:
        if args.worker:
            # This child may only be launched through the fail-closed guard entry.
            import httpx
            if not getattr(httpx.AsyncClient.post, "_photo_acceptance_guard", None):
                raise RuntimeError("GUARDED_REPLAY_WORKER_REQUIRED")
            return asyncio.run(review_once(args.capture_dir, args.output_dir, args.repository_root))
        if not args.live or args.policy_file is None or args.env_file is None:
            parser.error("--live, --policy-file and --env-file are required")
        return run(args)
    except Exception:
        print("Fictional review replay stopped; inspect the private diagnostics.")
        return 1
    finally:
        os.umask(old_umask)


if __name__ == "__main__":
    raise SystemExit(main())
