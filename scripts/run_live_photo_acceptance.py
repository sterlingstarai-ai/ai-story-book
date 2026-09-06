#!/usr/bin/env python3
"""Opt-in, isolated photo → reviewed portrait → 12-page OpenAI acceptance.

The owner or delegated tester reviews the source and portrait, then records that
decision with the approve subcommand. This tool calls the ordinary approval API;
it never inserts an approved database row. Fictional inputs are reported separately
and cannot establish real-child likeness. No environment file is changed.
"""

import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import stat
import time
from types import SimpleNamespace
import uuid

import boto3
from dotenv import dotenv_values
import httpx
from PIL import Image

from photo_acceptance_guard import REQUEST_LIMITS, validate_policy
from run_live_book_acceptance import require_ignored_path, run_acceptance, save_json, job_error_code
from run_runtime_e2e import GateFailure, require

MODELS = {"gpt-6-astra", "gpt-5.6-sol"}
CLASSIFICATIONS = {"real_child", "fictional_image"}
# Match the product's bounded page fan-out; serializing twelve pages can spend
# the unchanged job deadline before the last image and whole-book review start.
IMAGE_MAX_CONCURRENT = 3


def private_bytes(path, limit):
    """No symlinks, special files, shared files, unignored artifacts or unlimited reads."""
    path = Path(path)
    require_ignored_path(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
                    and info.st_uid == os.getuid(), "PRIVATE_INPUT_REQUIRES_0600_OWNED_FILE")
            data = stream.read(limit + 1)
        require(0 < len(data) <= limit, "PRIVATE_INPUT_SIZE_INVALID")
        return data
    except OSError:
        raise GateFailure("PRIVATE_INPUT_UNAVAILABLE") from None


def private_json(path):
    def unique(pairs):
        output = {}
        for key, value in pairs:
            require(key not in output, "DUPLICATE_PRIVATE_JSON_FIELD")
            output[key] = value
        return output
    try:
        value = json.loads(private_bytes(path, 16_384), object_pairs_hook=unique)
        require(type(value) is dict, "PRIVATE_JSON_OBJECT_REQUIRED")
        return value
    except (UnicodeError, ValueError):
        raise GateFailure("PRIVATE_JSON_INVALID") from None


def validate_manifest(manifest):
    require(manifest.get("classification") in CLASSIFICATIONS, "SOURCE_CLASSIFICATION_REQUIRED")
    require(type(manifest.get("source_path")) is str and Path(manifest["source_path"]).is_absolute(),
            "ABSOLUTE_PRIVATE_SOURCE_PATH_REQUIRED")
    name = manifest.get("character_name")
    require(type(name) is str and 1 <= len(name) <= 40 and name.strip() == name
            and all(character.isprintable() for character in name), "CHARACTER_NAME_INVALID")
    require(manifest.get("age_band") in {"3-5", "5-7", "7-9"}, "AGE_BAND_REQUIRED")
    source_kind = manifest.get("source_kind", "photo")
    require(source_kind in {"photo", "drawing"}, "SOURCE_KIND_INVALID")
    require(type(manifest.get("source_provenance")) is str
            and 10 <= len(manifest["source_provenance"]) <= 500, "SOURCE_PROVENANCE_REQUIRED")
    if manifest["classification"] == "fictional_image":
        require(manifest.get("contains_real_person") is False, "FICTIONAL_SOURCE_MUST_EXCLUDE_REAL_PERSON")
    else:
        require(manifest.get("parent_authorized") is True, "PARENT_SOURCE_AUTHORIZATION_REQUIRED")
    return manifest


def verified_policy(policy, classification):
    normalized = validate_policy(policy)
    require(policy.get("provider_conditions_verified") is True, "PROVIDER_CONDITIONS_NOT_VERIFIED")
    require(type(policy.get("evidence_note")) is str and 10 <= len(policy["evidence_note"]) <= 2000,
            "PROVIDER_EVIDENCE_REQUIRED")
    require(type(policy.get("pricing_evidence")) is str and 10 <= len(policy["pricing_evidence"]) <= 2000,
            "PRICING_RESERVATION_EVIDENCE_REQUIRED")
    try:
        checked = datetime.fromisoformat(policy.get("checked_at", "").replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - checked).total_seconds()
    except (AttributeError, TypeError, ValueError):
        raise GateFailure("PROVIDER_EVIDENCE_DATE_INVALID") from None
    require(0 <= elapsed <= 72 * 3600, "PROVIDER_EVIDENCE_NOT_CURRENT")
    if classification == "real_child":
        require(policy.get("zdr_applied_to_all_selected_projects") is True
                and policy.get("under18_processing_conditions_verified") is True,
                "REAL_CHILD_PROVIDER_CONDITIONS_NOT_VERIFIED")
    return normalized


def runtime_config(values, policy):
    expected = {
        "LLM_PROVIDER": "openai", "PHOTO_ANALYSIS_PROVIDER": "openai", "IMAGE_PROVIDER": "openai",
        "LLM_MODEL": policy["llm_model"], "PHOTO_ANALYSIS_MODEL": policy["photo_analysis_model"],
        "IMAGE_MODEL": "gpt-image-2",
    }
    for key, value in expected.items():
        require(values.get(key) == value, "PHOTO_RUNTIME_CONFIGURATION_MISMATCH")
    result = {key.lower(): value for key, value in expected.items()}
    for name in ("LLM_API_KEY", "PHOTO_ANALYSIS_API_KEY", "IMAGE_API_KEY"):
        secret = values.get(name)
        require(type(secret) is str and bool(secret) and secret.isascii()
                and not any(c.isspace() for c in secret), "EXPLICIT_PHOTO_PROVIDER_KEY_REQUIRED")
        result[name.lower()] = secret
    # These switches apply only to the isolated run, after policy evidence above.
    # They are not written to any application or deployment environment file.
    return SimpleNamespace(**result)


def approval_matches(record, version, digest):
    return (type(record.get("avatar_version")) is int and record["avatar_version"] == version
            and record.get("portrait_sha256") == digest and record.get("reviewed_source_and_portrait") is True
            and record.get("reviewer") in {"parent", "delegated_tester"} and record.get("decision") == "approve")


def require_portrait_preview(character, directory, report):
    """Do not label upstream generation/authentication failures as a visual QA rejection."""
    status = character.get("avatar_status")
    if status == "preview":
        return
    if status in {"generating", "failed"}:
        report["portrait_status"] = status
    journal = directory / "provider-usage.jsonl"
    if journal.is_file():
        for line in journal.read_text().splitlines():
            event = json.loads(line)
            http_status = event.get("http_status")
            if (event.get("kind") == "response" and event.get("role") in {"llm", "image"}
                    and type(http_status) is int and 400 <= http_status <= 599):
                report["provider_failure"] = {"role": event["role"], "http_status": http_status}
    raise GateFailure("PORTRAIT_GENERATION_TIMEOUT" if status == "generating" else "PORTRAIT_GENERATION_FAILED")


def approve(directory, reviewer):
    request = private_json(directory / "approval-request.json")
    portrait = private_bytes(directory / "portrait.png", 20 * 1024 * 1024)
    require(hashlib.sha256(portrait).hexdigest() == request.get("portrait_sha256"), "PREVIEW_CHANGED")
    save_json(directory / "portrait-approval.json", {
        "avatar_version": request["avatar_version"], "portrait_sha256": request["portrait_sha256"],
        "reviewed_source_and_portrait": True, "reviewer": reviewer, "decision": "approve",
    })
    print("Reviewed portrait decision recorded for the waiting acceptance run.", flush=True)


def journey(manifest, source, approval_timeout):
    with Image.open(BytesIO(source)) as image:
        extension, mime = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"),
                           "WEBP": ("webp", "image/webp")}[image.format]

    def execute(base, directory, report, runtime):
        owner = {"X-User-Key": str(uuid.uuid4())}
        object_store = boto3.client("s3", endpoint_url=runtime["S3_ENDPOINT"],
                                   aws_access_key_id=runtime["S3_ACCESS_KEY"],
                                   aws_secret_access_key=runtime["S3_SECRET_KEY"], region_name="us-east-1")
        bucket = runtime["S3_BUCKET"]

        def keys(prefix):
            return [item["Key"] for item in object_store.list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", [])]

        with httpx.Client(base_url=base, timeout=90, trust_env=False, follow_redirects=False) as client:
            def call(method, path, **kwargs):
                response = client.request(method, path, headers=owner, **kwargs)
                require(response.status_code == 200, "PHOTO_ACCEPTANCE_HTTP_FAILED")
                return response

            def download(url, filename):
                parsed = httpx.URL(url)
                require(parsed.scheme == "http" and parsed.host == "127.0.0.1", "NONLOCAL_ASSET_REJECTED")
                response = client.get(url)
                require(response.status_code == 200 and len(response.content) <= 20 * 1024 * 1024,
                        "PRIVATE_IMAGE_DOWNLOAD_FAILED")
                with Image.open(BytesIO(response.content)) as image:
                    size = {"width": image.width, "height": image.height}
                    image.verify()
                path = directory / filename
                path.write_bytes(response.content)
                path.chmod(0o600)
                return response.content, size

            call("GET", "/health/ready")
            call("POST", "/v1/consent", json={"privacy": True, "photos": True, "data_processing": True})
            kind = manifest.get("source_kind", "photo")
            character = call("POST", f"/v1/characters/from-{kind}",
                             files={kind: ("source." + extension, source, mime)},
                             data={"name": manifest["character_name"], "style": "watercolor"}).json()
            character_id = character["character_id"]
            deadline = time.monotonic() + 360
            while character.get("avatar_status") == "generating" and time.monotonic() < deadline:
                time.sleep(2)
                character = call("GET", f"/v1/characters/{character_id}").json()
            require_portrait_preview(character, directory, report)
            portrait, _ = download(character["avatar_url"], "portrait.png")
            digest, version = hashlib.sha256(portrait).hexdigest(), character["avatar_version"]
            save_json(directory / "approval-request.json", {
                "avatar_version": version, "portrait_sha256": digest,
                "source_classification": manifest["classification"], "status": "review_required",
            })
            report["portrait_product_qa"] = "passed"
            save_json(directory / "result.json", report)
            spec = {"topic": "친구들과 빗물을 모아 마을 정원을 살리는 이야기", "language": "ko",
                    "target_age": manifest["age_band"], "style": "watercolor", "page_count": 12,
                    "character_id": character_id, "protagonist_name": manifest["character_name"]}
            denied = client.post("/v1/books", headers=owner, json=spec)
            require(denied.status_code == 409, "UNAPPROVED_CHARACTER_BOOK_GATE_FAILED")
            print("Portrait ready. Review the supplied source and private portrait.png; then run the approve subcommand.", flush=True)
            deadline = time.monotonic() + approval_timeout
            while time.monotonic() < deadline:
                approval = directory / "portrait-approval.json"
                if approval.exists():
                    require(approval_matches(private_json(approval), version, digest), "PORTRAIT_APPROVAL_MISMATCH")
                    break
                time.sleep(1)
            else:
                raise GateFailure("PORTRAIT_REVIEW_TIMEOUT")
            approved = call("POST", f"/v1/characters/{character_id}/avatar/approve", json={"version": version}).json()
            require(approved.get("avatar_status") == "approved", "PORTRAIT_APPROVAL_FAILED")
            require(f"characters/{character_id}/{kind}.jpg" not in keys(f"characters/{character_id}/"),
                    "SOURCE_PURGE_NOT_COMPLETED")
            report["source_purge_after_approval"] = "passed"
            job_id = call("POST", "/v1/books", json=spec).json()["job_id"]
            started = time.monotonic()
            deadline = started + 1200
            job = {}
            previous_state = None
            report["stages"] = []
            while time.monotonic() < deadline:
                job = call("GET", f"/v1/books/{job_id}").json()
                state = {field: job.get(field) for field in ("status", "progress", "current_step")}
                if state != previous_state:
                    report["stages"].append({"seconds": round(time.monotonic() - started, 2), "state": state})
                    print("Book progress: " + str(state["progress"]) + "% / " + str(state["status"]), flush=True)
                    previous_state = state
                if job.get("status") in {"done", "failed"}:
                    break
                time.sleep(2)
            report["job_error_code"] = job_error_code(job)
            report["generation_seconds"] = round(time.monotonic() - started, 2)
            require(job.get("status") == "done", "PHOTO_BOOK_DID_NOT_COMPLETE")
            book_id = job["result"]["book_id"]
            detail = call("GET", f"/v1/books/{book_id}/detail").json()
            require(len(detail["pages"]) == 12, "TWELVE_PAGES_REQUIRED")
            report["images"] = []
            for number, page in enumerate([{"image_url": detail["cover_image_url"]}, *detail["pages"]]):
                _, size = download(page["image_url"], f"page-{number:02d}.png")
                report["images"].append({"page": number, **size})
            references = keys(f"jobs/{job_id}/character-reference/")
            require(len(references) == 1, "ONE_APPROVED_BOOK_REFERENCE_REQUIRED")
            reference = object_store.get_object(Bucket=bucket, Key=references[0])["Body"].read()
            require(hashlib.sha256(reference).hexdigest() == digest, "BOOK_REFERENCE_CHANGED")
            after = call("GET", f"/v1/characters/{character_id}").json()
            require(after.get("avatar_version") == version, "BOOK_REGENERATED_CHARACTER")
            save_json(directory / "book.json", {
                "title": detail["title"], "cover_image": "page-00.png",
                "pages": [{"page": index, "text": page["text"], "image": f"page-{index:02d}.png"}
                          for index, page in enumerate(detail["pages"], 1)],
            })
            save_json(directory / "quality-review.json", {
                "status": "pending_visual_review", "source_classification": manifest["classification"],
                "real_child_likeness": "pending" if manifest["classification"] == "real_child" else "not_applicable",
                "portrait_identity": "pending", "page_identity_and_outfit": "pending",
                "scene_alignment": "pending", "unwanted_text_or_anatomy_errors": "pending",
                "release_approved": False,
            })
            report.update(page_count=12, fixed_portrait_reuse="passed", product_illustration_qa="passed",
                          visual_quality_status="pending", launch_ready=False)
            call("POST", "/v1/consent/revoke")
            require(not keys(f"characters/{character_id}/") and not keys(f"jobs/{job_id}/"),
                    "DERIVED_ASSET_PURGE_INCOMPLETE")
            report["consent_withdrawal_cleanup"] = "passed"
    return execute


def run(args):
    require(args.live is True, "EXPLICIT_LIVE_OPT_IN_REQUIRED")
    manifest = validate_manifest(private_json(args.input_manifest))
    retain_evidence = getattr(args, "retain_fictional_review_evidence", False)
    require(type(retain_evidence) is bool, "INVALID_FICTIONAL_CAPTURE_OPTION")
    require(not retain_evidence or manifest["classification"] == "fictional_image",
            "REAL_CHILD_REVIEW_CAPTURE_FORBIDDEN")
    policy = verified_policy(private_json(args.policy_file), manifest["classification"])
    require(args.env_file.is_file(), "EXPLICIT_ENV_FILE_REQUIRED")
    config = runtime_config(dotenv_values(args.env_file, interpolate=False), policy)
    source = private_bytes(Path(manifest["source_path"]), 10 * 1024 * 1024)
    # Reject malformed inputs before startup. The ordinary upload API performs
    # the product's decode, orientation correction, resize and metadata removal.
    with Image.open(BytesIO(source)) as image:
        require(image.format in {"JPEG", "PNG", "WEBP"} and getattr(image, "n_frames", 1) == 1
                and image.width * image.height <= 16_000_000, "SOURCE_IMAGE_INVALID")
        image.verify()
    profile = SimpleNamespace(
        config=config, guard_module="photo_acceptance_guard", request_limits=dict(REQUEST_LIMITS),
        retain_fictional_review_evidence=retain_evidence,
        environment={"PHOTO_PROCESSING_ENABLED": "true", "ILLUSTRATION_QUALITY_ENABLED": "true",
                     "LIVE_ACCEPTANCE_PAGE_COUNT": "12", "LIVE_PHOTO_POLICY_FILE": str(args.policy_file.resolve()),
                     "IMAGE_MAX_CONCURRENT": str(IMAGE_MAX_CONCURRENT), "OPENAI_IMAGE_QUALITY": "medium"},
        report_fields={"real_child_data": manifest["classification"] == "real_child",
                       "source_classification": manifest["classification"], "photos_used": True,
                       "data_scope": {"appearance": manifest["classification"], "photos_used": True},
                       "provider_journal_version": 3, "visual_quality_status": "pending", "launch_ready": False,
                       "cost_basis": "Operator-verified request estimates stop new requests; not a hard dollar cap or invoice",
                       "budget_target_usd": float(policy["max_budget_usd"]), "image_max_concurrent": IMAGE_MAX_CONCURRENT,
                       "fictional_review_evidence_retained": retain_evidence,
                       "private_artifacts_retained": True, "source_copied_to_artifacts": False},
        journey=journey(manifest, source, args.review_timeout_seconds),
    )
    options = SimpleNamespace(output_dir=args.output_dir, reader_profile_file=None,
                              age=manifest["age_band"], case=1, page_count=12, hold_seconds=0)
    return run_acceptance(options, profile=profile)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    execute = commands.add_parser("run")
    execute.add_argument("--live", action="store_true", required=True)
    for name in ("env-file", "input-manifest", "policy-file", "output-dir"):
        execute.add_argument("--" + name, type=Path, required=True)
    execute.add_argument("--review-timeout-seconds", type=int, choices=range(60, 3601), default=600, metavar="60..3600")
    execute.add_argument("--retain-fictional-review-evidence", action="store_true",
                         help="Keep private generated illustrations and review context before cleanup; fictional inputs only")
    review = commands.add_parser("approve", help="Record an actual source+portrait review; never runs AI")
    review.add_argument("--output-dir", type=Path, required=True)
    review.add_argument("--reviewer", choices=("parent", "delegated_tester"), required=True)
    args = parser.parse_args()
    previous_umask = os.umask(0o077)
    try:
        if args.command == "approve":
            approve(args.output_dir, args.reviewer)
            return 0
        return run(args)
    except Exception as error:
        print("Photo acceptance stopped: " + (str(error) if isinstance(error, GateFailure) else type(error).__name__))
        return 1
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":
    raise SystemExit(main())
