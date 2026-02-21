#!/bin/bash
# =============================================================================
# build-acceptance-artifacts.sh
# Collect acceptance artifacts for phase review / handoff.
# =============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT_DIR="$ROOT_DIR/docs/acceptance/$STAMP"
API_PYTHON="$ROOT_DIR/apps/api/venv/bin/python"

SKIP_ANDROID_BUILD=false
SKIP_IOS_BUILD=false
INCLUDE_PHASE_GATE=true

for arg in "$@"; do
  case "$arg" in
    --skip-android-build)
      SKIP_ANDROID_BUILD=true
      ;;
    --skip-ios-build)
      SKIP_IOS_BUILD=true
      ;;
    --skip-phase-gate)
      INCLUDE_PHASE_GATE=false
      ;;
    *)
      echo "Unknown option: $arg"
      echo "Usage: $0 [--skip-android-build] [--skip-ios-build] [--skip-phase-gate]"
      exit 1
      ;;
  esac
done

if [ ! -x "$API_PYTHON" ]; then
  API_PYTHON="python3"
fi

mkdir -p "$OUT_DIR"

echo "[1/7] Snapshot git status"
(
  cd "$ROOT_DIR"
  git status --short > "$OUT_DIR/git-status-short.txt"
  git status > "$OUT_DIR/git-status.txt"
  git diff --name-only > "$OUT_DIR/changed-files.txt"
)

echo "[2/7] API tests"
(
  cd "$ROOT_DIR"
  "$API_PYTHON" -m pytest apps/api/tests -q > "$OUT_DIR/api-tests.log" 2>&1
)

echo "[3/7] Flutter analyze"
(
  cd "$ROOT_DIR/apps/mobile"
  flutter pub get > "$OUT_DIR/flutter-pub-get.log" 2>&1
  flutter analyze > "$OUT_DIR/flutter-analyze.log" 2>&1
)

echo "[4/7] Flutter tests"
(
  cd "$ROOT_DIR/apps/mobile"
  flutter test > "$OUT_DIR/flutter-test.log" 2>&1
)

if [ "$SKIP_ANDROID_BUILD" = false ]; then
  echo "[5/7] Android debug build"
  (
    cd "$ROOT_DIR/apps/mobile"
    flutter build apk --debug > "$OUT_DIR/android-build.log" 2>&1
  )
else
  echo "[5/7] Android debug build skipped"
  echo "skipped by option --skip-android-build" > "$OUT_DIR/android-build.log"
fi

if [ "$SKIP_IOS_BUILD" = false ]; then
  echo "[6/7] iOS no-codesign build"
  (
    cd "$ROOT_DIR/apps/mobile"
    flutter build ios --no-codesign > "$OUT_DIR/ios-build.log" 2>&1
  )
else
  echo "[6/7] iOS no-codesign build skipped"
  echo "skipped by option --skip-ios-build" > "$OUT_DIR/ios-build.log"
fi

if [ "$INCLUDE_PHASE_GATE" = true ]; then
  echo "[7/7] Phase gate"
  (
    cd "$ROOT_DIR"
    ./scripts/phase-gate.sh > "$OUT_DIR/phase-gate.log" 2>&1
  )
else
  echo "[7/7] Phase gate skipped"
  echo "skipped by option --skip-phase-gate" > "$OUT_DIR/phase-gate.log"
fi

API_PASSED="$(grep -Eo '[0-9]+ passed' "$OUT_DIR/api-tests.log" | tail -n1 || true)"

cat > "$OUT_DIR/README.md" <<REPORT
# Acceptance Artifacts

- Generated at: $STAMP
- Source repo: $ROOT_DIR
- API test runner: $API_PYTHON
- Android build skipped: $SKIP_ANDROID_BUILD
- iOS build skipped: $SKIP_IOS_BUILD
- Phase gate included: $INCLUDE_PHASE_GATE
- API result summary: ${API_PASSED:-unknown}

## Included files
- git-status-short.txt
- git-status.txt
- changed-files.txt
- api-tests.log
- flutter-pub-get.log
- flutter-analyze.log
- flutter-test.log
- android-build.log
- ios-build.log
- phase-gate.log

All commands completed successfully when this bundle was generated.
REPORT

echo "✅ Acceptance artifacts generated: $OUT_DIR"
