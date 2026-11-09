# 제한 베타 배포 준비

## 2026-11-09 한국어 낭독 후보 갱신

- 한국어에서는 성우·구연동화·잠자리 지시를 한국어로 전달한다. 받침과 연음, 조사와 어미, 의미 단위 호흡을 명시하고 원문 대조를 유지한다. 기존에 저장된 음원은 다시 쓰지 않았다.
- 실제 OpenAI Realtime에서 동일한 가상 대본으로 두 음색의 세 스타일을 새로 합성했다. 여섯 응답 모두 원문과 일치했고, 앱의 비교 샘플을 그 파일로 교체했다. 자연스러운 발음의 최종 청취 판정과 이 후보로 새로 생성하는 운영 동화 검증은 별도로 기록한다. [샘플 비교](acceptance/2026-11-09-korean-style-candidate/index.html)

## 2026-11-09 개인정보처리방침·이용약관 개정 검토본

- 두 문서를 각각 여섯 절로 정리했다. 개인정보처리방침은 처리 목적, 보호자 동의, 외부 처리, 보관·파기와 권리 행사 방법을 설명한다. 이용약관은 초대형 무료 첫 권, AI 결과 확인, 입력 자료의 권한, 계정 복구와 서비스 제한을 안내한다.
- 한국어 앱 내 문서와 웹 검토본이 일치한다. 새 iOS·Android 검수 패키지에서 같은 원문을 추출해 대조했고, 2.35배 글자 크기의 오프라인 문서 읽기와 동의 전 전문 열기를 검증했다. 보호자 동의 고지문과 공개 승인 상태에는 변경이 없다.
- 개인정보 국외 이전 조건과 백업 만료 기준, 최종 승인·시행일 및 공개 HTTPS가 확정된 뒤 공개한다. [문서와 패키지 대조](acceptance/2026-11-09-policy-review-candidate/verification.json)



## 2026-11-09 iPhone 실기기 검수와 발음 보완

- iOS 27.2에서 디버그 검수 빌드가 JIT 실행 중 시작 오류를 내 별도의 개발 서명 프로필 빌드로 검수했다. 앱 코드와 개정 정책을 반영했으며 로컬 시험 서버에 연결하는 조건만 검수본에서 별도로 적용했다. [검수 결과](acceptance/2026-11-09-iphone-physical-realtime/verification.json)
- iPhone 15에서 개정 방침·약관 열기, 참여 ID 복사, 초대 후 7–9세 첫 권, 삽화 13장, 더보기, 12쪽 연속 재생과 자연 종료, 완독 및 서재 복귀를 확인했다. 실제 생성·합성했던 가상 동화의 파일을 재사용했다.
- 사용자가 저장된 구연동화 음원에서 한국어 발음이 어색하다고 보고했다. Realtime의 한국어 요청에 표준 발음·받침·연음과 문장 억양 지시를 보강했다. 실제 비교 요청에서 같은 음색은 12쪽 원문과 전사가 일치했고, 다른 음색은 불일치로 제외했다. 전사 일치와 별도로 발음 비교 청취가 남아 있다. [같은 대본 비교](acceptance/2026-11-09-korean-narration-pronunciation/index.html)

## 2026-11-09 Android 실기기 검수

- 최신 초대 베타 APK를 USB로 설치하고 파일 해시를 대조했다. 보호자 동의, 미초대 안내, 보호자 확인을 거친 참여 ID 복사, 초대 후 무료 첫 권 활성화를 확인했다.
- 7–9세 한국어 첫 권은 본문 12쪽과 554어절이었다. 모든 쪽이 40어절 이상이었다. 표지와 본문 삽화 13장의 서명 다운로드를 대조했고, 실기기에서 표지와 12쪽 그림, 더보기 메뉴를 확인했다.
- 이미 생성된 실제 OpenAI Realtime 구연동화 음원을 사용해 기기에서 1–12쪽 자동 재생과 마지막 쪽 자연 종료를 확인했다. 두 음색·세 스타일 미리 듣기는 모두 네이티브 오디오 재생을 시작했다. 완독 확인과 앱 재실행 뒤 서재의 책 열기도 통과했다. 새 AI 요청은 없었다. [실기기 검증](acceptance/2026-11-09-android-physical-realtime/verification.json) · [마지막 쪽](acceptance/2026-11-09-android-physical-realtime/page-12.jpg)


## 2026-11-08 초대 베타 최종 검수 후보

- 초대 전에는 보호자 설정에서 참여 ID를 확인할 수 있다. 초대 등록 후 생성 화면으로 돌아오면 권한을 다시 읽는다. 생성 중지 중에는 서재를 안내한다. 스토어 설명과 검수 시나리오에 무료 첫 권 낭독이 모든 지원 연령에 포함된다고 반영했다.
- iPhone과 Android의 개발 서명, 최신 소스 및 실제 OpenAI 비교 샘플 여섯 개를 확인했다. 동일한 Android APK를 호환 모드를 끈 16 KiB 에뮬레이터에 설치해 보호자 동의 화면까지 확인했다. [iPhone 검수 IPA](acceptance/2026-11-08-invitation-release-candidate/ai-story-book-ios-device-qa.ipa) · [Android 검수 APK](acceptance/2026-11-08-invitation-release-candidate/ai-story-book-android-device-qa.apk)
- Linux amd64 API·워커는 동일한 서버 입력 198개와 OpenAPI를 대조했다. PostgreSQL·Redis·Celery·MinIO 격리 환경에서 7–9세 무료 첫 권 56개, 재시작 뒤 전권 음원 재사용과 동의 철회 뒤 접근 차단을 확인했다. 테스트 생성에는 합성 공급자 응답을 사용했다. [이미지 검증](acceptance/2026-11-08-invitation-release-candidate/image-verification.json) · [격리 통합 결과](acceptance/2026-11-08-invitation-release-candidate/runtime.json)
- API 전체 3,317개와 Flutter 전체 809개가 통과했다. API는 29개, Flutter는 2개를 건너뛰었다. Ruff, Flutter 정적 분석, UI 사전 검사도 통과했다. [검증 요약](acceptance/2026-11-08-invitation-release-candidate/verification.json)
- 배포 후 HTTPS 준비 상태와 Celery 워커별 Redis 응답을 모두 확인한다. 격리 Docker에서 새 이미지가 기존 태그를 가져간 뒤 준비 상태가 503이면 이전 API와 워커를 이미지 ID로 복원했다. 실제 후보 워커 두 대 중 한 대가 중지되거나 Redis가 끊기면 API 검사 결과가 200이어도 배포 검사가 실패했다. 배포 관련 테스트 42개가 통과했다. [배포 검증](acceptance/2026-11-08-invitation-release-candidate/deploy-gate-verification.json)
- 운영 낭독 설정을 바꾸는 Compose 경로도 검증했다. 격리 Docker에서 새 이미지가 이전 태그를 가져간 상태로 503을 반환하자 API와 워커 두 대 모두 이전 환경과 이미지로 돌아갔다. 잘못된 이전 환경 파일과 HTTPS 주소는 이미지 가져오기 전에 차단됐다. [제공자 전환 롤백 검증](acceptance/2026-11-09-provider-cutover-rollback/verification.json)
- OpenAI 키의 읽기 전용 마운트를 추가하는 전환도 격리 Docker로 시험했다. 새 API와 워커 두 대에서 마운트가 읽기 전용이었고, 503 뒤에는 세 컨테이너 모두 이전 Compose 파일 구성과 이미지로 돌아가며 해당 마운트가 제거됐다. 이전 오버라이드를 빠뜨리면 이미지 가져오기 전에 차단됐다. 배포 관련 테스트 43개가 통과했다. [키 마운트 롤백 검증](acceptance/2026-11-09-provider-cutover-rollback/key-mount-rollback.json)
- 공동 검수에서는 두 기기에 이 빌드를 연결한다. 미초대 안내와 참여 ID 확인, 초대 후 7–9세 동화 생성, 표지와 본문 삽화 13장, 두 음색·세 스타일 비교와 마지막 쪽 낭독, 앱 재실행 뒤 서재 복귀를 확인한다.
- 공개 배포 전에는 승인된 정책과 시행일을 반영하고 정책·지원 페이지 및 API·미디어의 공개 HTTPS 연결을 검증한다. 공동 검수 후 [배포 순서](#배포-순서)에 따라 OpenAI 운영 전환, 준비 상태와 실제 생성 확인, 운영 주소로 스토어용 서명 빌드, 제출을 진행한다.

## 2026-11-08 OpenAI 낭독 공동 검토 빌드

- 실제로 합성한 OpenAI 음원 여섯 개를 두 개발 서명 앱에 포함했다. 두 빌드의 Flutter 자산 목록과 음원 해시를 대조했다. Realtime을 알리는 시험 API에 연결하면 이야기 성우·구연동화·잠자리 세 스타일을 두 음색으로 비교할 수 있다. 이전 검토와 같은 기기별 로컬 연결 및 QA 앱 식별자를 사용한다.
- Android는 정확히 이 APK를 호환 모드를 끈 16KiB 에뮬레이터에 설치하고 보호자 동의 화면을 열었다. iOS IPA의 중첩 서명과 기존 개발 프로파일을 확인했다. Flutter 검사 807개가 통과했고 2개는 건너뛰었으며 정적 분석도 통과했다. 두 실기기의 청취 및 생성 검토는 남아 있다. [iOS IPA](acceptance/2026-11-08-realtime-device-qa/ai-story-book-ios-realtime-qa.ipa) · [Android APK](acceptance/2026-11-08-realtime-device-qa/ai-story-book-android-realtime-qa.apk) · [검증 기록](acceptance/2026-11-08-realtime-device-qa/verification.json)

## 2026-11-08 공동 검토 후보

- 생성 목록 오류 후 같은 작업으로 돌아가는 변경을 포함한 iOS·Android 공동 검토용 디버그 패키지를 다시 빌드했다. 현재 소스·설정·자산 116개와 두 빌드를 대조했고, 낭독 샘플 9개의 바이트가 원본과 일치했다. iOS는 기존 QA 개발 서명을 검증했다. Android는 호환 모드를 끈 16KiB 에뮬레이터에서 이 APK를 설치하고 해시를 대조한 뒤 보호자 동의 화면까지 실행했다. [최신 iOS IPA](acceptance/2026-11-08-active-generation-device-qa/ai-story-book-ios-device-qa.ipa) · [최신 Android APK](acceptance/2026-11-08-active-generation-device-qa/ai-story-book-android-device-qa.apk) · [검증 기록](acceptance/2026-11-08-active-generation-device-qa/verification.json)
- 로컬 API 주소를 지정하는 공동 검토용 앱은 iOS와 Android 모두 디버그 모드로 빌드한다. iOS는 기존 QA 식별자와 개발 서명을 재사용하며, 기기를 연결한 뒤 Xcode 디버거로 실행한다. 앞서 만든 프로필 IPA는 로컬 API 주소와 실행 모드가 맞지 않아 공동 검토에 사용하지 않는다. 운영 빌드에는 공개 HTTPS 주소와 승인된 정책 문서를 확인하는 기존 검사가 적용된다. [Flutter 빌드 모드](https://docs.flutter.dev/testing/build-modes) · [Xcode 디버깅](https://docs.flutter.dev/testing/native-debugging)
- 앞선 별도 통합 빌드는 iOS와 Android에서 각각 보호자 동의부터 7–9세 무료 첫 권, 서재 복귀와 명시적 완독까지 통과했다. 격리 서버에서 모의 AI를 사용했다. 최신 변경은 두 플랫폼의 별도 통합 빌드에서 목록 503 뒤 같은 생성 작업으로 복귀하는 경로를 통과했다. [무료 첫 권 기록](acceptance/2026-11-08-latest-joint-review/verification.json) · [생성 복귀 기록](acceptance/2026-11-08-active-generation-cta/verification.json)
- iPhone은 Mac의 `.local` 주소와 포트 57332로, Android는 USB 역방향 연결과 포트 18080으로 시험한다. 앞선 iPhone 15 시험에서는 격리 서버로 실제 동화 생성을 요청하고, 표지와 삽화 13장과 마지막 쪽 낭독 종료를 확인했다. 생성 화면 직접 조작은 공동 검토에 포함한다. [기기별 연결 절차](OPERATIONS_TEST_RUNBOOK.md#5-local-docker-runtime) · [iPhone 결과](acceptance/2026-11-08-iphone-7to9-joint-review/device-result.json)
- 검토 시 새 계정으로 보호자 동의와 무료 첫 권 이용을 확인한다. 7–9세 한국어 동화에서 본문 12쪽 중 9쪽 이상이 40어절 이상인지 확인하고, 표지와 본문 삽화 13장과 마지막 쪽까지 낭독을 확인한다. 이야기 성우·구연동화·잠자리 음성을 비교하고 재실행 후 서재에서 책을 다시 연다.
- 실제 운영 백업의 DB는 격리 복원했고, 후보와 같은 스키마 버전을 확인했다. 11월 9일 정규 예약 백업이 성공했고 같은 백업을 다시 격리 복원했다. 운영 미디어가 포함된 백업의 복원은 추가 확인이 필요하다. 승인·시행된 정책과 공개 HTTPS 주소, 최신 운영 연결 빌드의 공동 실기기 검증도 남아 있어 공개 출시는 보류한다. [출시 현황](LAUNCH_STATUS.md) · [후보 통합 검증](acceptance/2026-11-08-frozen-release-candidate/verification.json)

## 2026-11-08 삽화 주소 갱신 후보

- 같은 읽기 세션에서도 새로 거부된 삽화 주소를 다시 갱신한다. 자동 갱신은 1분 간격으로 제한하고 현재 쪽과 인접 쪽의 만료만 미리 확인한다. 전체 Flutter 검사 790개가 통과했고 2개는 건너뛰었다. 새 iOS QA 앱을 기존 앱과 별도로 설치하고 유선 디버깅에서 부모 동의 화면을 확인했다. Android APK는 호환 모드를 끈 16 KiB 가상 기기에서 보호자 동의 화면까지 실행했다. [검증 기록](acceptance/2026-11-08-illustration-renewal-qa/verification.json)

## 2026-11-08 낭독 연결 재사용

- 한 책 안에서 재생용과 미리 받기용 HTTP 연결을 각각 재사용한다. 접근이 차단되거나 계정·프로필 저장 범위가 바뀌면 연결과 재생을 종료한다. iOS 시뮬레이터와 16 KiB Android 에뮬레이터에서 다음 쪽 요청이 같은 연결을 사용하고 거부된 음원 링크가 갱신되는 것을 확인했다. 별도 전권 시험에서 보관된 실제 동화의 삽화 13장을 표시하고 Gemini 구연동화 음원을 1쪽부터 12쪽까지 순서대로 재생했다. [낭독 검증](acceptance/2026-11-08-narration-connection-reuse/verification.json)

## 2026-11-08 최신 실기기 시험 패키지

- 두 앱을 현재 Dart 소스 91개와 대조했다. iPhone 15에는 별도 QA 식별자로 서명한 빌드를 설치하고 기존 QA 앱이 남아 있는 것을 확인했다. 기기 잠금으로 실행은 보류됐다. Android는 실기기가 연결되지 않아 호환 모드를 끈 16 KiB 에뮬레이터에서 APK 설치 파일의 일치와 보호자 동의 화면을 확인했다. 두 기기에서 최신 앱으로 새 동화를 만들고 전권을 낭독하는 시험은 남아 있다. [기기와 패키지 검증](acceptance/2026-11-08-current-physical-qa/verification.json)

## 보관한 12쪽 동화의 실제 낭독을 로컬 시험에서 재생

- 가상 동화 《하루와 세 알의 기다림》의 12쪽 본문과 구연동화 음원 해시를 대조한 뒤 기존 삽화와 함께 격리 시험에 연결한다. 같은 제목으로 한국어 7–9세 수채화 12쪽 책을 만들고 기본 목소리·구연동화를 선택한다. 녹음이 없는 목소리나 스타일은 거절한다. [실행 절차](OPERATIONS_TEST_RUNBOOK.md#5-local-docker-runtime)
- 로컬 API와 iPhone용 연결을 Mac에서 각각 시험했다. 본문 12쪽, 서명 삽화 13장, 서명 음원 12개와 캐시를 원본과 대조했다. 마지막 음원의 범위 요청은 HTTP 206을 반환했다. 관련 자동 검사 47개를 통과했다. 이 시험은 보관 음원을 사용했으며 새 공급자 호출은 없었다. [로컬 결과](acceptance/2026-11-08-prerecorded-first-book-review/loopback.json) · [iPhone 연결 모의 결과](acceptance/2026-11-08-prerecorded-first-book-review/iphone-relay.json)

## iPhone 공동 검토용 로컬 연결

- 기존 서명 iPhone QA 빌드의 `.local` 주소로 시험 API와 서명 미디어를 전달한다. 선택한 Mac 인터페이스에만 포트를 열고 지정한 iPhone 주소와 Mac 자체만 허용한다. 서명에 포함된 호스트를 그대로 전달하며 시험 종료 후 두 포트를 닫는다. [실행 절차](OPERATIONS_TEST_RUNBOOK.md#5-local-docker-runtime)
- Mac의 모의 클라이언트가 해당 인터페이스를 통해 첫 권을 생성하고 표지 포함 13장을 읽었다. 서명 없는 요청, 호스트를 바꾼 요청과 허용 목록 밖 연결은 차단됐고 13장의 범위 요청이 통과했다. 일반 첫 권 검사 52개와 관련 자동 검사 30개도 통과했다. [검증 결과](acceptance/2026-11-07-iphone-review-local-transport/result.json)

## 로컬 첫 권 검토의 기기 초대

- Mac의 격리 첫 권 시험에서 앱이 복사한 베타 참여 ID를 실행 중에 추가할 수 있다. 기존 동의와 생성 기록을 유지한다. 시험 보고서에 앱 연결과 서명 미디어용 포트를 각각 제공해 Android의 두 USB 포트를 설정할 수 있다. [로컬 실행 절차](OPERATIONS_TEST_RUNBOOK.md#5-local-docker-runtime)
- PostgreSQL·Redis·Celery·MinIO에서 시작 전 초대와 실행 중 초대를 별도로 확인했다. 실행 중 초대를 제거하면 새 생성이 차단됐고, 이미 저장된 책은 열렸다. 7–9세 12쪽 책과 서명 삽화 13장을 읽었고 서명을 제거한 삽화 접근은 차단됐다. 모의 AI를 사용했고 관련 자동 검사 43개를 통과했다. [실행 중 초대](acceptance/2026-11-07-local-review-invitations/running.json) · [시작 전 초대](acceptance/2026-11-07-local-review-invitations/preset.json)

## 공동 검토용 서명 앱 후보

- 현재 앱 소스로 iOS 개발 서명 IPA와 Android arm64 디버그 APK를 빌드했다. 기존 iPhone 15의 개발 프로파일 일치, iOS 15.0 최소 대상과 앱 서명을 확인했다. iOS 디버그 실행은 개발 연결을 사용한다. 두 빌드에는 별도 QA 식별자와 Mac의 로컬 시험 API 연결을 사용하며 생성 대기·연령 미리보기 삽화 파일이 포함됐다.
- Android APK는 ZIP과 네이티브 라이브러리의 16KiB 정렬을 확인했다. 호환 모드를 끈 16KiB 에뮬레이터에서 보관한 APK와 설치된 파일의 해시가 같았고 부모 동의 화면까지 열렸다. [검증 결과](acceptance/2026-11-07-signed-joint-mobile-review/result.json) · [iOS IPA](acceptance/2026-11-07-signed-joint-mobile-review/ai-story-book-ios-qa.ipa) · [Android APK](acceptance/2026-11-07-signed-joint-mobile-review/ai-story-book-android-arm64-qa.apk)

## Gemini 낭독 인증 장애와 준비 상태

- Google 작업 자격증명을 가져오지 못하면 이전 낭독 성공 관측을 무효화한다. 이 단계에서는 합성 요청 한도를 차감하지 않는다. Gemini의 인증 거절은 기존 점검 예산 안에서 다시 확인할 수 있고, OpenAI 글·그림 키 거절에는 계속 운영자 확인이 필요하다.
- 최신 Linux amd64 API·워커의 실행 소스 138개씩을 대조했다. 외부 연결을 막은 Docker 환경의 실제 Redis와 PostgreSQL에서 인증 단계 실패와 모의 TTS HTTP 401이 각각 준비 상태 503으로 반영되고, 검증된 음원 응답 뒤 200으로 복구됐다. 새 이미지로 무료 첫 권 검사 52개, 집중 API 검사 82개와 Ruff도 통과했다. [준비 상태](acceptance/2026-11-07-gemini-credential-readiness/readiness.json) · [후보 이미지](acceptance/2026-11-07-gemini-credential-readiness/oci-verification.json)

## 완성할 수 없는 책의 대기 중 삽화 요청 중단

- 표지나 본문 삽화가 끝내 준비되지 않으면 전체 삽화 검수가 필요한 새 책의 대기 요청을 막는다. 이미 시작된 요청은 마무리한다. 시험 HTTP 응답이 인증을 거부한 경우에는 `AI_PROVIDER_UNAVAILABLE`을 유지했다.
- 격리 PostgreSQL·Redis·Celery·MinIO에서 7–9세 12쪽 시험 책의 첫 삽화를 실패시켰다. 표지와 본문 두 쪽의 작업만 시작했고, 대기 10쪽은 요청하지 않았다. 책은 서재에 추가되지 않았고 무료 이용권이 돌아왔으며, 저장된 그림 두 개의 파기 작업이 등록됐다. 별도로 정상 무료 첫 권 여정 검사 52개도 통과했다. [실행 결과](acceptance/2026-11-07-incomplete-illustration-admission/result.json)
- API 전체 테스트 3,123개가 통과했고 29개는 건너뛰었다. Ruff 검사도 통과했다. 공급자는 모의 응답을 사용했다.

## 예약 백업 사전 점검 중 개인정보 기록 변경

- 서비스가 실행 중인 사전 점검에서만 개인정보 기록 대조를 최대 세 번 수행한다. 두 복제 저장소 조회 사이에 기록이 추가된 경우와 저장소 조회 직후 DB가 갱신된 경우, 별도 PostgreSQL 16·MinIO 두 곳에서 모두 두 번째 대조가 통과했다. 검증 저장소의 완료 기록을 제거하자 세 번 모두 실패했고 서비스 중단과 백업 게시 경로는 실행되지 않았다.
- 관련 자동 검사 248개와 별도 합성 복원 검사 31개가 통과했다. 예약 후보 파일 195개를 현재 소스와 대조했다. [사전 점검](acceptance/2026-11-07-backup-live-journal-recheck/result.json) · [복원 결과](acceptance/2026-11-07-backup-live-journal-recheck/restore-result.json) · [후보 검증](acceptance/2026-11-07-backup-live-journal-recheck/candidate-verification.json)

## 생성 상태 조회 제한 시간

- 앱의 10분 상태 조회 한도를 대기 시간과 진행 중인 HTTP 요청에 함께 적용한다. 시간이 지나면 조회를 취소한다. 사용자가 ‘상태 다시 확인’을 누르면 같은 생성 작업을 다시 조회한다.
- 제한 시간에 멈춘 요청, 시간 초과 뒤 도착한 완료 응답, 같은 작업의 재조회에서 진행률이 표시되는 경로를 검증했다. Flutter 정적 분석과 전체 검사 758개가 통과했고 2개는 건너뛰었다.

## 2026-11-07 읽기 화면 닫기와 기록 전송

- 삽화 시험에 일반 종료 경로를 추가했다. iOS 27.2 시뮬레이터와 호환 모드를 끈 Android 16KiB 에뮬레이터에서 12쪽까지 넘긴 뒤 하단 점 세 개 메뉴로 책을 닫았다. 두 기기 모두 이전 화면으로 돌아왔고, 루프백 서버는 해당 책의 미완독 기록을 한 번씩 받았다. 시험에서 앱을 바로 철거했을 때의 네트워크 오류는 이 종료 경로에서 재현되지 않았다.
- 읽기·낭독 Flutter 검사 66개와 읽기 기록·프로필 API 검사 10개가 통과했다. [기기 및 HTTP 검증](acceptance/2026-11-07-reader-menu-exit/result.json)

## 2026-11-07 다음 쪽 삽화 미리 읽기

- 책을 읽는 동안 이웃 페이지도 기존 책별 캐시를 통해 삽화를 읽는다. iOS 27.2 시뮬레이터와 호환 모드를 끈 Android 16KiB 에뮬레이터에서 표지 포함 13장을 표시했고, 두 플랫폼에서 12쪽 모두 이동하기 전에 다음 삽화 디코딩을 확인했다. 각 삽화는 플랫폼당 한 번씩 내려받았다.
- Flutter 정적 분석과 자동 테스트 756개를 통과했고 2개는 건너뛰었다. 기존 삽화를 사용해 새 AI 요청은 없었다. 삽화 시험 종료 시 읽기 기록 전송에서 네트워크 오류가 기록됐다. [결과](acceptance/2026-11-07-reader-illustration-lookahead/result.json) · [iOS](acceptance/2026-11-07-reader-illustration-lookahead/ios.log) · [Android](acceptance/2026-11-07-reader-illustration-lookahead/android.log)

## 2026-11-07 예약 백업의 서비스 중단 전 개인정보 기록 확인

- 실제 예약 실행도 API·worker 연결과 원본을 확인한 뒤, 서비스 중단 전 개인정보 기록을 대조한다. 불일치 시 `journal_preflight`에서 실패한다. 서비스 중단 뒤 캡처 전과 원격 완료 표식 게시 전에는 새로 대조한다.
- 격리 PostgreSQL 16·MinIO에서 검증 저장소의 합성 완료 기록을 제거했다. `--execute`가 중단·백업 게시 경로에 진입하기 전에 실패했다. 집중 검사 135개와 별도 합성 복원 검사 31개를 통과했고, 후보 파일 195개를 소스와 대조했다. [실행 진단](acceptance/2026-11-07-backup-journal-before-stop/execute-preflight.json) · [복원 검사](acceptance/2026-11-07-backup-journal-before-stop/restore/result.json) · [후보 확인](acceptance/2026-11-07-backup-journal-before-stop/candidate-verification.json)

## 2026-11-07 저장소 쓰기 차단 검증 보강

- GCS 미디어 쓰기 동결 검사에서 새 객체 생성, 기존 시험 객체 덮어쓰기·삭제의 거부를 각각 요구한다. 새 키는 세대 조건 0을 쓰고, 기존 시험 객체는 내용과 세대를 확인한 뒤 그 세대만 대상으로 한다. 권한 거부 뒤 시험 객체의 세대와 바이트를 다시 읽는다. [GCS XML 요청 조건](https://docs.cloud.google.com/storage/docs/request-preconditions)
- 실제 boto3 서명 요청을 시험 응답으로 가로채 세대 조건 헤더가 서명에 포함되는지 확인했다. 쓰기가 허용되거나 세대가 바뀌면 검사에 실패했고, 새 키 충돌 시 다른 파일은 삭제하지 않았다. 관련 검사 180개가 통과했다. 운영 GCS 자격이나 과거 요청의 종료는 이번 검사 범위 밖이다.

## 2026-11-07 최신 앱의 12쪽 연속 낭독

- 《하루와 세 알의 기다림》의 43–51어절 본문 12쪽, 기존 삽화 13장과 실제 합성한 Gemini 음원 12개를 루프백 서버로 제공했다. iOS 27.2 시뮬레이터와 호환 모드를 끈 Android 16KiB 에뮬레이터에서 모두 삽화 13장 표시, 1.3배속 1–12쪽 순차 재생, 마지막 쪽의 자연 종료를 확인했다.
- 각 플랫폼에서 일반 음원 조회는 1쪽 한 번이었다. 2–12쪽은 각각 미리 받아 재생했다. 서버의 성공 응답은 두 플랫폼 합계 미리 받기 22회, 일반 조회 2회, 음원 파일 24회, 삽화 파일 26회였다. 새 AI 요청은 없었고 시험 기기와 루프백 서버를 정리했다. [전권 재생 결과](acceptance/2026-11-07-whole-book-prefetch/result.json) · [iOS](acceptance/2026-11-07-whole-book-prefetch/ios.log) · [Android](acceptance/2026-11-07-whole-book-prefetch/android.log)

## 2026-11-07 낭독 시작 위치 전달

- 새 쪽의 음원을 열 때 시작 위치를 네이티브 플레이어에 함께 전달한다. 새 파일을 연 뒤 별도 위치 이동을 요청하는 호출을 쪽마다 한 번 줄였다. 같은 쪽의 일시정지·재개와 끝난 쪽을 처음부터 다시 듣는 경로를 확인했다.
- 정적 분석과 집중 검사 55개가 통과했다. iOS 27.2 시뮬레이터에서 저장 위치·일시정지·재개와 내장 샘플 9개를 확인했다. 기존 음원으로 세 쪽을 연속 재생해 2쪽의 미리 받은 파일을 재사용하고 마지막 쪽이 끝나는 것을 확인했다. [iOS 네이티브 검사](acceptance/2026-11-07-native-narration-initial-position/ios-native.log) · [연속 낭독 검사](acceptance/2026-11-07-native-narration-initial-position/ios-prefetch-handoff.log)
- 호환 모드를 끈 Android 16KiB 에뮬레이터에서도 저장 위치 재생, 일시정지·재개·중지, 내장 샘플 9개 재생을 확인했다. 두 플랫폼 모두 기존 음원과 시험 파일을 사용했다. [Android 네이티브 검사](acceptance/2026-11-07-native-narration-initial-position/android-native.log)

## 2026-11-07 예약 백업 적용 전 원본·기록 대조

- 예약 설정 계획의 `--verify-prerequisites`는 검토한 예약 명령, 고정 스크립트, 해석된 인자의 해시를 확인하고 같은 인자로 원본 DB·미디어와 개인정보 기록을 읽는다. 진단 실패 또는 점검 도중 명령·버킷·스크립트 변경 시 적용 파일을 출력하지 않는다. [적용 절차](BACKUP_RESTORE.md#제한-운영의-예약-백업-검증-저장소-연결)
- 집중 검사 105개와 Linux systemd의 기존·보완·롤백 설정 구문 검사를 통과했다. 합성 전환에서 적용 전후에 동일한 인자를 사용했고, 후보 파일 195개를 소스와 대조했다. [전환 결과](acceptance/2026-11-07-reviewed-backup-prerequisites/transition.json) · [systemd 검사](acceptance/2026-11-07-reviewed-backup-prerequisites/systemd-verify.log) · [후보 대조](acceptance/2026-11-07-reviewed-backup-prerequisites/candidate-verification.json)

## 2026-11-07 운영 백업 상태와 중단 전 진단

- 제한 운영의 최근 24시간 API 준비 신호 280건은 모두 정상이었고, 백업 신호 140건은 모두 비정상이었다. 독립 기록 감시 지표 조회는 404였다. Cloud Logging API가 비활성이며 VM 시리얼 출력에도 해당 백업 서비스 로그가 없었다. 이번 조회에서는 로드된 예약 명령을 다시 확인하지 못했다. [운영 신호](acceptance/2026-11-07-backup-live-diagnosis/monitoring.json)
- 예약 백업 후보에 `--check-prerequisites`를 추가했다. 서비스 중단 전에 API·worker 설정, 원본 연결, 개인정보 기록을 확인한다. 격리 PostgreSQL 16과 MinIO에서 정상 대조를 통과했고, 검증 저장소의 완료 기록 한 건을 삭제하자 `journal_preflight`에서 차단됐다. 삭제된 기록은 다시 쓰이지 않았고 백업 파일도 생성되지 않았다. Docker 조회 응답과 원격 인증은 대역을 사용했다. [격리 진단](acceptance/2026-11-07-backup-live-diagnosis/local-prerequisites.json) · [운영 절차](BACKUP_RESTORE.md#제한-운영의-예약-백업-검증-저장소-연결)
- 집중 검사 97개와 별도 PostgreSQL·MinIO 복원 리허설 31개가 통과했다. 최신 삭제·동의 철회·인증 폐기 적용과 비공개 미디어 접근을 합성 데이터로 확인했다. [복원 리허설](acceptance/2026-11-07-backup-live-diagnosis/restore/result.json)

## 2026-11-07 첫 권 검토 빌드와 삽화 참조 다운로드

- 승인 캐릭터와 책 표지를 함께 쓰는 삽화 요청은 두 참조를 병행해 읽고 기존 순서로 전달한다. 한 파일을 읽을 수 없으면 진행 중인 읽기를 마친 뒤 오류를 반환하며 모델 호출이나 요청 한도 차감을 진행하지 않는다.
- 격리 MinIO에서 12쪽을 세 쪽씩 처리하고 참조 읽기마다 100ms 지연을 추가했다. 세 번씩 측정한 참조 준비 중앙값은 1.0805초에서 0.5616초였다. 각 실행의 실제 읽기는 24회였고 파일 바이트와 순서가 같았다. [참조 읽기 실측](acceptance/2026-11-07-parallel-illustration-references/reference-timing.json)
- 새 홈·서재 흐름을 포함한 Android 디버그 빌드와 iOS arm64 무서명 디버그 빌드를 만들었다. Android 서명과 16KiB ZIP 정렬, iOS 최소 버전 15.0, 두 빌드의 생성 화면 삽화 파일을 확인했다. 별도 PostgreSQL·Redis·Celery·MinIO에서 모의 AI를 사용한 무료 첫 권 여정을 통과했다. [모바일 빌드](acceptance/2026-11-07-parallel-illustration-references/mobile-build.json) · [격리 여정](acceptance/2026-11-07-parallel-illustration-references/runtime/result.json)
- 새 Linux amd64 API·워커 이미지 각각의 실행 소스 142개를 대조했다. 두 이미지를 외부 연결을 차단한 Docker 네트워크에서 띄워 첫 권·음원 접근 검사 52개를 통과했다. 실제 Redis에 시험 관측을 넣어 준비 상태가 미관측·장애·만료 때 503, 새 정상 관측 후 200으로 바뀌는 것을 확인했다. [이미지 대조](acceptance/2026-11-07-parallel-illustration-references/oci-build.json) · [첫 권 검사](acceptance/2026-11-07-parallel-illustration-references/oci-first-book.json) · [준비 상태 검사](acceptance/2026-11-07-parallel-illustration-references/oci-readiness.json)
- 기존 로컬 가상환경의 FastAPI 0.115.0에서 OpenAPI 계약 불일치가 발생했다. 프로젝트 고정 버전인 0.162.0 환경에서 계약·참조 집중 검사 61개와 전체 API 검사 3,093개가 통과했고, 전체 검사에서 29개를 건너뛰었다.

## 2026-11-07 백업 원본 미디어 다운로드 단축

- 예약 백업은 원본 삽화·음원 다운로드를 최대 두 개씩 병행한다. DB 스냅샷과 미디어 변경 감지를 유지하며, 개별 다운로드 실패 시 진행 중인 읽기가 끝난 뒤 부분 백업을 정리한다.
- 격리 PostgreSQL 16·MinIO에서 12개 파일에 요청당 50ms 지연을 추가하고 세 번씩 비교했다. 캡처 중앙값은 순차 1.1532초에서 두 개 병행 0.7360초였다. 외부 클라이언트가 원본을 교체하거나 DB 보호 연결이 끊어졌을 때 완료본이 생기지 않았다. 백업 집중 검사 101개와 격리 복원 검사 31개가 통과했다. [캡처 실측](acceptance/2026-11-07-parallel-source-backup/capture-result.json) · [복원 결과](acceptance/2026-11-07-parallel-source-backup/restore/result.json) · [후보 검증](acceptance/2026-11-07-parallel-source-backup/candidate-verification.json)

## 2026-11-07 백업 완료 표식 게시 전 재검증

- 공유 백업 절차는 원격 manifest 검증 후, 완료 표식 게시 직전에 개인정보 기록을 다시 확인한다. 표식 자체도 생성한 크기와 SHA-256으로 검사한다. 전송 중 독립 기록 복제본이 사라지거나 표식의 바이트가 바뀌면 완료 표식 게시가 차단된다.
- PostgreSQL·MinIO 격리 복원에서 원격 manifest 전송 중 독립 기록의 커밋을 제거했다. 완료 표식이 남지 않았고 서비스 복구 경로가 실행됐다. 원격 전송에는 GCS 대역을 사용했다. 복원 검사 31개와 백업 집중 검사 96개가 통과했다. [복원 결과](acceptance/2026-11-07-backup-final-publication-check/restore/result.json) · [후보 검증](acceptance/2026-11-07-backup-final-publication-check/candidate-verification.json)

## 2026-11-07 예약 백업 적용·롤백 명령 대조

- 예약 백업 계획은 기존 명령, 적용 예정 명령, 고정 실행 파일의 SHA-256을 각각 제공한다. 적용 전·후와 롤백 때 검토된 해시를 지정해 대조할 수 있다. 로드된 명령이나 실행 파일이 달라지면 연결 검사와 drop-in 출력 전에 중단한다. [적용·롤백 절차](BACKUP_RESTORE.md#제한-운영의-예약-백업-검증-저장소-연결)
- Ubuntu systemd에서 기존·보완·롤백 설정의 구문을 확인했다. 백업 집중 검사 94개와 새 격리 PostgreSQL·MinIO 복원 검사 30개가 통과했다. 복원 뒤 최신 계정 삭제, 동의 철회와 인증 폐기, 비공개 미디어 접근을 확인했다. 원격 전송 검증은 GCS 대역을 사용했다. [명령 대조](acceptance/2026-11-07-reviewed-backup-transition/transition-fixture.json) · [복원 결과](acceptance/2026-11-07-reviewed-backup-transition/restore/result.json) · [로컬 후보 확인](acceptance/2026-11-07-reviewed-backup-transition/candidate-verification.json)
- 운영 VM이 실행 중임을 읽기 전용으로 재확인했다. 현재 예약 명령과 최근 실패의 중앙 로그는 이 점검에서 읽지 못했고, 중앙 로그 조회 권한은 거절됐다. 운영 적용과 적용 뒤 새 백업의 복원은 별도 단계다. [운영 조회 결과](acceptance/2026-11-07-reviewed-backup-transition/production-readonly.json)

## 2026-11-07 통합 로컬 검토 후보

- 최신 Linux amd64 API·워커 이미지로 격리 PostgreSQL·Redis·Celery·MinIO에서 무료 첫 권과 접근 제어 52개를 확인했다. 기존 낭독의 서명 URL은 실제 저장소에서 읽었고, 캐시에 없는 쪽은 합성을 시작하지 않았다. 별도 API 컨테이너에서는 실제 Redis의 합성 관측으로 준비 상태가 503 → 200 → 503 → 503 → 200으로 바뀌는 것을 확인했다. 유료 제공자 요청은 0회였다. [첫 권 런타임](acceptance/2026-11-07-integrated-local-candidate/oci-first-book.json) · [준비 상태 전이](acceptance/2026-11-07-integrated-local-candidate/oci-readiness.json)
- 홈의 생성 복귀를 포함한 Android arm64 디버그 APK와 iOS arm64 무서명 앱을 빌드했다. APK 서명과 16KiB ZIP 정렬, 최소 iOS 15.0, 두 산출물의 해시를 확인했다. 예약 백업 로컬 후보 파일 195개도 현재 소스와 대조했다. [통합 후보](acceptance/2026-11-07-integrated-local-candidate/candidate.json) · [백업 후보](acceptance/2026-11-07-integrated-local-candidate/backup-candidate-verification.json)
- 기존 제한 운영 HTTPS의 생존·준비 상태·기능 응답은 각각 HTTP 200이었다. 운영 VM의 주소를 확인한 뒤 최근 24시간의 준비 신호 281건은 모두 정상, 백업 신호 141건은 모두 비정상임을 확인했다. 공개 베타 사전 검사는 공개 주소 및 승인된 정책 문서가 없어 차단됐고, 로컬 iOS 배포 프로파일 네 개 중 앱과 일치하는 유효 프로파일은 없었다. [운영 HTTPS](acceptance/2026-11-07-integrated-local-candidate/pilot-https-readonly.json) · [운영 모니터링](acceptance/2026-11-07-integrated-local-candidate/pilot-monitoring-readonly.json) · [배포 서명 점검](acceptance/2026-11-07-integrated-local-candidate/mobile-signing-preflight.json)

## 2026-11-07 제공자 관측 Redis 조회 단축

- 생성 접수와 준비 상태 점검은 관측값과 무효 표시를 Redis 트랜잭션 한 번으로 읽는다. 격리 Redis에서 생성 접수용 왕복은 4회에서 1회, 글·그림·사진·낭독·음성 인식의 전체 조회는 10회에서 1회로 줄었다. 추가 지연이 없는 환경에서 20회씩 비교한 생성 접수용 조회 중앙값은 1.202ms에서 0.399ms였다. [격리 실측](acceptance/2026-11-07-provider-observation-batch/redis-measurement.json)
- 손상된 무효 표시, 다른 제공자의 인증 거절, 정상 응답 후 복구, Redis 연결 실패를 확인했다. 준비 상태 HTTP 503에서 정상 관측 뒤 HTTP 200으로 복귀하는 경로를 포함해 API 전체 검사 3,074개가 통과했고 29개를 건너뛰었다.
- Linux amd64 API·워커 후보를 로컬에서 빌드했다. 각 이미지의 파일 195개를 소스와 대조하고 비관리자 사용자로 실행되는지 확인했다. [이미지 검증](acceptance/2026-11-07-provider-observation-batch/candidate.json)

## 2026-11-07 낭독 제공자 관측 갱신

- 낭독 관측만 갱신해야 할 때, 글·그림 관측이 19시간 이상 남고 영속 원장이 18시간 뒤 새 호출을 허용할 수 있으면 낭독만 확인한다. 시간이 부족하거나 월간 한도로 다음 호출이 늦어지면 같은 갱신에서 글·그림·낭독을 확인한다. 인증 거절이나 갱신 실패는 정상으로 기록하지 않는다.
- 격리 Redis와 SQLite 원장에서 낭독 단독 1회, 전체 3회, 인증 거절 0회, 낭독 실패를 모의 제공자 응답으로 확인했다. 월간 한도와 실제 원장 소비를 포함한 관련 검사 122개가 통과했다. [격리 실행 결과](acceptance/2026-11-07-narration-observation-refresh/result.json) · [운영 절차](PROVIDER_RUNTIME_AND_REPAIR.md#scheduled-pilot-observation-refresh)

## 2026-11-07 홈에서 만들던 동화로 복귀

- 홈이 현재 계정·프로필의 진행 중인 작업을 조회한다. 한 권이면 진행 화면을 바로 열고, 여러 권이면 서재에서 선택한다. 앱이 다시 활성화되거나 생성이 접수·종료되면 목록을 갱신한다. 홈에서 관찰하던 작업이 목록에서 빠지면 책 목록도 새로 읽어 백그라운드에서 완성된 동화를 표시한다. 조회가 실패해도 기존 동화는 열 수 있다.
- 정적 분석과 모바일 전체 검사 751개가 통과했고 2개를 건너뛰었다. 320×480 확대 글씨에서 복귀 버튼을 누를 수 있는지와 앱 복귀 후 목록 갱신, 생성 실패·환불 뒤 안내 갱신, 완료 뒤 기존 홈에 새 책이 나타나는지 확인했다.
- iOS 27.2 시뮬레이터에서 신규 동의·온보딩, 재방문·읽기 성장, 홈에서 기존 작업으로 복귀하는 통합 검사 3개가 통과했다. 모의 서버 응답을 사용했고 복귀할 때 기존 작업 ID만 조회하는지 확인했다. [통합 시험](acceptance/2026-11-07-home-generation-resume/ios.log)

## 2026-11-07 서재 완성 동화 열기 모바일 검증

- iOS 27.2 시뮬레이터와 16KiB 호환 모드를 끈 Android 에뮬레이터에서 가상 7–9세 첫 권을 생성했다. 진행 화면에서 서재로 이동한 뒤 3–5세 필터를 유지한 채 ‘완성된 동화 열기’로 읽기 화면을 열었다. 두 환경 모두 표지와 본문 삽화 13장 표시, 3쪽 이어 읽기, 12쪽 완독, 신고와 설정을 통과했다. 두 시험은 별도 PostgreSQL·Redis·Celery·MinIO와 모의 AI를 사용했고, 완료 응답을 서재 진입 뒤 표시하도록 시험에서 제어했다. [iOS 화면](acceptance/2026-11-07-completed-book-mobile-candidate/ios-filtered-completion.png) · [Android 화면](acceptance/2026-11-07-completed-book-mobile-candidate/android-filtered-completion.png) · [iOS 로그](acceptance/2026-11-07-completed-book-mobile-candidate/ios-native.log) · [Android 로그](acceptance/2026-11-07-completed-book-mobile-candidate/android-native.log)
- Android arm64 디버그 APK를 새로 패키징해 증분 APK의 남은 공간 30,902,358바이트를 줄였다. 최종 APK는 104,085,295바이트이며 서명과 16KiB ZIP 정렬을 확인했다. iOS arm64 무서명 디버그 빌드는 최소 iOS 15.0을 확인했다. [APK 비교](acceptance/2026-11-07-completed-book-mobile-candidate/android-packaging.json) · [산출물 해시](acceptance/2026-11-07-completed-book-mobile-candidate/sha256.txt)

## 2026-11-07 예약 백업 워커 확인 단축

- 실행 중·예약됨·실행 예정 작업을 독립된 Celery 연결 세 개로 동시에 확인한다. 각 조회는 지정된 워커 한 대가 빈 목록을 보냈을 때만 통과한다. API를 멈추기 전과 멈춘 뒤에 DB와 워커 확인을 각각 수행한다.
- 격리 Redis·Celery에서 기존 순차 조회는 33.91초, 병렬 조회는 11.13초였다. 다른 워커만 응답한 경우, 두 워커가 응답한 경우, 세 종류의 작업이 남은 경우, 응답이 없는 경우를 모두 차단했다. 백업 집중 검사 86개를 통과했고 로컬 후보 파일 195개를 현재 소스와 대조했다. 운영의 전체 백업 중단 시간은 별도 측정이 필요하다. [실측 결과](acceptance/2026-11-07-worker-drain-parallel/result.json) · [후보 소스 검증](acceptance/2026-11-07-worker-drain-parallel/candidate-verification.json)

## 2026-11-07 예약 백업 시작 전 원본 확인

- 예약 백업을 시작할 때 PostgreSQL 연결과 `pg_dump`·`pg_restore` 버전, 원본 비공개 S3 목록 조회, 원격 전송용 인증 토큰을 먼저 확인한다. 이 단계에서 실패하면 `source_preflight`로 기록하고 API·worker 중단 절차에 진입하지 않는다. 실제 원격 버킷 권한과 파일 무결성은 전송 단계에서 검증한다.
- 백업 집중 검사 86개를 통과했다. 별도 PostgreSQL 16·MinIO 환경에서 정상 연결, 잘못된 DB, 도구 버전 불일치, 존재하지 않는 원본 버킷을 시험했다. 원격 인증은 시험 대역을 사용했고 운영 서비스의 중단이나 백업을 수행하지 않았다. [원본 확인 시험](acceptance/2026-11-07-backup-source-preflight/result.json) · [후보 소스 확인](acceptance/2026-11-07-backup-source-preflight/candidate-verification.json)

## 2026-11-07 예약 백업 미디어 전송 단축

- 예약 백업은 DB 덤프 검증 후 미디어를 최대 두 개씩 원격 전송하고 각각의 원격 바이트를 검증한다. 전송이 모두 끝난 뒤 manifest를 게시하고, 개인정보 기록과 DB·미디어 경계를 다시 확인한 뒤 완료 표식을 남긴다. 전송 오류가 나면 실행 중인 전송이 끝날 때까지 기다리고 완료 표식 없이 서비스를 복구한다.
- 가상 미디어 12개와 HTTP 요청당 40ms 지연으로 각각 세 번 시험했다. 모의 API 중단 구간 중앙값은 순차 전송 1.4507초, 두 개 병행 0.8827초였다. 실운영 중단 시간은 별도 측정이 필요하다. 백업 집중 검사 73개, 격리 PostgreSQL·비공개 S3 복원 검사 30개를 통과했다. [비교 시험](acceptance/2026-11-07-parallel-backup-upload/result.json) · [복원 시험](acceptance/2026-11-07-parallel-backup-restore-rehearsal/result.json) · [백업 후보 확인](acceptance/2026-11-07-parallel-backup-upload/candidate-verification.json)

## 2026-11-07 계정별 첫 권 무료 안내

- 새 계정의 초대 여부와 첫 권 지급·사용·환불 거래 기록을 확인해 무료 자격을 표시한다. 자격 조회는 크레딧이나 거래를 생성하지 않는다. 유료 잔액, 이미 사용한 첫 권, 복원된 거래 기록만 있는 계정은 새 체험으로 안내하지 않는다.
- 홈·온보딩·만들기에서 자격이 확인된 계정에만 무료 안내를 표시한다. 낭독이 켜진 환경에서는 그림과 낭독을 안내하며, 만들기 버튼은 ‘무료 첫 동화 만들기’로 바뀐다. 서버가 생성 접수를 확인하거나 환불을 보고하면 자격을 다시 읽는다.
- 격리 PostgreSQL·Redis·Celery·MinIO에서 초대 계정 안내, 미초대 계정 제외, 생성 접수 뒤 안내 해제와 기존 첫 권·미디어 여정까지 52개를 확인했다. API 검사에서 환불 뒤 무료 자격이 돌아오는 경로를, 모바일 검사에서 해당 신호가 자격 조회를 갱신하는 경로를 확인했다. [격리 실행 결과](acceptance/2026-11-07-account-first-book-offer-final/result.json)
- API 전체 검사 3,059개와 모바일 전체 검사 746개가 통과했다. 최신 API·worker 이미지로 격리 여정 52개를 다시 실행했다. 최신 Android arm64 디버그 APK의 16KiB 정렬과 iOS arm64 무서명 앱의 최소 대상 iOS 15.0도 확인했다. [컨테이너 시험](acceptance/2026-11-07-account-first-book-offer-final/oci-runtime.json) · [로컬 후보와 해시](acceptance/2026-11-07-account-first-book-offer-final/candidate.json)

## 2026-11-07 연속 낭독의 미리 받기 이어받기

- 연속 낭독이 같은 쪽의 미리 받기와 겹치면 최대 200ms까지 완료를 확인한다. 파일이 준비되면 바로 재사용하고, 늦으면 기존 재생 요청으로 넘어간다. 늦게 끝난 미리 받기 때문에 그다음 쪽의 미리 받기를 놓치는 경우도 처리했다.
- iOS 27.2 시뮬레이터의 가상 3쪽 동화에서 두 상황을 재현했다. 2쪽의 미리 받기를 페이지 전환 직후 풀었을 때 2쪽 일반 요청 없이 재생했다. 미리 받기를 계속 지연시켰을 때는 일반 요청으로 2쪽이 재생된 뒤 3쪽 준비와 재생을 이어갔다. 기존 음원과 로컬 서버를 사용했다. [낭독 전환 검사](acceptance/2026-11-07-narration-prefetch-overlap/result.json)
- 정적 분석과 낭독 집중 검사 45개가 통과했다. 시뮬레이터와 병행한 전체 검사에서 캐릭터 승인 테스트 한 건이 실패했다. 해당 파일의 별도 검사 18개와 시뮬레이터 종료 뒤의 전체 재검사 744개는 통과했다.

## 2026-11-07 긴 본문의 스크롤 표시

- 본문이 화면보다 길 때 오른쪽에 얇은 스크롤 표시를 넣었다. 페이지별로 스크롤을 관리하고 표시는 터치를 받지 않는다. 짧은 본문에는 표시가 그려지지 않는다.
- 320×480 화면과 1.4배 글씨에서 마지막 문장과 완독 버튼까지 내려갈 수 있고, 하단 조작부와 겹치지 않는 것을 확인했다. Android API 36의 16KiB 에뮬레이터에서 가상 동화 《하루와 세 알의 기다림》의 삽화 13장을 표시하고, 마지막 쪽을 직접 밀어 완독 버튼 전체가 보이며 터치할 수 있는 상태를 확인했다. 정적 분석과 모바일 검사 744개가 통과했고 2개를 건너뛰었다. [Android 검사](acceptance/2026-11-07-reader-scroll-affordance/result.json) · [스크롤 뒤 화면](acceptance/2026-11-07-reader-scroll-affordance/reader-end.png)

## 2026-11-07 최신 로컬 앱 패키지와 Android 전권 재생

- 앱 시작 시 출시용 API 주소를 검사한다. 디버그 전용 `API_BASE_URL`은 출시 빌드에서 오류로 처리하고, 운영 주소는 `PROD_API_URL`만 사용한다. 모바일 전체 검사 744개가 통과했고 2개를 건너뛰었다. 정적 분석과 저장소 환경 계약 검사도 통과했다.
- 수정한 모바일 소스로 Android arm64 디버그 APK와 iOS arm64 무서명 디버그 앱을 빌드했다. Android 패키지와 네이티브 라이브러리 3개의 16KiB 정렬 및 디버그 서명을 검사했다. iOS 앱의 실행 파일과 두 프레임워크는 arm64였으며 실행 파일의 대상은 iOS 15.0 이상이었다. [로컬 패키지 검사와 해시](acceptance/2026-11-07-final-local-mobile-candidate/build-result.json)
- Android API 36의 16KiB 에뮬레이터에서 호환 모드를 끈 뒤 《하루와 세 알의 기다림》 삽화 13장과 구연동화 음원을 확인했다. 이미 합성한 12쪽 음원을 1.15배속으로 순서대로 재생했고 마지막 쪽 종료를 확인했다. 이 재생 빌드는 출시 주소 검증 변경 직전의 디버그 소스였다. [Android 결과](acceptance/2026-11-07-final-local-mobile-candidate/android-emulator-result.json) · [마지막 쪽 화면](acceptance/2026-11-07-final-local-mobile-candidate/last-page-android.png)
- 최신 API·worker 컨테이너를 격리 PostgreSQL·Redis·MinIO에 연결했다. 모의 AI로 첫 권 여정 49개 항목을 확인했고, 저장된 음원의 서명과 바이트 일치, 미저장 응답, 다른 계정 및 동의 철회 후 접근 차단을 확인했다. [컨테이너 시험](acceptance/2026-11-07-final-local-mobile-candidate/oci-runtime.json)
- 로컬 운영 구성의 제한 베타 사전 검사에서 공개 API·정책 주소, 정책 승인과 시행일, 운영 기능 및 제공자 설정이 준비되지 않았다. 이 점검의 입력은 로컬 운영 구성 파일이었다. [사전 검사](acceptance/2026-11-07-final-local-mobile-candidate/free-beta-preflight.json)

## 2026-11-07 선택 학습 자료의 대기 한도

- 검수를 마친 책의 선택 학습 자료는 한 번만 시도한다. 기본 대기 한도는 95초이며, 그림 검수 뒤에 남은 시간이 더 짧으면 그 안에서만 기다린다. 시간이 없거나 학습 요청이 시간 초과되면 본문과 삽화를 정상 저장한다.
- OpenAI Responses 경로의 12쪽 학습 자료 요청을 추론을 포함한 16,000토큰 상한에 맞췄다. 격리 첫 권 시험은 학습 자료가 실제 응답에 포함됐는지 별도 필드에 기록한다. 수정한 상한으로 실제 학습 자료를 생성하는 검증은 남아 있다. [격리 무료 첫 권 시험](acceptance/2026-11-07-optional-learning-first-book-runtime/result.json)
- 제한 운영 HTTPS 준비 상태는 200이었다. 최근 24시간에 준비 신호 280건은 모두 정상, 백업 신호 139건은 모두 비정상이었고 독립 기록 감시 지표는 조회 결과가 없었다. [읽기 전용 운영 확인](acceptance/2026-11-07-optional-learning-operations-readonly/result.json)

## 2026-11-07 본문 오류 수정 후 실제 첫 권

- 격리 서버에서 가상 7–9세 동화 《하루와 세 알의 기다림》을 373.33초에 완성했다. 12쪽 모두 43–51어절로 총 553어절이다. 무료 크레딧이 1에서 0으로 바뀌었고 동일 작업으로 복귀한 뒤 서재에서 완성본을 열었다. 삽화 13장과 계정 간 접근 차단을 확인했다. 제공자 관측 뒤 격리 API의 준비 상태도 정상으로 바뀌었다. [생성 결과](acceptance/2026-11-07-live-length-fixed-first-book/result.json) · [삽화 모음](acceptance/2026-11-07-live-length-fixed-first-book/visual-review.jpg)
- 글 요청 8회와 그림 요청 16회를 사용했다. 7·8쪽을 동시에 교정했고 8쪽을 한 번 더 교정했다. 최종 자동 검사에서 13장 모두 통과했다. 보호자 역할 검토에서 7쪽에 본문에 없는 어른 곰이 보인다는 지적이 있었다. 그림 교정 지시에서 특정 인물 유형의 예시를 빼고, 장면에 참여하는 인물만 그리도록 했다. 이전 그림에서 추가 인물이 생긴 원인은 확정하지 못했다. 변경한 지시의 회귀 검사 100개를 통과했다.
- 가상 동화 12쪽을 Gemini Kore 구연동화 스타일로 실제 합성했다. 요청 12회가 모두 성공했고 합성에는 66.34초가 걸렸다. 모든 음원을 PCM으로 디코딩했고 마지막 쪽은 30.19초였다. 선택 학습 자료는 이 표본에서 생성되지 않았다. 격리 시험의 글 응답 상한이 해당 요청의 설정값보다 낮았다. [낭독 합성 결과](acceptance/2026-11-07-live-length-fixed-first-book/review-audio/result.json) · [음원 신호 검사](acceptance/2026-11-07-live-length-fixed-first-book/review-audio/signal-check.json)
- 최신 앱으로 iOS 27.2 시뮬레이터에서 그림 13장을 표시하고 실제 합성 음원을 1.15배속으로 1쪽부터 12쪽까지 재생해 마지막 쪽 종료를 확인했다. 새 생성·합성 결과를 격리 로컬 서버에서 전달했고 시험용 시뮬레이터를 정리했다. [기기 검사](acceptance/2026-11-07-live-length-fixed-first-book/device-result.json) · [마지막 쪽 화면](acceptance/2026-11-07-live-length-fixed-first-book/last-page-simulator.png)
- 그림 교정 지시 수정 이후 API 전체 검사 3,054개가 통과했고 29개를 건너뛰었다. 모바일 전체 검사 740개가 통과했고 2개를 건너뛰었다. 최신 Linux amd64 API·worker 이미지를 로컬에서 빌드하고 각 이미지의 실행 파일 195개를 소스와 대조했다. [로컬 이미지 기록](acceptance/2026-11-07-live-length-fixed-first-book/candidate-oci.json)

## 2026-11-07 첫 권 생성 오류와 분량 기준 조정

- 가상 7–9세 무료 첫 권 시험에서 글 모델은 응답했으나 약 43초에 본문 단계가 `UNKNOWN`으로 끝났다. 분량 보정용 응답 형식이 OpenAI 허용 목록에 빠져 있었다. 해당 형식을 등록하고, 40어절 이상 9쪽을 목표로 유지하되 한 쪽이 38–39어절이면 통과하도록 앱과 실호출 시험 기준을 맞췄다. [변경 전 실제 생성 결과](acceptance/2026-11-07-live-repair-slot-first-book/result.json)
- 마케팅·보호자 역할 검토에서 기다림과 비슷한 장면의 반복이 작은 어절 차이보다 눈에 띄었다. 앞쪽의 발견이 다음 쪽 사건으로 이어지고 교훈이 행동과 결말에서 드러나도록 7–9세 집필 지시를 수정했다. 홈·온보딩·만들기의 무료 첫 권 안내에 그림과 낭독을 명시했다.
- 모바일 정적 분석과 집중 검사 27개가 통과했다. 격리 PostgreSQL·Redis·Celery·MinIO에서 모의 AI로 무료 첫 권의 생성·복귀·보호된 미디어 등 49개 항목을 확인했다. [격리 서버 결과](acceptance/2026-11-07-first-book-light-qc-runtime/result.json)

## 2026-11-07 첫 권 체험과 연속 낭독

- 서재에서 기다리던 작업이 완료되면 현재 연령·스타일 필터를 유지한 채 ‘완성된 동화 열기’를 표시한다. 필터가 새 책을 숨겨도 뷰어로 이동하며 계정 또는 프로필이 바뀌면 이전 작업의 버튼을 숨긴다. 집중 위젯 검사와 모바일 전체 검사 746개가 통과했고 2개를 건너뛰었다. 마케팅·보호자 역할 검토는 기존 실제 가상 표본을 사용했다.
- 마케팅과 보호자 역할의 검토에서 무료 혜택이 보이는 위치와 전권 낭독의 발견성을 우선했다. 코드를 바탕으로 한 역할 검토이며 실제 고객 조사는 진행하지 않았다.
- 홈의 빈 서재와 만들기 버튼 위에 기능이 켜진 경우에만 대상 계정의 첫 권 무료 혜택을 표시한다. 온보딩의 무료 안내도 동일한 기능 조건을 적용한다. 작업 중 서재를 둘러볼 수 있고 완성된 책을 어디서 열 수 있는지 생성 화면에서 설명한다.
- 최신 7–9세 가상 표본을 마케팅과 보호자 역할로 다시 검토했다. 그림의 작은 차이는 수용 가능했고, 약 6분 42초의 제작 시간 동안 기다리는 경험이 우선이었다. 무료 첫 권 버튼 옆에 몇 분 걸릴 수 있다고 안내한다. 진행 화면에서 서재로 이동하면 기존 작업 조회를 이어가고, 완료 후 화면을 옮기지 않은 채 선택한 서재 필터를 유지하며 목록을 갱신한다.
- iOS 시뮬레이터에서 별도의 새 초대 계정으로 보호자 동의, 무료 안내와 7–9세 12쪽 생성, 크레딧 1→0, 표지와 3쪽 이미지, 서재 재진입 시 3쪽 복귀, 신고 접수, 완독 및 설정까지 검증했다. 격리 PostgreSQL·Redis·Celery·비공개 MinIO의 검사 49개도 통과했다. AI는 모의 제공자를 사용했다. 전용 시뮬레이터, 일회용 설정 파일과 서버 리소스를 정리했다. [iOS 통합 결과](acceptance/2026-11-07-native-first-book-trial/flutter.log) · [서버 검사](acceptance/2026-11-07-native-first-book-trial/runtime.json)
- 호환 모드를 끈 16KiB Android 에뮬레이터에서 같은 무료 첫 권 여정을 실행했다. 별도 초대 계정이 생성한 가상 책에서 표지와 본문 삽화 13장이 모두 디코딩됐고, 3쪽 이어 읽기와 완독이 통과했다. 배포에 고정된 FastAPI 0.162.0으로 별도 격리 서버 검사 49개와 생성·준비 상태·OpenAPI 검사 24개가 통과했다. Android 앱 통합은 기존 로컬 API 환경에서 모의 AI로 실행했다. [Android 결과](acceptance/2026-11-07-android-native-first-book-trial/flutter.log) · [배포 의존성 서버 결과](acceptance/2026-11-07-android-native-first-book-trial/pinned-runtime.json)
- 표지에서 처음부터, 본문 더보기에서 현재 쪽부터 연속 낭독을 시작할 수 있다. 수면 타이머는 별도 동작이다. 작은 화면·확대 글씨에서 늦게 조회된 읽기 위치가 표지에서 선택한 첫 쪽 낭독을 덮어쓰지 않는지 확인했다. 모바일 전체 검사 736개가 통과했고 2개는 건너뛰었다. Android arm64 디버그 APK의 서명과 16KiB 정렬을 확인했다.
- iOS 27.2 시뮬레이터에서 보관한 가상 7–9세 동화로 표지의 연속 낭독을 시작했다. 표지와 본문 삽화 13장을 확인하고 수면 타이머 없이 1–12쪽을 순서대로 재생해 마지막 쪽 종료를 확인했다. 새 AI 호출은 발생하지 않았다. 최신 앱의 iOS arm64 무서명 빌드와 최소 iOS 15.0도 확인했다. [시뮬레이터 결과](acceptance/2026-11-07-cover-continuous-narration-simulator/result.json)
- 만들기 화면의 연령별 예시에 동일한 연 찾기 장면의 그림을 추가했다. 가상 인물로 제작한 기존 검수 자료를 사용했다. 한국어·영어·일본어 본문이 그림과 같은 장면을 설명하며, 미리보기는 앱에 포함한 파일로 표시한다. 관련 위젯 검사 36개 및 모바일 전체 검사 736개가 통과했고 Android APK와 iOS arm64 무서명 앱에 삽화가 포함된 것을 확인했다. [최신 로컬 빌드 해시](acceptance/2026-11-07-illustrated-preview-builds/sha256.txt)
- 낭독을 선택하면 이전 재생 위치를 읽는 동안 요청한 쪽의 음원을 조회한다. 하단에 준비 상태를 표시하고, 저장 위치는 같은 쪽·언어·목소리·스타일·제공자에만 적용한다. 작은 화면과 확대 글씨에서 준비 문구, 중복 요청 차단, 페이지를 바꾼 뒤 늦은 응답 무시를 확인했다. 모바일 전체 검사 739개와 최종 집중 검사 57개가 통과했다. iOS 시뮬레이터와 16KiB Android 에뮬레이터에서 저장 위치가 늦게 도착하는 재생·일시정지·이어 듣기와 앱에 포함된 세 스타일 샘플 재생을 확인했다. [iOS 네이티브 시험](acceptance/2026-11-07-narration-start-native/flutter.log) · [Android 네이티브 시험](acceptance/2026-11-07-narration-start-native-android/flutter.log)
- 연속 낭독에서는 서버에 이미 저장된 다음 한 쪽의 음원만 미리 내려받는다. 새 조회 경로는 소유권·프로필·동의를 확인하고 합성을 시작하지 않는다. iOS 시뮬레이터와 16KiB Android 에뮬레이터에서 1쪽을 듣는 중 2쪽을 준비해 그 파일을 재생했고, 저장 음원이 없는 3쪽은 실제로 넘어간 뒤에만 일반 낭독 요청을 보냈다. 앱에 보관한 음원으로 시험했다. API 검사 49개와 모바일 전체 검사 740개가 통과했다. [iOS 결과](acceptance/2026-11-07-narration-prefetch/ios.log) · [Android 결과](acceptance/2026-11-07-narration-prefetch/android.log)
- 음원 미리 받기를 포함한 현재 소스로 Android 디버그 APK, iOS 무서명 앱, Linux amd64 API·worker 이미지를 다시 만들었다. 두 앱의 음성 샘플 9개와 Android 16KiB 정렬을 검사했다. 두 이미지의 런타임 파일 193개씩을 소스와 대조하고, 격리 PostgreSQL·Redis·Celery·MinIO에서 초대용 무료 첫 권 검사 49개를 통과했다. 새 음원 조회는 저장된 MP3의 서명과 바이트 일치, 익명 미디어 접근 거부, 미저장 응답, 다른 계정과 동의 철회 이후 접근 거부를 확인했다. 격리 시험에서 유료 제공자를 호출하지 않았다. [후보 및 해시](acceptance/2026-11-07-prefetch-release-review/result.json) · [격리 서버 결과](acceptance/2026-11-07-prefetch-release-review/runtime.json)

## 2026-11-07 실제 AI 첫 권 체험 재검증

- 조정한 삽화 검수 기준과 초대 전용 무료 체험을 함께 켠 격리 환경에서 가상 7–9세 동화 《하루와 기다림의 씨앗》을 새로 생성했다. 12쪽 모두 43–51어절, 총 575어절이었다. 새 클라이언트가 진행 중인 작업을 찾았고, 완료 후 서재에서 열었다. 무료 크레딧은 1에서 0이 됐다. 서명된 삽화 13장과 다른 계정의 접근 차단을 확인했다. [실제 생성 기록](acceptance/2026-11-07-reader-quality-first-book/result.json)
- 그림 요청은 16회, 글·검수 요청은 9회였다. 4쪽을 두 번, 9쪽을 한 번 다시 그린 뒤 13장 모두 최종 검수를 통과했다. 생성 전체는 402.35초였고 최초 삽화 검수부터 완료까지 167.70초였다. 교정 진행률은 완료된 교정 수에 따라 최대 92%까지 올라가도록 변경했고, 관련 API 검사 194개가 통과했다. 최종 검수에서 저장소의 현재 바이트를 다시 읽는 동작은 유지한다.
- 새 격리 API는 제공자 호출 관측 전 HTTP 503이었다. 실제 글·그림 호출이 성공한 뒤 HTTP 200과 제공자 정상 상태를 확인했다. 격리 DB·큐·저장소는 정리했다. 로컬 Google ADC 갱신 실패로 이 책의 새 Gemini 낭독은 합성하지 않았다. [실제 호출 후 준비 상태](acceptance/2026-11-07-reader-quality-first-book/readiness-after-provider.json)
- 후속 시험에서는 기존에 승인된 Google Cloud CLI 인증과 격리 요청 한도를 사용했다. 같은 가상 동화 12쪽을 Gemini의 Kore 구연동화 스타일로 합성했다. 요청 12회가 성공했고 재시도는 0회였으며 모든 MP3가 디코딩됐다. 합성은 약 169초, 음원 길이 합계는 약 384초였다. 운영 ADC 및 운영 낭독 API 인증은 별도 검증 대상이다. [실제 합성 기록](acceptance/2026-11-07-reader-quality-first-book/review-audio/result.json)
- 뷰어의 더보기에서 낭독 속도를 0.9·1·1.15·1.3배 중 선택할 수 있게 했다. 기기에 선택을 저장하고 같은 음원에 적용한다. 작은 화면의 뷰어와 오디오 기능을 포함한 집중 검사 55개가 통과했다.
- 합성한 실제 음원 12개에 지속적인 오디오 신호가 있었고, 시작 무음은 최대 0.3초, 끝 무음은 최대 0.2초였다. 같은 책을 iOS 시뮬레이터에서 1배속, 16KiB Android 에뮬레이터에서 1.15배속으로 재생했다. 두 환경에서 삽화 13장과 1–12쪽 순서 및 마지막 쪽 종료를 확인했다. 이미 만든 음원을 격리 로컬 서버로 전달했으며 재생 중 추가 합성은 없었다. 모바일 전체 테스트 737개가 통과했고 2개는 건너뛰었다. [음원 신호 검사](acceptance/2026-11-07-reader-quality-first-book/review-audio/signal-check.json) · [iOS 결과](acceptance/2026-11-07-gemini-first-book-simulator/result.json) · [Android 결과](acceptance/2026-11-07-gemini-first-book-android-retry/result.json) · [최신 로컬 빌드 해시](acceptance/2026-11-07-narration-speed-mobile-builds/sha256.txt)
- 제한 운영을 읽기 전용으로 조회했다. HTTPS 준비 상태는 HTTP 200이었고 최근 24시간 준비 신호 280건은 모두 정상, 백업 신호 139건은 모두 비정상이었다. 기능 응답에서 Gemini 낭독·스타일 선택은 확인됐으며 무료 첫 권과 생성 초대 항목은 확인되지 않았다. [운영 관측 기록](acceptance/2026-11-07-narration-operations-status/result.json)

## 2026-11-07 운영 백업 예약 인자 불일치

- systemd가 실행하는 별도 고정 백업 코드의 실패 줄은 현재 작업 트리의 같은 줄과 의미가 달랐다. 실제 실행본의 실패는 기록 저장소 연결 불일치였다. 예약 실행 인자에 `--journal-witness-bucket`이 없었지만 실행 중인 API·worker는 둘 다 동일한 독립 기록 저장소를 쓰고 있었다. 예약은 활성 상태이며, 운영 백업의 성공 여부는 새 원격 검증 표식으로 확인한다.
- 예약과 같은 입력을 사용하는 `run_scheduled_backup.py --check-bindings` 모드를 추가했다. 서비스 중지, 백업 기록 생성, 복원 승인 없이 입력 파일·실행 이미지·DB·미디어·개인정보 기록 연결을 검증한다. 설정 오류는 항목 이름만 기록한다. 백업 관련 회귀 검사 44개와 격리 PostgreSQL·비공개 저장소의 합성 복원 검사 30개가 통과했다. [로컬 후보 명세](acceptance/2026-11-07-backup-bindings-candidate/manifest.json) · [격리 복원 기록](acceptance/2026-11-07-scheduler-restore-rehearsal/result.json)
- 실제 예약 인자에 현재 독립 기록 저장소 인자를 보충하고 후보를 VM 메모리에서 실행했다. Docker는 조회만 허용했으며 결과는 `BINDINGS_CHECKED`, 종료 코드 0이었다. 서비스와 기존 예약 설정은 유지됐고 새 백업 생성은 운영 적용 후 확인할 항목이다.
- 전환 전 검사는 운영 systemd에 로드된 백업 명령을 읽는다. API와 worker가 독립 기록 저장소를 사용하는 구성에서 백업 명령에 해당 인자가 빠졌거나 중복됐거나 systemd 설정을 다시 로드해야 하면 전환을 막는다. 관련 집중 검사 129개가 통과했다.
- `--plan-systemd-witness`는 로드된 명령과 고정 스크립트의 해시를 확인하고, 예약 명령의 검증 저장소 인자만 보충한 drop-in을 출력한다. 실제 Linux systemd에서 기존·보완·되돌리기 설정의 구문 검사를 통과했고, 관련 집중 검사 108개와 합성 PostgreSQL·비공개 저장소 백업·복원 리허설을 통과했다. 운영 적용과 새 백업의 격리 복원은 남아 있다. [적용·되돌리기 런북](BACKUP_RESTORE.md) · [Linux 구문 검사](acceptance/2026-11-07-witness-plan-systemd-fixture/systemd-verify.log) · [격리 복원](acceptance/2026-11-07-witness-plan-restore-rehearsal/result.json)
- 백업 복구 후보는 API 응답, 지정 Celery 워커 응답, nginx 재로딩 뒤 워커 교체를 확인한 뒤 복구 기록을 지운다. 격리 Docker에서 백업 프로세스를 중단하고 Redis 응답을 막자 두 컨테이너가 실행 중이어도 기록이 남았다. Redis 복귀 후 다시 실행했을 때 기록이 지워졌고 첫 프록시 요청이 성공했다. 집중 검사 77개가 통과했다. 운영 VM의 재부팅은 별도 확인 대상이다. [격리 복구 결과](acceptance/2026-11-07-backup-recovery-liveness/result.json)
- 부팅과 예약 백업 종료 시 실행되는 복구 명령은 잠금 경합·서비스 응답 실패에 최대 세 번, 150초 한도로 대응한다. 격리 Docker에서 첫 시도에 Redis를 멈추고 복구 기록 보존을 확인한 뒤 Redis를 재개했다. 같은 명령의 두 번째 시도에서 API·Celery·nginx가 복구됐고 첫 프록시 요청이 통과했다. 재시도 사이에 전환 기록이 생기면 중단하는 경우와 세 번 실패해 기록을 보존하는 경우를 포함해 집중 검사 82개가 통과했다. [자동 재시도 결과](acceptance/2026-11-07-backup-recovery-retry/result.json)

## 2026-11-07 최신 모바일 빌드와 운영 여유 확인

- 현재 작업 트리의 모바일 소스로 Android arm64 디버그 APK와 iOS arm64 무서명 앱을 빌드했다. Android 디버그 서명, APK 16KiB 정렬과 네이티브 라이브러리 3개의 ELF 16KiB 정렬을 확인했다. iOS 실행 파일의 대상은 iOS 15.0 이상이다. 두 산출물은 로컬 검증용이다. [빌드 해시와 검사 결과](acceptance/2026-11-07-current-mobile-builds/result.json)
- 생성 단계 안내를 반영한 뒤 두 앱을 다시 빌드했다. 새 Android APK의 디버그 서명과 ZIP 16KiB 정렬을 검사했고, 새 iOS 무서명 앱은 arm64 및 최소 iOS 15.0을 확인했다. 실기기 설치는 개발을 마친 뒤 진행한다.
- 운영 e2-micro의 메모리는 1GiB다. Cloud Monitoring 최근 24시간 표본의 최고 CPU 사용률은 86.58%, 게스트 메모리는 65.80%, 스왑은 52.27%였다. 현재 부하의 관측값이며 4장 병렬 생성 여유를 입증하지 않는다. 기본값은 3장을 유지했고, 동시 이미지 요청 수를 0으로 설정하면 앱 시작 및 배포 전 검사에서 거부한다. 현재 제한 운영 HTTPS의 생존·준비 상태·기능 응답은 각각 200이었다.
- 공개 베타 사전 검사는 공개 API 주소와 승인된 개인정보처리방침·이용약관 입력이 없어 차단 상태다. 운영 백업도 최근 30시간 상태 신호 174건 모두 이상을 보고했다. VM의 타이머는 활성 상태지만 최근 서비스 실행은 종료 코드 1이었고, 원격 저장소의 최신 검증 표식은 조회 시점보다 약 70시간 전이었다. 위 예약 인자 조사에서 실제 실패 원인을 확인했다.
- 8쪽의 창 안팎 배치가 인물 외모 설명 뒤에 묻히지 않도록 중심 행동과 공간 경계를 먼저 쓰게 했다. 복원한 가상 시험 본문에서 모델 출력 첫 문장에 마른 방, 닫힌 창, 창 밖 빗물통의 관계가 들어갔다. 시험 도구는 실내를 뜻하는 표현을 좁게 검사해 이미지 호출 전에 중단됐으므로, 최신 지시의 첫 삽화 판정은 추가 확인이 필요하다. [지시 시험 결과](acceptance/2026-11-07-window-explicit-boundary/result.json)
- 시험 도구가 동등한 실내 표현을 허용하도록 고쳐 8쪽 한 장을 새로 그렸다. 아이들은 실내에 있고 빗물통은 창 밖에 있는 것을 눈으로 확인했다. 보관한 나머지 그림 12장을 함께 제출한 전체 검수에서 13장 모두 지적 없이 통과했다. [한 쪽 재시험 결과](acceptance/2026-11-07-window-checked-replay/result.json)

## 2026-11-07 12쪽 삽화 병렬 처리와 안전 장면 재검증

- 실제 제공자를 사용한 빗물 정원 주제의 격리 표본에서 표지·본문 삽화 생성 구간은 3장 병렬 165.64초, 4장 병렬 135.53초와 129.59초였다. 앞의 두 책은 품질 검수 단계에서 중단됐으며, 새 책의 구간은 3장 병렬 표본보다 36.05초 짧았다. 같은 주제로 새로 생성한 서로 다른 책의 표본이므로 전체 생성 시간의 일반적인 개선율은 별도로 측정한다. 병렬 비교는 `scripts/run_live_book_acceptance.py --image-concurrency 4`로 재현한다. 4장 설정은 격리 시험에서 검증했으며 운영 기본값은 3장이다. [3장 표본](acceptance/2026-11-07-illustration-latency/result.json) · [4장 첫 표본](acceptance/2026-11-07-image-concurrency-four/result.json)
- 4장 첫 표본은 높은 턱에서의 어른 시범을 그린 4쪽이 안전 검수에서 차단됐다. 본문과 삽화 지시에 지면 모형과 작업 구역 밖 관찰을 반영해 다시 생성했다. 새 《하루와 빗방울 정원》은 289.50초에 완성됐고, 12쪽 모두 47–57어절로 총 643어절이었다. 지면 모형을 보여 주는 4쪽은 첫 검수를 통과했다. 8쪽을 한 번 교정해 아이들은 실내, 빗물통은 창 밖에 표시했고 전권 재검수에서 13장 모두 통과했다. 그림 요청은 교정 1회를 포함해 14회였다. 서명 미디어 다운로드, 다른 계정의 접근 거부, 무료 PDF 제한을 확인했다. [완성 및 정리 기록](acceptance/2026-11-07-image-concurrency-grounded/result.json) · [본문](acceptance/2026-11-07-image-concurrency-grounded/book.json)
- 품질 검수는 모든 저장소 키를 먼저 확인하고 최대 3장씩 읽는다. 실패하면 대기 중인 읽기를 정리하며, 페이지와 이미지의 대응 순서를 유지한다. OpenAI 편집 요청은 참조 그림을 원본 바이트로 보내고 Gemini의 기존 Base64 입력은 유지한다. API 집중 검사 303개와 배포 의존성 환경 집중 검사 256개가 통과했다.
- OpenAI와 Gemini의 본문 삽화 생성은 한 권 안에서 HTTPS 연결을 재사용한다. 로컬 HTTPS 서버에 같은 요청 12개를 최대 3개씩 보냈을 때 TLS 연결은 12개에서 3개로 줄었다. 제공자 호출 한도와 품질 검사는 유지된다. 배포에 고정된 FastAPI 0.162.0으로 전체 API 검사 3,008개가 통과했고 29개는 건너뛰었다. 실제 제공자를 사용한 총 생성 시간은 따로 측정해야 한다.
- OpenAI·Gemini 이미지 요청에 일시적 429가 돌아오면 `Retry-After`와 재시도 간격을 적용한다. 같은 책에서 아직 전송하지 않은 요청도 해당 시각까지 대기하고, 작업 마감 또는 요청 시간 한도 안에 대기할 수 없으면 새 제공자 호출 없이 중단한다. 모의 429 검사에서 11초 동안 호출 수가 늘지 않았고, 할당량 소진은 재시도 없이 차단했다. 격리 무료 첫 권 검사 49개와 전체 API 검사 3,037개가 통과했다. 정상 응답에서의 실제 생성 시간은 이번 시험으로 측정하지 않았다. [429 검사](acceptance/2026-11-07-image-throttle/provider-429.log) · [격리 서버](acceptance/2026-11-07-image-throttle/runtime.json) · [전체 API](acceptance/2026-11-07-image-throttle/full-api.log)
- 새 책에서 표지가 검수를 통과하면 본문 교정 요청을 최대 두 건씩 처리한다. 교정 한도·마감 시간과 전권 재검수는 유지한다. 고정 0.2초 응답으로 세 장을 교정한 모의 시험의 중앙값은 순차 0.609초, 병렬 0.408초였다. 격리 Celery 시험에서 일부러 세 장의 교정 결과를 요구해 두 건이 겹쳐 실행됐고, 세 장을 고친 뒤 13장을 다시 검수해 무료 첫 권 HTTP 검사 49개를 통과했다. 변경 집중 검사 153개도 통과했다. 실제 제공자의 교정 소요 시간은 별도 측정 대상이다. [격리 실행 결과](acceptance/2026-11-07-parallel-illustration-repair/result.json)
- 남은 시간 계산에 실제 병렬 슬롯을 반영하고, 먼저 끝난 교정의 슬롯에 다음 쪽을 바로 배정한다. 승인된 표지만 교정 참조로 쓰고, 실패가 관측되면 추가 요청을 시작하기 전에 처리한다. 같은 모의 응답 6회씩의 교정·재검수 중앙값은 0.427초에서 0.305초로 줄었다. 격리 Celery에서 느린 두 번째 교정이 끝나기 전에 세 번째가 시작됐으며, 전체 13장 재검수와 무료 첫 권 HTTP 검사 49개를 통과했다. 집중 검사 117개도 통과했다. 실제 제공자 호출 없이 측정했다. [비교 측정](acceptance/2026-11-07-repair-slot-scheduling/benchmark.json) · [Celery 시험](acceptance/2026-11-07-repair-slot-scheduling/runtime.json)
- 기본 동시 요청 수 3개로 실제 AI가 만든 7–9세용 《하루와 기다림의 씨앗》은 본문 12쪽 모두 44–56어절, 총 626어절이었다. 표지와 본문 13장 생성 구간은 상태 조회 기준 약 156초였다. 1·5·8·11쪽의 행동 불일치가 교정 허용 3쪽을 넘겨 전체 작업은 257.44초에 차단됐고 격리 환경을 정리했다. 1쪽 씨앗을 든 인물과 8쪽 흙에 남은 자국 크기를 직접 대조했다. [실제 표본과 실패 기록](acceptance/2026-11-07-latest-live-default-three/result.json)
- 1쪽 재현에서 기존 장면 지시에 일반적인 손·소품 연결 문구만 보태면 씨앗을 든 인물이 다시 바뀌었다. 같은 표지를 사용해 장면 지시에 토끼의 옷·위치·씨앗을 든 손과 곰의 빈손을 직접 지정하자 그림에서도 역할이 맞았다. 장면 지시 생성 규칙에 이 구분과 작은 접촉의 크기를 반영했고 관련 검사 157개가 통과했다. 1쪽 비교는 수동으로 장면 지시를 구체화한 표본이며, 새 지시의 자동 전권 생성과 낭독은 재검증이 필요하다. [첫 재현 그림](acceptance/2026-11-07-seed-owner-replay/page-01.png) · [구체화한 장면 재현](acceptance/2026-11-07-seed-actor-grounded-replay/page-01.png)
- 수정한 지시로 같은 주제의 새 7–9세 동화를 자동 생성했다. 본문 12쪽 모두 42–54어절, 총 584어절이었다. 첫 검수에서 10·11쪽을 지적했고 실제 교정 두 요청은 각각 28.53초와 29.24초, 교정 구간 전체는 상태 조회 기준 30.24초였다. 전권 재검수에서는 두 쪽과 함께 바이트가 그대로인 8쪽도 지적돼 남은 교정 한도를 넘겼고, 317.28초에 발행을 차단했다. 이 표본에는 낭독을 생성하지 않았다. [자동 재검증 결과](acceptance/2026-11-07-automatic-grounded-book/result.json)
- 후속 변경에서 무거운 물건을 옮기는 어른과 관찰하는 아이의 역할을 본문부터 분리하고, 시간 경과가 있는 장면은 한 순간으로 맞추며, 무릎 높이처럼 명시된 크기의 기준이 그림에 보이도록 했다. 교정 요청에서는 기존 교정 지시와 겹치는 손·소품 문구를 생략해 전체 장면과 본문을 길이 한도 안에 보존한다. 배포 의존성 환경의 전체 API 검사 3,011개가 통과했고 29개는 건너뛰었다. 후속 지시로 전권을 다시 자동 생성한 검증은 남아 있다.
- 후속 지시로 같은 주제의 새 책을 자동 생성했다. 7–9세 본문은 12쪽 모두 46–54어절, 총 590어절이었다. 최초 검수에서 7·9·11쪽을 교정했고, 전체 재검수에서 7·9쪽이 계속 지적돼 342.18초에 발행을 차단했다. 7쪽은 화분 옆 조약돌을 화분 안에 그렸고, 9쪽은 화분을 돌리는 토끼와 낙엽을 줍는 곰의 역할을 바꿔 그렸다. 이 표본에는 낭독을 생성하지 않았고 격리 환경을 정리했다. [자동 재검증 결과](acceptance/2026-11-07-aligned-scene-book/result.json)
- 행동 불일치 교정 요청은 본문을 맨 앞에 두고 기존 그림 지시는 본문과 양립하는 세부에만 사용하도록 바꿨다. 화분처럼 경계가 있는 물체의 안과 옆을 구분하는 문구도 넣었다. 네 제공자의 전송 순서, 원문 보존과 요청 길이 한도를 포함해 집중 검사 155개가 통과했다.
- 본문 순서만 바꾼 별도 재현에서는 7·9쪽을 새로 그렸지만 두 오류가 그대로 남았다. 보관한 11장을 함께 제출한 전권 재검수도 같은 두 쪽을 지적했다. 새 그림 지시에서는 장면과 인물 외형을 분리해 기록한다. 검수를 통과한 표지를 사용할 수 있는 행동 교정은 해당 본문과 외형 메모로 구성하고, 이전 장면은 보내지 않는다. 외형 메모나 참조 표지가 없는 기존 경로는 전체 시각 지시를 사용한다. 관련 집중 검사 158개가 통과했다. [두 장 재현 기록](acceptance/2026-11-07-narrative-first-repair-replay/result.json)
- 보관한 가상 본문으로 글 모델에 삽화 지시를 한 번 요청했다. 12쪽 모두 인물 외형 메모를 생성했고, 7·9쪽 교정 요청에 해당 쪽의 본문과 외형이 들어가고 기존 장면은 빠지는 것을 확인했다. 이 시험은 그림 요청 없이 최신 교정 입력을 확인했다. [외형 분리 검증](acceptance/2026-11-07-cast-only-brief-probe/result.json)
- 외형 분리 방식으로 보관한 7·9쪽 두 장을 실제로 교정했다. 두 요청은 병렬로 33.64초에 끝났다. 7쪽 조약돌은 화분 밖으로 옮겨졌지만 토끼에게 원본에 없던 멜빵바지가 생겼고, 9쪽은 토끼와 곰의 역할이 바뀐 상태였다. 다른 그림 11장을 함께 제출한 전권 검수에서 두 쪽 모두 외형과 행동 문제로 지적됐다. 처음에는 로컬 검수 도구 오류로 검수 요청이 전송되지 않았다. 받은 그림을 그대로 재사용해 검수만 1회 실행했다. [전권 검수 기록](acceptance/2026-11-07-cast-only-repair-replay/review-result.json)
- 표지와 기존 장면 지시에 맞춰 외형 메모를 재구성하고, 9쪽 교정에 새 시점과 배치를 명시해 한 번 더 요청했다. 토끼의 멜빵바지는 사라졌지만 표지처럼 곰이 화분을 잡았고 토끼가 낙엽을 모았다. 새 구도 지시는 제품 코드에 남기지 않았고, 외형 메모에는 같은 쪽 장면 지시에 있는 특징만 사용하도록 생성 규칙을 보완했다. [9쪽 재시험](acceptance/2026-11-07-distinct-repair-shot/result.json)
- 표지 없이 같은 장면을 요청해도 9쪽 역할은 바뀐 채였고, 수채화 질감은 입체 표현으로 달라졌다. 표지 사용은 유지한다. 세부 역할 분담은 장면과 결말의 의미를 유지하면 허용하도록 검수 기준을 보정했다. 안전, 인물의 핵심 외형, 본문을 오해하게 하는 행동 및 중심 소품 검수는 적용한다. 보관한 그림에 대한 반복 생성은 여기서 종료했다. [표지 제외 비교](acceptance/2026-11-07-reference-free-action-probe/result.json)
- 운영 복구 조건의 디렉터리 권한 검사 두 건은 실행 환경의 `umask 077`이 시험용 공개 디렉터리를 비공개로 바꿔 실패했다. 시험에서 의도한 파일 권한을 명시적으로 설정했고, 같은 `umask`로 운영 조건과 삽화 교정 등 집중 검사 160개가 통과했다.
- 최신 소스의 별도 격리 PostgreSQL·Redis·Celery·MinIO 시험에서 PostgreSQL 회귀 21개, 서명 미디어·소유권 검사 19개, 가상 캐릭터 승인·생성·삭제 검사 26개와 전체 HTTP 읽기 흐름이 통과했다. 이 시험은 모의 AI를 사용했고 종료 후 환경을 정리했다. [실행 기록](acceptance/2026-11-07-current-runtime/result.json)

## 2026-11-07 삽화 생성 진행률과 교정 검증

- 모바일 생성 화면은 대기와 생성 중을 구분한다. 생성 중에는 서버 단계와 실제 진행률을 예시 삽화 위에 표시하며, 동작 줄이기가 켜져 있으면 애니메이션을 생략한다. 기존 상태 조회 주기는 그대로다. 320×480 화면과 글자 크기 1.4배를 포함한 모바일 테스트 730개가 통과했고 2개는 건너뛰었다. [기본 화면](acceptance/2026-11-07-loading-current/creation-loading-light.png) · [작은 화면과 큰 글씨](acceptance/2026-11-07-loading-current/creation-loading-dark-reduced-motion.png)
- 생성 중 서재를 둘러볼 수 있다. 서재가 화면을 덮으면 생성 상태 조회 타이머와 진행 중인 HTTP 조회를 정리한다. 앱 안에서 뒤로 돌아오면 같은 생성 요청의 최신 상태를 읽고, 이미 완성됐으면 책을 연다. 작은 화면과 큰 글씨 설정에서 앱의 실제 서재 경로와 모의 API로 검증했다. 모바일 테스트 732개가 통과했고 2개는 건너뛰었다. 변경을 포함한 Android 디버그 및 iOS 무서명 빌드도 성공했다.
- 앱을 다시 연 뒤 서재에서 진행 중인 생성 요청을 서버에서 찾을 수 있다. 일반 동화, 오늘의 동화와 시리즈의 대기·실행 작업만 표시한다. 완료된 책은 기존 서재에 표시된다. 조회는 계정과 선택된 프로필 범위를 검증하며, 생성·차감 요청이나 주기적 조회를 시작하지 않는다. 새 서재에서 여러 작업 중 하나를 골라 같은 작업으로 돌아오는 흐름을 작은 화면과 큰 글씨 설정에서 검증했다. 전체 API 검사 3,009개와 모바일 전체 검사 733개, 별도 HTTP 전송·복귀 검사 29개가 통과했다. 새 서버 API와 두 플랫폼의 개발 빌드를 함께 적용하는 변경이다.
- 격리 PostgreSQL·Redis·Celery·MinIO에서 무료 첫 권과 생성 복귀를 HTTP로 재현했다. worker를 시작하기 전에 새 HTTP 클라이언트가 동일한 작업을 찾았고, 다른 프로필과 계정에는 노출되지 않았다. worker 시작 후 같은 작업이 12쪽으로 완성되어 서재에 들어갔고 서명된 삽화 12장을 내려받았다. 무료 크레딧 한 번 차감을 포함한 49개 확인을 통과했고 격리 환경을 정리했다. [실행 결과](acceptance/2026-11-07-queued-book-recovery-runtime/result.json)
- 같은 검사를 전체 격리 런타임에도 연결했다. PostgreSQL·Celery 회귀 21개, 생성 복귀·미디어 25개, 가상 캐릭터 수명주기 26개 및 전체 HTTP 읽기 흐름이 통과했다. 두 환경 모두 모의 AI를 사용했다. 로컬 무료 베타 사전 점검에서는 공개 HTTPS API·정책 주소와 내장 정책 승인 상태가 여전히 출시 조건을 충족하지 않았다. [전체 실행 결과](acceptance/2026-11-07-queued-book-full-runtime/result.json)
- 공통 금지 목록은 그림 제공자에 보낼 때 서버에서 붙이고, 글 모델은 각 장면에 필요한 제외 요소만 작성한다. 새 가상 책의 그림 지시 출력은 4,556토큰이었다. 직전 표본은 5,128토큰이었다. 주제가 다른 두 표본의 소요 시간은 각각 31.42초와 31.70초로, 체감 속도 개선을 입증하지 않는다. 표지·본문 진행률은 그림 요청 번호 대신 완료된 장수를 기준으로 반영한다.
- 새 7–9세 격리 생성은 본문 12쪽 모두 47–54어절, 총 605어절이었다. 두 번째 교정 그림까지 받았지만, 가상 증거 도구가 세 번째 검수를 차단해 전체 책 생성은 실패했다. 도구의 검수 한도를 제품의 교정 한도에서 계산하도록 수정했고 제공자 호출 한도는 유지했다. [격리 생성 기록](acceptance/2026-11-07-illustration-latency/result.json)
- 첫 두 자동 검수와 별도 9쪽 교정에서 빗물이 흐른 뒤의 상태가 제대로 표현되지 않았다. 아래 수도꼭지와 높은 넘침구를 구분하고 젖은 자갈길과 꽃밭을 중심에 두도록 지시한 뒤, 보관한 책의 9쪽만 다시 그렸다. 교정본의 수도꼭지에 물줄기가 없고 젖은 자갈길이 꽃밭에 닿는 것을 확인했다. 전권 재검수에서 표지와 본문 삽화 13장에 지적이 없었다. 전체 생성 재시험과 최신 실기기 검증은 별도다. [9쪽 교정 및 전권 검수](acceptance/2026-11-07-overflow-aftermath/result.json)
- 최신 변경에서 로컬 집중 검사 204개와 배포 의존성 버전의 집중 검사 157개가 통과했다. Flutter 분석과 테스트 730개, UI 사전 검사도 통과했다. 기존 제한 운영 HTTPS의 생존·준비 상태와 기능 응답은 모두 200이었다. 공개 베타 사전 검사는 공개 URL·승인 정책·운영 설정을 확인할 수 없어 차단 상태다.

## 2026-11-07 한국어 7–9세 본문 분량 및 iPhone 15 실기기 검증

- 12쪽 동화의 본문에서 40어절 이상인 쪽이 최소 9개인지 검사한다. 모자라면 필요한 쪽만 확장하고 분량과 본문 정합성을 다시 검사한 뒤 삽화 생성을 시작한다. 분량·삽화·생성 관련 API 시험 228개를 통과했다.
- 첫 재시험은 분량을 충족했지만 삽화 7쪽의 주요 행동이 본문과 달라 출판 단계에서 중단됐다. 분량을 늘리면서 쪽별 중심 행동을 하나로 잡도록 글·그림 지시를 보완한 뒤, 새 가상 이야기로 재검증했다. [첫 재시험 기록](acceptance/2026-11-07-iphone-7to9-length/result.json)
- iPhone 15에서 요청한 《서로 다른 장면, 함께 듣는 마음》은 274.46초에 완성됐다. 총 613어절, 쪽마다 50–53어절이었다. 표지와 본문 삽화 13장이 첫 자동 검수에서 통과했고 기기에서도 모두 표시됐다. 8쪽은 등장인물의 동작과 상상 속 물길을 한 장면에 표현했다. 구연동화 음성 12쪽을 실제로 합성해 기기에서 순서대로 재생했고 마지막 쪽 종료를 확인했다. 무료 크레딧 1개가 차감됐다. 격리 백엔드와 이번 시험 앱을 정리했고 기존 QA 앱은 보존했다. [본문](acceptance/2026-11-07-iphone-7to9-length-retry/book.json) · [삽화 모음](acceptance/2026-11-07-iphone-7to9-length-retry/illustration-review.jpg) · [12쪽 실기기 화면](acceptance/2026-11-07-iphone-7to9-length-retry/last-page-iphone.png) · [기기 검증 기록](acceptance/2026-11-07-iphone-7to9-length-retry/device-result.json)

## 2026-11-07 이전 iPhone 15 실기기 검증

- 앱 소스 `a49d0c5`의 iPhone 15 개발 서명 시험 앱이 격리 API에 7–9세 동화 생성을 요청했다. 첫 시도는 자동 교정 뒤에도 7쪽의 행동 불일치가 남아 실패했다. 본문 속 공동 행동에 참여하는 조연이 그림 지시의 등장인물 목록에서 빠진 것을 확인해 글·그림 지시와 교정 지시를 보완했다. 관련 API 시험 175개를 통과했다. [첫 시도 기록](acceptance/2026-11-07-iphone-current-live/result.json)
- 수정 후 iPhone이 요청한 《종이배가 돌아갈 곳》은 266.052초에 완성됐다. 무료 첫 권 크레딧은 1에서 0으로 바뀌었다. 표지·본문 삽화 13장이 첫 품질 검사에서 통과했고 기기에서 모두 표시됐다. 실제 OpenAI 구연동화 합성 12회와 1–12쪽 연속 재생 및 마지막 쪽 종료를 확인했다. 본문 460어절 중 40어절 이상인 쪽은 5개로, 12쪽 중 9개를 목표로 하는 7–9세 집필 지침에는 미달했다. 별도 시험 앱과 격리 백엔드를 정리했으며 기존 QA 앱은 보존했다. [기기 검증](acceptance/2026-11-07-iphone-current-live-fixed/device-result.json) · [삽화 모음](acceptance/2026-11-07-iphone-current-live-fixed/illustration-review.jpg)

## 2026-11-05 7–9세 기기 검토

- Mac의 [비공개 동화 검토 페이지](acceptance/2026-11-05-age7to9-review/index.html)에서 새로 자동 생성한 12쪽 본문과 표지·삽화 13장, 구연동화 낭독 전권, 세 가지 스타일의 Gemini 남녀 샘플을 확인할 수 있다. Chrome에서 모든 삽화의 표시와 음원의 재생을 확인했고, 각 음원 끝부분으로 이동해 다음 쪽 자동 전환과 마지막 쪽 종료를 검사했다.
- `6d69164`의 일반 앱 진입점 `lib/main.dart`를 iOS 27.2의 새 arm64 시뮬레이터에 설치했다. 초기 실행과 재실행에서 한국어 ‘부모 동의’ 화면을 확인했고, 계정 초기화 표시는 유지되며 설정 파일에 평문 계정 키가 없었다. Xcode 27.2에서 Flutter의 다중 아키텍처 검증이 실패해 arm64를 지정해 빌드했다. 시뮬레이터 로컬 서명을 적용했고, 무서명 빌드의 키체인 오류에서는 계정 보호 화면이 표시됐다. [시작 및 재실행 결과](acceptance/2026-11-05-free-beta-latest-mobile/ios-simulator-result.json)
- 최신 일반 터치 방식의 검토 앱을 iPhone 15에 설치하고 《하루와 빗방울 정원》 시작 화면을 열었다. 한 권에 7–9세용 12쪽 본문 601어절, 삽화 13장, 동일 본문의 구연동화 낭독 12개를 담았다. 가상 자료와 기기 내부 HTTP만 사용한다. [기기 검토 기록](acceptance/2026-11-04-manual-review-age7to9-corrected/manual-device-preview.json)
- 처음 자동 생성에서는 4쪽에서 아이들이 설계도를 보며 의논하는 대신 역할 카드에 그림을 그리는 장면이 들어가 품질 검사에서 거절됐다. 4쪽만 별도 교정하고 전권 삽화 검사를 통과했다. 자동 생성 실패 기록을 보존했다. 새 책의 글·삽화 생성 및 교정 지침에는 본문에서 계획하는 일을 현재 수행 중인 행동으로 바꾸지 않도록 반영했다. [자동 생성 결과](acceptance/2026-11-04-manual-review-age7to9/result.json) · [교정본 결과](acceptance/2026-11-04-manual-review-age7to9-corrected/result.json)
- 수정된 그림 지침을 실제 모델로 재검증했다. 본문과 일부러 충돌시킨 4쪽 장면을 넣자 빗물통을 설계도에만 묘사했고, 나중 장면에는 실제 수도꼭지와 물줄기를 묘사했다. 4쪽의 생성된 지시와 기존 가상 표지를 그림 모델에 보내, 인물 네 명이 설계도를 보며 의논하고 실제 통이나 역할 카드가 없는 삽화를 확인했다. 글 모델 1회와 그림 모델 2회를 사용했다. 첫 그림 응답은 검사 스크립트의 잘못된 크기 조건으로 보관되지 않았다. 한 쪽의 회귀 시험이며 12쪽 자동 재생성과는 별도다. [검증 기록](acceptance/2026-11-05-age7to9-planning-illustration/result.json) · [새 4쪽 삽화](acceptance/2026-11-05-age7to9-planning-illustration/page-04.png)
- 최신 생성 지침을 적용한 격리 백엔드에서 새 7–9세용 《하루와 빗방울 정원》을 301.14초에 자동으로 완성했다. 12쪽 570어절이며 모든 쪽이 40어절 이상이다. 표지와 본문 삽화 13장은 첫 자동 검수에서 모두 통과했고, 그림과 본문을 대조했다. 실제 OpenAI 글 요청 6회와 그림 요청 13회를 사용했다. 시작 시점의 readiness는 제공자 관측 전 상태였으며, 이 결과는 운영 readiness나 새 책의 낭독 시험을 포함하지 않는다. 별도 기기 검토 패키지는 기존 구연동화 음성을 보관한 교정본을 사용한다. [자동 생성 결과](acceptance/2026-11-05-age7to9-automatic-book/result.json) · [새 책의 삽화 모음](acceptance/2026-11-05-age7to9-automatic-book/visual-review.jpg)
- 같은 7–9세 교정본을 호환 모드를 끈 16 KiB Android 가상 기기에서 검사했다. 한 번의 실행으로 표지와 본문 삽화 13장을 화면에서 디코딩하고, 보관한 구연동화 낭독이 1–12쪽을 순서대로 재생한 뒤 완독을 기록하는 것을 확인했다. 캡처에서 확인한 수면 모드 상태바 대비는 이후 수정했고, 작은 화면의 하단 버튼과 함께 위젯 테스트로 검증했다. [Android 결과](acceptance/2026-11-05-android-age7to9/result.json)
- 동화 만들기 화면에서도 이야기 성우·구연동화·잠자리 세 스타일의 한국어 샘플을 비교할 수 있다. 설정과 같은 내장 샘플을 사용하며, 새 동화 요청이나 크레딧 차감 없이 들어볼 수 있다. 320×480 화면과 글자 크기 140%에서 세 버튼과 닫기를 검사했다. [미리 듣기 화면](acceptance/2026-11-05-create-narration-preview/create-narration-previews-small.png)
- 미리 듣기 창에서 기기의 기본 낭독 스타일도 바로 선택할 수 있다. 명시적으로 선택한 경우에만 기존 설정과 같은 값으로 저장하며, 낭독 화면이 이 설정을 사용한다. 320×480 화면과 글자 크기 140%에서 샘플 재생 후 닫기, 다시 열어 구연동화 선택, 설정 저장을 검증했다. [기본 낭독 선택 화면](acceptance/2026-11-05-create-narration-default-style/create-narration-default-style-small.png)
- 이 선택 기능을 포함한 일반 앱의 iOS arm64 개발 빌드와 Android 개발 APK를 다시 만들었다. 두 패키지에서 한국어·영어·일본어 문구, 내장 낭독 9개와 정책 파일 2개를 대조했다. Android 개발 서명과 16 KiB ZIP·arm64 ELF 정렬을 확인했다. [최신 개발 빌드 기록](acceptance/2026-11-05-narration-style-native-builds/result.json)
- iOS 후보는 등록된 iPhone 15와 일치하는 기존 개발 프로파일과 별도 QA 앱 ID로도 서명했다. IPA를 다시 풀어 중첩 서명과 원본 Flutter 파일 70개 일치를 확인했다. 이 IPA는 로컬 기기 디버깅용이며 API는 사용하지 않는 루프백 포트로 설정돼 있다. 실제 생성·낭독 검증은 격리 API를 연결한 기기 시험에서 진행한다. [iPhone QA 서명 검증](acceptance/2026-11-05-narration-style-native-builds/ios-device-qa-signing.json)
- Android 개발 APK를 16 KiB 호환 모드를 끈 격리 에뮬레이터에 설치했다. 가상 계정으로 부모 동의와 만들기 화면을 거쳐 세 샘플의 네이티브 AudioTrack 재생을 확인했다. 구연동화를 선택하고 프로세스를 재시작한 뒤에도 같은 선택이 표시됐다. 시험 API는 동의와 설정에 필요한 가상 응답을 제공했다. [Android 낭독 설정 검증](acceptance/2026-11-05-narration-style-native-builds/android-native-narration-result.json)
- 이때 기록된 만들기 진입 오류는 첫 프레임 도중 프로필을 갱신하면서 홈 화면의 재렌더링을 요청한 것이 원인이었다. 갱신을 프레임 종료 뒤로 옮겼다. 수정 전 회귀 시험에서 같은 오류를 재현했고, 수정 후 Flutter 시험 60개와 16 KiB Android 반복 진입을 통과했다. 진단 로그를 제거한 최종 Android APK에서도 확인했으며 iOS QA IPA를 기존 개발 프로파일로 다시 서명했다. [수정 검증과 최신 개발 빌드](acceptance/2026-11-05-create-profile-refresh/result.json)
- 미리 듣기가 포함된 `3a2252a`의 내장 샘플 9개를 iOS 27.2 시뮬레이터와 호환 모드를 끈 16 KiB Android 가상 기기에서 각각 재생해 네이티브 플레이어의 재생 위치가 움직이는지 확인했다. 개발용 iOS 앱과 Android 번들에도 동일한 파일 9개가 포함됐고, Android arm64 라이브러리는 ELF 구간 정렬이 16 KiB 이상이다. iOS 개발용 앱은 무서명이며 Android 번들은 디버그 서명이다. 공개 정책 URL 없는 iOS 릴리스 빌드는 컴파일 단계에서 차단됐다. [빌드와 검증 기록](acceptance/2026-11-05-native-narration-previews/result.json)
- `dca59a1`로 별도 검토용 iOS IPA와 Android APK를 만들었다. 첫 화면에서 7–9세 검토본의 삽화 13장·구연동화 12쪽 또는 세 가지 낭독 미리 듣기를 열 수 있다. 두 패키지의 서명과 내장 파일의 해시를 검사했고, 16 KiB Android 가상 기기에서 일반 터치로 두 메뉴를 열었다. 실제 폰 검증은 공동 검토 때 이 후보로 진행한다. [기기별 패키지와 검증 기록](acceptance/2026-11-05-joint-device-review/result.json)
- 이후 새로 자동 생성한 570어절 버전에 실제 한국어 구연동화 낭독 12개를 붙였다. 음원은 347.784초이며 각 쪽의 입력 본문과 파일 해시를 기록했다. iOS 27.2 시뮬레이터와 호환 모드를 끈 16 KiB Android 가상 기기에서 같은 책의 표지·삽화 13장과 1–12쪽 자동 재생·완독 기록을 확인했다. 새 책을 담은 개발 서명 IPA와 로컬 검토용 APK의 서명, 내장 파일 32개 및 Android 16 KiB ZIP 정렬도 확인했다. 실제 폰 설치는 공동 검토 때 진행한다. [최신 기기용 검토 빌드 및 낭독 결과](acceptance/2026-11-05-automatic-book-device-review/result.json)
- 전체 회귀에서 Flutter 730개가 통과하고 2개를 건너뛰었다. API는 배포와 같은 버전의 컨테이너에서 2,928개가 통과하고 29개를 건너뛰었다. 컨테이너에 Git 실행 파일이 없어 시작하지 못한 나머지 51개는 Mac의 테스트 환경에서 별도로 실행해 모두 통과했다.

## 2026-11-04 후보 재검증

- 최종 리더 소스 `35b7c7c`를 별도 개발 서명한 iPhone 15에서 검증했다. 기기 내 시험 서버에 보관한 그림·본문과 실제 Gemini 합성 음성을 연결했다. 그림 13장 표시, 그림 탭으로 하단 접기·복구, 본문 탭으로 재생·일시정지, 더보기에서 수면 모드 열기, 1–12쪽 순차 재생과 마지막 종료를 확인했다. 새 AI 요청은 없었고 시험 앱을 제거했다. 자동화 빌드는 손으로 누르는 입력을 차단하므로 수동 검토는 일반 앱 진입점에서 시작한다. [실기기 증거](acceptance/2026-11-04-offline-iphone-final-reader/result.json)
- 첫 권 체험을 포함한 `05fa2d3`의 iPhone 15 시험 앱이 격리 OpenAI 백엔드에서 《바람아, 연을 돌려줘!》를 새로 생성했다. 270.243초에 완료했고, 새 계정의 무료 크레딧은 1에서 0으로 바뀌었다. 표지와 본문 그림 13장을 기기에서 열고, 그림을 본문과 비교한 뒤 잠자리 낭독이 1–12쪽을 순서대로 재생하고 끝나는 것을 확인했다. 인물과 연이 일관됐으며 첫 세 쪽의 구도는 비슷했다. 시험 앱과 격리 백엔드를 정리했다. [기기 결과](acceptance/2026-11-04-iphone-physical-trial-latest/device-result.json) · [그림 모음](acceptance/2026-11-04-iphone-physical-trial-latest/visual-review.jpg)
- 읽기 화면은 조작부를 하단에 모으고, 닫기와 언어 전환을 더보기에서 제공한다. 그림을 눌러 조작부를 접거나 펼치고, 낭독을 지원하면 본문을 눌러 재생하거나 일시정지한다. 수면 모드는 그림을 덮는 회색 효과 대신 어두운 바탕과 밝은 본문을 사용한다. 16 KiB Android 가상 기기의 기존 Gemini 음성 1–12쪽 연속 재생은 수정된 화면에서도 마지막 쪽까지 통과했다. [일반 모드 미리보기](acceptance/2026-11-04-reader-compact/reader-normal-final.png) · [수면 모드 미리보기](acceptance/2026-11-04-reader-compact/reader-bedtime-final.png)
- 연령별 글쓰기 지침을 보완하고 생성 화면에서 같은 장면의 3–5세·5–7세·7–9세 본문 예시를 비교할 수 있게 했다. 동일 주제의 실제 4쪽 글 샘플에서 3–5세와 5–7세의 한국어 어절 중앙값은 각각 17과 26이었다. 지침을 다시 보완한 뒤 7–9세 12쪽 원고는 총 508어절, 중앙값 43어절이었고 12쪽 중 10쪽이 40어절 이상이었다. 7–9세 재검사는 본문 생성만 실행했다. 구매자·초등 독자·반증 역할의 AI 평가를 참고했다. [연령별 화면 예시](acceptance/2026-11-04-reader-compact/creation-age-preview-7-to-9.png) · [7–9세 원고](acceptance/2026-11-04-age-7-to-9-twelve-page-final/case-1.json)
- 무료 첫 권을 포함한 소스 `05fa2d3`의 Linux amd64 API·worker 이미지를 로컬에서 빌드했다. 두 이미지를 격리 PostgreSQL·Redis·MinIO에 연결해 초대 계정의 12쪽 생성과 서명 다운로드, 비초대 계정의 생성 거부와 잔액 유지 등 41개 검사를 통과했다. 글·그림은 모의 제공자를 사용했다. 같은 모바일 소스를 호환 모드를 끈 16 KiB Android 에뮬레이터에 설치하고, 보관한 Gemini 음성 1–12쪽 순차 재생과 마지막 쪽 종료를 확인했다. [이미지 및 Android 증거](acceptance/2026-11-04-first-book-oci/result.json)
- 최신 모바일 소스(`7a17248`)를 별도 서명한 iPhone 15의 유선 시험에서 실제 12쪽 가상 동화 《하루와 초록 싹》을 생성했다. 기기의 앱 클라이언트가 요청했고 253.94초 만에 완료됐다. iPhone에서 표지와 본문 12장을 모두 내려받아 디코딩했다. 삽화 자동 검수는 13장 모두 지적 사항이 없었다. 그림을 본문과 대조했으며 인물과 성장 단계가 일관됐고 일부 장면의 자세와 구도는 비슷했다. 잠자리 모드에서 1–12쪽을 순서대로 재생해 마지막 쪽 종료를 확인했다. 글·그림·음성은 모두 격리 OpenAI 연결로 검사했다. 기기의 시험 앱과 격리 서비스는 정리했다. [최신 iPhone 실기기 증거](acceptance/2026-11-04-iphone-physical-final-current/physical-evidence.json) · [삽화 모음](acceptance/2026-11-04-iphone-physical-final-current/visual-review.jpg)
- 최신 모바일 코드로 Galaxy SM-F721N을 USB 검사했다. 보관한 Gemini 한국어 음성 1–12쪽을 순서대로 받아 잠자리 모드에서 마지막 쪽까지 재생했고, 보안 저장소의 초기화·복구 키 활성화·재초기화·삭제도 통과했다. 음성 시험의 그림 자리는 1픽셀 대역이었다. 별도 리더 시험에서 《하루와 초록 싹》의 실제 표지와 본문 그림을 하나씩 넘기면서 13장이 화면 위젯에서 디코딩되는 것을 확인했다. 두 시험은 별도 합성 데이터셋으로 진행했고 추가 AI 호출 없이 끝냈다. 시험 앱·서버·USB 역방향 연결은 정리했다. [낭독 및 보안 저장소](acceptance/2026-11-04-android-physical-final-current/physical-evidence.json) · [그림 표시](acceptance/2026-11-04-android-physical-illustrations/physical-evidence.json)
- iPhone 15(iOS 27.2)를 USB로 연결하고 `a8fe338`의 별도 서명 시험 앱에서 3–5세용 가상 동화 《하루의 작은 정원》을 요청했다. 생성에 194.28초가 걸렸으며 기기에서 표지와 본문 삽화 네 장을 열었다. 자동 검사에서 지적된 항목은 없었고, 그림 다섯 장을 본문과 대조했다. 같은 책의 한국어 음성 네 쪽을 순서대로 재생하고 마지막 쪽의 종료를 확인했다. XCTest 1개가 통과했다. 시험은 격리 백엔드와 OpenAI로 진행했다. 운영 `/health/ready`의 HTTP 200과 설정 응답의 Gemini 낭독·음색·스타일 활성화는 별도로 확인했다. [실기기 결과](acceptance/2026-11-04-iphone-physical-fictional-wired/physical-evidence.json) · [그림 모음](acceptance/2026-11-04-iphone-physical-fictional-wired/visual-review.jpg)
- 갤럭시 SM-F721N을 USB로 연결해 `a8fe338`의 별도 시험 앱에서 《하루와 친구의 작은 정원》을 새로 요청했다. 표지와 본문 삽화 네 장이 자동 검사를 통과했고, 기기에서 모두 열어 본문과 대조했다. 네 쪽 낭독이 차례로 재생되고 마지막 쪽에서 정상 종료됐다. 기기 페이지 크기는 4 KiB였다. 격리 OpenAI 백엔드와 시험 앱은 검증 후 정리했다. [Android 실기기 결과](acceptance/2026-11-04-android-physical-fictional/physical-evidence.json) · [그림 모음](acceptance/2026-11-04-android-physical-fictional/visual-review.jpg)
- 앱 시작, 홈의 동화 만들기, 생성 진행 화면에 같은 책 일러스트를 적용했다. 생성 화면은 서버의 실제 진행 단계와 비율을 보여 주며, 기존 잡 재조회·실패 안내·자동 이동을 유지한다.
- 실제 가상 동화 시험에서 캐릭터 시트의 스타일 설명이 200자를 넘어 생성이 중단됐다. 프롬프트와 지원 모델의 응답 스키마에 길이 제한을 적용했다. 이후 실제 그림은 마지막 장면의 단체 동작과 소품 중복 문제로 품질 게이트가 출고를 막았다. 본문의 모든 행동 주체와 소품의 현재 상태가 생성·교정 지시에 반영되도록 보완했다. [실패 증거](acceptance/2026-11-04-beta-live-fictional-v3/result.json)
- 수정 후 격리된 PostgreSQL·Redis·Celery·MinIO에서 OpenAI를 사용해 새 가상 4쪽 동화를 221.68초에 생성했다. 표지와 삽화 네 장은 첫 자동 검사를 통과했다. 본문과 나란히 확인한 결과 캐릭터와 중심 행동이 대체로 일치했다. 한 권의 결과이며, 마지막 장면의 이전 실패는 별도 증거에 보존했다. [생성 결과](acceptance/2026-11-04-beta-live-fictional-v4/result.json) · [그림 모음](acceptance/2026-11-04-beta-live-fictional-v4/visual-review.jpg)
- 같은 책의 기본 한국어 낭독 네 건을 OpenAI로 합성했다. iOS 시뮬레이터와 Android 에뮬레이터의 잠자리 모드에서 1–4쪽 순차 재생과 마지막 쪽의 재생 종료를 확인했다. Android는 이미 합성된 음성을 재사용했다. 초기 시험의 일일 예산 거절이 10분짜리 재시도 잠금을 남기는 문제를 재현했다. 제공자 호출 전에 확정 거절된 예산 오류는 잠금을 해제하며, 공급자 처리 여부가 불확실한 경우에는 중복 호출을 막는다. [iOS 검사](acceptance/2026-11-04-beta-live-fictional-v4/ios-playback.log) · [Android 검사](acceptance/2026-11-04-beta-live-fictional-v4/android-playback.log) · [네 쪽 오디오 디코딩](acceptance/2026-11-04-beta-live-fictional-v4/narration-audio-decode.json)
- Android 에뮬레이터(API 36, 4 KiB)에서 복구·리더·네이티브 오디오·보안 저장소 검사 35개가 통과했다. 현 소스의 Android 디버그 APK와 iOS 기기용 무서명 디버그 앱을 빌드했다.
- 기존 GCE 주소는 제한 운영용이다. 초기 직접 TLS 연결은 시간 초과됐고, 후속 연결에서 `/health/ready`의 HTTP 200과 제공자 상태 `healthy`를 확인했다. 로컬 사전 점검은 베타용 HTTPS API 호스트명, 승인된 정책 URL 두 개, 내장 정책의 승인 상태와 시행일이 비어 있어 배포를 차단했다. 지원·삭제 페이지는 비공개 미리보기로 생성했다. iOS 앱 전용 배포 프로파일은 로컬에서 확인되지 않았다.
- 모바일 릴리스 빌더에서도 내장 개인정보처리방침과 이용약관의 승인 상태와 시행일을 검사한다. Android와 iOS 모두 검토본으로 `--execute`를 실행하면 컴파일 전에 중단된다. 로컬 사전 점검에서 두 문서 모두 검토가 필요한 상태로 확인됐다. Android 디버그 APK는 ZIP과 64비트 ELF 로드 구간의 16 KiB 정렬을 통과했다. 16 KiB 환경 실행과 제출용 AAB의 검증은 별도 항목이다. [Android 16 KB 검증 가이드](https://developer.android.com/guide/practices/page-sizes)
- 운영 VM의 서비스 계정으로 Gemini에 인증하는 격리 API에서 한국어 한 문장의 응답이 41.904초인 사례를 확인했다. MP3 프레임 구조와 본문 길이 대비 재생 시간을 검사하고, 한도를 넘은 응답을 저장하기 전에 거부하도록 후보 코드를 보완했다. 원본 응답 재검사에서 거부됐고, 후보를 격리 적용해 같은 문장을 다시 요청했을 때 3.960초 MP3가 생성됐다. 동일 요청은 저장된 응답을 재사용했고, 다른 스타일 요청은 격리 한도에 따라 429로 거부됐다. 시험은 격리 SQLite와 메모리 저장소를 사용했다. 운영 이미지·저장소·설정은 그대로 유지했다. [격리 시험 결과](acceptance/2026-11-04-beta-operational-gemini/result.json)
- 운영은 초대 전용, 구매 비활성화, Gemini 낭독 활성화 상태다. Gemini 별도 한도는 일일 24회·월간 120회지만 앱의 공유 생성 한도는 일일 1회다. 새 캐릭터와 기본 12쪽 동화 및 전체 낭독을 같은 날 검증하려면 공유 한도가 최소 14회 필요하다. `scripts/final_external_preflight.py --free-beta`에 이 조건을 넣었다. [사전 검사 절차](OPERATIONS_TEST_RUNBOOK.md#7-external-integration-status)
- 공유 한도 14회·Gemini 일일과 월간 한도 각 12회를 설정한 격리 API에서 직접 작성한 한국어 가상 동화 12쪽을 Puck 구연동화 음성으로 실제 합성했다. 캐릭터·동화 생성 몫은 두 슬롯을 미리 예약하는 방식으로 재현했다. 초대받지 않은 계정은 호출 전 차단됐고, 초대 계정의 12쪽 응답은 모두 HTTP 200이었다. 같은 음성 재요청에는 추가 슬롯을 사용하지 않았다. 공유 한도 14회와 Gemini 두 카운터 12회를 확인했고, 새 스타일을 한 번 더 요청했을 때 HTTP 429를 받았다. MP3 12개는 모두 디코딩됐으며 쪽당 8.112–10.560초, 합계 107.328초였다. [12쪽 합성 기록](acceptance/2026-11-04-beta-gemini-twelve/result.json)
- Android 에뮬레이터의 첫 연속 재생에서 3쪽이 건너뛰어졌다. 낭독 소스마다 완료 신호를 한 번만 받고 현재 페이지의 바로 다음 쪽으로 이동하도록 수정했다. 수정판의 Android 에뮬레이터와 iOS 시뮬레이터에서 각각 1–12쪽의 재생 시작, 페이지 요청 순서, 마지막 쪽 재생 종료를 확인했다. Flutter 전체 자동 검사는 721개 통과, 2개 건너뜀이고 정적 분석은 통과했다. [Android 재생 기록](acceptance/2026-11-04-beta-gemini-twelve/android-playback.log) · [iOS 재생 기록](acceptance/2026-11-04-beta-gemini-twelve/ios-playback.log)
- 다음 USB 실기기 검사를 위해 별도 빌드와 가상 본문·실제 합성 음성 12개를 보관했다. Android 디버그 APK의 서명 검증과 ZIP 16 KiB 정렬을 확인했다. Android 앱은 USB 역방향 포트 8000의 격리 QA API와 연결한다. iPhone용 arm64 디버그 앱은 무서명 빌드이며, 연결 시 기기용 개발 서명과 격리 API 주소를 적용한다. 양쪽 기기에서 수정판을 설치한 후 12쪽 연속 재생·마지막 쪽 종료를 다시 확인하고 시험 앱을 정리한다. 보관한 음성은 추가 AI 호출 없이 재생 시험에 재사용할 수 있다. [Android APK](acceptance/2026-11-04-beta-gemini-twelve/device-builds/android-usb-debug.apk) · [iPhone 무서명 빌드](acceptance/2026-11-04-beta-gemini-twelve/device-builds/ios-iphoneos-debug-unsigned.zip) · [음성 해시](acceptance/2026-11-04-beta-gemini-twelve/playback-fixture/audio-sha256.json)
- 위 APK의 arm64 및 x86-64 라이브러리 5개에서 ELF `LOAD` 구간 14개의 최소 정렬이 16,384바이트였다. 공식 Android 36.1 16 KiB ARM64 이미지의 초기 부팅 시도 두 번은 `mprotect` 오류와 ADB 오프라인으로 중단됐다. 이 Mac의 `avdmanager`가 가상 기기 대상 버전을 `android-0`으로 기록해 ARM 가속이 활성화되지 않았다. 시험용 AVD의 대상 버전만 `android-36.1`로 교정하자 정상 부팅했고, `getconf PAGE_SIZE`에서 16,384를 확인했다. 16 KiB 호환 모드를 끈 상태에서 보관한 APK로 보호자 동의 화면을 열었고, 같은 소스의 통합 빌드로 한국어 음성 1–12쪽 연속 재생 및 마지막 쪽 종료와 네이티브 보안 저장소의 초기화·복구 키 활성화·재초기화·삭제를 검증했다. 제출용 AAB는 별도 검증 항목이다. [16 KiB 검증 기록](acceptance/2026-11-04-beta-gemini-twelve/android-16k-result.json)
- 현재 글·그림 및 낭독 변경을 포함한 Linux amd64 API·worker 이미지를 새로 빌드했다. 첫 빌드는 자동 선택된 Kombu 5.7.0이 Redis 클라이언트 5.2.0과 호환되지 않아 worker 시작이 실패했다. 기존에 검증한 Kombu 5.6.2를 명시한 후 두 이미지에서 의존성 검사와 소스 해시 대조를 통과했다. 격리 PostgreSQL·Redis·Celery·MinIO에서 마이그레이션 `f32a7b4d190c`, worker 응답, 비공개 미디어 검사 19건과 책 생성부터 읽기·동의 철회까지 34건을 확인했다. AI 생성에는 시험 대역을 사용했다. 두 이미지에서 보관한 실제 Gemini MP3의 정상·과다 길이 사례도 재검증했다. 후보는 로컬에 보관했다. [이미지 ID와 검증 기록](acceptance/2026-11-04-beta-backend-candidate/result.json)
- 위 후보를 Trivy로 검사한 후 FastAPI·Starlette와 setuptools를 갱신하고, 실행 이미지에 복사하는 가상환경에서 빌드용 pip를 제거했다. 새 FastAPI로 OpenAPI 명세를 다시 생성했다. 최종 이미지 `e709065a14ad` 두 개에서 CI의 치명적 취약점 기준을 통과했고, 같은 DB의 추가 검사에서 수정본이 있는 고위험·치명적 항목은 0건이었다. 검사 DB에 수정본이 없는 고위험 항목은 API 49건, worker 45건이었다. 전체 API 2,962개 통과·27개 건너뜀, 이미지에서 생성한 OpenAPI 해시 일치, 격리 미디어 19건·읽기 34건을 확인했다. [최종 이미지 ID와 검사 기록](acceptance/2026-11-04-beta-backend-candidate/security-final/result.json)
- 최신 모바일 소스의 Android 디버그 AAB를 빌드했다. `bundletool`에서 `PAGE_ALIGNMENT_16K`를 확인하고 arm64용 분할 APK 네 개를 만들었다. 네 개의 서명과 ZIP 정렬, 공유 라이브러리 세 개의 ELF 정렬이 통과했다. 호환 모드를 끈 16 KiB 가상 기기에 분할 APK를 설치해 보호자 동의 화면까지 열었다. 제출 서명이 적용된 출시용 AAB는 배포 전 별도로 확인한다. [분할 APK 검증 기록](acceptance/2026-11-04-beta-android-bundle/result.json)
- 보관한 iPhone 디버그 빌드의 소스 해시를 현재 모바일 소스와 대조했다. 이전 시험 iPhone 15가 정확히 등록된 기존 개발 프로파일로 앱과 내부 프레임워크 24개를 서명했고, ZIP을 다시 풀어 전체 서명을 검증했다. 기존 앱 식별자를 사용하는 빌드이므로 설치 전 기기에 같은 식별자의 앱이 있는지 확인한다. USB 연결 후 격리 API를 연결하고 수정판의 실기기 재생을 확인한다. [개발 서명 확인 기록](acceptance/2026-11-04-beta-iphone-signed/result.json)
- 실기기 시험에는 별도 식별자 `com.storybook.aiStoryBook.qa.nov04`와 전용 키체인 그룹을 사용하는 iPhone QA 아카이브를 우선 사용한다. 기존 개발 와일드카드 프로파일로 재서명하고 QA 앱의 공유 URL 스킴을 제거했다. 압축을 다시 푼 뒤 앱 및 내장 서명과 별도 키체인 그룹을 확인했다. 실기기 설치와 격리 API 경로는 기기 연결 후 검증한다. [격리 QA 서명 확인](acceptance/2026-11-04-beta-iphone-isolated/result.json)
- iPhone 재생 재시험용으로 같은 별도 식별자의 로컬 네트워크 아카이브를 빌드했다. 기존 `API_BASE_URL` 빌드 옵션에 시험 Mac의 `.local` 호스트명과 포트 57332를 넣고, 별도 QA 아카이브에만 로컬 네트워크 예외를 적용했다. 실행 시 주소를 주입하는 실험에서는 iOS 27.2 시뮬레이터가 주소를 채택하지 않아 해당 코드를 제거했다. [개발 서명 및 아카이브 해시](acceptance/2026-11-04-beta-iphone-mdns/result.json) · [Apple 로컬 네트워크 설정](https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity/nsallowslocalnetworking)
- 위 아카이브와 같은 주소에서 12쪽 재생 데이터를 제공할 수 있도록 별도 합성 전용 서버를 준비했다. 저장소 루트에서 `apps/api/venv/bin/python docs/acceptance/2026-11-04-beta-iphone-mdns/playback-fixture/serve.py --local-network`로 시험 때만 실행한다. 하나의 사설 IPv4에 바인딩하고 `.local` 주소를 반환한다. Mac에서 전 페이지 MP3의 해시 일치를 확인한 뒤 서버를 종료했다. 실기기의 로컬 네트워크 접근과 실제 생성용 격리 백엔드 연결은 기기 연결 후 확인한다. [로컬 서버 검증 기록](acceptance/2026-11-04-beta-iphone-mdns/local-network-fixture.json)
- Android도 추적된 최신 소스의 임시 사본에서 별도 `com.storybook.ai_story_book.qa.nov04` APK를 빌드했다. APK v2 서명과 ZIP 16 KiB 정렬을 검사했다. 호환 모드를 끈 16 KiB 임시 가상 기기에 일반 앱과 QA 앱을 함께 설치해 QA 앱 실행 및 제거를 확인했다. 일반 앱의 설치 경로는 그대로였다. [APK 검증](acceptance/2026-11-04-beta-android-isolated/result.json) · [가상 기기 검증](acceptance/2026-11-04-beta-android-isolated/emulator-isolation.json)
- 기기 재연결 전에 iPhone 개발 서명 ZIP과 Android USB용 APK의 SHA-256을 다시 확인했다. 보관한 재생 시험 서버를 로컬에서 시작해 1–12쪽의 오디오 URL과 MP3 응답을 확인했고, 내려받은 12개 파일이 모두 보관 해시와 일치했다. 시험 서버는 종료했다. 실기기 재생에는 보관 음성을 재사용하고, 기기에서 시작하는 새 동화 생성과 삽화 검증은 별도로 기록한다.
- 지원·삭제·정책 사이트의 HTTPS 검사를 릴리스 빌드에 연결했다. 앱의 정책 URL과 내장 문서가 승인된 사이트 주소 및 HTML과 일치해야 한다. 이후 다섯 HTML과 CSS, `robots.txt`의 공개 응답을 바이트 단위로 대조한 뒤에만 컴파일한다. 두 플랫폼에서 현재 정책 검토본이 네트워크 연결과 컴파일 전에 차단되는 것을 확인했다. [게시 후 검증 명령](../apps/public-site/README.md#게시-후-검증)
- 양쪽 실기기 시험 후 제한 운영 주소를 읽기 전용으로 다시 확인했다. TLS 검증과 `/health/live`, `/health/ready`, `/v1/config/capabilities`는 모두 HTTP 200이었다. 기능 응답에서 Gemini 낭독과 음색·스타일 선택은 활성, 신규 구매·가족 음성·실물 주문은 비활성이었다. 이 주소는 제한 운영 경로이며 공개 베타 주소와 초대 계정의 새 동화 전체 여정은 별도로 검증한다. 로컬에는 Android 업로드 서명 설정이 있고, 앱과 일치하는 iOS 배포 프로파일은 확인되지 않았다. [운영 응답](acceptance/2026-11-04-free-beta-readiness/pilot-http.json) · [서명 점검](acceptance/2026-11-04-free-beta-readiness/signing-preflight.json)

무료 체험으로 만든 첫 동화는 선택한 연령에 관계없이 새 낭독을 생성할 수 있다. 첫 권 체험은 프로필이나 보호자가 고른 연령이 없으면 3–5세를 기본 선택한다. 첫 권 이후에는 기존 무료 플랜의 3–5세 낭독 예외를 적용한다. 출시용 후보에서는 운영 Gemini 음성 선택과 재생, 계정 복구와 삭제, 앱 재실행 후 서재 접근도 확인한다.

제한 베타 후보는 `FREE_PLAN_FIRST_BOOK_TRIAL=true`에서 신규 계정에 첫 동화 한 권을 지급한다. 잔액 생성과 지급 기록은 같은 트랜잭션으로 저장하며, 생성 실패 환불은 기존 잡 경로를 사용한다. 기존 잔액은 유지하고 매월 자동 지급은 중단한다. 기본 낭독·구연동화·잠자리 스타일은 앱에 들어 있는 미리듣기로 비교할 수 있다. 베타 운영에 연결하기 전에 일일 예산과 초대 계정으로 전체 첫 권을 검증한다.

테스터는 앱의 **설정 → 베타 참여 ID 복사**에서 보호자 확인을 거쳐 64자리 ID를 운영자에게 보낸다. 운영자는 다른 초대 ID를 유지한 채 `GENERATION_ALLOWED_USER_HASHES`의 쉼표 구분 목록에 받은 ID를 추가하고, 기존 배포 절차에 따라 API·worker에 설정을 반영한다. 복구 후에도 동일 계정은 같은 참여 ID를 사용한다. 앱 계정 키와 복구 코드는 운영자가 받지 않는다. [격리 환경 첫 권 및 초대 검증](acceptance/2026-11-05-beta-invitation/result.json)

서버 후보 `6d69164`의 Linux amd64 API·worker 이미지 소스를 해당 커밋과 대조했다. 격리 PostgreSQL·Redis·Celery·비공개 MinIO에서 초대 계정의 7–9세 첫 권을 만든 뒤 낭독 음원이 없는 1–12쪽 모두 새 낭독 요청과 다운로드를 확인했다. 이 검사는 모의 제공자를 사용했다. 별도 격리 검사에서는 12쪽의 실제 OpenAI 구연동화 합성과 재요청 시 음원 재사용을 확인했다. 그 검사의 글·그림은 모의 제공자, 1–11쪽 음성은 시험 파일을 사용했다. 무료 베타 운영에는 공개 API·정책 주소, 승인된 내장 정책과 별도 베타 운영 설정이 필요하다. [서버 후보 검증](acceptance/2026-11-05-free-beta-narration-oci/result.json) · [실제 12쪽 낭독 검증](acceptance/2026-11-05-first-book-trial-narration-live/result.json)

격리 PostgreSQL·Redis·Celery·비공개 저장소에서 신규 계정의 12쪽 동화, 이미지 다운로드, 재시도 시 같은 작업 반환, 두 번째 생성의 402 응답을 확인했다. 글·그림은 모의 제공자를 사용했다. 결제 지원이 확인된 앱에서는 잔액이 소진되면 낱권 구매를 먼저 표시하고 구독을 별도로 제공한다. 결제가 꺼진 베타에서는 서재와 잔액을 안내한다. [첫 권 체험 검증](acceptance/2026-11-04-first-book-runtime/result.json)

생성 대기 화면에는 가상 동화 《하루와 초록 싹》의 예시 삽화를 넣었다. 단계와 비율은 서버 잡의 값을 표시한다. 기본 크기와 작은 화면의 큰 글씨·다크 모드에서 렌더링을 확인했다. 낭독 설정의 표시 이름은 이야기 성우·구연동화·잠자리이며, 기존 설정 값과 미리듣기 파일을 사용한다. [밝은 화면](acceptance/2026-11-04-first-book-loading-design/creation-loading-light.png) · [작은 화면 다크 모드](acceptance/2026-11-04-first-book-loading-design/creation-loading-dark-reduced-motion.png)

테스터용 HTTPS API에는 기존 소유의 DNS 호스트명을 연결하고, 새 유료 AI 작업은 `invite_only`와 전역 한도를 유지한다. 새 구매는 비활성화한다. 서로 다른 시험 계정으로 허용된 생성 1회와 비초대 계정의 제공자 호출 전 거부를 확인한다. 이어 실제 연락처와 승인된 정책으로 지원·삭제 사이트를 게시하고, API 및 정책 주소를 `scripts/build_mobile_release.py`의 공개 전용 JSON에 넣어 검사한 뒤 배포 서명으로 빌드한다. 공개 URL이나 유효한 배포 서명을 확인할 수 없으면 디버그 후보를 테스트 트랙에 올리지 않는다. [지원 사이트](../apps/public-site/README.md) · [스토어 체크리스트](appstore/submission-checklist.md)

이용약관 3절의 초대형 베타 안내를 첫 그림 동화 한 권, 매월 재지급 없음, 새 구매·구독 비활성화로 맞췄다. 앱 내 한국어 원문과 웹 검토본이 일치한다. 개인정보처리방침은 기존 원문이며 두 문서 모두 승인 및 시행일 확정 전이다. [비공개 정책 검토본](acceptance/2026-11-05-beta-policy-review/index.html)

기존 제한 운영 VM은 TLS 검증을 유지한 상태에서 `/health/live`, `/health/ready`, `/v1/config/capabilities`가 모두 HTTP 200이었다. DB·Redis·저장소·제공자 관측 상태는 정상이고 Gemini 낭독은 활성화돼 있다. 무료 첫 권과 참여 ID는 기존 운영 기능 응답에 아직 없다. Android 로컬 업로드 키와 인증서 유효성을 확인했으며 Play 등록 인증서 대조가 남아 있다. iOS는 배포 인증서가 있으나 앱 식별자에 맞는 배포 프로파일은 로컬에서 확인되지 않았다. [제한 운영 및 서명 확인](acceptance/2026-11-05-beta-external-recheck/result.json)

이전 구현·검증과 당시 활성화 조건은 [2026-09-12 출시 후보](LAUNCH_CANDIDATE_2026-09-12.md)에 기록했다. 아래 날짜별 기록은 당시 증거다.

2026-09-07 추가 QA 통합 수정 이후의 현재 상태는 [출시 현황](LAUNCH_STATUS.md)과 [두 보고서 검토](QA_RECONCILIATION_2026-09-07.md)를 우선합니다. 아래 검사 수치와 빌드 산출물은 각각 당시 소스의 이력입니다. 새 정책·readiness·삭제·과금 수정이 반영된 공개 release를 배포했다고 의미하지 않습니다.

## 이전 준비 이력

2026-09-07 최종 소스는 Python3.11 API **1,924개 통과·21개 건너뜀·실패0, 커버리지77.26%**, Ruff·과금 경로 커버리지 통과다. 두 참조 어댑터·오케스트레이션·저장본 교정 검증 도구를 포함한다. 별도 실제 PG/Celery21개 통과, 모바일 **522개 통과·커버리지64.2345%·정적 분석0**와 Android 서명 APK/AAB(Billing8)·iOS 무서명 release 빌드 결과는 유지한다. [최종 검사](acceptance/2026-09-07-dual-reference-api-final/result.json), [산출물·네이티브 확인](PRE_REGISTRATION_PACKAGE_2026-09-06.md). 앞선1,862개 및 아래1,400개 등의 기록은 이전 시점이다.

실제 가상 캐릭터의 개인12쪽 교정판은 전체 삽화13장과 PDF14쪽 검토를 통과했다. 이후 새8쪽판은 두 참조 교정 뒤에도5쪽 오류·6쪽 육안 보류가 남아 내보내지 않았다. 새로운 자동 책 전체의 품질 통과는 완료되지 않았다. 자동 원본 작업의 실패를 성공으로 변경하지 않았고 실제 아동 닮음 검증도 아니다. 운영은 [외부 연결 준비](EXTERNAL_HOSTING_DEPLOYMENT.md)와 [월$67 구성](RENDER_DEPLOYMENT_PACKAGE.md)까지 준비했으며, 과금 승인·실제 연결·공개 정책/지원 경로·처리 조건·공동 최종 검토가 끝나기 전 공개 배포나 스토어 제출을 하지 않는다.

2026-09-06 후속 제공자 계정 확인, 실제 사진의 로컬 전처리와 가상 입력 실호출 결과는 [사진 실검증 기록](PHOTO_LIVE_VERIFICATION_2026-09-06.md)을 따른다. 실제 아동 사진의 외부 처리·닮음 검증과 공개 출시 승인은 별개이며 아직 완료로 표시하지 않는다.

> 2026-09-06 최신 확정: 사진 → 대표 캐릭터 한 장 → 부모 최초 확인 → 이후 책에 고정 재사용. 책마다 캐릭터를 새로 생성하지 않는다. 구현·처리 조건의 정본은 [사진 캐릭터 흐름](PHOTO_CHARACTER_FLOW.md)이다. 실제 사진 품질과 제공자 승인 확인은 자동 테스트 통과와 별개다.

## 삽화 품질 게이트 최종 검증 — 2026-09-06

검사·부분 재생성·전체 재검사와 실패 시 완성 차단을 반영한 최종 소스에서 Python3.11.15 전체 **1,400통과·14건너뜀·실패0**, 커버리지 **75.62%**, 금전 경로 커버리지 통과를 확인했다. 실행217.83초, 네트워크 차단·소스 사본만 사용했으며 실제 환경/개인 자료는 복사하지 않았다. 정본 [실행 기록](acceptance/2026-09-06-illustration-gate/api-python311-20260906T040116Z-3d65bfa9-summary.json), 소스 snapshot SHA `3d65bfa99e8bbbcdee57753323cea0b7ef8d6ebe141d8c757fafae3e76ca4a72`이다. 중간 검증 컨테이너의 PATH·실행 권한 문제는 수정했고 실패 이력도 별도로 보존했다.

루트 `phase-gate.sh`도 통과했다(API1,400·Flutter367·분석·UI사전검사). 건너뛴14개 PG/Celery 검사는 별도 실제 일회용 환경에서 모두 통과했고 미디어19개·HTTP여정33개·자원 정리도 확인했다. [전체 런타임 기록](acceptance/2026-09-06-illustration-gate/runtime-all/verification.json). 이 런타임의 생성/그림 검토는 명시 모의 대역이다.

실제 AI에서는 기존 오류 책의2쪽만 다시 생성한 뒤 전체5장 재검사와 육안 확인을 통과했다. 나머지 그림과 원본 설명을 보존했다. 이는 저장소를 로컬로 대체한 부분 교정 검증이며 운영 출고·새15권 품질 GO와 구분한다. [실제 부분 교정 결과](acceptance/2026-09-06-saved-illustration-repair-v2/result.json), [동작·한도·한계](ILLUSTRATION_QUALITY_GATE.md).


운영 코드는 GHCR의 커밋 SHA 이미지로 배포합니다. 현재 이 문서는 **배포 절차와 로컬 복구 검증이 준비된 상태**를 기록하며, 운영 서버 가동이나 스토어 배포 완료를 뜻하지 않습니다. 실제 AI 품질·앱 검증의 최신 결과는 [LAUNCH_STATUS.md](LAUNCH_STATUS.md)를 참조합니다.

## 그림 검사 흐름과 최신 모바일 검증

2026-09-06에 출고 전 그림 검사와 부분 재생성의 모바일 안내를 연결했습니다. 생성 화면은 서버 진행률 **86% 그림 확인 → 87% 필요한 그림 다시 그리기 → 88% 수정 그림 재확인**을 한국어·영어·일본어로 표시합니다. `verify_illustrations`와 `repair_illustrations` 같은 내부 단계 이름이 화면에 노출되지 않습니다.

새 책의 `IMAGE_QUALITY_FAILED` 오류는 일부 그림을 확인하지 못해 완성하지 못했다는 안내와 재시도 동선을 제공합니다. 실패 응답에 책 결과나 100% 진행률이 있어도 완성 화면으로 이동하지 않습니다. 기존 책의 그림 수정이 같은 오류로 실패하면 변경사항을 저장하지 않았으며 기존 책이 유지된다고 안내하고, 기존 본문과 상세 캐시를 보존합니다. 확인되지 않은 환불 완료 문구나 공급자 진단 원문은 표시하지 않습니다. 세 언어의 검사·보완·재검사와 실패 동선은 320×480 화면·글자 배율 1.4에서 확인했고, 실패 화면의 조작 영역은 최소 64×64 논리 픽셀입니다. 새 구매·오디오·실물 주문 설정은 유지했습니다.

| 검사·빌드 | 이번 결과 |
|---|---|
| 영향 경로 Flutter 검사 | **22개 통과** |
| `flutter analyze` | **문제 없음**, 도구 보고 6.7초 |
| `flutter test --coverage` | **367개 통과**, line coverage **50.5135%**(6,197/12,268줄) |
| `flutter test integration_test/app_flow_test.dart -d flutter-tester --no-pub` | 모의 사용자 흐름 **2개 통과** |
| `flutter build apk --debug` | Android 디버그 APK 생성 완료, Gradle 단계 12.0초 |
| `flutter build ios --debug --no-codesign` | iOS 서명 없는 디버그 앱 생성 완료, Xcode 단계 12.8초 |

통합 검사 폴더 전체 실행에서는 위 사용자 흐름 2개가 통과했지만, 별도 실서버·기기 조건이 필요한 `live_backend_flow_test.dart`와 `native_storage_test.dart`는 앱 로그 리더 시작 오류로 테스트 본문을 실행하지 못했습니다. 따라서 이번 결과는 전체 통합 검사나 실기기·네이티브 플러그인 검증 완료를 뜻하지 않습니다. 적용 가능한 모의 사용자 흐름 파일은 따로 실행해 종료 코드 0을 확인했습니다.

새 산출물의 SHA-256은 Android APK `32f0591f14d6a0ce01b5cd524e0eac27ce16bb0268f0e891b1470e24afac10d9`, iOS 앱 파일 목록 기준 묶음 `305cb007511037c546b14c8ef2fe763fa87771af3c956ed2b477f87f7d4974b6`입니다. iOS 호스트 실행 파일 외에 실제 Dart 코드 파일도 따로 해시를 기록했습니다. 명령·로그·파일별 해시·묶음 해시 방식은 [모바일 검사·빌드 증거](acceptance/2026-09-06-release-ops/mobile-image-quality-builds.json)에 보존했습니다. iOS는 빌드 완료 로그와 생성 파일로 성공을 확인했으며, 닫힌 실행 세션의 최종 종료 코드는 별도로 확보하지 못했다고 기록했습니다.

두 산출물은 로컬 검사용이며 스토어 제출용 앱이 아닙니다. 이번에 실기기 설치나 운영 배포는 실행하지 않았습니다. 화면 회귀 검사와 빌드 성공은 실제 비전 검사의 탐지 정확도나 재생성한 그림의 품질 합격을 증명하지 않습니다.

## 최신 전체 API 검증

2026-09-06 11:30 KST에 Python **3.11.15** 전체 API 검사 **1,227개 통과·0개 실패·14개 건너뜀**, line coverage **74.21%**를 확인했습니다. 전체 커버리지 40% 기준과 money-path coverage gate도 통과했습니다. StoryDraft·ImagePrompts 네이티브 JSON Schema, 프롬프트 길이 지시, 실검증 요청·비용 가드, 비공개 독자 프로필과 matrix 전달 회귀 검사 3개까지 포함한 **392개 소스**를 별도 복사했고, 실행 종료까지 해당 소스가 변경되지 않았습니다.

이후 Gemini 참조 이미지·현재 장면의 인물 수·인물별 외모 연결 규칙을 보강했고, **11:46 KST Python 3.11 영향 경로 58개가 모두 통과**했습니다(새 회귀 4개 포함). 전체 검사는 반복하지 않았고 위 커버리지를 새 보강 코드의 측정값으로 표시하지 않습니다. [후속 검사 JSON](acceptance/2026-09-06-release-ops/api-python311-cast-identity.json), [후속 JUnit XML](acceptance/2026-09-06-release-ops/api-tests-python311-cast-identity.xml)에 별도 보존했습니다. 자동 검사는 실제 생성된 그림의 인물 일관성·장면 품질 합격을 증명하지 않습니다.

참조 이미지 다운로드의 차단·예외 로그에서 원문 URL·서명 쿼리·예외 문자열을 제거한 후속 변경은 **11:54 KST Python 3.11 집중 검사 33개 통과**로 확인했습니다(새 민감정보 회귀 3개 포함). 고정 메시지와 예외 유형만 기록하며 SSRF 방어·스토리지 경로·30초 제한시간·생성 요청 내용은 유지했습니다. [로그 보호 검사 JSON](acceptance/2026-09-06-release-ops/api-python311-reference-logging.json), [JUnit XML](acceptance/2026-09-06-release-ops/api-tests-python311-reference-logging.xml)에 별도로 기록했습니다.

실제 Git 제외·추적 여부 검사를 위해 기존 Python 검사 이미지에 Git을 추가한 전용 이미지를 사용했습니다. 검사 컨테이너는 `--network none`이며, 계정 환경 파일·서명 자료·개인 독자 설정 폴더를 복사하지 않았습니다. 이 결과는 SQLite와 모의 공급자를 사용하는 전체 API 자동 검사입니다. 실생성 품질·실기기·스토어·운영 배포 상태는 별도 검증하며, 건너뛴 14개 PostgreSQL·Redis·Celery 전용 검사의 앞선 실제 의존성 검증 기록도 아래에 구분했습니다.

증거: [검사 결과 JSON](acceptance/2026-09-06-release-ops/api-python311-final.json), [JUnit XML](acceptance/2026-09-06-release-ops/api-tests-python311-final.xml), [coverage XML](acceptance/2026-09-06-release-ops/api-coverage-final.xml), [소스 파일별 SHA-256](acceptance/2026-09-06-release-ops/api-python311-final-source-manifest.json). 스냅샷 SHA-256은 `29f95c74f217acdcf33b72a749fd1ff79181081d477f69a81b62bc2c6aa041a3`입니다.

## 이번에 확인한 배포 경로

- `--image-tag`가 `infra/.env`의 오래된 `API_IMAGE`·`WORKER_IMAGE`를 확실히 덮어씁니다.
- 상태 검사는 `PROD_API_URL`의 TLS 인증서를 검증하고 `/health/live`와 `/health/ready`에서 정확히 200만 통과시킵니다. 리다이렉트·503·인증서 오류는 실패이며 준비 상태 회복을 제한 시간 동안 기다립니다.
- CI의 최종 smoke도 같은 HTTPS origin을 사용합니다. 새 릴리스 상태 검사 실패 시 이전 API·워커 이미지로 되돌리고 CI는 실패로 남습니다.
- DB 덤프는 비공개 권한으로 작성하고 읽을 수 있는 완성본만 보관합니다. 합성 DB·미디어를 별도 환경에 복원한 뒤 내용·제약·인증 폐기 상태·미디어 접근 권한을 검증하는 리허설을 CI에 추가했습니다.
- 무료 제한 베타의 새 구매·오디오·실물 주문은 계속 꺼져 있습니다. 실제 긴 생성 응답을 고려한 LLM 요청 제한시간은 90초입니다.

## 앞선 검증 기록

같은 날 앞서 수행한 전체 검사에서 Python 3.11 API **1,109개 통과**, line coverage **74.09%**, money-path coverage gate가 통과했습니다. 일반 API 실행에서 건너뛴 PostgreSQL 의존 검사 14개는 별도 실제 PostgreSQL/Redis/Celery 환경에서 모두 통과했습니다. 같은 환경에서 비공개 미디어 검사 19개와 HTTP 사용자 여정 33개도 통과했습니다. 이는 실행 계층과 권한·데이터 복구에 관한 증거이며 실기기·스토어·운영 배포 완료를 의미하지 않습니다.

이후 StoryDraft 전용 네이티브 JSON Schema 연결은 별도 Python 3.11 영향 경로 **301개 통과**로 검증했습니다(새 회귀 검사 22개 포함). 앞의 1,109개 전체 검사·커버리지 결과와 구분하며, 실공급자의 내용 품질은 새로운 비교 표본에서 확인합니다. 증거: `docs/acceptance/2026-09-06-release-ops/api-python311-structured.json`.

ImagePrompts 보완 전 전체 검사 **1,169개 통과**는 [별도 스냅샷](acceptance/2026-09-06-release-ops/api-python311-pre-imageprompts.json)으로 보존했습니다. 보완 후 첫 실행에서 독자 프로필 검사 31개가 Git 없는 검사 이미지의 준비 단계에서 실패한 [환경 오류 기록](acceptance/2026-09-06-release-ops/api-python311-missing-git.json)도 보존했습니다. 테스트의 Git 검사를 유지하고 환경을 보완한 뒤, matrix 옵션과 추가 회귀까지 포함해 위의 최신 전체 검사에서 통과했습니다.

## 운영 대상에 필요한 값과 상태

2026-09-06에 값을 출력하지 않고 확인한 상태입니다. `apps/api/.env`의 정상 동작하는 로컬 AI 연결과 `infra/.env`의 운영 설정은 별개입니다.

| 항목 | 확인된 상태 | 다음 적용 위치 |
|---|---|---|
| 서버·SSH 배포 대상 | GitHub 저장소와 `production` environment 모두 배포 secret/variable 미등록 | `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_KEY`, 검증 후 `DEPLOY_ENABLED=true` |
| 공개 API와 TLS | 운영 `PROD_API_URL` 미설정 | 공개 HTTPS 주소(호스팅 기본 주소 가능), `infra/.env`, 모바일 `PROD_API_URL` |
| 공개 정책 페이지 | 실제 개인정보처리방침·이용약관 주소 미설정 | 공개 HTTPS `PRIVACY_POLICY_URL`·`TERMS_OF_SERVICE_URL`, 모바일 `--dart-define`에 별도 전달 |
| 비공개 미디어 | 운영 S3 자격증명·장치에서 접근할 HTTPS endpoint 미구성 | `S3_ENDPOINT`, `S3_DOWNLOAD_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`, 안정적인 canonical URL base |
| 운영 프로세스 설정 | 개발용 `infra/.env`에 필수 운영 필드 누락 | 실제 AI provider/model secret 주입, `ADMIN_API_KEY`, strict IAP, 비용 한도 등 `infra/.env.example` 계약 적용 |
| Android 릴리스 서명 | 로컬 업로드 키와 `android/key.properties` 준비·0600/Git 제외 검증 완료 | [ANDROID_SIGNING.md](ANDROID_SIGNING.md)의 외부 암호화 백업, Play Console 등록/기존 인증서 확인 |
| iOS 서명 | 프로젝트 팀 설정·로컬 유효 code-signing identity 2개 존재 | 해당 앱/팀의 배포 profile, App Store Connect 접근 및 실제 archive/export 검증 |
| 운영 백업 보관소 | 지정된 외부 보관소 없음 | 비공개 암호화 백업 대상, 최신 삭제·인증 폐기 기록의 복구 수단 |

등록된 GitHub 배포 값이 없다고 해서 사용자가 다른 곳에 서버를 소유하지 않는다는 뜻은 아닙니다. 현재 프로젝트에서 실행 대상으로 확인된 서버가 없다는 뜻입니다. 운영 대상이 정해지면 같은 AI 키를 비밀 저장 경로로 주입할 수 있으며 새 AI 계정을 만들 필요는 없습니다.

## 배포 순서

1. [DEPLOYMENT.md](DEPLOYMENT.md)에 따라 운영 서버·DNS·TLS와 비공개 미디어를 구성합니다. 앱과 API의 URL은 HTTPS로 고정합니다.
2. `infra/.env.example`을 기준으로 별도 베타 환경을 구성합니다. 초대 계정 해시와 함께 `GENERATION_ACCESS_MODE=invite_only`, `FREE_PLAN_FIRST_BOOK_TRIAL=true`를 설정합니다. 예제는 OpenAI `gpt-image-2`와 `AUDIO_FEATURE_ENABLED=true`, `AUDIO_NARRATION_ONLY_ENABLED=true`, `TTS_PROVIDER=openai_realtime`을 사용합니다. 낭독 키는 `OPENAI_TTS_API_KEY_FILE`로 비공개 마운트에서 읽거나 `OPENAI_TTS_API_KEY`로 전달합니다. `PURCHASES_ENABLED=false`, `POD_ORDERING_ENABLED=false`, `IAP_VERIFICATION_MODE=strict`, `DAILY_GENERATION_BUDGET=20`, `LLM_TIMEOUT=90`을 적용합니다. 운영자가 OpenAI 프로젝트의 ZDR 적용 확인을 완료했다고 전달했습니다. 최신 빌드의 실제 한국어 낭독과 실기기 재생을 마친 뒤 운영 전환을 진행합니다. 생성 횟수 제한과 공급자 금액 한도는 별도로 확인합니다.
3. 실제 공개 개인정보처리방침·이용약관·지원 페이지가 로그인 없이 열리는지 확인합니다. 호스팅 서비스의 기본 HTTPS 주소도 사용할 수 있으며 별도 도메인은 필수가 아닙니다. `PRIVACY_POLICY_URL`·`TERMS_OF_SERVICE_URL`은 운영자·모바일 빌드 설정이므로 백엔드 Settings나 API/worker Compose 환경에 전달하지 않습니다. 아래 세 환경 변수에는 실제 검증한 주소를 먼저 설정해야 합니다. 미설정이면 명령이 중단되며, 예시 주소를 실제 운영 주소로 간주하지 않습니다. 이후 검증을 통과시키고 SHA 이미지가 GHCR에 존재하는지 확인합니다.

```bash
: "${PROD_API_URL:?검증한 공개 HTTPS API 주소를 설정하세요}"
: "${PRIVACY_POLICY_URL:?실제 공개 HTTPS 개인정보처리방침 주소를 설정하세요}"
: "${TERMS_OF_SERVICE_URL:?실제 공개 HTTPS 이용약관 주소를 설정하세요}"
export PROD_API_URL PRIVACY_POLICY_URL TERMS_OF_SERVICE_URL
./scripts/check-env.sh --mode production --env-file infra/.env
./scripts/final-external-preflight.sh --free-beta --env-file infra/.env --json
./scripts/run_backup_restore_rehearsal.sh
```

4. 확정한 서버에서만 SHA 배포와 상태 검사를 실행합니다. 제공자 전환에서는 현재 운영 설정의 비공개 사본을 `--rollback-env-file`로 지정합니다. 읽기 전용 키 마운트처럼 Compose 파일도 달라지면 이전 기본 파일과 오버라이드를 원래 순서대로 `--rollback-compose-file`에 각각 지정합니다. 별도 파일 구성을 쓰는 시험 운영 서버는 해당 서버의 고정 실행 절차를 따릅니다. smoke는 새 합성 사용자·생성 요청을 만들 수 있습니다.

```bash
: "${ASB_PREVIOUS_ENV_FILE:?직전 운영 설정의 비공개 사본 경로를 지정하세요}"
./scripts/deploy.sh --env-file infra/.env --rollback-env-file "$ASB_PREVIOUS_ENV_FILE" \
  --image-tag <검증한-커밋-SHA> deploy
./scripts/deploy.sh --env-file infra/.env health
./scripts/deploy.sh --env-file infra/.env smoke
```

5. 서명이 준비되면 같은 HTTPS API와 공개 정책 페이지를 명시한 배포용 앱을 빌드합니다. 앞 단계와 동일한 실제 환경 값을 사용하며, 백엔드 환경 파일의 값이 Flutter 앱으로 자동 전달된다고 가정하지 않습니다. 서명되지 않은 iOS 앱이나 Android debug APK는 스토어 배포 산출물로 표시하지 않습니다.

```bash
: "${PROD_API_URL:?검증한 공개 HTTPS API 주소를 설정하세요}"
: "${PRIVACY_POLICY_URL:?실제 공개 HTTPS 개인정보처리방침 주소를 설정하세요}"
: "${TERMS_OF_SERVICE_URL:?실제 공개 HTTPS 이용약관 주소를 설정하세요}"
cd apps/mobile
flutter build appbundle --release \
  --dart-define="PROD_API_URL=$PROD_API_URL" \
  --dart-define="PRIVACY_POLICY_URL=$PRIVACY_POLICY_URL" \
  --dart-define="TERMS_OF_SERVICE_URL=$TERMS_OF_SERVICE_URL"
flutter build ipa --release \
  --dart-define="PROD_API_URL=$PROD_API_URL" \
  --dart-define="PRIVACY_POLICY_URL=$PRIVACY_POLICY_URL" \
  --dart-define="TERMS_OF_SERVICE_URL=$TERMS_OF_SERVICE_URL"
```

법무·사업자·개인정보 및 스토어의 본인 확인/약관/최종 제출 항목은 [appstore/submission-checklist.md](appstore/submission-checklist.md)와 현재 출시 기록에서 확인합니다. 이 문서는 약관 동의나 스토어 등록을 대신하지 않습니다.
