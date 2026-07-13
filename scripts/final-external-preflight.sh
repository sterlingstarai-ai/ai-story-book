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

echo "==> Checking fail-closed security settings"
# IAP 영수증 검증은 strict(스토어 실검증 필수)여야 위조 영수증이 크레딧·구독을 발급받지
# 못한다. local/hybrid는 무검증 fail-open 경로가 있으므로 출시 전 차단.
if [[ "${IAP_VERIFICATION_MODE:-}" != "strict" ]]; then
  missing+=("IAP_VERIFICATION_MODE=strict (got '${IAP_VERIFICATION_MODE:-unset}')")
fi
# 웹훅 시크릿 미설정 시 무인증 상태변조(구독 강등·크레딧 클로백)가 가능.
require_var "IAP_WEBHOOK_SECRET"
# /v1/credits/add 관리자 키. 미설정 시 라우트가 거부되지만 명시 설정을 강제.
require_var "ADMIN_API_KEY"
# CORS 미설정 시 브라우저 클라이언트가 동작하지 않음(공백=전 origin 거부).
require_var "CORS_ORIGINS"

echo "==> Checking required mobile dart-defines"
require_var "KAKAO_NATIVE_APP_KEY"
# PROD_API_URL 미설정 시 릴리스 빌드는 실행 중 StateError를 던진다(env_config.dart).
require_var "PROD_API_URL"
# 광고 제거됨 — AdMob 값은 더 이상 필수 아님(전략 변경 반영).

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
  --dart-define=PROD_API_URL=\$PROD_API_URL \\
  --dart-define=KAKAO_NATIVE_APP_KEY=\$KAKAO_NATIVE_APP_KEY
EOF
