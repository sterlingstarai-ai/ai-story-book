"""Prove PostgreSQL + private-S3 restore using disposable synthetic data only.

No project .env is loaded, no existing volume or remote Docker daemon is accepted,
and no production backup is created. All synthetic dumps/media are removed on exit.
"""

import argparse
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from run_runtime_e2e import GateFailure, clean_environment, port_for, require, run

ROOT = Path(__file__).resolve().parents[1]
BUCKET = "restore-rehearsal"
CREDENTIAL = "disposable-runtime-password"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def storage(endpoint):
    import boto3
    from botocore.config import Config
    return boto3.client("s3", endpoint_url=endpoint, aws_access_key_id="runtime_test",
        aws_secret_access_key=CREDENTIAL, region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))


def object_inventory(client):
    inventory = {}
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET):
        for item in page.get("Contents", []):
            obj = client.get_object(Bucket=BUCKET, Key=item["Key"])
            try:
                data = obj["Body"].read()
            finally:
                obj["Body"].close()
            inventory[item["Key"]] = {
                "sha256": sha256(data), "size": len(data),
                "content_type": obj["ContentType"], "metadata": obj.get("Metadata", {}),
            }
    return inventory


async def wait_for_host_database(port):
    """Container health does not prove Docker Desktop's published port is ready."""
    import asyncpg
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        connection = None
        try:
            connection = await asyncpg.connect(host="127.0.0.1", port=port, user="runtime_test",
                password=CREDENTIAL, database="runtime_test", timeout=2)
            require(await connection.fetchval("SELECT 1", timeout=2) == 1,
                    "Disposable PostgreSQL host probe returned an unexpected result")
            return
        except (OSError, asyncio.TimeoutError, asyncpg.PostgresError):
            await asyncio.sleep(0.5)
        finally:
            if connection is not None:
                await connection.close(timeout=2)
    raise GateFailure("Disposable PostgreSQL published port did not become ready on this host")


async def database_snapshot(port):
    import asyncpg
    connection = await asyncpg.connect(host="127.0.0.1", port=port, user="runtime_test",
        password=CREDENTIAL, database="runtime_test")
    try:
        tables = await connection.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        snapshot = {}
        for row in tables:
            name = row["tablename"]
            quoted = '"' + name.replace('"', '""') + '"'
            data = await connection.fetchval(
                f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), '[]'::jsonb)::text FROM {quoted} t")
            snapshot[name] = {"rows": len(json.loads(data)), "sha256": sha256(data.encode())}
        return snapshot
    finally:
        await connection.close()


async def seed_database(port, media):
    import asyncpg
    connection = await asyncpg.connect(host="127.0.0.1", port=port, user="runtime_test",
        password=CREDENTIAL, database="runtime_test")
    try:
        # The fixed bearer-shaped fixture exists only inside this disposable run.
        owner = "00000000-0000-4000-8000-000000000001"
        await connection.execute("""INSERT INTO account_identities
            (user_key,device_key_hash,recovery_code_hash,previous_recovery_code_hash,deleted,created_at,updated_at)
            VALUES ($1,$2,$3,$4,false,now(),now())""", owner,
            sha256(b"synthetic-active-device"), sha256(b"synthetic-active-recovery"),
            sha256(b"synthetic-revoked-recovery"))
        await connection.execute("""INSERT INTO account_identities
            (user_key,deleted,created_at,updated_at)
            VALUES ('00000000-0000-4000-8000-000000000002',true,now(),now())""")
        await connection.execute("""INSERT INTO user_consents
            (user_key,consent_version,privacy,photos,data_processing,granted)
            VALUES ($1,'v2',true,false,true,true)""", owner)
        await connection.execute("""INSERT INTO jobs
            (id,status,progress,current_step,user_key,idempotency_key,image_keys)
            VALUES ('restore-job','done',100,'done',$1,'restore-idempotency',$2)""",
            owner, json.dumps(list(media)))
        await connection.execute("""INSERT INTO books
            (id,job_id,title,language,target_age,style,cover_image_url,pdf_url,user_key)
            VALUES ('restore-book','restore-job','복구 시험용 동화','ko','3-5','watercolor',$1,$2,$3)""",
            "s3://restore-rehearsal/books/cover.png", "s3://restore-rehearsal/books/book.pdf", owner)
        for number in (1, 2):
            await connection.execute("""INSERT INTO pages (book_id,page_number,text,image_url)
                VALUES ('restore-book',$1,$2,$3)""", number,
                f"합성 데이터 {number}: 토끼가 친구와 책을 읽어요.",
                f"s3://restore-rehearsal/books/page-{number}.png")
        await connection.execute("""INSERT INTO storage_purge_tasks
            (user_key,reason,kind,target,status,attempts)
            VALUES ($1,'account_deletion','keys','["pending-erasure/asset.png"]','pending',0)""", owner)
    finally:
        await connection.close()


async def verify_restored_constraints(port):
    import asyncpg
    connection = await asyncpg.connect(host="127.0.0.1", port=port, user="runtime_test",
        password=CREDENTIAL, database="runtime_test")
    checks = []
    try:
        next_id = await connection.fetchval("""INSERT INTO pages(book_id,page_number,text)
            VALUES ('restore-book',3,'복구 후 새 페이지') RETURNING id""")
        require(next_id > 2, "Restored page sequence would overwrite an existing row")
        checks.append("PostgreSQL sequences continue after restored rows")
        for statement, expected, label in (
            ("INSERT INTO pages(book_id,page_number,text) VALUES ('absent-book',1,'orphan')",
             asyncpg.ForeignKeyViolationError, "Restored foreign keys reject orphan pages"),
            ("INSERT INTO pages(book_id,page_number,text) VALUES ('restore-book',1,'duplicate')",
             asyncpg.UniqueViolationError, "Restored uniqueness rejects duplicate page numbers"),
        ):
            try:
                await connection.execute(statement)
            except expected:
                checks.append(label)
            else:
                raise GateFailure(label)
        pending = await connection.fetchval("SELECT count(*) FROM storage_purge_tasks WHERE status='pending'")
        require(pending == 1, "Restore lost a pending deletion instruction")
        checks.append("Pending media deletion outbox survives restore")
        require(await connection.fetchval("SELECT count(*) FROM account_identities WHERE deleted=true") == 1,
                "Restore lost a deleted-account tombstone")
        require(await connection.fetchval("SELECT previous_recovery_code_hash FROM account_identities WHERE deleted=false")
                == sha256(b"synthetic-revoked-recovery"), "Restore lost the previous recovery-code revocation state")
        checks.append("Account tombstones and recovery credential rotation state survive restore")
        return checks
    finally:
        await connection.close()


def binary_command(command, env, *, source=None, destination=None):
    result = subprocess.run(command, env=env, stdin=source, stdout=destination or subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=120)
    require(result.returncode == 0, "PostgreSQL archive step failed")


def copy_media(source, destination, folder):
    manifest = object_inventory(source)
    for index, (key, metadata) in enumerate(sorted(manifest.items())):
        path = folder / str(index)
        source.download_file(BUCKET, key, str(path))
        require(sha256(path.read_bytes()) == metadata["sha256"], "Media backup checksum mismatch")
        destination.upload_file(str(path), BUCKET, key, ExtraArgs={
            "ContentType": metadata["content_type"], "Metadata": metadata["metadata"]})
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path,
                        help="Only secret-free evidence/logs persist here; all dump/media files are temporary")
    args = parser.parse_args()
    os.umask(0o077)
    report_dir = (args.report_dir or Path(tempfile.mkdtemp(prefix="storybook-restore-report-"))).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {"status": "failed", "synthetic_data_only": True, "production_touched": False,
              "started_at": datetime.now(timezone.utc).isoformat(), "checks": [],
              "limits": ["Tiny fixture does not establish production RTO/RPO or capacity",
                         "No production object versioning, encryption, retention or offsite recovery was tested",
                         "Redis queue recovery is not part of a PostgreSQL/S3 restore"]}
    env = clean_environment()
    projects = []
    started = time.monotonic()

    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)

    try:
        docker_host = env.get("DOCKER_HOST") if not env.get("DOCKER_CONTEXT") else None
        if not docker_host:
            docker_host = run(["docker", "context", "inspect", "--format", '{{.Endpoints.docker.Host}}'], env=env).strip()
        require(docker_host.startswith(("unix://", "npipe://")), "Only a local Docker socket is allowed")
        report["images"] = {name: run(["docker", "image", "inspect", name, "--format", "{{.Id}}"], env=env).strip()
                            for name in ("postgres:15-alpine", "quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e")}
        report["docker_version"] = run(["docker", "info", "--format", "{{.ServerVersion}}"], env=env).strip()
        with tempfile.TemporaryDirectory(prefix="storybook-restore-private-") as temporary:
            workspace = Path(temporary)
            api = workspace / "api"
            api.mkdir()
            for name in ("src", "alembic"):
                shutil.copytree(ROOT / "apps/api" / name, api / name,
                                ignore=shutil.ignore_patterns(".env*", "__pycache__", "*.pyc"))
            shutil.copy2(ROOT / "apps/api/alembic.ini", api / "alembic.ini")
            dependencies = []
            print("Starting two isolated PostgreSQL/private-S3 environments...", flush=True)
            for label in ("source", "restored"):
                project = "storybook-restore-" + uuid.uuid4().hex[:12]
                compose = ["docker", "compose", "--project-name", project, "--env-file", os.devnull,
                           "-f", str(ROOT / "infra/docker-compose.e2e.yml")]
                projects.append((project, compose))
                run(compose + ["up", "-d", "--pull", "never", "--wait", "--wait-timeout", "90", "postgres", "minio"],
                    env=env, log=report_dir / f"{label}-dependencies.log")
                pg = port_for(compose, "postgres", 5432, env)
                asyncio.run(wait_for_host_database(pg))
                endpoint = f"http://127.0.0.1:{port_for(compose, 'minio', 9000, env)}"
                dependencies.append((compose, pg, endpoint, storage(endpoint)))
            source_compose, source_pg, _, source_s3 = dependencies[0]
            target_compose, target_pg, target_endpoint, target_s3 = dependencies[1]
            runtime_env = dict(env, DATABASE_URL=f"postgresql+asyncpg://runtime_test:{CREDENTIAL}@127.0.0.1:{source_pg}/runtime_test",
                               TESTING="true", LLM_PROVIDER="mock", IMAGE_PROVIDER="mock",
                               AUDIO_FEATURE_ENABLED="false", POD_ORDERING_ENABLED="false", PURCHASES_ENABLED="false")
            run([sys.executable, "-m", "alembic", "upgrade", "head"], env=runtime_env, cwd=api,
                log=report_dir / "migrations.log")
            report["checks"].append("Source schema migrates to current Alembic head")
            pixel = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+afo4AAAAASUVORK5CYII=")
            media = {"books/cover.png": (pixel, "image/png"), "books/page-1.png": (pixel, "image/png"),
                     "books/page-2.png": (pixel, "image/png"), "books/book.pdf": (b"%PDF-1.4\n%synthetic restore fixture\n%%EOF\n", "application/pdf"),
                     "pending-erasure/asset.png": (pixel, "image/png")}
            for client in (source_s3, target_s3):
                client.create_bucket(Bucket=BUCKET)
            for key, (data, content_type) in media.items():
                source_s3.put_object(Bucket=BUCKET, Key=key, Body=data, ContentType=content_type,
                                     Metadata={"fixture": "synthetic-restore"})
            asyncio.run(seed_database(source_pg, media))
            source_snapshot = asyncio.run(database_snapshot(source_pg))
            archive = workspace / "database.dump"
            print("Backing up synthetic rows/media and restoring to the empty environment...", flush=True)
            backup_started = time.monotonic()
            with archive.open("wb") as destination:
                binary_command(source_compose + ["exec", "-T", "postgres", "pg_dump", "-U", "runtime_test",
                               "--format=custom", "--no-owner", "--no-privileges", "runtime_test"], env, destination=destination)
            with archive.open("rb") as source:
                binary_command(target_compose + ["exec", "-T", "postgres", "pg_restore", "--list"], env, source=source)
            report["database_archive"] = {"bytes": archive.stat().st_size, "sha256": sha256(archive.read_bytes())}
            restore_started = time.monotonic()
            with archive.open("rb") as source:
                binary_command(target_compose + ["exec", "-T", "postgres", "pg_restore", "-U", "runtime_test",
                               "--dbname=runtime_test", "--no-owner", "--no-privileges", "--exit-on-error", "--single-transaction"],
                               env, source=source)
            folder = workspace / "media"
            folder.mkdir()
            manifest = copy_media(source_s3, target_s3, folder)
            report["fixture_restore_seconds"] = round(time.monotonic() - restore_started, 3)
            report["fixture_backup_and_restore_seconds"] = round(time.monotonic() - backup_started, 3)
            restored_snapshot = asyncio.run(database_snapshot(target_pg))
            require(source_snapshot == restored_snapshot, "Restored database rows differ from the backup")
            report["database_tables"] = source_snapshot
            report["checks"].append("Every public table row count and canonical row checksum matches after restore")
            require(manifest == object_inventory(target_s3), "Restored media differs in bytes or metadata")
            report["media"] = {"objects": len(manifest), "bytes": sum(value["size"] for value in manifest.values()),
                               "manifest_sha256": sha256(json.dumps(manifest, sort_keys=True).encode())}
            report["checks"].append("Every media object retains its SHA-256, size, content type and metadata")
            report["checks"].extend(asyncio.run(verify_restored_constraints(target_pg)))
            import httpx
            with httpx.Client(timeout=15, follow_redirects=False) as client:
                for key, metadata in manifest.items():
                    anonymous = client.get(f"{target_endpoint}/{BUCKET}/{key}")
                    require(anonymous.status_code == 403, "Restored media became public")
                    signed = target_s3.generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": key}, ExpiresIn=60)
                    downloaded = client.get(signed)
                    require(downloaded.status_code == 200 and sha256(downloaded.content) == metadata["sha256"],
                            "Signed restored media cannot be downloaded intact")
            report["checks"].append("All restored objects reject anonymous reads and accept intact signed downloads")
            report["status"] = "passed"
    except Exception as exc:
        report["failure"] = str(exc) if isinstance(exc, GateFailure) else type(exc).__name__
    finally:
        failed_cleanup = []
        for project, compose in reversed(projects):
            try:
                run(compose + ["down", "--volumes", "--remove-orphans"], env=env, timeout=90,
                    log=report_dir / f"{project}-cleanup.log")
            except Exception:
                failed_cleanup.append(project)
        report["cleanup"] = "failed" if failed_cleanup else "completed"
        if failed_cleanup:
            report.update(status="failed", cleanup_projects=failed_cleanup)
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        (report_dir / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(f"Restore rehearsal: {report['status']}. Report: {report_dir}", flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
