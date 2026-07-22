"""배포 설정 배관 가드 (W6: H22).

prod compose가 앱 config가 요구하는 환경변수를 컨테이너로 실제 전파하는지, .env.example이
운영 필수 IAP readiness 변수를 선언하고 죽은 변수를 남기지 않는지, check-env.sh가 IAP를
production 필수로 강제하는지 — 배포 배관 드리프트(readiness 503 반쪽 장애·전량 이미지 실패)를
구조 수준에서 잠근다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[3]
PROD_COMPOSE = REPO_ROOT / "infra/docker-compose.prod.yml"
INFRA_ENV_EXAMPLE = REPO_ROOT / "infra/.env.example"
CHECK_ENV = REPO_ROOT / "scripts/check-env.sh"


def _env_keys(service: dict) -> set[str]:
    keys = set()
    for item in service.get("environment", []) or []:
        # `KEY=${VALUE}` 형태 — '=' 앞이 키
        keys.add(item.split("=", 1)[0])
    return keys


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(PROD_COMPOSE.read_text())


def test_prod_compose_passes_image_model_and_stt_and_pod_and_admin(compose):
    services = compose["services"]
    api_keys = _env_keys(services["api"])
    worker_keys = _env_keys(services["worker"])

    required_api = {
        "IMAGE_MODEL",
        "STT_PROVIDER",
        "STT_API_KEY",
        "GOOGLE_STT_API_KEY",
        "POD_MODE",
        "PRINTFUL_API_KEY",
        "ADMIN_API_KEY",
        "SHARE_BASE_URL",
    }
    missing_api = required_api - api_keys
    assert not missing_api, f"api environment 누락: {sorted(missing_api)}"

    # worker가 실제 이미지 생성을 수행 — IMAGE_MODEL 필수. STT/POD도 미러.
    assert "IMAGE_MODEL" in worker_keys, "worker environment에 IMAGE_MODEL 누락"
    assert "STT_PROVIDER" in worker_keys
    assert "POD_MODE" in worker_keys


def test_stt_provider_has_no_mock_default():
    # MI3/H1: compose가 STT_PROVIDER에 :-mock 폴백을 재도입하면 안 됨(fail-open 방지).
    text = PROD_COMPOSE.read_text()
    assert "STT_PROVIDER=${STT_PROVIDER:-mock}" not in text
    assert "TTS_PROVIDER=${TTS_PROVIDER:-mock}" not in text


def test_infra_env_example_declares_iap_readiness_vars():
    text = INFRA_ENV_EXAMPLE.read_text()
    for var in (
        "APPLE_IAP_SHARED_SECRET",
        "GOOGLE_PLAY_PACKAGE_NAME",
        "IAP_WEBHOOK_SECRET",
        "IAP_VERIFICATION_MODE",
    ):
        assert var in text, f"infra/.env.example에 {var} 선언 누락"


def test_infra_env_example_has_no_dead_vars():
    text = INFRA_ENV_EXAMPLE.read_text()
    assert not re.search(r"^SECRET_KEY=", text, re.MULTILINE), "config에 없는 죽은 SECRET_KEY"
    # bare RATE_LIMIT= (RATE_LIMIT_REQUESTS/WINDOW 아님)
    assert not re.search(r"^RATE_LIMIT=", text, re.MULTILINE), "죽은 RATE_LIMIT= (실명 RATE_LIMIT_REQUESTS)"
    assert "RATE_LIMIT_REQUESTS" in text, "실제 config 필드 RATE_LIMIT_REQUESTS가 있어야 함"


def test_check_env_requires_iap_vars():
    text = CHECK_ENV.read_text()
    # 닫는 괄호는 줄머리 ')' — 주석 안의 괄호에 조기 매칭되지 않도록 고정.
    m = re.search(r"PRODUCTION_REQUIRED_VARS=\(\n(.*?)\n\)", text, re.DOTALL)
    assert m, "PRODUCTION_REQUIRED_VARS 블록을 찾을 수 없음"
    block = m.group(1)
    assert "IAP_VERIFICATION_MODE" in block, "IAP_VERIFICATION_MODE가 production 필수여야 함"
    assert "IAP_WEBHOOK_SECRET" in block, "IAP_WEBHOOK_SECRET이 production 필수여야 함"
