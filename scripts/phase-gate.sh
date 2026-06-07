#!/bin/bash
# =============================================================================
# phase-gate.sh - Phase gate quality checks for AI Story Book
# =============================================================================
# Usage:
#   ./scripts/phase-gate.sh
#   ./scripts/phase-gate.sh --with-mobile-build --with-ios-build --with-api-smoke
# =============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOBILE_DIR="$ROOT_DIR/apps/mobile"
API_DIR="$ROOT_DIR/apps/api"
API_PYTHON="$API_DIR/venv/bin/python"
API_SMOKE_BASE_URL="${API_SMOKE_BASE_URL:-http://localhost:8000}"

if [ ! -x "$API_PYTHON" ]; then
  API_PYTHON="python3"
fi

WITH_MOBILE_BUILD=false
WITH_IOS_BUILD=false
WITH_API_SMOKE=false

for arg in "$@"; do
  case "$arg" in
    --with-mobile-build)
      WITH_MOBILE_BUILD=true
      ;;
    --with-ios-build)
      WITH_IOS_BUILD=true
      ;;
    --with-api-smoke)
      WITH_API_SMOKE=true
      ;;
    *)
      echo "Unknown option: $arg"
      echo "Usage: ./scripts/phase-gate.sh [--with-mobile-build] [--with-ios-build] [--with-api-smoke]"
      exit 1
      ;;
  esac
done

echo "==> [1/6] API unit/integration tests"
(
  cd "$API_DIR"
  "$API_PYTHON" -m pytest tests -q
)

echo "==> [2/6] Mobile static analysis"
(
  cd "$MOBILE_DIR"
  flutter analyze
)

echo "==> [3/6] Mobile widget/unit tests"
(
  cd "$MOBILE_DIR"
  flutter test
)

echo "==> [4/6] Mobile UI preflight"
(
  cd "$ROOT_DIR"
  bash ./scripts/flutter-ui-preflight.sh
)

if [ "$WITH_MOBILE_BUILD" = true ]; then
  echo "==> [5/6] Mobile Android build (debug)"
  (
    cd "$MOBILE_DIR"
    flutter build apk --debug
  )
else
  echo "==> [5/6] Mobile Android build skipped (use --with-mobile-build)"
fi

if [ "$WITH_IOS_BUILD" = true ]; then
  echo "==> [6/6] Mobile iOS build (no codesign)"
  (
    cd "$MOBILE_DIR"
    flutter build ios --no-codesign
  )
else
  echo "==> [6/6] Mobile iOS build skipped (use --with-ios-build)"
fi

if [ "$WITH_API_SMOKE" = true ]; then
  echo "==> Additional: API smoke ($API_SMOKE_BASE_URL)"
  (
    cd "$ROOT_DIR"
    ./scripts/smoke.sh "$API_SMOKE_BASE_URL"
  )
else
  echo "==> Additional: API smoke skipped (use --with-api-smoke)"
fi

echo "✅ Phase gate checks passed"
