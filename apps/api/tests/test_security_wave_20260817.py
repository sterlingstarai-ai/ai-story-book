"""2026-08-17 보안 감사 반송분 회귀 게이트 (R1 잔여 · R3 · R4).

R1의 FK/파기 클래스는 `test_pg_fk_erasure.py`(실 PostgreSQL)에 있다 — SQLite로는 구조적으로
못 잡기 때문이다. 이 파일은 SQLite로도 결정적으로 잡히는 나머지를 봉인한다.
"""

import inspect

import pytest

from src.core.config import settings

H = {"X-User-Key": "550e8400-e29b-41d4-a716-446655440000"}


# ════════════════ R3-2: 실비용 엔드포인트 전수 계량 (구조 불변식) ════════════════


def test_every_paid_generation_endpoint_consumes_budget():
    """H5/R3-2: 실비용(LLM/이미지) 엔드포인트 **전부**가 전역 예산을 소비한다.

    이 테스트는 '한 곳만 고치고 나머지가 새는' 반복 결함을 구조로 막는다. 예전에는
    `create_book` 한 곳만 예산을 소비해서, retell·비전 캐릭터·재생성·인페인트·오늘의 동화가
    모두 예산을 우회하는 무계량 청구 채널이었다(예산을 켜도 소용없음).

    red-proof: 아래 목록 중 아무 엔드포인트에서든 `consume_generation_budget(...)` 호출을
    지우면 즉시 FAIL한다.
    """
    from src.routers import books as books_module
    from src.routers import characters as characters_module
    from src.routers import streak as streak_module

    paid_endpoints = [
        (books_module.create_book, "books.create"),
        (books_module.create_series_next, "books.series"),
        (books_module.regenerate_book_page, "books.regenerate"),
        (books_module.inpaint_book_page, "books.inpaint"),
        (books_module.retell_book, "books.retell"),
        (characters_module.create_character_from_photo, "characters.from_photo"),
        (characters_module.create_character_from_drawing, "characters.from_drawing"),
        (streak_module.generate_today_story, "streak.today_generate"),
    ]

    missing = []
    for func, label in paid_endpoints:
        src = inspect.getsource(func)
        if "consume_generation_budget(" not in src:
            missing.append(label)
    assert not missing, f"전역 예산을 소비하지 않는 유료 경로: {missing}"


def test_budget_is_consumed_after_validation_not_before():
    """M10/R3-3: 예산 소비는 선검증(멱등·소유권·동의) **뒤**에 있다.

    검증 전에 소비하면 비용 0인 무효 요청 스팸만으로 전역 카운터가 소진되어, 가드레일이
    전 사용자 대상 DoS 벡터로 역전된다.

    red-proof: `consume_generation_budget` 호출을 `create_book` 함수 첫 줄로 옮기면 FAIL.
    """
    from src.routers import books as books_module

    src = inspect.getsource(books_module.create_book)
    consume_at = src.index("consume_generation_budget(")
    # 이 검증들은 반드시 예산 소비보다 앞에 있어야 한다.
    for marker in (
        "check_guardrails(",              # 일일 한도
        "idempotency_key",                # 멱등 재시도
        "_enforce_free_plan_create_limits(",  # 무료플랜 한도
        # H7 이후 소유권·동의는 공용 헬퍼로 추출됐다(streak과 공유).
        "enforce_book_spec_access(",
    ):
        assert src.index(marker) < consume_at, (
            f"예산 소비가 '{marker}' 검증보다 앞에 있다(consume-before-validate)"
        )


def test_check_guardrails_does_not_consume_budget():
    """M10/R3-3: 선검증 헬퍼 자체는 예산을 건드리지 않는다(비용 0 경로에서 소진 금지)."""
    from src.routers import books as books_module

    # 주석·독스트링은 제외하고 **실행되는 코드**만 본다(설명 문구가 오탐을 만든다).
    code_lines = [
        line
        for line in inspect.getsource(books_module.check_guardrails).splitlines()
        if not line.strip().startswith("#")
    ]
    body = "\n".join(code_lines).split('"""')[-1]
    assert "consume_daily_generation_budget(" not in body
    assert "consume_generation_budget(" not in body


@pytest.mark.asyncio
async def test_budget_exhausted_returns_upper_snake_envelope(client, monkeypatch):
    """예산 소진 시 429 + UPPER_SNAKE 봉투 코드(M2 규약 유지)."""
    from src.routers import books as books_module

    async def exhausted():
        return False, 999

    monkeypatch.setattr(
        books_module, "consume_daily_generation_budget", exhausted
    )
    r = await client.post(
        "/v1/books",
        headers=H,
        json={
            "topic": "예산 소진 확인",
            "language": "ko",
            "target_age": "5-7",
            "style": "watercolor",
            "page_count": 8,
        },
    )
    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == "SERVICE_BUDGET_EXCEEDED"


# ════════════════ R3-4: per-user / 전역 큐 상한 분리 ════════════════


@pytest.mark.asyncio
async def test_per_user_pending_limit_does_not_block_other_users(
    client, db_session, monkeypatch
):
    """M11/R3-4: 한 사용자가 큐를 채워도 **다른 사용자**는 계속 생성할 수 있다.

    수정 전에는 전역 합산 카운터 하나뿐이라, 공격자가 max_pending_jobs 만큼 채우면 전
    사용자가 503을 맞았다(공유자원 고갈).

    red-proof: per-user 분기를 지우고 전역 카운터만 남기면, 아래에서 victim 이 503을 받아 FAIL.
    """
    from src.models.db import Job

    # 전역 상한은 넉넉히 — 이 테스트의 관심사는 'per-user 상한이 타인을 막지 않는가'다.
    # (전역을 낮게 잡으면 옛 결함과 새 동작이 구분되지 않는다.)
    monkeypatch.setattr(settings, "max_pending_jobs_per_user", 3)
    monkeypatch.setattr(settings, "max_pending_jobs", 100)

    attacker = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
    for i in range(4):
        db_session.add(
            Job(id=f"job_attacker_{i}", status="queued", user_key=attacker)
        )
    await db_session.commit()

    # 공격자는 per-user 상한에서 429로 막힌다.
    body = {
        "topic": "테스트",
        "language": "ko",
        "target_age": "5-7",
        "style": "watercolor",
        "page_count": 8,
    }
    r_attacker = await client.post(
        "/v1/books", headers={"X-User-Key": attacker}, json=body
    )
    assert r_attacker.status_code == 429, r_attacker.text
    assert r_attacker.json()["error"]["code"] == "TOO_MANY_PENDING_JOBS"

    # 다른 사용자는 영향 없이 생성 가능해야 한다.
    victim = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
    r_victim = await client.post(
        "/v1/books", headers={"X-User-Key": victim}, json=body
    )
    assert r_victim.status_code == 200, r_victim.text


# ════════════════ R3-1: 비용 가드 배선 ════════════════


def test_cost_budget_is_wired_into_deploy_artifacts():
    """H4/R3-1: 배포 산출물에 예산 env가 배선돼 있다(값 주입 자체가 불가능하던 상태 회귀 차단).

    직전 감사가 '출시 최소 조건'으로 승격한 완화책이, 코드에는 있는데 docker-compose.prod와
    .env.example 양쪽에 없어서 **값을 넣을 방법이 없었다** — 즉 실제로는 꺼져 있었다.
    """
    import pathlib

    api_root = pathlib.Path(__file__).resolve().parents[1]
    repo_root = api_root.parent.parent

    env_example = (api_root / ".env.example").read_text()
    assert "DAILY_GENERATION_BUDGET" in env_example

    compose = (repo_root / "infra" / "docker-compose.prod.yml").read_text()
    assert "DAILY_GENERATION_BUDGET" in compose
    # 워커도 같은 전역 카운터를 봐야 한다(API만 배선하면 워커 경로가 어긋난다).
    assert compose.count("DAILY_GENERATION_BUDGET") >= 2


@pytest.mark.asyncio
async def test_readiness_reports_cost_budget_disabled_in_production(
    client, monkeypatch
):
    """H4/R3-1: 프로덕션에서 예산이 0/미설정이면 readiness가 그 사실을 표면화한다.

    red-proof: main.py 의 cost_budget 판정을 지우면 services.cost_budget 키가 사라져 FAIL.
    """
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "daily_generation_budget", 0)

    r = await client.get("/health/ready")
    body = r.json()
    assert body["services"]["cost_budget"] == "disabled"

    monkeypatch.setattr(settings, "daily_generation_budget", 300)
    r2 = await client.get("/health/ready")
    assert r2.json()["services"]["cost_budget"] == "configured"


# ════════════════ R4: 로그 마스킹 · 배포 자세 ════════════════


def test_all_logging_paths_redact_share_tokens():
    """R4: 예외 핸들러 5곳이 `_redact_path`를 우회하던 이원화 제거.

    `/share/{token}` 은 인증 없이 아동 콘텐츠를 여는 자격증명 그 자체다. 에러가 난 요청의
    경로만 원문으로 남으면, 로그 접근자가 무인증으로 재생할 수 있다.

    red-proof: exceptions.py 의 `redact_path(...)` 중 하나를 `request.url.path` 로 되돌리면 FAIL.
    """
    import pathlib

    api_root = pathlib.Path(__file__).resolve().parents[1]
    for rel in ("src/main.py", "src/core/exceptions.py"):
        src = (api_root / rel).read_text()
        for line_no, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith("path=request.url.path"):
                continue
            raise AssertionError(
                f"{rel}:{line_no} 가 마스킹 없이 경로를 로깅한다: {stripped}"
            )


def test_share_token_is_actually_redacted():
    """마스킹 함수 자체의 행위 검증(정규식 오타로 조용히 통과하는 것 방지)."""
    from src.core.utils import redact_path

    assert redact_path("/share/" + "a" * 32) == "/share/{token}"
    assert redact_path("/v1/books/job_1") == "/v1/books/job_1"


def test_production_uvicorn_disables_access_log():
    """M6/R4: 프로덕션 CMD에 `--no-access-log`.

    uvicorn 기본 액세스 로그는 원문 경로를 찍으므로 앱·nginx의 공유 토큰 마스킹을 한 줄로
    무력화한다(로그 접근자가 무인증 재생).
    """
    import pathlib

    api_root = pathlib.Path(__file__).resolve().parents[1]
    dockerfile = (api_root / "Dockerfile").read_text()
    cmd_lines = [
        line for line in dockerfile.splitlines() if line.startswith('CMD ["uvicorn"')
    ]
    assert cmd_lines, "uvicorn CMD 를 찾지 못했다"
    for line in cmd_lines:
        assert "--no-access-log" in line, line


def test_nginx_terminates_tls_with_hsts_and_redirect():
    """H9/R4: 엣지가 TLS를 종단하고 HTTP는 HTTPS로 리다이렉트하며 HSTS를 보낸다.

    X-User-Key(유일 자격증명)와 아동 콘텐츠가 평문으로 흐르던 상태의 회귀 차단.
    """
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    conf = (repo_root / "infra" / "nginx" / "nginx.conf").read_text()

    # 주석이 아닌 실제 지시문만 본다(예전 상태가 '전부 주석'이었다).
    active = "\n".join(
        line for line in conf.splitlines() if not line.strip().startswith("#")
    )
    assert "listen 443 ssl" in active, "443 리스너가 없다(평문 전용)"
    assert "ssl_certificate " in active
    assert "return 301 https://$host$request_uri" in active, "HTTP→HTTPS 리다이렉트 없음"
    assert "Strict-Transport-Security" in active, "HSTS 없음"
    assert "TLSv1.2" in active and "TLSv1.3" in active


def test_deployment_doc_has_tls_procedure():
    """H9/R4: DEPLOYMENT.md 에 TLS 절차가 실제로 존재한다(문서 0회 → 절차 명문화)."""
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    doc = (repo_root / "docs" / "DEPLOYMENT.md").read_text()
    assert "TLS termination" in doc
    assert "certbot" in doc
    assert "Strict-Transport-Security" in doc or "HSTS" in doc


# ════════════════ R4: IDOR 봉인 ════════════════


@pytest.mark.asyncio
async def test_pronunciation_rejects_foreign_book(client, db_session):
    """R4: 발음 평가가 남의 책 id를 거부한다(형제 write 경로 불변식 적용).

    red-proof: `assert_book_not_foreign(...)` 호출을 지우면 200이 되어 FAIL.
    """
    from src.models.db import Book, Job

    other = "cccccccc-3333-4333-8333-cccccccccccc"
    db_session.add(Job(id="job_foreign_pron", status="done", user_key=other))
    await db_session.flush()
    db_session.add(
        Book(
            id="book_foreign_pron",
            job_id="job_foreign_pron",
            title="남의 책",
            language="ko",
            target_age="5-7",
            style="watercolor",
            user_key=other,
        )
    )
    await db_session.commit()

    r = await client.post(
        "/v1/pronunciation/evaluate",
        headers=H,
        json={
            "book_id": "book_foreign_pron",
            "page_number": 1,
            "transcript": "토끼가 하늘을 날아요",
            "expected_text": "토끼가 하늘을 날아요",
        },
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_voice_profile_rejects_foreign_storage_url(client):
    """R4: 샘플 오디오 URL이 내 prefix 밖이면 거부한다(임의 객체 삭제 프리미티브 차단).

    이 URL은 나중에 `key_from_public_url`로 역산돼 그대로 삭제 대상이 된다 — 검증이 없으면
    타인의 아동 사진 키를 지정한 뒤 프로필을 지워 임의 객체를 파기할 수 있다.

    red-proof: `_normalize_required_url` 의 prefix 검사를 지우면 200이 되어 FAIL.
    """
    base = settings.s3_public_url.rstrip("/")
    r = await client.post(
        "/v1/voice-profiles",
        headers=H,
        json={
            "label": "엄마",
            "sample_audio_url": f"{base}/characters/char_victim/photo.jpg",
            "consented": True,
        },
    )
    assert r.status_code == 400, r.text

    # 내 prefix 안의 URL은 정상 통과 — 반대 방향 봉인.
    ok = await client.post(
        "/v1/voice-profiles",
        headers=H,
        json={
            "label": "엄마",
            "sample_audio_url": f"{base}/voice-samples/{H['X-User-Key']}/s.m4a",
            "consented": True,
        },
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_voice_profile_patch_purges_old_sample_not_new(client, monkeypatch):
    """R4: PATCH 파기 순서 — 교체된 **옛** 샘플을 지우고 새 파일은 남긴다.

    수정 전에는 setattr 루프 뒤에 purge_url을 읽어, sample_audio_url 교체 + consented=false가
    같은 요청에 오면 **방금 올린 새 파일을 지우고 옛 샘플을 남겼다**.

    red-proof: `previous_sample_url` 캡처를 setattr 루프 뒤로 되돌리면 FAIL.
    """
    from src.routers import voice_profiles as vp_module

    deleted: list = []

    async def spy_delete_keys(keys):
        deleted.extend(keys)
        return []

    # 라우터가 모듈 상단에서 `from ... import delete_keys` 로 바인딩하므로 그 이름을 패치한다.
    monkeypatch.setattr(vp_module, "delete_keys", spy_delete_keys)

    base = settings.s3_public_url.rstrip("/")
    uk = H["X-User-Key"]
    old_url = f"{base}/voice-samples/{uk}/old.m4a"
    new_url = f"{base}/voice-samples/{uk}/new.m4a"

    created = await client.post(
        "/v1/voice-profiles",
        headers=H,
        json={"label": "아빠", "sample_audio_url": old_url, "consented": True},
    )
    assert created.status_code == 200, created.text
    profile_id = created.json()["id"]

    patched = await client.patch(
        f"/v1/voice-profiles/{profile_id}",
        headers=H,
        json={"sample_audio_url": new_url, "consented": False},
    )
    assert patched.status_code == 200, patched.text

    assert f"voice-samples/{uk}/old.m4a" in deleted, deleted
    assert f"voice-samples/{uk}/new.m4a" not in deleted, deleted


def test_key_from_public_url_recognizes_legacy_bases(monkeypatch):
    """R4: 과거 도메인 prefix도 역산 대상 — 도메인 변경이 파기를 조용한 no-op으로 만들지 않게.

    red-proof: `_public_url_bases()`에서 legacy 목록을 빼면 legacy URL이 None이 되어 FAIL.
    """
    from src.services.storage import key_from_public_url

    monkeypatch.setattr(settings, "s3_public_url", "https://cdn.new.example/bucket")
    monkeypatch.setattr(
        settings,
        "s3_legacy_public_urls",
        "https://cdn.old.example/bucket, https://minio.internal:9000/bucket",
    )

    assert (
        key_from_public_url("https://cdn.new.example/bucket/images/a.png")
        == "images/a.png"
    )
    assert (
        key_from_public_url("https://cdn.old.example/bucket/images/a.png")
        == "images/a.png"
    )
    assert (
        key_from_public_url("https://minio.internal:9000/bucket/images/a.png")
        == "images/a.png"
    )
    # 남의 버킷은 여전히 None(무차별 삭제 방지).
    assert key_from_public_url("https://evil.example/images/a.png") is None


# ════════════════ R1-5: durable 파기 큐 ════════════════


@pytest.mark.asyncio
async def test_purge_sweep_retries_interrupted_purge(db_session, monkeypatch):
    """M8/R1-5: 인라인 파기가 실패해도 지시가 남고, 스윕이 멱등 재실행해 완결한다.

    이게 없으면 '커밋 후 in-memory 키'만으로 파기하던 예전 구조 그대로다 — 중단 시
    아동 PII 영구 고아 + 재시도 success 위장.

    red-proof: `run_purge_tasks` 가 실패 시 status를 'done'으로 종결하게 바꾸면,
    스윕이 대상을 찾지 못해 아래 두 번째 단계에서 FAIL한다.
    """
    import src.services.purge_queue as purge_module
    from src.models.db import StoragePurgeTask
    from sqlalchemy import select

    calls = {"n": 0}

    async def flaky_execute(task):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("S3 unavailable")
        return []

    monkeypatch.setattr(purge_module, "_execute_task", flaky_execute)

    tasks = purge_module.enqueue_purge_keys(
        db_session,
        user_key="uk-purge-retry",
        reason="account_deletion",
        keys=["images/replicate/orphan.png"],
    )
    await db_session.commit()

    # 1단계: 인라인 실행 실패 → 실패 키 표면화 + 지시는 pending 유지.
    failed = await purge_module.run_purge_tasks(db_session, tasks)
    assert failed, "실패를 success로 위장했다"

    db_session.expire_all()
    pending = (
        await db_session.execute(
            select(StoragePurgeTask).where(
                StoragePurgeTask.user_key == "uk-purge-retry"
            )
        )
    ).scalars().all()
    assert [t.status for t in pending] == ["pending"]

    # 2단계: 스윕이 같은 지시를 재실행해 완결(멱등).
    monkeypatch.setattr(
        "src.core.database.AsyncSessionLocal", lambda: _PassthroughSession(db_session)
    )
    completed = await purge_module.sweep_pending_purges()
    assert completed == 1

    db_session.expire_all()
    after = (
        await db_session.execute(
            select(StoragePurgeTask).where(
                StoragePurgeTask.user_key == "uk-purge-retry"
            )
        )
    ).scalars().all()
    assert [t.status for t in after] == ["done"]


class _PassthroughSession:
    """스윕이 여는 새 세션을 테스트 세션으로 대체(같은 SQLite 인메모리 상태를 보게)."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_orphan_guard_survives_failed_character_creation(
    client, db_session, monkeypatch
):
    """H8/R1-3: 사진 업로드 후 캐릭터 생성이 실패하면, 파기 지시가 pending으로 남는다.

    예전에는 업로드(외부 부작용)가 커밋보다 먼저라, 실패 시 **행 없는 고아 아동 사진**이
    남아 계정삭제·동의철회 어떤 경로로도 파기할 수 없었다(URL 역산 불가).

    red-proof: `enqueue_purge_keys(... "photo_upload_guard" ...)` 선기록을 지우면
    storage_purge_tasks 가 비어 FAIL한다.
    """
    from sqlalchemy import select

    from src.models.db import StoragePurgeTask
    from src.services import photo_character as photo_module

    async def returns_invalid_payload(**kwargs):
        # 업로드는 성공시키고 **그 뒤** 커밋 전 DTO 검증에서 실패시킨다 — 고아가 실제로
        # 생기는 창(업로드 완료 ~ 커밋 실패)을 재현해야 가드가 의미를 갖는다.
        # (vision 호출 자체가 실패하면 업로드도 없어 고아가 없다.)
        return {
            "name": "",  # assert_character_dto_valid 에서 ValueError
            "master_description": "",
            "appearance": {},
            "clothing": {},
            "personality_traits": [],
        }

    monkeypatch.setattr(
        photo_module.photo_character_service,
        "create_character_from_photo",
        returns_invalid_payload,
    )

    r = await client.post(
        "/v1/characters/from-photo",
        headers=H,
        files={"photo": ("child.jpg", b"\xff\xd8\xff\xdb" + b"0" * 64, "image/jpeg")},
        data={"name": "아이", "style": "cartoon"},
    )
    assert r.status_code == 500, r.text

    guards = (
        await db_session.execute(
            select(StoragePurgeTask).where(
                StoragePurgeTask.reason == "photo_upload_guard"
            )
        )
    ).scalars().all()
    assert guards, "업로드 고아 가드가 기록되지 않았다"
    assert all(g.status == "pending" for g in guards), [g.status for g in guards]
    assert all(g.target.startswith("characters/") for g in guards)


@pytest.mark.asyncio
async def test_orphan_guard_cancelled_on_successful_creation(
    client, db_session, monkeypatch
):
    """반대 방향 봉인: 캐릭터가 살아남으면 가드가 취소되어 **살아있는 사진을 지우지 않는다**."""
    from sqlalchemy import select

    from src.models.db import StoragePurgeTask
    from src.services import photo_character as photo_module

    async def ok(**kwargs):
        return {
            "name": "아이",
            "master_description": "a cheerful child in storybook style",
            "appearance": {"age_visual": "6세", "hair_color": "검정", "skin_tone": "밝은"},
            "clothing": {"top": "티셔츠", "bottom": "바지", "shoes": "운동화"},
            "personality_traits": ["밝은"],
        }

    monkeypatch.setattr(
        photo_module.photo_character_service, "create_character_from_photo", ok
    )

    r = await client.post(
        "/v1/characters/from-photo",
        headers=H,
        files={"photo": ("child.jpg", b"\xff\xd8\xff\xdb" + b"0" * 64, "image/jpeg")},
        data={"name": "아이", "style": "cartoon"},
    )
    assert r.status_code == 200, r.text

    guards = (
        await db_session.execute(
            select(StoragePurgeTask).where(
                StoragePurgeTask.reason == "photo_upload_guard"
            )
        )
    ).scalars().all()
    assert guards, "가드 자체가 기록되지 않았다(선기록 누락)"
    assert all(g.status == "cancelled" for g in guards), [g.status for g in guards]


# ════════════════ H6: 리텔/원본 S3 이미지 키 공유 ════════════════


async def _seed_book_with_pipeline_image(db, user_key: str, tag: str) -> tuple[str, str]:
    """`images/{provider}/…`(books/{id}/ prefix 밖) 삽화를 가진 책 1권. 반환 (book_id, key)."""
    import uuid as _uuid

    from src.core.config import settings
    from src.models.db import Book, Job, Page

    suffix = _uuid.uuid4().hex[:8]
    job_id = f"job_{tag}_{suffix}"
    book_id = f"book_{tag}_{suffix}"
    key = f"images/replicate/{tag}-{suffix}.png"
    base = settings.s3_public_url.rstrip("/")

    db.add(Job(id=job_id, status="done", user_key=user_key))
    await db.flush()
    db.add(
        Book(
            id=book_id,
            job_id=job_id,
            title="원본",
            language="ko",
            target_age="5-7",
            style="watercolor",
            user_key=user_key,
            cover_image_url=f"{base}/{key}",
        )
    )
    db.add(
        Page(book_id=book_id, page_number=1, text="p1", image_url=f"{base}/{key}")
    )
    await db.commit()
    return book_id, key


async def _seed_legacy_retell(db, source_book_id: str, user_key: str) -> str:
    """**수정 전 방식**(URL 그대로 복사 = 같은 S3 객체 공유)으로 만든 리텔 책.

    이미 만들어진 리텔들이 이 상태이므로, 파기 시점 방어가 실제로 필요한 대상이다.
    """
    import uuid as _uuid

    from sqlalchemy import select

    from src.models.db import Book, Job, Page

    suffix = _uuid.uuid4().hex[:8]
    job_id = f"retell_{suffix}"
    book_id = f"book_retell_{suffix}"

    source = (
        await db.execute(select(Book).where(Book.id == source_book_id))
    ).scalar_one()
    src_pages = (
        await db.execute(select(Page).where(Page.book_id == source_book_id))
    ).scalars().all()

    db.add(Job(id=job_id, status="done", user_key=user_key))
    await db.flush()
    db.add(
        Book(
            id=book_id,
            job_id=job_id,
            title="리텔",
            language=source.language,
            target_age="3-5",
            style=source.style,
            user_key=user_key,
            cover_image_url=source.cover_image_url,  # ← 공유(옛 동작)
            retelling_source_book_id=source_book_id,
        )
    )
    for sp in src_pages:
        db.add(
            Page(
                book_id=book_id,
                page_number=sp.page_number,
                text="리텔 본문",
                image_url=sp.image_url,  # ← 공유(옛 동작)
            )
        )
    await db.commit()
    return book_id


@pytest.mark.asyncio
async def test_deleting_retell_does_not_purge_shared_source_images(
    client, db_session, monkeypatch
):
    """H6: 리텔을 지워도 **원본이 아직 참조 중인** 삽화 키는 파기하지 않는다.

    수정 전에는 `collect_book_image_keys` 가 배타 소유를 가정해 공유 객체를 지웠고, 남은
    책의 표지·전 페이지가 전부 404가 됐다(사용자 데이터 손실).

    red-proof: `collect_purgeable_image_keys` 의 `still_referenced` 제외를 없애면
    공유 키가 삭제 목록에 들어와 FAIL한다.
    """
    from src.services import storage as storage_module

    deleted: list = []

    async def spy_delete_keys(keys):
        deleted.extend(keys)
        return []

    async def noop_prefix(prefix):
        return []

    monkeypatch.setattr(storage_module, "delete_keys", spy_delete_keys)
    monkeypatch.setattr(storage_module.storage_service, "delete_prefix", noop_prefix)

    uk = H["X-User-Key"]
    source_id, shared_key = await _seed_book_with_pipeline_image(db_session, uk, "src")
    retell_id = await _seed_legacy_retell(db_session, source_id, uk)

    r = await client.delete(f"/v1/library/{retell_id}", headers=H)
    assert r.status_code == 200, r.text

    assert shared_key not in deleted, (
        f"원본이 아직 쓰는 공유 삽화를 파기했다(원본 책 404): {deleted}"
    )


@pytest.mark.asyncio
async def test_deleting_source_does_not_purge_images_used_by_retell(
    client, db_session, monkeypatch
):
    """H6 반대 방향: 원본을 지워도 리텔이 참조 중인 삽화는 남는다."""
    from src.services import storage as storage_module

    deleted: list = []

    async def spy_delete_keys(keys):
        deleted.extend(keys)
        return []

    async def noop_prefix(prefix):
        return []

    monkeypatch.setattr(storage_module, "delete_keys", spy_delete_keys)
    monkeypatch.setattr(storage_module.storage_service, "delete_prefix", noop_prefix)

    uk = H["X-User-Key"]
    source_id, shared_key = await _seed_book_with_pipeline_image(db_session, uk, "src2")
    await _seed_legacy_retell(db_session, source_id, uk)

    r = await client.delete(f"/v1/library/{source_id}", headers=H)
    assert r.status_code == 200, r.text
    assert shared_key not in deleted, deleted


@pytest.mark.asyncio
async def test_deleting_last_book_does_purge_its_images(
    client, db_session, monkeypatch
):
    """반대 방향 봉인: 공유가 없으면 원래대로 파기한다(과잉 보존으로 고아를 만들지 않음)."""
    from src.services import storage as storage_module

    deleted: list = []

    async def spy_delete_keys(keys):
        deleted.extend(keys)
        return []

    async def noop_prefix(prefix):
        return []

    monkeypatch.setattr(storage_module, "delete_keys", spy_delete_keys)
    monkeypatch.setattr(storage_module.storage_service, "delete_prefix", noop_prefix)

    uk = H["X-User-Key"]
    book_id, key = await _seed_book_with_pipeline_image(db_session, uk, "solo")

    r = await client.delete(f"/v1/library/{book_id}", headers=H)
    assert r.status_code == 200, r.text
    assert key in deleted, deleted


@pytest.mark.asyncio
async def test_retell_copies_images_to_its_own_keys(client, db_session, monkeypatch):
    """H6 근본 원인: 새 리텔은 원본 URL을 공유하지 않고 **자기 사본**을 갖는다.

    red-proof: `_copy_retell_image` 대신 `source.cover_image_url` 을 그대로 쓰게 되돌리면
    새 책의 URL이 원본과 같아져 FAIL한다.
    """
    from sqlalchemy import select

    from src.models.db import Book, Page
    from src.services import llm as llm_module
    from src.services import orchestrator as orch_module

    uk = H["X-User-Key"]
    source_id, source_key = await _seed_book_with_pipeline_image(db_session, uk, "copy")

    # 복사 대상 객체를 페이크 S3에 심는다(copy_object 가 원본 키를 요구).
    from src.services import storage as storage_module

    storage_module.get_s3_client().objects[source_key] = b"img"

    class _Retold:
        title = "리텔 제목"
        pages = ["다시 쓴 본문"]

    async def fake_retext(**kwargs):
        return _Retold()

    async def always_safe(text, language):
        return True

    monkeypatch.setattr(llm_module, "call_story_retext", fake_retext)
    monkeypatch.setattr(orch_module, "moderate_text_localized", always_safe)

    r = await client.post(
        f"/v1/books/{source_id}/retell",
        headers=H,
        json={"target_age": "3-5"},
    )
    assert r.status_code == 200, r.text
    new_book_id = r.json()["book_id"]

    db_session.expire_all()
    source = (
        await db_session.execute(select(Book).where(Book.id == source_id))
    ).scalar_one()
    new_book = (
        await db_session.execute(select(Book).where(Book.id == new_book_id))
    ).scalar_one()

    assert new_book.cover_image_url, "리텔 표지 URL이 비었다"
    assert new_book.cover_image_url != source.cover_image_url, (
        "리텔이 원본과 **같은 S3 객체**를 가리킨다 — 한쪽 삭제 시 나머지가 404"
    )

    src_page = (
        await db_session.execute(
            select(Page).where(Page.book_id == source_id, Page.page_number == 1)
        )
    ).scalar_one()
    new_page = (
        await db_session.execute(
            select(Page).where(Page.book_id == new_book_id, Page.page_number == 1)
        )
    ).scalar_one()
    assert new_page.image_url and new_page.image_url != src_page.image_url


# ════════════════ H7: streak 오늘의 동화 게이트 ════════════════


def test_every_book_creation_entrypoint_enforces_character_access():
    """H7: 책을 만드는 **모든** 진입점이 소유권·동의 게이트를 통과한다(구조 불변식).

    `create_book` 에만 있던 블록을 `enforce_book_spec_access` 로 추출해 streak과 공유한다.
    새 생성 진입점이 생겨도 이 테스트가 누락을 즉시 잡는다.

    red-proof: streak 의 `enforce_book_spec_access(...)` 호출을 지우면 FAIL.
    """
    from src.routers import books as books_module
    from src.routers import streak as streak_module

    entrypoints = [
        (books_module.create_book, "books.create"),
        (streak_module.generate_today_story, "streak.today_generate"),
    ]
    missing = [
        label
        for func, label in entrypoints
        if "enforce_book_spec_access(" not in inspect.getsource(func)
    ]
    assert not missing, f"캐릭터 소유권·동의 게이트가 없는 생성 진입점: {missing}"


@pytest.mark.asyncio
async def test_today_generate_rejects_foreign_character(client, db_session):
    """H7: 오늘의 동화가 **타인 캐릭터**로 생성되지 않는다(IDOR).

    red-proof: streak 의 `enforce_book_spec_access(...)` 호출을 지우면 200이 되어 FAIL.
    """
    from src.models.db import Character

    other = "dddddddd-4444-4444-8444-dddddddddddd"
    db_session.add(
        Character(
            id="char_foreign_today",
            name="남의 아이",
            master_description="another user's child character",
            appearance={},
            clothing={},
            personality_traits=[],
            user_key=other,
            from_photo=True,
        )
    )
    await db_session.commit()

    r = await client.post(
        "/v1/streak/today/generate",
        headers=H,
        json={
            "target_age": "5-7",
            "style": "watercolor",
            "character_id": "char_foreign_today",
        },
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_today_generate_requires_photo_consent(client, db_session, monkeypatch):
    """H7: 동의가 없으면 사진 파생 캐릭터로 오늘의 동화를 만들 수 없다.

    create_book 은 막는데 이 경로만 뚫려 있으면, 철회한 보호자의 아동 얼굴이 계속 렌더된다.
    """
    from src.core.config import settings
    from src.models.db import Character

    # 테스트 환경 기본은 동의 게이트 우회 — 이 테스트만 실제 집행으로 켠다.
    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)

    uk = H["X-User-Key"]
    db_session.add(
        Character(
            id="char_own_photo_today",
            name="내 아이",
            master_description="my child character from a photo",
            appearance={},
            clothing={},
            personality_traits=[],
            user_key=uk,
            from_photo=True,
        )
    )
    await db_session.commit()

    r = await client.post(
        "/v1/streak/today/generate",
        headers=H,
        json={
            "target_age": "5-7",
            "style": "watercolor",
            "character_id": "char_own_photo_today",
        },
    )
    assert r.status_code == 403, r.text

    # 동의를 받으면 통과 — 반대 방향 봉인(게이트가 기능을 죽이지 않는다).
    grant = await client.post(
        "/v1/consent",
        headers=H,
        json={"privacy": True, "photos": True, "data_processing": True},
    )
    assert grant.status_code == 200, grant.text

    r2 = await client.post(
        "/v1/streak/today/generate",
        headers=H,
        json={
            "target_age": "5-7",
            "style": "watercolor",
            "character_id": "char_own_photo_today",
        },
    )
    assert r2.status_code == 200, r2.text
