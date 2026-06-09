#!/bin/bash
# =============================================================================
# run_integration.sh - Flutter 통합 E2E 실행
# =============================================================================
# integration_test는 *디바이스/시뮬레이터*가 필요하다(헤드리스 widget test와 다름).
# 로컬: macOS 데스크톱이 가장 빠름. CI에서 돌리려면 Android 에뮬레이터 잡이 필요.
#
# 사용:
#   ./scripts/run_integration.sh                # -d macos
#   ./scripts/run_integration.sh chrome         # 웹
#   ./scripts/run_integration.sh "emulator-5554"
#
# flutter_driver(실기기 리포팅)로 돌리려면:
#   cd apps/mobile && flutter drive \
#     --driver=test_driver/integration_test.dart \
#     --target=integration_test/app_flow_test.dart -d <device>
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEVICE="${1:-macos}"

cd "$ROOT_DIR/apps/mobile"
echo "==> 통합 E2E (device=$DEVICE)"
flutter test integration_test/ -d "$DEVICE"
