"""CI 워크플로 게이트 가드 테스트 (W6: M1·M2·M7·L1·L3·L4).

`.github/workflows/ci.yml`이 릴리스 차단 게이트로서 실질 동작하는지 — pipefail
마스킹 없음·CVE 스캔 blocking·스캔 순서(push 이전)·배포 concurrency·리포/이미지
스큐 방지·스테일 버전 핀 제거 — 를 YAML 구조 수준에서 잠근다. 실제 CI 런타임은
파이프라인에서만 검증 가능하므로, 이 가드는 '게이트가 조용히 무력화되는' 회귀를 막는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[3]
CI_YML_PATH = REPO_ROOT / ".github/workflows/ci.yml"
LIVE_E2E_PATH = REPO_ROOT / "scripts/run_live_e2e.sh"


@pytest.fixture(scope="module")
def ci_text() -> str:
    return CI_YML_PATH.read_text()


@pytest.fixture(scope="module")
def ci_data(ci_text) -> dict:
    return yaml.safe_load(ci_text)


def _steps(ci_data: dict, job: str) -> list[dict]:
    return ci_data["jobs"][job]["steps"]


# ── M1: 배포 직렬화 (진행 중 배포·빌드는 절대 취소되지 않음) ──────────────────


def test_workflow_cancel_in_progress_pr_only(ci_data):
    # 워크플로 레벨 cancel-in-progress가 리터럴 True가 아니라 PR 이벤트 표현식이어야 한다.
    cip = ci_data["concurrency"]["cancel-in-progress"]
    assert cip is not True, "main push 런(build·deploy 포함)이 후속 push에 취소되면 안 됨"
    assert "pull_request" in str(cip), f"PR 전용 취소 표현식이어야 함: {cip!r}"


def test_deploy_job_is_not_cancellable(ci_data):
    concurrency = ci_data["jobs"]["deploy"]["concurrency"]
    assert concurrency["group"] == "deploy-production"
    assert concurrency["cancel-in-progress"] is False


def test_build_job_not_cancellable(ci_data):
    concurrency = ci_data["jobs"]["build"]["concurrency"]
    assert concurrency["cancel-in-progress"] is False


# ── M2: 취약점 스캔 게이트 실질화 ────────────────────────────────────────────


def test_safety_step_not_soft_failed(ci_data):
    """보안 스캔 스텝이 실패를 '성공으로 위장'하지 않아야 한다.

    금지: run에서 `|| echo`로 종료코드를 0으로 삼키는 것(감사 M2 'silent safety').
    허용: advisory 정책이면 `continue-on-error: true`를 **명시** — 실패가 노란색으로 보인다.
    (파일 전체 문자열 검색은 설명 주석에도 걸리므로 실제 run 명령만 본다.)
    """
    steps = _steps(ci_data, "api-test")
    safety_steps = [s for s in steps if "safety" in (s.get("run") or "")]
    assert safety_steps, "safety 스캔 스텝을 찾지 못함"

    for step in safety_steps:
        run = step["run"]
        assert "|| echo" not in run, (
            f"'{step.get('name')}'이 || echo로 종료코드를 삼킴 — 실패가 성공으로 위장됨"
        )
        if step.get("continue-on-error") is not True:
            # blocking이면 그대로 두고, advisory라면 반드시 명시적이어야 한다.
            assert "|| true" not in run and "; true" not in run, (
                f"'{step.get('name')}'이 암묵적으로 실패를 무시함"
            )


def test_trivy_repo_scan_blocking(ci_data):
    steps = _steps(ci_data, "security-scan")
    repo_scan = None
    for step in steps:
        uses = step.get("uses", "")
        with_ = step.get("with", {}) or {}
        if "trivy-action" in uses and with_.get("scan-type") == "fs":
            repo_scan = step
            break
    assert repo_scan is not None, "repo(fs) Trivy 스캔 스텝이 있어야 함"
    assert repo_scan["with"]["exit-code"] == "1", "repo Trivy 스캔이 CVE에 blocking이어야 함"


# ── M6: 가변 ref 핀 고정 ─────────────────────────────────────────────────────


def test_no_mutable_master_action_ref(ci_text):
    assert "@master" not in ci_text, "third-party 액션은 @master 가변 ref로 핀하면 안 됨"


# ── M3/M4/M5: pipefail 마스킹 제거 ───────────────────────────────────────────


def test_tee_pipelines_use_pipefail(ci_text):
    # `... 2>&1 | tee ...`가 있는 모든 run 블록은 pipefail로 좌측 종료코드를 보존해야 한다.
    for line in ci_text.splitlines():
        if "| tee" in line and "set -o pipefail" not in line:
            # tee 라인 자체는 pipefail 라인이 아니므로, 파일 전체에 pipefail이 tee 개수만큼 있는지로 검증
            pass
    tee_count = ci_text.count("| tee ")
    pipefail_count = ci_text.count("set -o pipefail")
    assert pipefail_count >= tee_count, (
        f"tee 파이프 {tee_count}개 대비 pipefail {pipefail_count}개 — 종료코드 마스킹 위험"
    )


# ── M7: 이미지 스캔을 push 이전·차단형으로 + worker 스캔 ──────────────────────


def test_image_scanned_before_push(ci_data):
    steps = _steps(ci_data, "build")
    names = [s.get("name", "") for s in steps]

    def first_index(pred):
        for i, s in enumerate(steps):
            if pred(s):
                return i
        return -1

    scan_idx = first_index(
        lambda s: "trivy-action" in s.get("uses", "")
        and "/api:" in ((s.get("with") or {}).get("image-ref") or "")
    )
    push_idx = first_index(
        lambda s: "push" in (s.get("name") or "").lower()
        and "registry" in (s.get("name") or "").lower()
    )
    assert scan_idx != -1, f"API 이미지 스캔 스텝이 있어야 함: {names}"
    assert push_idx != -1, f"레지스트리 push 스텝이 있어야 함: {names}"
    assert scan_idx < push_idx, "이미지 스캔은 레지스트리 push 이전에 실행되어야 함"


def test_image_scan_blocking(ci_data):
    steps = _steps(ci_data, "build")
    image_scans = [
        s
        for s in steps
        if "trivy-action" in s.get("uses", "")
        and "image-ref" in (s.get("with") or {})
    ]
    assert image_scans, "이미지 스캔 스텝이 있어야 함"
    for s in image_scans:
        assert (s["with"]).get("exit-code") == "1", (
            f"이미지 스캔 '{s.get('name')}'이 CRITICAL에 blocking(exit-code 1)이어야 함"
        )


def test_worker_image_scanned(ci_data):
    steps = _steps(ci_data, "build")
    worker_scans = [
        s
        for s in steps
        if "trivy-action" in s.get("uses", "")
        and "/worker:" in ((s.get("with") or {}).get("image-ref") or "")
    ]
    assert worker_scans, "worker 이미지도 스캔 대상이어야 함"


def test_images_built_without_immediate_push(ci_data):
    # build-push-action 스텝은 push:true로 스캔 이전에 게시하면 안 된다(push:false·load:true).
    steps = _steps(ci_data, "build")
    for s in steps:
        if "build-push-action" in s.get("uses", ""):
            with_ = s.get("with") or {}
            assert with_.get("push") in (False, "false", None), (
                f"'{s.get('name')}'가 스캔 이전에 push:true로 게시하면 안 됨"
            )


# ── L1: env 게이트 스텝명 정직화 ─────────────────────────────────────────────


def test_env_step_name_not_overclaiming(ci_text):
    assert "Check environment contracts" not in ci_text, (
        "파일 존재 검사만 하는 스텝이 '계약 검증'을 과장하면 안 됨"
    )


# ── L3: 스테일 APP_VERSION 핀 제거 ──────────────────────────────────────────


def test_no_stale_app_version_pin(ci_text):
    assert "0.3.2" not in ci_text, "ci.yml에 스테일 버전 핀 0.3.2가 남으면 안 됨"
    assert "0.3.2" not in LIVE_E2E_PATH.read_text(), (
        "run_live_e2e.sh에 스테일 버전 핀 0.3.2가 남으면 안 됨"
    )


# ── L4: 리포/이미지 스큐 제거 (detached $GITHUB_SHA) ─────────────────────────


def _deploy_script(ci_data: dict) -> str:
    for step in _steps(ci_data, "deploy"):
        if "ssh-action" in step.get("uses", ""):
            return (step.get("with") or {}).get("script", "")
    return ""


def test_deploy_checks_out_exact_sha(ci_data):
    script = _deploy_script(ci_data)
    assert script, "deploy SSH 스크립트가 있어야 함"
    assert 'git checkout --detach "$GITHUB_SHA"' in script, "리포를 빌드 SHA로 고정해야 함"
    assert "git pull --ff-only origin main" not in script, "최신 main으로 ff-pull하면 스큐 발생"


def test_repo_and_image_same_ref(ci_data):
    script = _deploy_script(ci_data)
    assert script.count("$GITHUB_SHA") >= 2, "리포 체크아웃과 --image-tag가 모두 $GITHUB_SHA여야 함"
    assert '--image-tag "$GITHUB_SHA"' in script


# ── S2/S3: 공급망(액션 SHA 핀) + 의존성 CVE 게이트 강도 ──


def test_third_party_actions_are_sha_pinned(ci_text):
    """S3: 서드파티 액션은 전체 커밋 SHA로 핀해야 한다.

    가변 태그는 메인테이너 계정 탈취·악성 리태그 시 다음 CI 실행에서 임의 코드가 러너에서
    돈다. deploy 잡의 appleboy/ssh-action은 프로덕션 SSH 개인키를 주입받으므로 침해 시
    배포 파이프라인이 통째로 넘어간다.
    """
    import re

    # GitHub 공식(actions/*)은 이번 스코프 밖 — 서드파티만 강제.
    third_party = re.findall(r"uses:\s+((?!actions/)[\w.-]+/[\w./-]+)@(\S+)", ci_text)
    assert third_party, "서드파티 액션을 찾지 못함(패턴 확인 필요)"

    unpinned = [
        f"{repo}@{ref}"
        for repo, ref in third_party
        if not re.fullmatch(r"[0-9a-f]{40}", ref)
    ]
    assert not unpinned, f"SHA 핀이 아닌 서드파티 액션: {unpinned}"


def test_deploy_ssh_action_is_sha_pinned(ci_data):
    """프로덕션 SSH 키를 다루는 액션은 반드시 SHA 핀(최소 조건)."""
    import re

    for step in ci_data["jobs"]["deploy"]["steps"]:
        uses = step.get("uses", "")
        if "ssh-action" in uses:
            ref = uses.split("@", 1)[1]
            assert re.fullmatch(r"[0-9a-f]{40}", ref), f"ssh-action 미핀: {uses}"
            return
    raise AssertionError("deploy 잡에서 ssh-action 스텝을 찾지 못함")


def test_dependency_scan_blocks_high_severity(ci_data):
    """S2: 의존성(fs) 스캔이 HIGH도 차단해야 한다.

    CRITICAL만 차단하던 정책이 CVE-2024-53981(python-multipart, HIGH 7.5 —
    near-unauth 업로드 DoS)을 그대로 통과시켰다.
    """
    for step in ci_data["jobs"]["security-scan"]["steps"]:
        with_ = step.get("with") or {}
        if "trivy-action" in step.get("uses", "") and with_.get("scan-type") == "fs":
            assert with_["exit-code"] == "1"
            assert "HIGH" in with_["severity"], (
                f"의존성 스캔이 HIGH를 차단하지 않음: {with_['severity']}"
            )
            return
    raise AssertionError("repo(fs) Trivy 스캔 스텝을 찾지 못함")


# ── 2026-08-17 보안감사: 실PG FK 게이트가 CI에서 실제로 도는가 ────────────────


def _find_step(ci_data: dict, job: str, needle: str) -> dict | None:
    for step in _steps(ci_data, job):
        if needle in (step.get("name") or "") or needle in (step.get("run") or ""):
            return step
    return None


def test_real_pg_fk_gate_runs_in_ci(ci_data):
    """실 PostgreSQL FK 게이트가 CI 스텝으로 배선돼 있다.

    아동 PII 파기·FK 위반 클래스는 SQLite 스위트가 구조적으로 못 잡는다
    (`data_deletion.py` 독스트링). 이 테스트 파일이 CI에 없으면 그 클래스는 **무방비**다.

    red-proof: ci.yml 에서 'Real-PostgreSQL FK gate' 스텝을 지우면 FAIL.
    """
    step = _find_step(ci_data, "api-test", "tests/test_pg_fk_erasure.py")
    assert step is not None, (
        "ci.yml 에 실PG FK 게이트 스텝이 없다 — 아동 PII 파기 회귀가 CI에서 무방비"
    )


def test_real_pg_fk_gate_has_database_url_env(ci_data):
    """게이트 스텝에 `E2E_PG_DATABASE_URL` 이 주입돼 있다.

    이 변수가 없으면 `tests/test_pg_fk_erasure.py` 는 **전건 skip 후 exit 0** 이다 —
    즉 게이트가 조용히 사라지고 CI는 green으로 보인다(이 저장소가 반복해서 당한 false-green).

    red-proof: 스텝의 env 에서 E2E_PG_DATABASE_URL 을 지우면 FAIL.
    """
    step = _find_step(ci_data, "api-test", "tests/test_pg_fk_erasure.py")
    assert step is not None
    env = step.get("env") or {}
    assert "E2E_PG_DATABASE_URL" in env, (
        "E2E_PG_DATABASE_URL 미주입 — 게이트가 전건 skip으로 조용히 무력화된다"
    )
    assert str(env["E2E_PG_DATABASE_URL"]).startswith("postgresql+asyncpg://"), env


def test_real_pg_fk_gate_runs_before_create_all_gate(ci_data):
    """FK 게이트가 C1 워커 게이트보다 **앞선다**.

    FK 게이트는 `alembic upgrade head` 로 스키마를 세우고, C1 게이트는 `create_all` 을 쓴다.
    순서가 뒤집히면 alembic 이 이미 존재하는 테이블을 만들려다 실패한다.
    """
    names = [(s.get("name") or "") + (s.get("run") or "") for s in _steps(ci_data, "api-test")]
    fk_at = next(i for i, n in enumerate(names) if "test_pg_fk_erasure.py" in n)
    c1_at = next(i for i, n in enumerate(names) if "test_celery_worker_pg.py" in n)
    assert fk_at < c1_at, "실PG FK 게이트는 C1(create_all) 게이트보다 먼저 돌아야 한다"
