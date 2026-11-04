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

from run_runtime_e2e import GateFailure, MINIO_TEST_IMAGE, clean_environment, port_for, require, run

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


async def seed_database(port, media, *, voice_media_base=None):
    import asyncpg
    connection = await asyncpg.connect(host="127.0.0.1", port=port, user="runtime_test",
        password=CREDENTIAL, database="runtime_test")
    try:
        # The fixed bearer-shaped fixture exists only inside this disposable run.
        owner = "00000000-0000-4000-8000-000000000001"
        await connection.execute("""INSERT INTO account_identities
            (user_key,device_key_hash,recovery_code_hash,previous_recovery_code_hash,deleted,created_at,updated_at)
            VALUES ($1,$2,$3,$4,false,now(),now())""", owner,
            sha256(('asb:device:v1\0' + 'asb_device_' + 'A' * 43).encode()),
            sha256(('asb:recovery:v1\0' + 'ASB-R1-' + 'C' * 43).encode()),
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
            owner, json.dumps([key for key in media if not key.startswith(('consent-fixture/', 'voice-samples/'))]))
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
        other = '00000000-0000-4000-8000-000000000003'
        await connection.execute("""INSERT INTO account_identities
            (user_key,device_key_hash,recovery_code_hash,deleted,created_at,updated_at)
            VALUES ($1,$2,$3,false,now(),now())""", other,
            sha256(('asb:device:v1\0' + 'asb_device_' + 'B' * 43).encode()),
            sha256(('asb:recovery:v1\0' + 'ASB-R1-' + 'E' * 43).encode()))
        await connection.execute("""INSERT INTO user_consents
            (user_key,consent_version,privacy,photos,data_processing,granted)
            VALUES ($1,'v2',true,true,true,true)""", other)
        await connection.execute("""INSERT INTO child_profiles
            (id,user_key,name,age_band,is_default)
            VALUES ('profile-fixture',$1,'Synthetic','5-7',false)""", other)
        if voice_media_base is not None:
            await connection.execute("""INSERT INTO voice_profiles
                (id,user_key,label,sample_audio_url,consented,active)
                VALUES ('voice-fixture',$1,'Synthetic',$2,true,true)""", other,
                f'{voice_media_base}/voice-samples/{other}/sample.wav')
        await connection.execute("""INSERT INTO characters
            (id,name,master_description,appearance,clothing,personality_traits,from_photo,user_key)
            VALUES ('consent-character','Synthetic','Synthetic','{}','{}','[]',true,$1)""", other)
        await connection.execute("""INSERT INTO jobs
            (id,status,progress,current_step,user_key,photo_derived,image_keys)
            VALUES ('consent-job','done',100,'done',$1,true,$2)""", other,
            json.dumps([key for key in media if key.startswith('consent-fixture/')]))
        await connection.execute("""INSERT INTO books
            (id,job_id,title,language,target_age,style,user_key,character_id)
            VALUES ('consent-book','consent-job','Synthetic','ko','3-5','watercolor',$1,'consent-character')""", other)
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
        require(await connection.fetchval("SELECT previous_recovery_code_hash FROM account_identities WHERE user_key='00000000-0000-4000-8000-000000000001'")
                == sha256(b"synthetic-revoked-recovery"), "Restore lost the previous recovery-code revocation state")
        checks.append("Account tombstones and recovery credential rotation state survive restore")
        return checks
    finally:
        await connection.close()


async def privacy_state(port):
    """Inspect only the fixed synthetic identity in this disposable rehearsal."""
    import asyncpg
    connection = await asyncpg.connect(host="127.0.0.1", port=port, user="runtime_test",
        password=CREDENTIAL, database="runtime_test")
    try:
        row = await connection.fetchrow("""SELECT i.deleted, COALESCE(c.granted, false) AS granted,
            (c.revoked_at IS NOT NULL OR (i.deleted AND c.user_key IS NULL)) AS revoked
            FROM account_identities i LEFT JOIN user_consents c USING (user_key)
            WHERE i.user_key = '00000000-0000-4000-8000-000000000001'""")
        require(row is not None, "Synthetic privacy fixture is missing")
        return dict(row)
    finally:
        await connection.close()


async def finish_fixture_pending_task(port):
    """Mark the already-deleted, fixed synthetic object as completed."""
    import asyncpg
    connection = await asyncpg.connect(host="127.0.0.1", port=port, user="runtime_test",
        password=CREDENTIAL, database="runtime_test")
    try:
        result = await connection.execute("""UPDATE storage_purge_tasks SET status='done', attempts=1
            WHERE user_key='00000000-0000-4000-8000-000000000001'
            AND reason='account_deletion' AND target='["pending-erasure/asset.png"]'
            AND status='pending'""")
        require(result == 'UPDATE 1', 'Synthetic prior purge task was not found')
    finally:
        await connection.close()


async def mark_disposable_restore_target(port, token, storage_endpoint):
    import asyncpg
    connection = await asyncpg.connect(host="127.0.0.1", port=port, user="runtime_test",
        password=CREDENTIAL, database="runtime_test")
    try:
        await connection.execute('CREATE TABLE public.asb_disposable_fixture_guard (token text PRIMARY KEY, s3_endpoint text NOT NULL)')
        await connection.execute('INSERT INTO public.asb_disposable_fixture_guard VALUES ($1,$2)', token, storage_endpoint)
    finally:
        await connection.close()


async def verify_synthetic_account_replayed(port):
    import asyncpg
    connection = await asyncpg.connect(host="127.0.0.1", port=port, user="runtime_test",
        password=CREDENTIAL, database="runtime_test")
    try:
        owner = '00000000-0000-4000-8000-000000000001'
        identity = await connection.fetchrow("""SELECT deleted,device_key_hash,recovery_code_hash,
            previous_recovery_code_hash FROM account_identities WHERE user_key=$1""", owner)
        require(identity is not None and identity['deleted'] and all(
            identity[key] is None for key in ('device_key_hash','recovery_code_hash','previous_recovery_code_hash')),
            'Synthetic identity was not safely revoked')
        for table in ('books', 'jobs', 'user_consents'):
            require(await connection.fetchval(f'SELECT count(*) FROM {table} WHERE user_key=$1', owner) == 0,
                    'Synthetic deleted account data remained')
        require(await connection.fetchval("SELECT count(*) FROM account_identities WHERE user_key='00000000-0000-4000-8000-000000000002' AND deleted=true") == 1,
                'Unrelated synthetic identity changed')
        require(await connection.fetchval("SELECT count(*) FROM storage_purge_tasks WHERE user_key=$1 AND status NOT IN ('done','cancelled')", owner) == 0,
                'Synthetic deletion queue is incomplete')
    finally:
        await connection.close()


async def verify_synthetic_consent_replayed(port):
    import asyncpg
    connection = await asyncpg.connect(host="127.0.0.1", port=port, user="runtime_test",
        password=CREDENTIAL, database="runtime_test")
    try:
        owner = '00000000-0000-4000-8000-000000000003'
        identity = await connection.fetchrow("""SELECT deleted,device_key_hash,recovery_code_hash,
            previous_recovery_code_hash FROM account_identities WHERE user_key=$1""", owner)
        require(identity is not None and not identity['deleted']
                and identity['device_key_hash'] == sha256(('asb:device:v1\0' + 'asb_device_' + 'F' * 43).encode())
                and identity['recovery_code_hash'] == sha256(('asb:recovery:v1\0' + 'ASB-R1-' + 'G' * 43).encode())
                and identity['previous_recovery_code_hash'] == sha256(('asb:recovery:v1\0' + 'ASB-R1-' + 'E' * 43).encode()),
                'Synthetic latest credential verifiers were not preserved')
        require(await connection.fetchval("SELECT count(*) FROM user_consents WHERE user_key=$1 AND revoked_at IS NULL", owner) == 0,
                'Synthetic consent revocation was not preserved')
        require(await connection.fetchval("SELECT count(*) FROM user_consents WHERE user_key=$1 AND granted=false AND revoked_at IS NOT NULL", owner) >= 2,
                'Synthetic consent revoke/regrant/revoke history was not preserved')
        for table in ('characters', 'books', 'jobs'):
            require(await connection.fetchval(f'SELECT count(*) FROM {table} WHERE user_key=$1', owner) == 0,
                    'Synthetic photo-derived data remained')
        require(await connection.fetchval("SELECT count(*) FROM storage_purge_tasks WHERE user_key=$1 AND status NOT IN ('done','cancelled')", owner) == 0,
                'Synthetic photo deletion queue is incomplete')
    finally:
        await connection.close()


async def verify_regranted_consent_preserved(port):
    import asyncpg
    connection = await asyncpg.connect(host="127.0.0.1", port=port, user="runtime_test",
        password=CREDENTIAL, database="runtime_test")
    try:
        owner = '00000000-0000-4000-8000-000000000003'
        require(await connection.fetchval("SELECT count(*) FROM user_consents WHERE user_key=$1 AND granted=true AND photos=true AND revoked_at IS NULL", owner) == 1,
                'Previously regranted synthetic consent was incorrectly changed')
        require(await connection.fetchval("SELECT count(*) FROM characters WHERE user_key=$1", owner) == 1,
                'Previously regranted synthetic photo character was incorrectly deleted')
        require(await connection.fetchval("SELECT count(*) FROM books WHERE user_key=$1", owner) == 1,
                'Previously regranted synthetic book was incorrectly deleted')
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
                         "Redis queue recovery is not part of a PostgreSQL/S3 restore",
                         "Account, consent and credential replay use synthetic data; independent journal completeness and release authorization remain unproved"]}
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
                            for name in ("postgres:15-alpine", MINIO_TEST_IMAGE)}
        report["docker_version"] = run(["docker", "info", "--format", "{{.ServerVersion}}"], env=env).strip()
        with tempfile.TemporaryDirectory(prefix="storybook-restore-private-") as temporary:
            workspace = Path(temporary)
            fixture_journal_dir = workspace / 'journal'
            fixture_journal_key = os.urandom(32).hex()
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
            source_compose, source_pg, source_endpoint, source_s3 = dependencies[0]
            target_compose, target_pg, target_endpoint, target_s3 = dependencies[1]
            runtime_env = dict(env, DATABASE_URL=f"postgresql+asyncpg://runtime_test:{CREDENTIAL}@127.0.0.1:{source_pg}/runtime_test",
                               TESTING="true", LLM_PROVIDER="mock", IMAGE_PROVIDER="mock",
                               AUDIO_FEATURE_ENABLED="false", POD_ORDERING_ENABLED="false", PURCHASES_ENABLED="false")
            run([sys.executable, "-m", "alembic", "upgrade", "head"], env=runtime_env, cwd=api,
                log=report_dir / "migrations.log")
            report["checks"].append("Source schema migrates to current Alembic head")
            privacy_fixture_env = dict(runtime_env, PYTHONPATH=str(api), S3_ENDPOINT=source_endpoint,
                S3_BUCKET=BUCKET, S3_ACCESS_KEY='runtime_test', S3_SECRET_KEY=CREDENTIAL,
                ASB_FIXTURE_JOURNAL_DIR=str(fixture_journal_dir), ASB_FIXTURE_JOURNAL_KEY=fixture_journal_key)
            run([sys.executable, str(ROOT / 'scripts/run_privacy_outbox_fixture.py')], env=privacy_fixture_env,
                cwd=api, log=report_dir / 'synthetic-outbox-concurrency.log')
            report['checks'].append('Synthetic PostgreSQL concurrent privacy revisions serialize; fenced recovery rejects committed events and resolves a rolled-back intent')
            report['checks'].append('Overlapping retry batches leave a failing privacy event pending while publishing later selected events and preserving revisions')
            report['checks'].append('A persistent retry cursor rotates past a fully failing batch and revisits a claimed batch after simulated process loss')
            report['checks'].append('PostgreSQL serializes concurrent retry claims and downgrade refuses pending privacy events')
            report['checks'].append('Synthetic PostgreSQL backup checkpoint matches outbox and journal; a modified fingerprint is rejected')
            report['checks'].append('A source fence blocks cooperating PostgreSQL privacy writers throughout the protected section')
            report['checks'].append('A fenced synthetic source can backfill a separate immutable witness without authorizing restore')
            run([sys.executable, str(ROOT / 'scripts/run_backup_fence_fixture.py')], env=privacy_fixture_env,
                cwd=api, log=report_dir / 'synthetic-backup-fence.log')
            report['checks'].append('Synthetic HTTP reads stay available and deletes are denied during a PostgreSQL fence; direct DB writes block while independent S3 mutation remains possible')
            run([sys.executable, str(ROOT / 'scripts/run_storage_write_fence_fixture.py')], env=privacy_fixture_env,
                cwd=api, log=report_dir / 'synthetic-storage-write-fence.log')
            report['checks'].append('Synthetic cooperative S3 lock blocks mutations; session loss permits late S3 but precommitted in-flight intent blocks backup and duplicate retry; production use is not authorized')
            pixel = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+afo4AAAAASUVORK5CYII=")
            media = {"books/cover.png": (pixel, "image/png"), "books/page-1.png": (pixel, "image/png"),
                     "books/page-2.png": (pixel, "image/png"), "books/book.pdf": (b"%PDF-1.4\n%synthetic restore fixture\n%%EOF\n", "application/pdf"),
                     "pending-erasure/asset.png": (pixel, "image/png"),
                     "consent-fixture/photo.png": (pixel, "image/png"),
                     "consent-fixture/illustration.png": (pixel, "image/png")}
            for client in (source_s3, target_s3):
                client.create_bucket(Bucket=BUCKET)
            mirror_env = dict(privacy_fixture_env, ASB_SECOND_FIXTURE_S3=target_endpoint)
            run([sys.executable, str(ROOT / 'scripts/run_mirror_storage_fixture.py')], env=mirror_env,
                cwd=api, log=report_dir / 'synthetic-journal-mirror.log')
            report['checks'].append('Two disposable S3 stores verify backfill, partial intent and commit repair, reject conflicts and detect a missing witness copy')
            run([sys.executable, str(ROOT / 'scripts/run_privacy_readback_fixture.py')], env=privacy_fixture_env,
                cwd=api, log=report_dir / 'synthetic-privacy-readback.log')
            report['checks'].append('PostgreSQL privacy mutation blocks on unreadable MinIO intent; commit readback failure stays pending until retry')
            run([sys.executable, str(ROOT / 'scripts/run_privacy_source_loss_fixture.py')], env=privacy_fixture_env,
                cwd=api, log=report_dir / 'synthetic-source-loss.log')
            report['checks'].append('Synthetic source DB loss after deletion with missing journal commit is blocked; loss of its intent leaves historical witness latestness unproven')
            run([sys.executable, str(ROOT / 'scripts/run_privacy_single_store_loss_fixture.py')], env=mirror_env,
                cwd=api, log=report_dir / 'synthetic-single-replica-loss.log')
            report['checks'].append('After synthetic acknowledged deletion a single mirror loss leaves a surviving pending intent and blocks replay')
            run([sys.executable, str(ROOT / 'scripts/run_mirrored_privacy_routes_fixture.py')], env=mirror_env,
                cwd=api, log=report_dir / 'synthetic-mirrored-privacy-routes.log')
            report['checks'].append('Synthetic privacy routes write matching journal records to two S3 stores and block on a witness outage')
            report['checks'].append('A GCS stand-in and S3 witness are checked before and after backup; a missing replica blocks publication and restores services')
            for key, (data, content_type) in media.items():
                source_s3.put_object(Bucket=BUCKET, Key=key, Body=data, ContentType=content_type,
                                     Metadata={"fixture": "synthetic-restore"})
            asyncio.run(seed_database(source_pg, media))
            privacy_fixture_env['ASB_REPLAY_SCENARIO'] = 'historical'
            run([sys.executable, str(ROOT / 'scripts/run_source_privacy_fixture.py')], env=privacy_fixture_env,
                cwd=api, log=report_dir / 'synthetic-prebackup-consent.log')
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
            # A perfect copy of an old backup can still resurrect later-deleted
            # data. Demonstrate this explicitly without opening either stack.
            privacy_fixture_env['ASB_REPLAY_SCENARIO'] = 'account'
            run([sys.executable, str(ROOT / 'scripts/run_source_privacy_fixture.py')], env=privacy_fixture_env,
                cwd=api, log=report_dir / 'synthetic-source-account-event.log')
            report['checks'].append('Synthetic source privacy mutation and DB outbox commit together; a separate local encrypted journal is read by the restore process')
            source_privacy = asyncio.run(privacy_state(source_pg))
            restored_privacy = asyncio.run(privacy_state(target_pg))
            require(source_privacy == {"deleted": True, "granted": False, "revoked": True},
                    "Synthetic later deletion and consent change was not recorded")
            require(restored_privacy == {"deleted": False, "granted": True, "revoked": False},
                    "Old restored snapshot did not preserve the expected stale state")
            source_s3.delete_object(Bucket=BUCKET, Key="books/cover.png")
            require("books/cover.png" not in object_inventory(source_s3)
                    and "books/cover.png" in object_inventory(target_s3),
                    "Synthetic deletion divergence was not detected")
            report["checks"].append("A later synthetic deletion and consent withdrawal leaves stale restored DB and media; replay remains required")
            report["privacy_restore_gate"] = "NO_GO_REVOCATION_REPLAY_NOT_IMPLEMENTED"
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
            # Complete the pre-existing fixture task without conflating it with
            # the new account replay, then run replay only against this local
            # disposable target. A real restore still needs authoritative,
            # complete independent records and externally enforced quarantine.
            old_signed = target_s3.generate_presigned_url('get_object',
                Params={'Bucket': BUCKET, 'Key': 'books/cover.png'}, ExpiresIn=60)
            target_s3.delete_object(Bucket=BUCKET, Key='pending-erasure/asset.png')
            asyncio.run(finish_fixture_pending_task(target_pg))
            fixture_token = uuid.uuid4().hex
            asyncio.run(mark_disposable_restore_target(target_pg, fixture_token, target_endpoint))
            replay_env = dict(runtime_env,
                DATABASE_URL=f'postgresql+asyncpg://runtime_test:{CREDENTIAL}@127.0.0.1:{target_pg}/runtime_test',
                PYTHONPATH=str(api), S3_ENDPOINT=target_endpoint, S3_PUBLIC_URL=f'{target_endpoint}/{BUCKET}',
                S3_BUCKET=BUCKET, S3_ACCESS_KEY='runtime_test', S3_SECRET_KEY=CREDENTIAL, S3_REGION='us-east-1',
                ASB_DISPOSABLE_REPLAY_TOKEN=fixture_token, ASB_FIXTURE_JOURNAL_DIR=str(fixture_journal_dir),
                ASB_FIXTURE_JOURNAL_KEY=fixture_journal_key)
            for index in (1, 2):
                replay_env['ASB_REPLAY_RUN'] = str(index)
                run([sys.executable, str(ROOT / 'scripts/run_restore_replay_fixture.py')], env=replay_env,
                    cwd=api, log=report_dir / f'synthetic-replay-{index}.log')
            asyncio.run(verify_synthetic_account_replayed(target_pg))
            asyncio.run(verify_regranted_consent_preserved(target_pg))
            require(set(object_inventory(target_s3)) == {'consent-fixture/photo.png', 'consent-fixture/illustration.png'},
                    'Account replay removed unrelated media or left deleted-account media')
            with httpx.Client(timeout=15, follow_redirects=False) as client:
                require(client.get(old_signed).status_code in (403, 404),
                        'Old synthetic signed media URL still works after replay')
            report['checks'].append('A synthetic deleted account and its restored media are removed by replay; an old signed URL is denied and a repeat is safe')
            report['checks'].append('A historical withdrawal already included in the backup does not erase later regranted consent or its synthetic media')
            consent_signed = target_s3.generate_presigned_url('get_object',
                Params={'Bucket': BUCKET, 'Key': 'consent-fixture/photo.png'}, ExpiresIn=60)
            privacy_fixture_env['ASB_REPLAY_SCENARIO'] = 'consent'
            run([sys.executable, str(ROOT / 'scripts/run_source_privacy_fixture.py')], env=privacy_fixture_env,
                cwd=api, log=report_dir / 'synthetic-source-consent-events.log')
            source_s3.delete_object(Bucket=BUCKET, Key='consent-fixture/photo.png')
            source_s3.delete_object(Bucket=BUCKET, Key='consent-fixture/illustration.png')
            replay_env['ASB_REPLAY_SCENARIO'] = 'consent'
            for index in (1, 2):
                replay_env['ASB_REPLAY_RUN'] = str(index)
                run([sys.executable, str(ROOT / 'scripts/run_restore_replay_fixture.py')], env=replay_env,
                    cwd=api, log=report_dir / f'synthetic-consent-replay-{index}.log')
            asyncio.run(verify_synthetic_consent_replayed(target_pg))
            require(not object_inventory(target_s3), 'Synthetic photo-derived media remained after consent replay')
            with httpx.Client(timeout=15, follow_redirects=False) as client:
                require(client.get(consent_signed).status_code in (403, 404),
                        'Old synthetic photo URL still works after consent replay')
            report['checks'].append('Synthetic consent withdrawal and credential rotation are replayed; old credentials and photo URLs fail, latest device credential works, and a repeat is safe')
            run([sys.executable, str(ROOT / 'scripts/run_restore_recovery_fixture.py')], env=replay_env,
                cwd=api, log=report_dir / 'synthetic-recovery-after-replay.log')
            report['checks'].append('Synthetic latest recovery code works once after replay and its consumed predecessor is rejected')
            report['privacy_restore_gate'] = 'NO_GO_JOURNAL_COVERAGE_AND_ISOLATION_NOT_ESTABLISHED'
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
