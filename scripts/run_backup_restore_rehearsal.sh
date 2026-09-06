#!/bin/bash
# Disposable synthetic PostgreSQL and private-S3 backup/restore rehearsal.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESTORE_PYTHON="${RESTORE_PYTHON:-$ROOT_DIR/apps/api/venv/bin/python}"
if [[ ! -x "$RESTORE_PYTHON" ]] && ! command -v "$RESTORE_PYTHON" >/dev/null 2>&1; then
  RESTORE_PYTHON="python3"
fi
exec "$RESTORE_PYTHON" "$ROOT_DIR/scripts/run_backup_restore_rehearsal.py" "$@"
