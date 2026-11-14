# 내가 만드는 동화 아이콘 — 빌드 7

## 변경과 현재 결과

사용자의 요청은 책을 읽는 앱이라는 표현보다 **아이가 자신의 동화를 만든다는 점**이 아이콘에서 먼저 드러나도록 바꾸고 출시하는 것이다. 열린 책에서 주인공이 된 아이가 큰 금색 연필로 이야기를 쓰는 원본을 제작했다. 짙은 청록 배경·코랄색 옷·아이 얼굴·연필·책을 하나의 실루엣으로 묶었다. 실제 아이 사진이나 앱의 AI 제공자 키는 사용하지 않았다. [원본·전체 생성 프롬프트·재생성 명령](../branding/CREATOR_ICON_2026-11-14.md)

| 대상 | 직접 확인한 현재 상태 |
|---|---|
| Apple | 버전 1.0에 1.0.0(7)을 지정해 최종 제출. 2026-11-14 15:33 KST 접수 화면과 후속 조회에서 `심사 대기 중`, `1개의 항목 제출됨`, 제출 초안 0개 |
| Apple 출시 방식 | 이전 6의 `개발자 출시 대기 중` 상태에서 출시를 취소한 뒤 새 7로 교체. `자동으로 버전 출시` 선택·저장·재조회 확인. 새 심사 승인 후 자동 출시이며 아직 일반 공개 완료는 아님 |
| TestFlight | Apple 처리 완료·기존 수출 분류 저장·기존 `내부 베타` 그룹에 7 배정 확인. 새 테스터 초대나 새 접근 권한은 만들지 않음 |
| Google Play | Alpha `1.0.0 (7) - 내가 만드는 동화`와 한국어 앱 아이콘 2건 최종 전송. 자동 사전 검사 종료 후 `변경사항을 검토 중입니다` 확인 |
| Google 게시 범위 | 기존 관리형 게시 OFF 유지. 승인 후 Alpha에 반영되며 프로덕션은 비활성. 사용자 담당 테스터 모집·프로덕션 요건은 이번 작업에서 변경하지 않음 |
| 스토어 그림 신고 | Google의 AI 생성/수정 자산 표시를 이번 새 앱 아이콘에만 저장. 이전 변경 없는 이미지의 제작 경로는 추정하지 않음 |

기존 연락처·심사자 접근 안내·지원 및 정책 주소·앱 설명과 스크린샷은 보존했다. Apple 검토 메모에는 빌드 7이 아이콘 변경이며 기능·데이터 처리·베타 한도는 같다는 안내만 앞에 덧붙였다. 표준 암호화를 사용하는 기존 Kakao SDK가 그대로이므로 이전 수출 분류와 프랑스 제외 답변을 유지했다. 신규 법적 계약이나 계정 생성은 없었다.

## 소스와 자산

- 기준 커밋: `ba5dcabed315a33f2189bd19dac854452587ee83`.
- `pubspec.yaml` 버전: `1.0.0+7`. 패키지 의존성과 잠금 파일, Dart 기능 코드는 변경하지 않았다.
- 불투명 마스터 1254×1254 SHA-256: `a5a71acef2361e49144f2d2f699e45cac232cb0a2c91c1093b9877b2b938abc5`.
- Android 투명 전경 SHA-256: `01e532b0a66e29b287f5a5e55293838f18b29d736c8d27c9489b4c9d14044539`. 배경 `#102E32`, inset 16.
- Play 자산은 같은 마스터의 불투명 512×512 축소본이다. 새 원본은 내장 이미지 생성으로 제작하고 크기별 출력은 기존 `flutter_launcher_icons 0.14.4`로 생성했다.
- iOS 카탈로그 25개 항목·PNG 21개가 올바른 크기이며 모두 불투명하다. Android 일반 아이콘 5개 밀도와 적응형 전경 5개 밀도가 모두 변경됐다. [자산 검사](../acceptance/2026-11-14-creator-icon/native-source-verification.json)

## 빌드와 검증

| 패키지 | 검증 결과 |
|---|---|
| iOS IPA 1.0.0(7) | 38,172,155바이트, SHA-256 `21576bec40e2516b65d605dd234104ba1e496a16c666c61a867982da7a81bd6d`. 기존 Apple Distribution 서명·배포 프로파일, 중첩 서명, 디버그 권한 OFF, 기기 바이너리 25개와 필수 SDK 개인정보 매니페스트 검사 통과. 패키지의 아이콘 120px와 고정 소스 픽셀 차이 0 |
| Android AAB 1.0.0(7) | 63,225,779바이트, SHA-256 `24cb3e6bb186e5aa2addaa8685f45aac35b8929e26de14c5d294a1d03cfd2ee0`. 기존 업로드 인증서 일치, JAR 서명·bundletool 통과, 네이티브 9개 모든 LOAD 구간 16 KB 이상 정렬. 패키지의 마스터·전경·Play 자산 해시와 밀도별 표시 픽셀·알파 일치 |

양쪽은 각각 397개 소스 파일의 깨끗한 사본으로 만들고 빌드 전후 현재 소스와 대조했다. 두 영수증의 소스 manifest 해시는 경로·직렬화 방식이 달라 동일 소스 집합이어도 다르며 개별 파일 대조를 통과했다. Android AAPT가 완전히 투명한 픽셀의 숨은 RGB를 정규화한 차이는 기록하되 알파·보이는 RGB·검정/흰색 위 합성 결과는 모두 같다.

첫 Android 작업 사본의 `--no-pub` 빌드는 기존 생성 registrant의 개발용 플러그인 참조로 실패했다. 생성 파일을 수동 수정하지 않고 깨끗한 사본에서 offline pub 복원과 표준 빌드를 실행해 성공했다. 첫 작업 사본 캐시 문제의 전체 원인을 재현했다고 주장하지 않는다. 기존 서명 파일은 보존했으며 소유한 임시 서명 심볼릭 링크는 정리했다.

iOS 업로드는 같은 검증 archive를 기존 Xcode 로그인으로 내보냈고 Apple의 `Upload succeeded`와 종료 코드 0을 확인했다. 내보내기가 archive 최상단 `Info.plist`의 배포 메타데이터만 갱신한 것을 확인했으며 앱 payload·서명·로컬 IPA는 그대로다. 제공자가 받은 바이트의 해시를 독립 다운로드로 재검증한 결과는 아니다. 기존 `objective_c` dSYM 비차단 경고는 업로드 기록에 보존했다. 이후 제공자 화면에서 실제 빌드 7 처리·배정·최종 심사 접수를 확인했다.

## 증거와 남은 범위

- [iOS 패키지 검사](../acceptance/2026-11-14-creator-icon-ios7/verification.json)와 [동일 앱 payload 업로드 확인](../acceptance/2026-11-14-creator-icon-ios7/upload-binding-verification.json).
- [Android 패키지 검사](../acceptance/2026-11-14-creator-icon-android7/verification.json), [임시 서명 링크 정리](../acceptance/2026-11-14-creator-icon-android7/signing-links-final-cleanup.json).
- [Apple 처리·TestFlight 배정](../acceptance/2026-11-14-creator-icon/apple7-ready-testflight.json), [Google 최종 검토 화면](../acceptance/2026-11-14-creator-icon/play7-after-submit.jpg), [통합 최종 상태](../acceptance/2026-11-14-creator-icon/verification.json).
- [공개 경로 읽기 검사](../acceptance/2026-11-14-creator-icon/public-release-readonly.json): 15:12 KST `/health/ready`·개인정보처리방침·이용약관 HTTPS 200. 이는 새 동화나 장기 가용성 검사가 아니다.

패키지 생성 당시 영수증의 `NOT_UPLOADED`·`AWAITING_APPLE_PROCESSING`은 그 시점의 이력이다. 최종 스토어 상태는 위 통합 영수증과 접수 화면을 따른다. 바이너리·archive·스크린샷·검증 영수증은 기존 규칙대로 로컬 `docs/acceptance/`에 보존하며 Git에는 원본·생성 아이콘과 이 설명을 기록한다. 비공개 심사 인증이 화면에 포함된 원본 캡처는 공개하거나 추적 파일에 넣지 않는다.

이번 변경에 새 동화·그림·음원 API 요청, 백엔드 배포, 정책 완화, 보호자 메일 활성화 또는 추가 결제는 없다. 신규 이미지 제작은 내장 도구로 수행했다. 새 실기기 청취를 실행하지 않았으며 기존 기기 미완료 항목을 통과로 바꾸지 않는다. Apple 심사 승인과 실제 App Store 공개, Google Alpha 승인·게시 및 별도 프로덕션 요건은 외부 후속이다.

공식 참고: [Apple 아이콘 변경](https://developer.apple.com/help/app-store-connect/manage-app-information/add-an-app-icon/), [Apple 제출 철회](https://developer.apple.com/help/app-store-connect/manage-submissions-to-app-review/remove-a-submission-from-review/), [Google AI 시각 자산 표시](https://support.google.com/googleplay/android-developer/answer/17262077?hl=ko).
