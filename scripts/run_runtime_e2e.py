"""Disposable runtime gate. Never loads project env files or calls paid providers.

Docker images must already exist locally; this tool never installs/pulls anything.
Only containers carrying this run's unique Compose project label are removed.
Illustration review uses a deterministic all-pages test double, not live vision.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

from mock_illustration_review import MARKER_NAME, MARKER_VALUE, write_startup_loader

ROOT = Path(__file__).resolve().parents[1]
MINIO_TEST_IMAGE = "storybook-minio-test:2025-09-07"
IMAGES = ("postgres:15-alpine", "redis:7-alpine", MINIO_TEST_IMAGE)


class GateFailure(RuntimeError):
    pass


def first_book_trial_environment():
    owner = str(uuid.uuid4())
    allowed_hash = hashlib.sha256(f"asb:generation-access:v1\0{owner}".encode()).hexdigest()
    return {
        "FREE_PLAN_FIRST_BOOK_TRIAL": "true",
        "GENERATION_ACCESS_MODE": "invite_only",
        "GENERATION_ALLOWED_USER_HASHES": allowed_hash,
        "RUNTIME_TRIAL_OWNER": owner,
    }


def clean_environment():
    # Preserve tools/platform configuration, never ambient API/store/database keys.
    names = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "DOCKER_HOST",
             "DOCKER_CONTEXT", "DOCKER_CONFIG")
    return {key: os.environ[key] for key in names if key in os.environ}


def run(command, *, env, cwd=None, timeout=240, log=None):
    process = subprocess.Popen(command, env=env, cwd=cwd, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException:
        stop_process_group(process)
        stdout, stderr = process.communicate()
        if log:
            log.write_text(stdout + stderr)
        raise
    if log:
        log.write_text(stdout + stderr)
    if process.returncode:
        raise GateFailure(f"{Path(command[0]).name} step failed; inspect the local report logs")
    return stdout


def stop_process_group(process):
    # pytest launches Celery subprocesses. A timeout must stop the whole owned group.
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)


def require(condition, message):
    if not condition:
        raise GateFailure(message)


def port_for(compose, service, port, env):
    address = run(compose + ["port", service, str(port)], env=env).strip()
    require(address.startswith("127.0.0.1:"), "Dependency did not bind exclusively to localhost")
    return int(address.rsplit(":", 1)[1])


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def private_media_journey(base, env, report):
    """Actual HTTP/API/S3 checks, using only synthetic newly generated books."""
    import httpx
    from urllib.parse import urlsplit, urlunsplit

    checks = []
    first_book_trial = env.get("FREE_PLAN_FIRST_BOOK_TRIAL") == "true"

    def check(condition, name):
        require(condition, name)
        checks.append(name)

    with httpx.Client(base_url=base, timeout=30, follow_redirects=False) as client:
        ready = client.get("/health/ready")
        services = ready.json().get("services", {})
        check(all(services.get(key) == "healthy" for key in
                  ("database", "redis", "storage", "job_monitor")),
              "Real database, Redis, storage and job monitor are healthy")
        check(ready.status_code == 503 and services.get("provider_keys") == "unhealthy",
              "Readiness correctly rejects mock provider release configuration")
        owner = {"X-User-Key": env["RUNTIME_TRIAL_OWNER"] if first_book_trial else str(uuid.uuid4())}
        foreign = {"X-User-Key": str(uuid.uuid4())}
        consent = client.post("/v1/consent", headers=owner, json={
            "privacy": True, "photos": False, "data_processing": True})
        check(consent.status_code == 200, "Parent consent is persisted")
        if first_book_trial:
            capabilities = client.get("/v1/config/capabilities").json()
            check(capabilities.get("free_first_book_trial") is True and capabilities.get("purchases_supported") is False,
                  "Free beta advertises one trial book and keeps checkout disabled")
            check(client.get("/v1/credits/balance", headers=owner).json().get("credits") == 1,
                  "A new account receives exactly one trial credit")
        page_count = 12 if first_book_trial else 4
        spec = {
            "topic": "친구와 함께하는 작은 도서관", "language": "ko",
            "target_age": "3-5", "style": "watercolor", "page_count": page_count,
        }
        if first_book_trial:
            outsider_consent = client.post("/v1/consent", headers=foreign, json={
                "privacy": True, "photos": False, "data_processing": True})
            check(outsider_consent.status_code == 200, "Uninvited account can grant parental consent")
            denied = client.post("/v1/books", headers=foreign, json=spec)
            check(denied.status_code == 503 and denied.headers.get("retry-after") == "3600",
                  "Uninvited account cannot start book generation")
            check(client.get("/v1/credits/balance", headers=foreign).json().get("credits") == 1,
                  "Denied request does not spend the uninvited account's trial credit")
        request_headers = {**owner, "X-Idempotency-Key": str(uuid.uuid4())}
        created = client.post("/v1/books", headers=request_headers, json=spec)
        check(created.status_code == 200, "HTTP generation request enters Celery")
        job_id = created.json()["job_id"]
        job = {}
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            response = client.get(f"/v1/books/{job_id}", headers=owner)
            check(response.status_code == 200, "Owner can poll generation") if not job else None
            job = response.json()
            if job.get("status") in {"done", "failed"}:
                break
            time.sleep(1)
        check(job.get("status") == "done", "Celery generation completes through real PostgreSQL")
        book_id = job["result"]["book_id"]
        detail = client.get(f"/v1/books/{book_id}/detail", headers=owner)
        check(detail.status_code == 200, "Owner receives book detail")
        if first_book_trial:
            pages = detail.json()["pages"]
            check([page["page_number"] for page in pages] == list(range(1, 13)),
                  "The trial delivers a full twelve-page book")
            for page in pages:
                media = client.get(page["image_url"])
                check(media.status_code == 200 and bool(media.content), f"Owner can download page {page['page_number']}")
            repeated = client.post("/v1/books", headers=request_headers, json=spec)
            check(repeated.status_code == 200 and repeated.json()["job_id"] == job_id,
                  "A retry reuses the first trial job")
            check(client.get("/v1/credits/balance", headers=owner).json().get("credits") == 0,
                  "The completed book consumes the trial credit")
            next_book = client.post("/v1/books", headers=owner, json=spec)
            check(next_book.status_code == 402
                  and next_book.json()["error"]["details"]["reason"] == "insufficient_credits",
                  "Another book is declined when the account has no credits")
            today = client.post("/v1/streak/today/generate", headers=owner, json={
                "target_age": "3-5", "style": "watercolor", "language": "ko",
            })
            check(today.status_code == 402 and today.json()["error"]["details"]["reason"] == "insufficient_credits",
                  "Quick creation enforces the same trial limit")
        check("no-store" in detail.headers.get("cache-control", ""),
              "Private API responses prohibit intermediary caching")
        image_url = detail.json()["cover_image_url"]
        parsed = urlsplit(image_url)
        check("X-Amz-Signature=" in parsed.query, "Owner media carries a time-limited signature")
        image = client.get(image_url)
        check(image.status_code == 200 and len(image.content) > 0,
              "Signed image downloads from the private S3 bucket")
        unsigned = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        check(client.get(unsigned).status_code in {403, 404}, "Anonymous image access is blocked")
        tampered = image_url.replace("X-Amz-Signature=", "X-Amz-Signature=0", 1)
        check(client.get(tampered).status_code == 403, "Tampered signatures are rejected")
        check(client.get(f"/v1/books/{book_id}/detail", headers=foreign).status_code in {403, 404},
              "Another account cannot obtain signed book media")
        check(client.get(f"/v1/books/{book_id}/detail").status_code in {400, 401, 422},
              "Anonymous API access cannot obtain signed book media")
        shared = client.post(f"/v1/books/{book_id}/share", headers=owner, json={})
        check(shared.status_code == 200, "Parent can create a revocable share")
        share_url = shared.json()["url"]
        check(client.get(share_url + "/img/cover").status_code == 200,
              "Active share proxy can read private S3 media")
        check(client.post(f"/v1/books/{book_id}/share/revoke", headers=owner).status_code == 200,
              "Parent can revoke the share")
        check(client.get(share_url + "/img/cover").status_code == 404,
              "Revoked share loses image access immediately")
        # Verify expiry against the real storage server without sleeping for the app's 1h TTL.
        import boto3
        from botocore.config import Config
        storage = boto3.client("s3", endpoint_url=env["S3_ENDPOINT"],
            aws_access_key_id=env["S3_ACCESS_KEY"], aws_secret_access_key=env["S3_SECRET_KEY"],
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
        key = parsed.path.split("/", 2)[2]
        short_url = storage.generate_presigned_url("get_object", Params={
            "Bucket": env["S3_BUCKET"], "Key": key}, ExpiresIn=1)
        time.sleep(2)
        check(client.get(short_url).status_code == 403, "Expired storage signatures are rejected")
    report["private_media_checks"] = checks


def photo_avatar_journey(base, env, report):
    """Synthetic pixels -> Celery portrait -> approval -> book -> real S3 erasure."""
    from io import BytesIO
    from urllib.parse import urlsplit

    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
    import httpx
    from PIL import Image
    from sqlalchemy import create_engine, text

    require(all(env.get(name) == "mock" for name in
                ("LLM_PROVIDER", "IMAGE_PROVIDER", "PHOTO_ANALYSIS_PROVIDER"))
            and env.get("PHOTO_PROCESSING_ENABLED") == "false",
            "Photo runtime journey requires explicit disabled-live, all-mock providers")
    require(urlsplit(base).hostname == "127.0.0.1"
            and urlsplit(env["S3_ENDPOINT"]).hostname == "127.0.0.1",
            "Photo runtime journey only accepts the disposable localhost API and storage")
    checks = []
    report["photo_avatar_journey"] = "failed"
    report["photo_avatar_checks"] = checks

    def check(condition, name):
        require(condition, name)
        checks.append(name)

    storage = boto3.client("s3", endpoint_url=env["S3_ENDPOINT"],
        aws_access_key_id=env["S3_ACCESS_KEY"], aws_secret_access_key=env["S3_SECRET_KEY"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
    bucket = env["S3_BUCKET"]

    def keys_under(prefix):
        keys = []
        for page in storage.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
            keys.extend(item["Key"] for item in page.get("Contents", []))
        return keys

    def object_missing(key):
        try:
            storage.head_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            return str(exc.response.get("Error", {}).get("Code")) in {"404", "NoSuchKey"}
        return False

    # A flat generated color tile with synthetic metadata, never a person/photo.
    tile = Image.new("RGB", (96, 128), (102, 153, 204))
    metadata = Image.Exif()
    metadata[270] = "synthetic-only-metadata-to-remove"
    source = BytesIO()
    tile.save(source, format="JPEG", exif=metadata)
    owner_key = str(uuid.uuid4())
    owner = {"X-User-Key": owner_key}
    engine = create_engine(env["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"), echo=False)
    try:
        with httpx.Client(base_url=base, timeout=30, follow_redirects=False) as client:
            check(client.post("/v1/consent", headers=owner, json={
                "privacy": True, "photos": True, "data_processing": True,
            }).status_code == 200, "Synthetic photo account records parental consent")
            response = client.post("/v1/characters/from-photo", headers={
                **owner, "X-Idempotency-Key": str(uuid.uuid4()),
            }, files={"photo": ("synthetic-tile.jpg", source.getvalue(), "image/jpeg")},
                data={"name": "합성 테스트", "style": "watercolor"})
            check(response.status_code == 200, "Synthetic image upload creates an asynchronous portrait")
            character = response.json()
            character_id = character["character_id"]
            check(character.get("avatar_status") == "generating" and not character.get("avatar_url"),
                  "Upload returns generating state before any preview is published")
            check("source_image_url" not in character, "Character API never returns the source photo URL")
            spec = {"topic": "친구와 작은 정원을 돌보는 이야기", "language": "ko",
                    "target_age": "7-9", "style": "watercolor", "page_count": 12,
                    "character_ids": [character_id]}
            check(client.post("/v1/books", headers=owner, json=spec).status_code == 409,
                  "A generating or unapproved portrait cannot start a book")

            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                response = client.get(f"/v1/characters/{character_id}", headers=owner)
                require(response.status_code == 200, "Portrait polling request failed")
                character = response.json()
                if character.get("avatar_status") in {"preview", "failed"}:
                    break
                time.sleep(0.5)
            check(character.get("avatar_status") == "preview",
                  "Celery publishes one versioned portrait preview using mock AI")
            avatar_url = character.get("avatar_url") or ""
            avatar_image = client.get(avatar_url)
            check(avatar_image.status_code == 200 and bool(avatar_image.content),
                  "Preview is an existing private S3 image with signed access")
            original_key = f"characters/{character_id}/photo.jpg"
            original = storage.get_object(Bucket=bucket, Key=original_key)["Body"].read()
            with Image.open(BytesIO(original)) as normalized:
                check(normalized.format == "JPEG" and not normalized.getexif()
                      and max(normalized.size) <= 1024,
                      "Stored synthetic source is decoded, bounded and stripped of EXIF metadata")
            check(client.post("/v1/books", headers=owner, json=spec).status_code == 409,
                  "Preview alone does not bypass parental portrait approval")

            approved = client.post(f"/v1/characters/{character_id}/avatar/approve",
                                   headers=owner, json={"version": character["avatar_version"]})
            check(approved.status_code == 200 and approved.json().get("avatar_status") == "approved",
                  "Parent approves the exact current portrait version")
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and not object_missing(original_key):
                time.sleep(0.5)
            check(object_missing(original_key), "Approval removes original source bytes from real S3")
            with engine.connect() as db:
                purge_state = db.scalar(text(
                    "SELECT status FROM storage_purge_tasks "
                    "WHERE user_key = :owner AND target = :target AND reason = 'avatar_source_approved' "
                    "ORDER BY id DESC LIMIT 1"
                ), {"owner": owner_key, "target": original_key})
            check(purge_state == "done", "Original-source erasure has a completed durable outbox record")

            created = client.post("/v1/books", headers=owner, json=spec)
            check(created.status_code == 200, "Approved portrait starts a twelve-page book through Celery")
            job_id = created.json()["job_id"]
            job = {}
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                polled = client.get(f"/v1/books/{job_id}", headers=owner)
                require(polled.status_code == 200, "Photo-derived book polling request failed")
                job = polled.json()
                if job.get("status") in {"done", "failed"}:
                    break
                time.sleep(0.5)
            check(job.get("status") == "done", "Photo-derived book completes on real PostgreSQL/Celery")
            book_id = job["result"]["book_id"]
            detail = client.get(f"/v1/books/{book_id}/detail", headers=owner)
            check(detail.status_code == 200 and len(detail.json().get("pages", [])) == 12,
                  "Completed photo-derived book contains twelve story pages")
            book = detail.json()
            image_urls = [book["cover_image_url"], *(page["image_url"] for page in book["pages"])]
            check(all(client.get(url).status_code == 200 for url in image_urls),
                  "Cover and all twelve page images exist in private S3")
            snapshots = keys_under(f"jobs/{job_id}/character-reference/")
            check(len(snapshots) == 1, "Book owns one durable approved-portrait reference snapshot")
            reference = storage.get_object(Bucket=bucket, Key=snapshots[0])["Body"].read()
            check(reference == avatar_image.content, "Book reference bytes match the parent-approved portrait")
            with engine.connect() as db:
                derived = db.scalar(text("SELECT photo_derived FROM jobs WHERE id = :id AND user_key = :owner"),
                                    {"id": job_id, "owner": owner_key})
            check(derived is True, "Book generation retains durable photo provenance")

            check(client.delete(f"/v1/characters/{character_id}", headers=owner).status_code == 200,
                  "Parent can remove the reusable character")
            check(client.get(f"/v1/books/{book_id}/detail", headers=owner).status_code == 200
                  and not object_missing(snapshots[0]),
                  "Existing book and its own portrait snapshot survive character removal")
            check(client.post("/v1/consent/revoke", headers=owner).status_code == 200,
                  "Photo consent can be withdrawn after the character was removed")
            check(client.get(f"/v1/books/{book_id}/detail", headers=owner).status_code == 404,
                  "Consent withdrawal erases the derived book even without its character record")
            check(not keys_under(f"characters/{character_id}/")
                  and not keys_under(f"jobs/{job_id}/")
                  and not keys_under(f"books/{book_id}/"),
                  "Withdrawal removes original, portrait, snapshot and generated book bytes from S3")
            check(all(client.get(url).status_code == 404 for url in image_urls),
                  "Previously signed page URLs cannot retrieve erased images")
            with engine.connect() as db:
                remaining = db.scalar(text(
                    "SELECT count(*) FROM storage_purge_tasks WHERE user_key = :owner "
                    "AND status IN ('pending', 'failed')"
                ), {"owner": owner_key})
            check(remaining == 0, "This completed journey leaves no unfinished media-erasure task")
    finally:
        engine.dispose()
    report["photo_avatar_journey"] = "passed"
    report["photo_avatar_page_count"] = 12
    report["photo_avatar_source"] = "locally generated color tile; no real person or photo"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path,
                        help="Optional directory for synthetic-only logs/results (default: temporary)")
    parser.add_argument("--suite", choices=("all", "media", "first-book-trial"), default="all",
                        help="Run all regressions, media journeys, or the full first-book trial journey")
    parser.add_argument("--serve", action="store_true",
                        help="After successful checks, keep the synthetic localhost API running until Ctrl-C")
    parser.add_argument("--api-port", type=int, default=0,
                        help="Local API port (default: choose a free port)")
    parser.add_argument("--web-origin", default="http://127.0.0.1:18281",
                        help="Local browser preview origin allowed only with --serve")
    args = parser.parse_args()
    if not 0 <= args.api_port <= 65535:
        parser.error("--api-port must be between 0 and 65535")
    if args.serve:
        from urllib.parse import urlsplit
        origin = urlsplit(args.web_origin)
        if (origin.scheme != "http" or origin.hostname not in {"127.0.0.1", "localhost"}
                or origin.username or origin.password or origin.path or origin.query or origin.fragment):
            parser.error("--web-origin must be an HTTP localhost origin without credentials or a path")
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    report_dir = (args.report_dir or Path(tempfile.mkdtemp(prefix="storybook-runtime-report-"))).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    env = clean_environment()
    report = {"status": "failed", "providers": "deterministic mocks",
              "illustration_review": "deterministic explicit all-pages test double; not live vision",
              "real_dependencies": ["PostgreSQL", "Redis", "Celery", "private S3"],
              "suite": args.suite, "live_provider_or_store_validation": False,
              "started_at": datetime.now(timezone.utc).isoformat(),
              "python_version": sys.version.split()[0]}
    processes = []
    handles = []
    project = "storybook-runtime-" + uuid.uuid4().hex[:12]
    compose = ["docker", "compose", "--project-name", project, "--env-file", os.devnull,
               "-f", str(ROOT / "infra/docker-compose.e2e.yml")]
    started = False
    try:
        # DOCKER_CONTEXT takes precedence over DOCKER_HOST in the Docker CLI.
        if env.get("DOCKER_HOST") and not env.get("DOCKER_CONTEXT"):
            docker_host = env["DOCKER_HOST"]
        else:
            docker_host = run(
                ["docker", "context", "inspect", "--format", '{{.Endpoints.docker.Host}}'], env=env).strip()
        require(docker_host.startswith(("unix://", "npipe://")),
                "Runtime gate requires a local Docker socket; remote Docker hosts are refused")
        report["docker_version"] = run(["docker", "info", "--format", "{{.ServerVersion}}"], env=env).strip()
        report["dependency_images"] = {}
        for image in IMAGES:
            report["dependency_images"][image] = run(
                ["docker", "image", "inspect", image, "--format", "{{.Id}}"], env=env).strip()
        with tempfile.TemporaryDirectory(prefix="storybook-runtime-source-") as workspace:
            api = Path(workspace) / "api"
            api.mkdir()
            # Explicit allowlist means .env, runtime databases and credentials never enter the copy.
            for name in ("src", "tests", "alembic", "scripts", "assets"):
                shutil.copytree(ROOT / "apps/api" / name, api / name,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env*"))
            for name in ("alembic.ini", "pyproject.toml", "pytest.ini"):
                shutil.copy2(ROOT / "apps/api" / name, api / name)
            write_startup_loader(api)
            started = True
            print("Starting disposable PostgreSQL, Redis and private MinIO...", flush=True)
            run(compose + ["up", "-d", "--pull", "never", "--wait", "--wait-timeout", "90"],
                env=env, log=report_dir / "dependencies.log")
            pg = port_for(compose, "postgres", 5432, env)
            redis = port_for(compose, "redis", 6379, env)
            s3 = port_for(compose, "minio", 9000, env)
            runtime_env = dict(env, PYTHONPATH=str(api), TESTING="false", USE_CELERY="true",
                DATABASE_URL=f"postgresql+asyncpg://runtime_test:disposable-runtime-password@127.0.0.1:{pg}/runtime_test",
                REDIS_URL=f"redis://127.0.0.1:{redis}/0", CELERY_BROKER_URL=f"redis://127.0.0.1:{redis}/1",
                CELERY_RESULT_BACKEND=f"redis://127.0.0.1:{redis}/2",
                S3_ENDPOINT=f"http://127.0.0.1:{s3}", S3_DOWNLOAD_ENDPOINT=f"http://127.0.0.1:{s3}",
                S3_PUBLIC_URL=f"http://127.0.0.1:{s3}/runtime-test", S3_BUCKET="runtime-test",
                S3_ACCESS_KEY="runtime_test", S3_SECRET_KEY="disposable-runtime-password",
                LLM_PROVIDER="mock", IMAGE_PROVIDER="mock", TTS_PROVIDER="mock", STT_PROVIDER="mock",
                PHOTO_ANALYSIS_PROVIDER="mock", PHOTO_PROCESSING_ENABLED="false",
                ILLUSTRATION_QUALITY_ENABLED="true",
                AUDIO_FEATURE_ENABLED="false", POD_ORDERING_ENABLED="false", PURCHASES_ENABLED="false",
                IAP_VERIFICATION_MODE="strict",
                RATE_LIMIT_REQUESTS="100000", DAILY_GENERATION_BUDGET="100", OBJC_DISABLE_INITIALIZE_FORK_SAFETY="YES")
            if args.suite == "first-book-trial":
                runtime_env.update(first_book_trial_environment())
            runtime_env[MARKER_NAME] = MARKER_VALUE
            if args.serve:
                runtime_env["CORS_ORIGINS"] = args.web_origin
            runtime_env.update(E2E_PG_DATABASE_URL=runtime_env["DATABASE_URL"],
                E2E_REDIS_URL=f"redis://127.0.0.1:{redis}/5", E2E_S3_ENDPOINT=runtime_env["S3_ENDPOINT"],
                E2E_S3_ACCESS_KEY=runtime_env["S3_ACCESS_KEY"], E2E_S3_SECRET_KEY=runtime_env["S3_SECRET_KEY"],
                E2E_S3_BUCKET=runtime_env["S3_BUCKET"])
            if args.suite == "all":
                print("Running PostgreSQL migration, erasure, photo concurrency, account recovery and Celery gates...", flush=True)
                junit = report_dir / "runtime-tests.xml"
                run([sys.executable, "-m", "pytest", "tests/test_pg_fk_erasure.py",
                     "tests/test_celery_worker_pg.py", "tests/test_account_recovery_pg.py",
                     "tests/test_photo_lifecycle_pg.py",
                     "-q", f"--junitxml={junit}"],
                    env=runtime_env, cwd=api, timeout=480, log=report_dir / "runtime-tests.log")
                cases = list(ET.parse(junit).getroot().iter("testcase"))
                require(len(cases) >= 21 and not any(case.find("skipped") is not None for case in cases),
                        "PostgreSQL/Celery gate must execute all cases without skips")
                account_cases = [case for case in cases if "test_account_recovery_pg" in case.get("classname", "")]
                photo_cases = [case for case in cases if "test_photo_lifecycle_pg" in case.get("classname", "")]
                require(len(account_cases) >= 4, "PostgreSQL account recovery concurrency gate did not run")
                require(len(photo_cases) >= 7, "PostgreSQL photo lifecycle concurrency gate did not run")
                report["postgres_regression_tests_passed"] = len(cases)
                report["postgres_account_recovery_tests_passed"] = len(account_cases)
                report["postgres_photo_lifecycle_tests_passed"] = len(photo_cases)
                report["postgres_celery_tests_passed"] = len(cases) - len(account_cases) - len(photo_cases)
            else:
                run([sys.executable, "-m", "alembic", "upgrade", "head"], env=runtime_env,
                    cwd=api, log=report_dir / "migrations.log")
            api_port = args.api_port or free_port()
            for name, command in (("worker", [sys.executable, "-m", "celery", "-A", "src.worker", "worker",
                                              "--loglevel=warning", "--concurrency=1", "--pool=solo"]),
                                  ("api", [sys.executable, "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1",
                                           "--port", str(api_port), "--no-access-log",
                                           "--header", f"X-Storybook-Runtime:{project}"])):
                handle = (report_dir / f"{name}.log").open("w")
                handles.append(handle)
                processes.append(subprocess.Popen(command, env=runtime_env, cwd=api,
                    stdout=handle, stderr=subprocess.STDOUT, start_new_session=True))
            import httpx
            base = f"http://127.0.0.1:{api_port}"
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                require(all(process.poll() is None for process in processes), "API or worker stopped before readiness")
                try:
                    response = httpx.get(base + "/health/live", timeout=1)
                    if (response.status_code == 200
                            and response.headers.get("x-storybook-runtime") == project):
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            else:
                raise GateFailure("Disposable API did not start")
            print("Checking signed media, ownership, sharing and real expiry...", flush=True)
            private_media_journey(base, runtime_env, report)
            if args.suite == "first-book-trial":
                report["first_book_trial_journey"] = "passed"
            else:
                print("Checking synthetic portrait preview, approval, twelve-page generation and erasure...", flush=True)
                photo_avatar_journey(base, runtime_env, report)
                print("Running the complete HTTP reading journey through Celery...", flush=True)
                run([sys.executable, "scripts/e2e_journey.py", base], env=runtime_env, cwd=api,
                    timeout=240, log=report_dir / "journey.log")
                report["http_journey"] = "passed"
            report["status"] = "passed"
            if args.serve:
                report.update(preview_api_url=base, preview_origin=args.web_origin,
                              preview_running=True, cleanup="pending until preview stops")
                (report_dir / "result.json").write_text(json.dumps(report, indent=2) + "\n")
                print(f"Synthetic preview API ready: {base}. Ctrl-C stops its owned resources.", flush=True)
                try:
                    while True:
                        require(all(process.poll() is None for process in processes),
                                "Preview API or worker stopped unexpectedly")
                        time.sleep(1)
                except KeyboardInterrupt:
                    print("Stopping synthetic preview...", flush=True)
                finally:
                    report["preview_running"] = False
    except Exception as exc:
        # Avoid raw SDK/HTTP error text which can include credentials or signed URLs.
        report["failure"] = str(exc) if isinstance(exc, GateFailure) else type(exc).__name__
        print(f"Runtime gate failed: {report['failure']}", flush=True)
    finally:
        for process in reversed(processes):
            stop_process_group(process)
        for handle in handles:
            handle.close()
        if started:
            try:
                run(compose + ["down", "--volumes", "--remove-orphans"], env=env,
                    timeout=90, log=report_dir / "cleanup.log")
                report["cleanup"] = "completed"
            except Exception:
                report.update(status="failed", cleanup="failed", compose_project=project)
        (report_dir / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"Runtime gate: {report['status']}. Report: {report_dir}", flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
