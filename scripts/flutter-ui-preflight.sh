#!/bin/bash
# =============================================================================
# flutter-ui-preflight.sh
# Focused Flutter UI/UX checks for overlay layering and scroll safety.
# =============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOBILE_DIR="$ROOT_DIR/apps/mobile"
CHECKLIST_PATH="$ROOT_DIR/docs/UI_PREFLIGHT_CHECKLIST.md"

count_dart_matches() {
  local pattern="$1"
  shift
  local matches
  matches="$(rg -n --glob '*.dart' "$pattern" "$@" 2>/dev/null || true)"
  if [ -z "$matches" ]; then
    echo "0"
    return
  fi
  printf '%s\n' "$matches" | wc -l | tr -d ' '
}

echo "==> [UI 1/3] Focused UI preflight tests"
(
  cd "$MOBILE_DIR"
  flutter test test/ui_preflight_test.dart
)

echo "==> [UI 2/3] Overlay and scroll inventory"
bottom_sheet_count="$(count_dart_matches 'showModalBottomSheet' "$MOBILE_DIR/lib")"
dialog_count="$(count_dart_matches 'showDialog' "$MOBILE_DIR/lib")"
stack_count="$(count_dart_matches 'Stack\(' "$MOBILE_DIR/lib")"
ignore_pointer_count="$(count_dart_matches 'IgnorePointer\(' "$MOBILE_DIR/lib")"
filter_count="$(count_dart_matches 'BackdropFilter|ImageFilter\.blur|ColorFiltered|ShaderMask' "$MOBILE_DIR/lib")"
scroll_controller_count="$(count_dart_matches 'ScrollController\(' "$MOBILE_DIR/lib")"
scroll_restoration_count="$(count_dart_matches 'PageStorageKey|RestorationMixin|restorationId|restorationScopeId' "$MOBILE_DIR/lib")"

echo "  Bottom sheets: $bottom_sheet_count"
echo "  Dialogs: $dialog_count"
echo "  Stack-based overlays: $stack_count"
echo "  IgnorePointer overlays: $ignore_pointer_count"
echo "  Filter/blur widgets: $filter_count"
echo "  Scroll controllers: $scroll_controller_count"
echo "  Scroll restoration primitives: $scroll_restoration_count"

echo ""
echo "  Bottom sheet locations:"
rg -n "showModalBottomSheet" "$MOBILE_DIR/lib" | sed 's#^#   - #'

if [ "$filter_count" -eq 0 ]; then
  echo ""
  echo "  Note: no blur/filter widgets are currently in use, so filter-specific regressions are informational only."
fi

if [ "$scroll_controller_count" -gt 0 ] && [ "$scroll_restoration_count" -eq 0 ]; then
  echo ""
  echo "  Note: explicit scroll restoration primitives are not in use yet."
  echo "  Keep the manual list-detail-return scroll check in the release checklist."
fi

if [ ! -f "$CHECKLIST_PATH" ]; then
  echo "❌ Missing checklist: $CHECKLIST_PATH"
  exit 1
fi

echo ""
echo "==> [UI 3/3] Manual release checklist"
sed -n '1,220p' "$CHECKLIST_PATH"

echo ""
echo "✅ Flutter UI preflight checks passed"
