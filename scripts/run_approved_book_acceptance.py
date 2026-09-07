#!/usr/bin/env python3
"""One paid 12-page acceptance using an already approved illustrated character.

Restores an explicit private approved-character fixture into disposable storage
and PostgreSQL. This tests approved portrait reuse and book generation, not photo
upload, portrait generation or initial approval. Never reads production databases.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import uuid

import asyncpg
import boto3
from dotenv import dotenv_values
import httpx

from run_live_book_acceptance import run_acceptance, save_json, require_ignored_path, job_error_code
from run_live_photo_acceptance import private_json, private_bytes, runtime_config
from run_runtime_e2e import require
from photo_acceptance_guard import validate_policy


def unverified_candidate_readiness(http_status, payload):
    """Permit only a fresh isolated candidate's explicit provider probe gap."""
    services = payload.get("services", {})
    return (
        http_status == 503
        and services.get("provider_runtime") == "unverified"
        and all(services.get(name) == "healthy" for name in
                ("database", "redis", "job_monitor", "storage", "provider_keys"))
        and services.get("cost_budget") == "configured"
    )


def approved_journey(fixture, portrait):
    def execute(base, directory, report, runtime):
        owner = {"X-User-Key": str(uuid.uuid4())}
        character_id = "char_" + uuid.uuid4().hex[:20]
        store = boto3.client("s3", endpoint_url=runtime["S3_ENDPOINT"],
            aws_access_key_id=runtime["S3_ACCESS_KEY"], aws_secret_access_key=runtime["S3_SECRET_KEY"],
            region_name="us-east-1")
        bucket = runtime["S3_BUCKET"]
        portrait_key = f"characters/{character_id}/avatars/v1/approved.png"
        avatar_url = runtime["S3_PUBLIC_URL"] + "/" + portrait_key
        report["http_observations"] = {"status_polls": 0, "http_429": 0, "other_non_200": []}
        with httpx.Client(base_url=base, timeout=90, trust_env=False) as client:
            def call(method, path, **kwargs):
                response = client.request(method, path, headers=owner, **kwargs)
                if response.status_code == 429:
                    report["http_observations"]["http_429"] += 1
                elif response.status_code != 200:
                    report["http_observations"]["other_non_200"].append(response.status_code)
                require(response.status_code == 200, f"APPROVED_BOOK_HTTP_{response.status_code}")
                return response
            readiness = client.get("/health/ready")
            report["readiness_before"] = readiness.json()
            report["readiness_before_http_status"] = readiness.status_code
            unverified_candidate = unverified_candidate_readiness(
                readiness.status_code, report["readiness_before"])
            # A disposable candidate may establish its first observations with
            # this explicitly paid book. Production promotion still requires 200.
            require(readiness.status_code == 200 or unverified_candidate,
                    "APPROVED_BOOK_INFRASTRUCTURE_NOT_READY")
            report["initial_provider_probe_required"] = unverified_candidate
            call("POST", "/v1/consent", json={"privacy": True, "photos": True, "data_processing": True})
            child = call("POST", "/v1/profiles", json={"name": fixture["name"], "age_band": "7-9", "is_default": True}).json()
            owner["X-Profile-Id"] = child["id"]
            store.put_object(Bucket=bucket, Key=portrait_key, Body=portrait, ContentType="image/png")

            async def restore_approved_fixture():
                connection = await asyncpg.connect(runtime["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
                try:
                    await connection.execute('''INSERT INTO characters
                        (id,name,master_description,appearance,clothing,personality_traits,visual_style_notes,
                         distinctive_features,from_photo,source_image_url,avatar_status,avatar_url,
                         avatar_version,avatar_attempts,avatar_approved_at,avatar_style,avatar_source_kind,user_key,created_at)
                        VALUES ($1,$2,$3,$4::json,$5::json,$6::json,$7,$8::json,true,NULL,'approved',$9,1,1,
                                NOW(),'watercolor','photo',$10,NOW())''', character_id, fixture["name"],
                        fixture["master_description"], json.dumps(fixture["appearance"]), json.dumps(fixture["clothing"]),
                        json.dumps(fixture["personality_traits"]), fixture["visual_style_notes"],
                        json.dumps(fixture["distinctive_features"]), avatar_url, owner["X-User-Key"])
                finally:
                    await connection.close()
            asyncio.run(restore_approved_fixture())
            character = call("GET", f"/v1/characters/{character_id}").json()
            require(character["avatar_status"] == "approved", "RESTORED_AVATAR_NOT_APPROVED")
            initial_balance = call("GET", "/v1/credits/balance").json()["credits"]
            # Ordinary pre-generation reads exercise the production read bucket.
            call("GET", "/v1/profiles")
            call("GET", "/v1/books/generation-options")
            started = time.monotonic()
            spec = {"topic": fixture["topic"], "language": "ko", "target_age": "7-9", "style": "watercolor",
                    "page_count": 12, "character_id": character_id, "protagonist_name": fixture["name"]}
            job_id = call("POST", "/v1/books", json=spec).json()["job_id"]
            app_fixture = {"base_url": base, "user_key": owner["X-User-Key"], "profile_id": child["id"],
                           "character_id": character_id, "job_id": job_id, "book_id": None}
            save_json(directory / "private-fixture.json", app_fixture)
            report["stages"] = []
            job = {}
            while time.monotonic() - started < 660:
                response = client.get(f"/v1/books/{job_id}", headers=owner)
                report["http_observations"]["status_polls"] += 1
                if response.status_code == 429:
                    report["http_observations"]["http_429"] += 1
                    # Record the real failure; do not turn it into an internet diagnosis.
                    save_json(directory / "result.json", report)
                    time.sleep(min(60, max(1, int(response.headers.get("Retry-After", "2")))))
                    continue
                require(response.status_code == 200, f"STATUS_HTTP_{response.status_code}")
                job = response.json()
                state = {field: job.get(field) for field in ("status", "progress", "current_step")}
                if not report["stages"] or report["stages"][-1]["state"] != state:
                    report["stages"].append({"seconds": round(time.monotonic()-started, 2), "state": state})
                    save_json(directory / "result.json", report)
                    print(f"Book progress: {state['progress']}% / {state['status']}", flush=True)
                if job.get("status") in {"done", "failed"}:
                    break
                time.sleep(2)
            report["generation_seconds"] = round(time.monotonic()-started, 2)
            report["job_error_code"] = job_error_code(job)
            report["credit_refund_status"] = job.get("credit_refund_status")
            report["credit_balance_before"] = initial_balance
            report["credit_balance_after"] = call("GET", "/v1/credits/balance").json()["credits"]
            require(job.get("status") == "done", "APPROVED_BOOK_DID_NOT_COMPLETE")
            book_id = job["result"]["book_id"]
            app_fixture["book_id"] = book_id
            save_json(directory / "private-fixture.json", app_fixture)
            detail = call("GET", f"/v1/books/{book_id}/detail").json()
            require(len(detail["pages"]) == 12, "TWELVE_PAGES_REQUIRED")
            report["images"] = []
            for number, page in enumerate([{"image_url": detail["cover_image_url"]}, *detail["pages"]]):
                url = page["image_url"]
                parsed = httpx.URL(url)
                require(parsed.host == "127.0.0.1" and parsed.scheme == "http", "NONLOCAL_ASSET_REJECTED")
                response = client.get(url)
                require(response.status_code == 200, "IMAGE_DOWNLOAD_FAILED")
                path = directory / f"page-{number:02}.png"
                path.write_bytes(response.content)
                path.chmod(0o600)
                report["images"].append({"page": number, "sha256": hashlib.sha256(response.content).hexdigest()})
            references = store.list_objects_v2(Bucket=bucket, Prefix=f"jobs/{job_id}/character-reference/").get("Contents", [])
            require(len(references) == 1, "ONE_FROZEN_PORTRAIT_REQUIRED")
            frozen = store.get_object(Bucket=bucket, Key=references[0]["Key"])["Body"].read()
            require(hashlib.sha256(frozen).hexdigest() == fixture["portrait_sha256"], "FROZEN_PORTRAIT_CHANGED")
            after = call("GET", f"/v1/characters/{character_id}").json()
            require(after["avatar_version"] == 1 and after["avatar_status"] == "approved", "PORTRAIT_CHANGED")
            save_json(directory / "book.json", {"title": detail["title"], "cover_image": "page-00.png",
                "pages": [{"page": index, "text": page["text"], "image": f"page-{index:02}.png"}
                          for index, page in enumerate(detail["pages"], 1)]})
            report.update(page_count=12, fixed_portrait_reuse="passed", product_illustration_qa="passed",
                          visual_quality_status="pending", generation_warnings=detail.get("generation_warnings", []))
            readiness = client.get("/health/ready")
            report["readiness_after"] = readiness.json()
            report["readiness_after_http_status"] = readiness.status_code
            # Reusing a portrait intentionally does not exercise a distinct
            # photo-analysis credential. Keep that operational gap explicit.
            report["all_provider_access_observed"] = bool(
                report["readiness_after"].get("services", {}).get("provider_access_observed")
            )
            require(readiness.status_code == 200 or unverified_candidate_readiness(
                    readiness.status_code, report["readiness_after"]),
                    "APPROVED_BOOK_POST_GENERATION_INFRASTRUCTURE_NOT_READY")
            require(report["http_observations"]["http_429"] == 0, "STATUS_POLL_RATE_LIMIT_REGRESSION")
    return execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    for field in ("env-file", "approved-fixture", "policy-file", "output-dir"):
        parser.add_argument("--" + field, type=Path, required=True)
    parser.add_argument("--hold-seconds", type=int, default=1200)
    args = parser.parse_args()
    os.umask(0o077)
    require(0 <= args.hold_seconds <= 14400, "INVALID_HOLD")
    fixture = private_json(args.approved_fixture)
    require(fixture.get("approval_already_completed") is True, "EXISTING_APPROVAL_REQUIRED")
    require_ignored_path(Path(fixture["portrait_path"]))
    portrait = private_bytes(Path(fixture["portrait_path"]), 10 * 1024 * 1024)
    require(hashlib.sha256(portrait).hexdigest() == fixture["portrait_sha256"], "APPROVED_PORTRAIT_HASH_MISMATCH")
    policy = validate_policy(private_json(args.policy_file))
    require(policy["max_budget_usd"] <= 2, "ONE_BOOK_ESTIMATE_CAP_EXCEEDED")
    config = runtime_config(dotenv_values(args.env_file, interpolate=False), policy)
    profile = SimpleNamespace(config=config, guard_module="photo_acceptance_guard", request_limits={"llm": 16, "image": 16},
        environment={"PHOTO_PROCESSING_ENABLED": "true", "ILLUSTRATION_QUALITY_ENABLED": "true",
                     "LIVE_ACCEPTANCE_PAGE_COUNT": "12", "LIVE_PHOTO_POLICY_FILE": str(args.policy_file.resolve()),
                     "IMAGE_MAX_CONCURRENT": "3", "OPENAI_IMAGE_QUALITY": "medium"},
        report_fields={"source_classification": "previously_approved_illustration", "photos_used": False,
                       "portrait_generation_requests": 0, "portrait_sha256": fixture["portrait_sha256"],
                       "real_child_data": True, "provider_journal_version": 3,
                       "data_scope": {"appearance": "previously_approved_illustration", "photos_used": False},
                       "budget_target_usd": policy["max_budget_usd"], "launch_ready": False},
        journey=approved_journey(fixture, portrait))
    return run_acceptance(SimpleNamespace(output_dir=args.output_dir, reader_profile_file=None,
        age="7-9", case=1, page_count=12, hold_seconds=args.hold_seconds), profile=profile)


if __name__ == "__main__":
    raise SystemExit(main())
