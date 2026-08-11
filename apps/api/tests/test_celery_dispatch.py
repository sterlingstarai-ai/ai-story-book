"""R1: 장기 실행 잡 3종이 USE_CELERY를 실제로 존중하는지 — 라우터 디스패치 회귀.

배경: 책 생성(books.py:557)·시리즈(:1114)만 `.delay()`로 큐에 보내고, 페이지 재생성·
인페인트·오디오는 USE_CELERY 분기 **없이** 무조건 FastAPI BackgroundTasks로 돌았다.
`USE_CELERY=true`인 프로덕션에서도 API 프로세스가 최대 90초×재시도의 이미지 작업을
직접 수행했고(재시작 시 유실·API 지연), tasks.py의 regenerate_page_task는 시그니처가
어긋난 채 아무도 호출하지 않는 죽은 코드였다.

이 테스트가 지키는 불변식:
  USE_CELERY=true  → 해당 Celery 태스크의 .delay()가 호출되고 BackgroundTasks에는
                     러너가 등록되지 않는다.
  USE_CELERY=false → 정확히 반대.

red-proof: books.py의 `_dispatch_long_running_job`에서 `if not settings.use_celery`
분기를 지우고 항상 `background_tasks.add_task(...)`로 되돌리면 celery=true 3케이스가
모두 FAIL한다(과거 상태 그대로 재현).
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.models.db import Book, Job, Page


async def _seed_book(db_session: AsyncSession, user_key: str) -> None:
    job = Job(id="job-dispatch", status="done", user_key=user_key)
    db_session.add(job)
    await db_session.flush()
    db_session.add(
        Book(
            id="book-dispatch",
            job_id=job.id,
            title="원본",
            language="ko",
            target_age="5-7",
            style="watercolor",
            user_key=user_key,
            cover_image_url="http://localhost:9000/storybook/images/mock/cover.png",
        )
    )
    db_session.add(
        Page(
            book_id="book-dispatch",
            page_number=1,
            text="원본 1",
            image_url="http://localhost:9000/storybook/images/mock/p1.png",
            image_prompt="a cozy forest",
        )
    )
    await db_session.commit()


class _Dispatch:
    """BackgroundTasks.add_task 와 Celery .delay 를 동시에 관측하는 스파이.

    add_task 를 **대체**하므로 등록된 러너가 실제로 실행되지도 않는다(테스트가 진짜
    재생성 파이프라인을 돌리지 않게 하는 부수 효과).
    """

    def __init__(self):
        self.background = []
        self.delayed = []

    def install(self, monkeypatch, task_name: str):
        spy = self

        def _record_add_task(self, func, *args, **kwargs):  # noqa: ANN001
            spy.background.append(func)

        monkeypatch.setattr(BackgroundTasks, "add_task", _record_add_task)

        from src.services import tasks as celery_tasks

        task = getattr(celery_tasks, task_name)
        monkeypatch.setattr(
            task, "delay", lambda *a, **k: spy.delayed.append((a, k))
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("use_celery", [True, False])
async def test_regenerate_dispatch_respects_use_celery(
    client: AsyncClient,
    db_session: AsyncSession,
    headers: dict,
    monkeypatch,
    use_celery: bool,
):
    await _seed_book(db_session, headers["X-User-Key"])
    monkeypatch.setattr(settings, "use_celery", use_celery)
    spy = _Dispatch()
    spy.install(monkeypatch, "regenerate_page_task")

    res = await client.post(
        "/v1/books/job-dispatch/pages/1/regenerate",
        json={"mode": "image"},
        headers=headers,
    )
    assert res.status_code == 200, res.text

    from src.services.job_runners import run_regeneration_job

    if use_celery:
        assert len(spy.delayed) == 1, "USE_CELERY=true인데 큐로 보내지 않았다"
        assert run_regeneration_job not in spy.background, (
            "큐로 보내놓고 API 프로세스에서도 실행하면 이중 실행이다"
        )
    else:
        assert spy.delayed == [], "USE_CELERY=false인데 큐로 보냈다"
        assert run_regeneration_job in spy.background


@pytest.mark.asyncio
@pytest.mark.parametrize("use_celery", [True, False])
async def test_inpaint_dispatch_respects_use_celery(
    client: AsyncClient,
    db_session: AsyncSession,
    headers: dict,
    monkeypatch,
    use_celery: bool,
):
    await _seed_book(db_session, headers["X-User-Key"])
    # 인페인트는 replicate/fal 에서만 허용(mock 은 409) — 능력 게이트를 통과시킨다.
    monkeypatch.setattr(settings, "image_provider", "fal")
    monkeypatch.setattr(settings, "use_celery", use_celery)
    spy = _Dispatch()
    spy.install(monkeypatch, "inpaint_page_task")

    with patch(
        "src.services.storage.storage_service.upload_bytes",
        new=AsyncMock(return_value="http://localhost:9000/storybook/masks/m.png"),
    ):
        res = await client.post(
            "/v1/books/job-dispatch/pages/1/inpaint",
            files={"mask": ("mask.png", b"\x89PNG\r\n", "image/png")},
            data={"region_prompt": "make the sky orange"},
            headers=headers,
        )
    assert res.status_code == 200, res.text

    from src.services.job_runners import run_inpaint_job

    if use_celery:
        assert len(spy.delayed) == 1, "USE_CELERY=true인데 큐로 보내지 않았다"
        assert run_inpaint_job not in spy.background
    else:
        assert spy.delayed == [], "USE_CELERY=false인데 큐로 보냈다"
        assert run_inpaint_job in spy.background


@pytest.mark.asyncio
@pytest.mark.parametrize("use_celery", [True, False])
async def test_audio_dispatch_respects_use_celery(
    client: AsyncClient,
    db_session: AsyncSession,
    headers: dict,
    monkeypatch,
    use_celery: bool,
):
    await _seed_book(db_session, headers["X-User-Key"])
    # G9: 오디오는 기본 비활성(409) — 디스패치 지점까지 가려면 기능을 켠다.
    monkeypatch.setattr(settings, "audio_feature_enabled", True)
    monkeypatch.setattr(settings, "use_celery", use_celery)
    spy = _Dispatch()
    spy.install(monkeypatch, "generate_audio_task")

    res = await client.post("/v1/books/book-dispatch/audio", headers=headers)
    assert res.status_code == 200, res.text

    from src.services.job_runners import run_audio_job

    if use_celery:
        assert len(spy.delayed) == 1, "USE_CELERY=true인데 큐로 보내지 않았다"
        assert run_audio_job not in spy.background
    else:
        assert spy.delayed == [], "USE_CELERY=false인데 큐로 보냈다"
        assert run_audio_job in spy.background


@pytest.mark.asyncio
async def test_enqueue_failure_marks_job_failed_instead_of_leaving_it_queued(
    client: AsyncClient,
    db_session: AsyncSession,
    headers: dict,
    monkeypatch,
):
    """브로커 장애로 enqueue가 실패하면 잡을 queued로 방치하지 않는다(fail-closed).

    방치하면 사용자는 job_monitor가 회수하는 15~30분 뒤에야 실패를 본다.
    """
    await _seed_book(db_session, headers["X-User-Key"])
    monkeypatch.setattr(settings, "use_celery", True)

    def _boom(*_a, **_k):
        raise RuntimeError("broker down")

    from src.services import tasks as celery_tasks

    monkeypatch.setattr(celery_tasks.regenerate_page_task, "delay", _boom)

    res = await client.post(
        "/v1/books/job-dispatch/pages/1/regenerate",
        json={"mode": "image"},
        headers=headers,
    )
    assert res.status_code == 500
    assert res.json()["error"]["code"] == "INTERNAL_ERROR"

    # 잡 행이 failed(QUEUE_FAILED)로 전이됐는지 — queued 잔류가 회귀다.
    from sqlalchemy import select

    from src.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        regen_jobs = (
            await session.execute(select(Job).where(Job.id.startswith("regen_")))
        ).scalars().all()
    assert regen_jobs, "재생성 잡 행이 생성되지 않았다"
    assert all(j.status == "failed" for j in regen_jobs)
    assert all(j.error_code == "QUEUE_FAILED" for j in regen_jobs)
