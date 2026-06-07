# Flutter UI Preflight Checklist

배포 전 `CSS z-index / filter / SPA scroll` 체크를 이 저장소에 맞게 Flutter 관점으로 번역한 체크리스트입니다.

## 용어 매핑

- CSS `z-index` 충돌
  - Flutter의 `Stack`, `Positioned`, `showDialog`, `showModalBottomSheet`, `Overlay` 겹침과 터치 차단 문제
- 누락 필터
  - `BackdropFilter`, `ImageFilter.blur`, `ColorFiltered`, `ShaderMask` 같은 시각 효과가 의도대로 적용되는지 확인
- SPA 스크롤
  - 리스트-상세-복귀, 바텀시트 내부 스크롤, 키보드가 열린 폼, CTA까지의 도달성 확인

## 자동 점검

- `./scripts/flutter-ui-preflight.sh`
- `apps/mobile/test/ui_preflight_test.dart`

## 수동 릴리스 체크

- Overlay layering
  - `ViewerScreen`의 상단 컨트롤, 경고 배너, 수면 모드 오버레이, 바텀시트, 스낵바가 서로 가리지 않는지
  - `LibraryScreen`의 카드 우상단 메뉴가 표지/칩 위에서 정상적으로 열리고 탭 가능한지
  - 화면 시간 잠금 오버레이가 실제로 탭을 막고, 해제 후 원래 화면이 정상 복귀하는지

- Bottom sheet scroll safety
  - `ViewerScreen` 옵션 시트와 공유 시트를 320x480 수준의 작은 화면에서 끝까지 스크롤할 수 있는지
  - 글자 크기 130% 이상에서도 마지막 액션 버튼이 잘리지 않는지
  - `CharactersScreen` 텍스트 입력 시트에서 키보드가 열린 상태로도 제출 버튼까지 도달 가능한지

- Scroll continuity
  - 서재에서 책을 열고 다시 돌아왔을 때 사용자가 보던 위치 감각이 깨지지 않는지
  - 크레딧 화면의 CTA가 실제로 플랜 섹션까지 스크롤시키는지
  - 긴 본문/학습 시트/부모 가이드 시트가 작은 화면에서 끝까지 탐색 가능한지

- Filter and blur
  - 현재 코드베이스는 blur/filter 위젯 사용이 거의 없으므로 기본적으로 정보성 체크만 수행
  - 추후 blur/filter를 도입하면 가독성, 대비, 성능 저하까지 함께 확인

- Web target
  - 현재 기본 배포 타깃은 모바일 앱이지만, `flutter build web`을 릴리스에 쓰는 경우 브라우저 뒤로가기/새로고침/스크롤 복원은 별도 확인

## 권장 실행 순서

1. `./scripts/phase-gate.sh`
2. `./scripts/flutter-ui-preflight.sh`
3. 필요 시 실제 디바이스에서 작은 화면 + 큰 글꼴 조합으로 수동 확인
