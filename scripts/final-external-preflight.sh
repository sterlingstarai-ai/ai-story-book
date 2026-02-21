#!/bin/bash
# =============================================================================
# final-external-preflight.sh
# Check required external-integration keys before final sandbox/store validation.
# =============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

missing=()

require_var() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    missing+=("$name")
  fi
}

require_any_google_auth() {
  if [[ -n "${GOOGLE_PLAY_ACCESS_TOKEN:-}" ]]; then
    return
  fi
  if [[ -n "${GOOGLE_PLAY_SERVICE_ACCOUNT_JSON:-}" ]]; then
    return
  fi
  if [[ -n "${GOOGLE_PLAY_SERVICE_ACCOUNT_FILE:-}" && -f "${GOOGLE_PLAY_SERVICE_ACCOUNT_FILE}" ]]; then
    return
  fi
  missing+=("GOOGLE_PLAY_ACCESS_TOKEN or GOOGLE_PLAY_SERVICE_ACCOUNT_JSON or GOOGLE_PLAY_SERVICE_ACCOUNT_FILE")
}

echo "==> Checking required backend keys"
require_var "APPLE_IAP_SHARED_SECRET"
require_var "GOOGLE_PLAY_PACKAGE_NAME"
require_any_google_auth
require_var "PRINTFUL_API_KEY"
require_var "PRINTFUL_SYNC_VARIANT_ID"

echo "==> Checking required mobile dart-defines"
require_var "KAKAO_NATIVE_APP_KEY"
require_var "ADMOB_REWARDED_AD_UNIT_ANDROID"
require_var "ADMOB_REWARDED_AD_UNIT_IOS"

if [[ ${#missing[@]} -gt 0 ]]; then
  echo ""
  echo "❌ Missing required values:"
  for item in "${missing[@]}"; do
    echo " - $item"
  done
  echo ""
  echo "Set missing values, then rerun:"
  echo "  $ROOT_DIR/scripts/final-external-preflight.sh"
  exit 1
fi

echo ""
echo "✅ All required external values are present."
echo ""
echo "Recommended final validation commands:"
cat <<EOF
cd $ROOT_DIR
python3 -m pytest apps/api/tests/test_phase_new_endpoints.py -q
./scripts/phase-gate.sh

cd $ROOT_DIR/apps/mobile
flutter build apk --release \\
  --dart-define=KAKAO_NATIVE_APP_KEY=\$KAKAO_NATIVE_APP_KEY \\
  --dart-define=ADMOB_REWARDED_AD_UNIT_ANDROID=\$ADMOB_REWARDED_AD_UNIT_ANDROID \\
  --dart-define=ADMOB_REWARDED_AD_UNIT_IOS=\$ADMOB_REWARDED_AD_UNIT_IOS
EOF
