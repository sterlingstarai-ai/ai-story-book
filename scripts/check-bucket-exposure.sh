#!/usr/bin/env bash
# Read-only: verify a known object exists, signed access succeeds, and anonymous access fails.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-$ROOT_DIR/apps/api/venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then PYTHON_BIN=python3; fi
exec "$PYTHON_BIN" "$ROOT_DIR/scripts/check_bucket_exposure.py" "$@"
