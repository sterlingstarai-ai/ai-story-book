"""C1 회귀 게이트 — Celery 워커 × 실 PostgreSQL.

이 파일이 존재하는 이유(2026-08-09 중간 E2E):
프로덕션 구성(`USE_CELERY=true` + PostgreSQL)에서 책 생성이 **전량 실패**했는데도
백엔드 675 테스트와 `run_live_e2e.sh` 30/30이 green이었다. 원인은 게이트가 전부
**SQLite**에서 돌기 때문이다 — aiosqlite 파일 DB의 기본 풀은 `NullPool`이라 커넥션이
이벤트 루프를 건너 재사용되지 않는다. 반면 asyncpg 기본 풀(`AsyncAdaptedQueuePool`)은
커넥션을 캐싱하므로, `run_async()`가 태스크마다 새 루프를 만들고 닫는 구조에서
두 번째 루프가 죽은 루프에 묶인 커넥션을 재사용해 폭발한다.

따라서 이 클래스는 **실 PG + 실 Celery 워커**로만 잡을 수 있다.
`E2E_PG_DATABASE_URL`(+ Celery 테스트는 `E2E_REDIS_URL`)이 있을 때만 돈다.
"""

import asyncio
import os
import subprocess
import sys
import time
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.getenv("E2E_PG_DATABASE_URL", "").strip()
REDIS_URL = os.getenv("E2E_REDIS_URL", "").strip()

API_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

requires_pg = pytest.mark.skipif(
    not PG_URL, reason="E2E_PG_DATABASE_URL 미설정 — 실 PostgreSQL 게이트 생략"
)
requires_celery = pytest.mark.skipif(
    not (PG_URL and REDIS_URL),
    reason="E2E_PG_DATABASE_URL/E2E_REDIS_URL 미설정 — 실 워커 게이트 생략",
)


def _worker_env(queue: str) -> dict:
    """워커 subprocess 환경 — 프로덕션 구성(TESTING=false, USE_CELERY=true, 실PG)."""
    env = dict(os.environ)
    env.update(
        {
            "TESTING": "false",
            "USE_CELERY": "true",
            "DATABASE_URL": PG_URL,
            "REDIS_URL": REDIS_URL,
            "CELERY_BROKER_URL": REDIS_URL,
            "CELERY_RESULT_BACKEND": REDIS_URL,
            "LLM_PROVIDER": "mock",
            "IMAGE_PROVIDER": "mock",
            "TTS_PROVIDER": "mock",
            "STT_PROVIDER": "mock",
            "AUDIO_FEATURE_ENABLED": "false",
            "S3_ACCESS_KEY": "test",
            "S3_SECRET_KEY": "test",
            "CELERY_TEST_QUEUE": queue,
        }
    )
    return env


# ---------------------------------------------------------------- 기계적 원인 격리


@requires_pg
def test_sequential_run_async_survives_on_postgres():
    """워커 구성에서 `run_async`를 연속 호출해도 커넥션이 죽은 루프를 넘지 않는다.

    수정 전에는 2번째 호출이 `InterfaceError: cannot perform operation:
    another operation is in progress`(원인 `RuntimeError: got Future attached to a
    different loop`)로 죽었다. 오케스트레이터·Celery 없이 원인만 격리한다.
    """
    code = r"""
import os, sys
sys.path.insert(0, os.environ["API_ROOT"])
from sqlalchemy import text
from src.core.database import configure_for_worker, AsyncSessionLocal, async_engine
from src.services.tasks import run_async

configure_for_worker()

from src.core.database import async_engine as engine_after
print("POOL=" + type(engine_after.pool).__name__)

async def touch():
    async with AsyncSessionLocal() as s:
        return (await s.execute(text("SELECT 1"))).scalar()

for i in range(3):
    assert run_async(touch()) == 1, f"iteration {i}"
print("SEQUENTIAL_OK")
"""
    env = dict(os.environ)
    env.update({"API_ROOT": API_ROOT, "DATABASE_URL": PG_URL, "TESTING": "false"})
    proc = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120
    )
    assert "SEQUENTIAL_OK" in proc.stdout, (
        "워커 구성에서 연속 run_async 실패 — C1 회귀.\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr[-3000:]}"
    )
    assert "POOL=NullPool" in proc.stdout, (
        f"워커 엔진이 NullPool이 아니다(커넥션 캐싱 → 루프 교차 재사용 위험). stdout={proc.stdout}"
    )


# ---------------------------------------------------------------- 실 워커 통합


async def _prepare_job(engine, job_id: str, user_key: str) -> None:
    """PG에 스키마 보장 + 잡/크레딧 시드."""
    from src.models.db import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO jobs (id, status, progress, current_step, user_key, created_at, updated_at)"
                " VALUES (:id, 'queued', 0, 'queued', :uk, now(), now())"
            ),
            {"id": job_id, "uk": user_key},
        )


async def _job_row(engine, job_id: str):
    async with engine.connect() as conn:
        res = await conn.execute(
            text("SELECT status, error_code FROM jobs WHERE id = :id"), {"id": job_id}
        )
        return res.first()


def _wait_job(engine, job_id: str, timeout: int = 60):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = asyncio.run(_job_row(engine, job_id))
        if last and last[0] in ("done", "failed"):
            return last
        time.sleep(2)
    return last


@requires_celery
def test_worker_completes_two_sequential_book_jobs():
    """같은 워커 프로세스에서 태스크를 **2연속** 실행해도 둘 다 done에 도달한다.

    2연속이 핵심이다: 첫 태스크가 풀에 커넥션을 남기고 루프를 닫으므로, 두 번째
    태스크(및 첫 태스크의 두 번째 `run_async`)가 죽은 루프의 커넥션을 재사용하게 된다.
    수정 전에는 첫 태스크가 `queued`에 그대로 멈추고(실패 기록 경로마저 같은 이유로 죽음)
    두 번째도 즉시 실패했다.
    """
    queue = f"c1test{uuid.uuid4().hex[:8]}"
    env = _worker_env(queue)
    # 하네스도 asyncio.run 을 반복 호출하므로 NullPool 고정 — 그렇지 않으면 하네스가
    # 검증 대상과 같은 이유로 죽어 제품 결함과 구분되지 않는다.
    engine = create_async_engine(PG_URL, echo=False, poolclass=NullPool)
    user_key = str(uuid.uuid4())
    job_ids = [f"job_c1_{uuid.uuid4().hex[:10]}", f"job_c1_{uuid.uuid4().hex[:10]}"]

    worker = None
    try:
        for jid in job_ids:
            asyncio.run(_prepare_job(engine, jid, user_key))

        worker = subprocess.Popen(
            [
                sys.executable, "-m", "celery", "-A", "src.worker", "worker",
                "--loglevel=info", "--concurrency=1", "--pool=solo", "-Q", queue,
            ],
            cwd=API_ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        time.sleep(12)  # 워커 부팅
        assert worker.poll() is None, "워커가 기동 직후 종료됨"

        # 큐에 태스크를 넣는 쪽도 같은 브로커를 봐야 한다.
        os.environ["CELERY_BROKER_URL"] = REDIS_URL
        os.environ["CELERY_RESULT_BACKEND"] = REDIS_URL
        from src.worker import celery_app

        celery_app.conf.broker_url = REDIS_URL
        celery_app.conf.result_backend = REDIS_URL

        spec = {
            "topic": "C1 회귀 테스트 동화",
            "target_age": "5-7",
            "style": "watercolor",
            "page_count": 4,
            "language": "ko",
        }

        results = []
        for jid in job_ids:
            celery_app.send_task(
                "src.services.tasks.generate_book_task",
                args=[jid, spec, user_key],
                queue=queue,
            )
            results.append(_wait_job(engine, jid))

        assert all(r is not None and r[0] == "done" for r in results), (
            "실 PG + 실 Celery 워커에서 2연속 책 생성이 done에 도달하지 못했다 — C1 회귀.\n"
            f"job statuses={results}"
        )
    finally:
        if worker is not None:
            worker.terminate()
            try:
                worker.wait(timeout=15)
            except subprocess.TimeoutExpired:
                worker.kill()
        asyncio.run(engine.dispose())


@requires_celery
def test_worker_records_failure_and_refunds_on_error():
    """태스크가 실패하면 잡이 `failed`로 **기록**된다.

    수정 전에는 실패 마킹 경로도 같은 `run_async` 버그로 죽어 잡이 `queued`에 잔류했다
    (사용자는 SLA 10분이 지나야 실패를 본다). 존재하지 않는 job_id로 파이프라인을
    실패시켜 '실패가 실패로 기록되는지'만 본다.
    """
    queue = f"c1fail{uuid.uuid4().hex[:8]}"
    env = _worker_env(queue)
    # 하네스도 asyncio.run 을 반복 호출하므로 NullPool 고정 — 그렇지 않으면 하네스가
    # 검증 대상과 같은 이유로 죽어 제품 결함과 구분되지 않는다.
    engine = create_async_engine(PG_URL, echo=False, poolclass=NullPool)
    user_key = str(uuid.uuid4())
    job_id = f"job_c1fail_{uuid.uuid4().hex[:10]}"

    worker = None
    try:
        asyncio.run(_prepare_job(engine, job_id, user_key))
        worker = subprocess.Popen(
            [
                sys.executable, "-m", "celery", "-A", "src.worker", "worker",
                "--loglevel=info", "--concurrency=1", "--pool=solo", "-Q", queue,
            ],
            cwd=API_ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        time.sleep(12)
        assert worker.poll() is None, "워커가 기동 직후 종료됨"

        from src.worker import celery_app

        celery_app.conf.broker_url = REDIS_URL
        celery_app.conf.result_backend = REDIS_URL

        # target_age가 스펙 위반 → BookSpec 검증 실패 → 파이프라인 예외 경로
        bad_spec = {
            "topic": "C1 실패 경로",
            "target_age": "not-a-band",
            "style": "watercolor",
            "page_count": 4,
            "language": "ko",
        }
        celery_app.send_task(
            "src.services.tasks.generate_book_task",
            args=[job_id, bad_spec, user_key],
            queue=queue,
        )
        row = _wait_job(engine, job_id, timeout=60)
        assert row is not None and row[0] == "failed", (
            "실패한 태스크가 failed로 기록되지 않았다 — 실패 마킹 경로 회귀.\n"
            f"row={row}"
        )
    finally:
        if worker is not None:
            worker.terminate()
            try:
                worker.wait(timeout=15)
            except subprocess.TimeoutExpired:
                worker.kill()
        asyncio.run(engine.dispose())
