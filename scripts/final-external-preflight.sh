#!/bin/bash
# Configuration-only release gate; never calls providers or stores.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFLIGHT_PYTHON="$ROOT_DIR/apps/api/venv/bin/python"
if [[ ! -x "$PREFLIGHT_PYTHON" ]]; then
  PREFLIGHT_PYTHON="python3"
fi
exec "$PREFLIGHT_PYTHON" "$ROOT_DIR/scripts/final_external_preflight.py" "$@"
