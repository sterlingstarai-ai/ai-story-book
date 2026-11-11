# iOS SDK 개인정보 매니페스트 누락 수정 — 2026-11-12

## 원인과 수정

사용자가 전달한 Apple `ITMS-91061` 알림은 AI 동화책 빌드 5의 `Frameworks/share_plus.framework/share_plus`에 개인정보 매니페스트가 없다는 내용이었다. 실제 빌드 5 IPA와 고정된 `share_plus 7.2.2` 배포 소스를 확인한 결과, SDK 자체에 `PrivacyInfo.xcprivacy`와 CocoaPods 리소스 번들 선언이 없었다. 단순 업로드 지연이나 앱 개인정보 신고의 체크 누락이 아니다. [사용자 알림](../acceptance/2026-11-12-ios-build6/itms-91061-user-notice.jpg)

이전 감사는 존재하는 매니페스트 16개의 내용만 파싱해 SDK별 필수 파일의 부재를 잡지 못했다. 존재 파일 수·추적 설정 확인을 필수 SDK 포함 검증으로 확대 해석한 누락이었다.

`share_plus`를 정식 배포 **10.1.4**로 고정하고 빌드를 **1.0.0(6)**으로 올렸다. Pub 잠금 파일은 공유 패키지와 플랫폼 인터페이스 두 종류만, iOS 잠금 파일은 해당 Pod 체크섬만 바뀌었다. Podfile·공유 UI·앱 정책은 변경하지 않았다. 현재 Flutter 3.38.7 및 Android 도구와 호환되는 기존 정적 공유 API를 유지해 불필요한 도구 변경을 피했다. SDK 매니페스트를 추측해 새로 작성하지 않았다.

설치된 10.1.4의 원본 매니페스트와 podspec을 공식 Git 태그의 두 파일과 대조해 **2/2 바이트 일치**를 확인했다. podspec이 `share_plus_privacy` 리소스 번들에 해당 매니페스트를 포함하며 Pods에도 실제 리소스 타깃이 생성됐다. `flutter pub get`·`pod install --no-repo-update`·정적 분석과 공유 보호자 게이트/리더 집중 회귀 **14개**를 통과했다. [소스 대조](../acceptance/2026-11-12-ios-build6/share-plus-source-verification.json) · [집중 검사](../acceptance/2026-11-12-ios-build6/share-regression.log)

## 재발 방지와 실제 패키지 확인

[`validate_ios_native_platforms.py`](../../scripts/validate_ios_native_platforms.py)에 현재 대상인 `share_plus`의 SDK 귀속·허용 위치 검사를 추가했다. 다른 SDK나 앱의 매니페스트가 있다는 이유만으로 통과하지 않는다. 파일의 plist 구조·기본 필드 형식·최상위 미지원 키·크기 제한도 확인한다. 관련 집중 검사 **61개**를 통과했고, 실제 기존 빌드 5는 `Missing SDK privacy manifest for share_plus`로 차단됐다. Apple 전체 스키마·사유 코드·모든 SDK의 정책 적합성을 대신 판정하는 검사는 아니다. [기존 5 차단](../acceptance/2026-11-12-ios-build6/rejected-build5-check.json)

캐시를 제외한 모바일 소스 395개의 깨끗한 사본에서 새 아카이브와 IPA를 만들었다. 기기용 네이티브 바이너리 25개, 개인정보 매니페스트 17개와 중첩 배포 서명을 확인했다. 새 IPA에는 아래 SDK 소유 매니페스트 한 개가 있고 정식 SDK 원본과 바이트가 일치했다.

```text
Payload/Runner.app/Frameworks/share_plus.framework/share_plus_privacy.bundle/PrivacyInfo.xcprivacy
```

검증한 로컬 IPA의 SHA-256은 `903e93400460220d7e02eee0102f05452187310b9733495c285867b285f6c659`다. 같은 검증된 아카이브에서 실행한 Xcode 업로드 명령은 종료 코드 0·업로드 성공·오류 줄 0을 확인했다. Apple로 전송된 재포장 바이트의 해시를 별도로 확인한 결과는 아니다. [주 검증](../acceptance/2026-11-12-ios-build6/verification.json) · [아카이브 앱 검사](../acceptance/2026-11-12-ios-build6/native-app-check.json) · [IPA 검사](../acceptance/2026-11-12-ios-build6/native-ipa-check.json) · [업로드 로그](../acceptance/2026-11-12-ios-build6/upload.log)

## 현재 스토어 상태와 남은 확인

기존 빌드 5는 심사에서 철회한 뒤 잘못된 바이너리 상태를 관측했다. 새 빌드 6은 Apple 처리·기존 수출 분류 저장과 내부 베타 그룹 배정을 마쳤다. 본 심사 후보도 6으로 교체해 **2026-11-12 03:55 KST** 재제출했고, 제출 상세에서 **1.0.0(6)·심사 대기 중**을 확인했다. 제출 ID는 `5f7eb2dd-47e9-48ab-b634-c502988fd18a`이며 iOS 수동 출시 설정을 유지했다. [내부 베타](../acceptance/2026-11-12-ios-build6/testflight-build6-internal.png) · [심사 접수](../acceptance/2026-11-12-ios-build6/review-build6-status.png)

Apple 필수 목록과 실제 IPA도 추가 대조했다. 포함된 필수 SDK framework 12개는 각각 자기 매니페스트가 있고, 명백한 누락은 0개였다. `path_provider_foundation 2.6.0`은 정식 소스가 FFI로 전환돼 별도 Pod·framework가 없으며 리소스 복사 누락으로 단정하지 않았다. 정적으로 합쳐진 모든 SDK의 정책 판정이나 Apple 최종 검증을 보장하는 결과는 아니다. [SDK별 경로·해시·불확실 항목](../acceptance/2026-11-12-ios-build6/sdk-manifest-inventory.json)

Google Play의 Android 빌드 5 심사는 유지한다. 같은 SDK의 로컬 Android 빌드 6도 성공했고, 이 호환성 검사 패키지는 업로드하지 않았다. 실기기 검사는 사용자의 다음 연결 때로 보류했다. 이번 패키지 수정·검사·재제출 성공이 스토어 승인, 새 빌드의 기기 재생 또는 공개 출시 완료를 뜻하지 않는다.

최종 통합 검사는 SDK 변경 후 Flutter 전체 **830개 통과·2개 건너뜀**, 네이티브·출시 준비·SMTP Python **89개 통과**로 끝났다. 두 명령 모두 종료 코드 0이었다. 변경한 Pub 패키지 두 개의 고정 버전을 OSV에 조회한 결과 반환된 권고는 없었다. 이는 해당 시점의 두 버전 조회 결과이며 전체 앱의 보안 승인이나 미공개 취약점 부재를 뜻하지 않는다. [전체 Flutter 검사](../acceptance/2026-11-12-ios-build6/flutter-full-after-sdk.log) · [Python 검사](../acceptance/2026-11-12-ios-build6/python-final.log) · [새 SDK 권고 조회](../acceptance/2026-11-12-ios-build6/new-sdk-advisories.json)

## 공식 근거

- [Apple 필수 SDK 목록](https://developer.apple.com/support/third-party-SDK-requirements/): `share_plus`를 포함하며 목록에 있는 SDK의 매니페스트 요구를 설명한다.
- [Apple DTS의 ITMS-91061 처리 안내](https://developer.apple.com/forums/thread/774960): 제공자가 배포한 업데이트와 예상 위치의 SDK 매니페스트를 확인하도록 안내한다. 앱의 매니페스트에 SDK 내용을 임의로 대신 적는 방식으로 처리하지 않았다.
- [share_plus 10.1.4 공식 배포·호환 조건](https://pub.dev/packages/share_plus/versions/10.1.4)
- [공식 10.1.4 iOS podspec](https://raw.githubusercontent.com/fluttercommunity/plus_plugins/share_plus-v10.1.4/packages/share_plus/share_plus/ios/share_plus.podspec)
- [공식 10.1.4 iOS 매니페스트](https://raw.githubusercontent.com/fluttercommunity/plus_plugins/share_plus-v10.1.4/packages/share_plus/share_plus/ios/share_plus/Sources/share_plus/PrivacyInfo.xcprivacy)
