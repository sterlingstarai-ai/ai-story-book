# iOS 빌드 복구 — 2026-10-22

Xcode 27.1 설치 후 최신 작업 트리의 iOS 네이티브 빌드와 실제 시뮬레이터 실행을 확인했다. 최소 지원 버전 오류와 시작 직후 종료되는 UIScene 미전환 문제를 수정했고 iOS 27의 실제 Keychain 경계를 통과했다. 기존 미커밋 변경과 데이터는 보존했다.

## 완료

- 첫 빌드는 앱의 iOS 13.0 및 Pod의 iOS 9.0~13.0 설정 때문에 `Target Integrity` 단계에서 실패했다. 설치된 Xcode 27.1 SDK는 iOS 15.0 이상만 지원하며 [Apple의 Xcode 지원 범위](https://developer.apple.com/xcode/system-requirements/)와 일치한다.
- 앱 Debug·Profile·Release 프로젝트 설정, Flutter 앱 프레임워크, Podfile의 최소 버전을 15.0으로 맞췄다. Pod 설치 후 120개 생성 구성 모두 15.0임을 확인했다. 이미 더 높은 최소 버전을 요구하는 Pod는 낮추지 않는다. 패키지 버전은 유지했고 Podfile.lock의 Podfile 체크섬만 갱신됐다.
- `flutter build ios --debug --no-codesign --no-pub --dart-define=API_BASE_URL=http://127.0.0.1:18280` 성공(exit 0). Xcode 컴파일 139.4초.
- 결과: `apps/mobile/build/ios/iphoneos/Runner.app`, `com.storybook.aiStoryBook`, 1.0.0(1), 최소 iOS 15.0, SDK `iphoneos27.1`. 165개 파일의 SHA-256을 아래 근거 폴더에 기록했다. 이 변경부터 iOS 13·14는 지원 대상에서 제외된다.
- Podfile Ruby 문법 검사, Xcode 프로젝트·프레임워크 plist 검사, 변경 범위 `git diff --check` 통과.
- 빌드만 통과한 첫 시뮬레이터 앱은 `UIScene life cycle is required`로 시작 직후 SIGTRAP 종료됐다. [Flutter 공식 마이그레이션](https://docs.flutter.dev/release/breaking-changes/uiscenedelegate)에 따라 Info.plist에 단일 FlutterSceneDelegate 구성을 추가하고 AppDelegate의 플러그인 등록을 `didInitializeImplicitFlutterEngine`으로 이동했다. 알림 delegate 설정은 보존했고, 기존 Flutter 3.38.7의 API를 사용해 SDK·패키지 버전을 올리지 않았다.
- 수정 후 iOS 27.0 전용 임시 시뮬레이터에서 `integration_test/native_storage_test.dart` **1개 통과(exit 0)**. 실제 Keychain을 통해 새 계정 저장, 복구키 준비·활성화, 캐시 재초기화 후 유지, 삭제 후 새 계정 발급을 확인했다. 네트워크는 호출하지 않았고 시험 키는 고유 접두사를 사용한 뒤 삭제했다. 이 검사는 앱의 UIScene 시작과 네이티브 플러그인 등록도 실행한다.
- `test/native_config_test.dart` **13개 통과**. 기존 권한 문구·지역화·공유 스킴·백그라운드 음성 설정의 정적 검사를 유지했다. 실제 알림·IAP·음성·카메라의 기기 동작 통과로 확대하지 않는다.
- UIScene 수정 뒤 일반 앱 진입점 `lib/main.dart`로 동일 디버그 빌드를 다시 완료했다(exit 0, Xcode 15.7초). 최종 번들의 최소 iOS·SDK·SceneManifest를 직접 읽고 새 파일별 해시를 기록했다. 처음의 UIScene 미전환 산출물 해시는 별도 이력으로 보존했다. Dart 소스·시험·앱 자산은 작업 시작 전 해시와 같다.

## 검증 범위와 남은 조건

이 앱은 **로컬 검사용 무서명 디버그 산출물이며 스토어 업로드 금지**다. 공개 운영 주소나 정책을 임의로 만들어 release 가드를 우회하지 않았다. Apple 개발자 계정·서명 사용 가능 상태와 제품의 실제 출시 가능 상태는 별개다.

운영 `infra/.env` 대상으로 값이 없는 상태명만 출력하는 외부 사전검사를 실행했다. `launch_ready=false`이며 공개 API·개인정보처리방침·약관 URL, 운영 AI·비공개 저장소·관리자 설정이 미완성이다. 번들 정책 두 문서도 `review_required`이며 운영 그림 품질 검사 설정이 빠져 있다. 로컬 API 키 보유를 운영 환경 연결 완료로 해석하지 않는다.

새 유료 호스팅·계약·구독, 실제 사용자나 아동 사진의 전송, 스토어 업로드·제출은 수행하지 않았다. 기존의 신규 결제·음성·실물 주문 비활성 상태를 유지한다.

## 재개 지점

전용 임시 시뮬레이터의 검증은 완료했고 이 실행이 만든 기기만 종료·삭제했다. 기존 개인 기기와 다른 프로젝트의 시뮬레이터는 변경하지 않았다. 다음은 공개 운영 환경과 정책 연결이다. 아래 검사를 통과한 뒤 운영 URL을 포함하는 release 빌드·실제 기기 검증·스토어 제출로 진행한다.

```bash
cd /Users/jmac/Desktop/ai-story-book
./scripts/final-external-preflight.sh --env-file infra/.env --json
python3 scripts/build_mobile_release.py --config /absolute/path/public-mobile-defines.json --platform ios
```

사전검사 통과는 실 공급자·운영 복원·스토어 거래 성공을 대신하지 않는다. `public-mobile-defines.json`은 실제 공개 URL만 담은 입력 파일이며 백엔드 `.env`나 비밀키를 사용하면 안 된다.

근거: Git 제외 `docs/acceptance/2026-10-22-xcode-native/`의 최초/수정 후 빌드 로그, `simulator-runner.log`, `native-storage-test-uiscene.log`, `native-config-test.log`, `source-before.json`, `ios-debug-artifact.json`, `external-preflight.json`, `simulator-owned.json`. 기존 웹·합성 백엔드 검사는 [로컬 복구 기록](LOCAL_PREVIEW_RECOVERY_2026-10-21.md)을 따른다.
