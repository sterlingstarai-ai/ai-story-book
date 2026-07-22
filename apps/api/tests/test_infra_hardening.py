"""인프라 저위험 하드닝 가드 (W6: L15).

prod api healthcheck가 의존성 인지형 /health/ready를 쓰는지, .dockerignore가 실 .env를
이미지에서 제외하는지, minio 포트가 localhost 바인딩인지, nginx body 한도가 앱 사진 한도보다
큰지, dev/prod postgres 메이저가 일치하는지 — 구조 수준에서 잠근다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[3]
PROD_COMPOSE = REPO_ROOT / "infra/docker-compose.prod.yml"
DEV_COMPOSE = REPO_ROOT / "infra/docker-compose.yml"
DOCKERIGNORE = REPO_ROOT / "apps/api/.dockerignore"
NGINX_CONF = REPO_ROOT / "infra/nginx/nginx.conf"

# 앱 캐릭터 사진 한도 (characters.py: _MAX_CHARACTER_IMAGE_BYTES = 10 * 1024 * 1024)
APP_IMAGE_LIMIT_MB = 10


@pytest.fixture(scope="module")
def prod() -> dict:
    return yaml.safe_load(PROD_COMPOSE.read_text())


def test_prod_api_healthcheck_uses_ready_probe(prod):
    hc = prod["services"]["api"].get("healthcheck")
    assert hc, "api 서비스에 healthcheck 오버라이드가 있어야 함(이미지 기본 /health는 무조건 200)"
    test = hc["test"]
    joined = " ".join(test) if isinstance(test, list) else str(test)
    assert "/health/ready" in joined, "healthcheck가 의존성 인지형 /health/ready를 대상으로 해야 함"


def test_dockerignore_excludes_env():
    lines = [ln.strip() for ln in DOCKERIGNORE.read_text().splitlines()]
    assert ".env" in lines, "실 .env가 이미지 레이어에 포함되지 않도록 .dockerignore에 있어야 함"
    assert "!.env.example" in lines, ".env.example은 예제로 유지(negation)"


def test_minio_ports_bound_to_localhost(prod):
    minio = prod["services"].get("minio")
    assert minio, "minio 서비스가 있어야 함"
    for port in minio.get("ports", []):
        assert str(port).startswith("127.0.0.1:"), f"minio 포트가 localhost 바인딩이어야 함: {port}"


def test_nginx_body_size_exceeds_app_limit():
    m = re.search(r"client_max_body_size\s+(\d+)([MmKk])", NGINX_CONF.read_text())
    assert m, "client_max_body_size 지시어를 찾을 수 없음"
    value, unit = int(m.group(1)), m.group(2).upper()
    mb = value if unit == "M" else value / 1024
    assert mb > APP_IMAGE_LIMIT_MB, (
        f"nginx 한도({mb}MB)가 앱 사진 한도({APP_IMAGE_LIMIT_MB}MB)보다 커야 "
        "multipart 오버헤드 사진이 nginx 413이 아닌 앱 JSON으로 처리됨"
    )


def _postgres_major(compose_path: Path) -> int:
    m = re.search(r"image:\s*postgres:(\d+)", compose_path.read_text())
    assert m, f"{compose_path.name}에서 postgres 이미지 태그를 찾을 수 없음"
    return int(m.group(1))


def test_postgres_major_consistent_dev_and_prod():
    assert _postgres_major(DEV_COMPOSE) == _postgres_major(PROD_COMPOSE), (
        "dev/prod postgres 메이저 버전이 일치해야 함(엔진 드리프트 제거)"
    )
