#!/bin/bash
# Real PostgreSQL/Redis/Celery/private-S3 integration with deterministic AI providers.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_PYTHON="${RUNTIME_PYTHON:-$ROOT_DIR/apps/api/venv/bin/python}"
if [[ ! -x "$RUNTIME_PYTHON" ]] && ! command -v "$RUNTIME_PYTHON" >/dev/null 2>&1; then
  RUNTIME_PYTHON="python3"
fi
exec "$RUNTIME_PYTHON" "$ROOT_DIR/scripts/run_runtime_e2e.py" "$@"
