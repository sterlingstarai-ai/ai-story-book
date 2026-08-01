#!/bin/bash
# =============================================================================
# run_live_e2e.sh - 라이브 백엔드 E2E 여정을 오프라인(SQLite+mock)으로 구동
# =============================================================================
# TESTING=true(in-process pytest)는 생성 백그라운드 태스크를 건너뛰므로, 전체 생성
# 파이프라인(create→done)을 검증하려면 TESTING=false로 실서버를 띄워야 한다.
# 이 스크립트는 스키마 생성 → uvicorn 기동(mock providers·SQLite) → e2e_journey.py 실행
# → 서버 종료까지 자급자족으로 수행한다(키·Postgres·Redis·S3 불필요).
#
# 사용: ./scripts/run_live_e2e.sh
# 환경: PYTHON(기본 python), PORT(기본 8077)
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/apps/api"

PYTHON="${PYTHON:-python}"
PORT="${PORT:-8077}"
DB_FILE="live_e2e.db"

export TESTING=false USE_CELERY=false \
  LLM_PROVIDER=mock IMAGE_PROVIDER=mock TTS_PROVIDER=mock \
  DATABASE_URL="sqlite+aiosqlite:///./${DB_FILE}" \
  S3_ENDPOINT="http://localhost:9000" S3_ACCESS_KEY=test S3_SECRET_KEY=test S3_BUCKET=storybook \
  RATE_LIMIT_REQUESTS="${RATE_LIMIT_REQUESTS:-100000}"
# CI에는 Redis가 떠 있어 rate limiter가 활성(로컬은 fail-open)이므로, 단일 여정이 분당
# 한도(기본 10)에 걸리지 않도록 한도를 크게 둔다. 레이트리밋 자체는 단위테스트가 검증.

rm -f "$DB_FILE"

echo "==> 스키마 생성(SQLite)"
"$PYTHON" - <<'PY'
import asyncio
from src.core.database import async_engine
from src.models.db import Base


async def main():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await async_engine.dispose()


asyncio.run(main())
print("schema ready")
PY

echo "==> 서버 기동(TESTING=false, mock providers, port=$PORT)"
nohup "$PYTHON" -m uvicorn src.main:app --host 127.0.0.1 --port "$PORT" \
  > "${TMPDIR:-/tmp}/live_e2e_server.log" 2>&1 &
SVPID=$!
cleanup() {
  kill "$SVPID" 2>/dev/null || true
  rm -f "$DB_FILE"
}
trap cleanup EXIT

for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:${PORT}/health/live" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "==> e2e_journey 실행"
"$PYTHON" scripts/e2e_journey.py "http://127.0.0.1:${PORT}" || {
  echo "--- server log ---"
  cat "${TMPDIR:-/tmp}/live_e2e_server.log" || true
  exit 1
}
