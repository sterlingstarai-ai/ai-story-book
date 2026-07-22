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


def test_safety_step_not_soft_failed(ci_text):
    # safety 스텝이 `|| echo`로 종료코드를 0으로 삼키면 안 된다.
    assert "|| echo" not in ci_text, "safety/security 스텝이 실패를 성공으로 위장하면 안 됨"


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
