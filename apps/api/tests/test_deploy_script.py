"""deploy.sh 배포 순서/롤백/정리 가드 (W6: M26).

셸 실행 없이 정적 분석으로 배포 시퀀스 불변식을 잠근다 — migrate-before-up(구 스키마로
신 코드 서빙 제거), compose down 부재(다운타임 제거), health 실패 시 롤백, cleanup의
named volume prune 부재(데이터 전손 방지). subprocess는 `bash -n` 구문 검사에만 사용.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_SH = REPO_ROOT / "scripts/deploy.sh"


def _deploy_case_block(text: str) -> str:
    # `  deploy)` ~ 다음 `    ;;` 사이
    m = re.search(r"\n  deploy\)\n(.*?)\n    ;;", text, re.DOTALL)
    assert m, "deploy) case 블록을 찾을 수 없음"
    return m.group(1)


def _cleanup_body(text: str) -> str:
    m = re.search(r"\ncleanup\(\) \{\n(.*?)\n\}", text, re.DOTALL)
    assert m, "cleanup() 함수를 찾을 수 없음"
    return m.group(1)


def test_deploy_runs_migrations_before_start():
    block = _deploy_case_block(DEPLOY_SH.read_text())
    assert "run_migrations" in block and "start_services" in block
    assert block.index("run_migrations") < block.index("start_services"), (
        "마이그레이션이 서비스 기동보다 먼저여야 함(구 스키마로 신 코드 서빙 방지)"
    )


def test_deploy_does_not_compose_down_before_up():
    block = _deploy_case_block(DEPLOY_SH.read_text())
    assert "stop_services" not in block, "deploy 경로에 compose down(전면 다운타임)이 없어야 함"


def test_cleanup_does_not_prune_volumes():
    body = _cleanup_body(DEPLOY_SH.read_text())
    assert "docker volume prune" not in body, "named volume(postgres/redis/minio) 데이터 전손 방지"


def test_deploy_has_rollback_on_health_failure():
    text = DEPLOY_SH.read_text()
    block = _deploy_case_block(text)
    assert "rollback" in block, "health 실패 시 롤백 경로가 있어야 함"
    assert re.search(r"^rollback\(\) \{", text, re.MULTILINE), "rollback() 함수 정의가 있어야 함"


def test_bash_syntax_valid():
    result = subprocess.run(
        ["bash", "-n", str(DEPLOY_SH)], capture_output=True, text=True
    )
    assert result.returncode == 0, f"deploy.sh 구문 오류:\n{result.stderr}"


def test_health_check_waits_for_service_to_listen():
    """#5: up -d 직후 무대기 1회 curl은 사실상 항상 실패해 정상 릴리스를 자동 롤백시킨다.

    compose up -d는 컨테이너 '기동 시작'에서 리턴하고 앱 리슨을 기다리지 않으며, api 재생성
    중 nginx는 502를 반환한다. M26이 migrate를 앞으로 옮기며 우연한 암묵 대기가 사라졌고,
    동시에 배선된 자동 롤백 때문에 실패의 결과가 치명적으로 커졌다.
    """
    text = DEPLOY_SH.read_text()
    assert "wait_for_liveness" in text, "부팅 대기 루프가 있어야 함"
    # health_check가 대기 루프를 실제로 호출하는지(정의만 하고 미사용 방지).
    m = re.search(r"\nhealth_check\(\) \{\n(.*?)\n\}", text, re.DOTALL)
    assert m, "health_check 함수를 찾을 수 없음"
    assert "wait_for_liveness" in m.group(1), "health_check가 대기 루프를 호출해야 함"
    # 롤백 경로도 같은 health_check를 재사용하므로 대기가 함께 적용된다.
    rb = re.search(r"\nrollback\(\) \{\n(.*?)\n\}", text, re.DOTALL)
    assert rb and "health_check" in rb.group(1)
