# 제한 베타 배포 준비

## 2026-11-04 후보 재검증

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

새 합성은 현재 3–5세 책만 무료 플랜에서 가능하다. 베타 설명과 시험 계정의 실제 이용 범위를 이에 맞춘다. 출시용 후보에서는 운영 Gemini 음성 선택과 재생, 계정 복구와 삭제, 앱 재실행 후 서재 접근도 확인한다.

제한 베타 후보는 `FREE_PLAN_FIRST_BOOK_TRIAL=true`에서 신규 계정에 첫 동화 한 권을 지급한다. 잔액 생성과 지급 기록은 같은 트랜잭션으로 저장하며, 생성 실패 환불은 기존 잡 경로를 사용한다. 기존 잔액은 유지하고 매월 자동 지급은 중단한다. 기본 낭독·구연동화·잠자리 스타일은 앱에 들어 있는 미리듣기로 비교할 수 있다. 베타 운영에 연결하기 전에 일일 예산과 초대 계정으로 전체 첫 권을 검증한다.

생성 대기 화면에는 가상 동화 《하루와 초록 싹》의 예시 삽화를 넣었다. 단계와 비율은 서버 잡의 값을 표시한다. 기본 크기와 작은 화면의 큰 글씨·다크 모드에서 렌더링을 확인했다. 낭독 설정의 표시 이름은 이야기 성우·구연동화·잠자리이며, 기존 설정 값과 미리듣기 파일을 사용한다. [밝은 화면](acceptance/2026-11-04-first-book-loading-design/creation-loading-light.png) · [작은 화면 다크 모드](acceptance/2026-11-04-first-book-loading-design/creation-loading-dark-reduced-motion.png)

테스터용 HTTPS API에는 기존 소유의 DNS 호스트명을 연결하고, 새 유료 AI 작업은 `invite_only`와 전역 한도를 유지한다. 새 구매는 비활성화한다. 서로 다른 시험 계정으로 허용된 생성 1회와 비초대 계정의 제공자 호출 전 거부를 확인한다. 이어 실제 연락처와 승인된 정책으로 지원·삭제 사이트를 게시하고, API 및 정책 주소를 `scripts/build_mobile_release.py`의 공개 전용 JSON에 넣어 검사한 뒤 배포 서명으로 빌드한다. 공개 URL이나 유효한 배포 서명을 확인할 수 없으면 디버그 후보를 테스트 트랙에 올리지 않는다. [지원 사이트](../apps/public-site/README.md) · [스토어 체크리스트](appstore/submission-checklist.md)

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
2. `infra/.env.example` 계약을 기준으로 운영 설정을 채웁니다. 초기값은 `PURCHASES_ENABLED=false`, `AUDIO_FEATURE_ENABLED=false`, `POD_ORDERING_ENABLED=false`, `IAP_VERIFICATION_MODE=strict`, `DAILY_GENERATION_BUDGET=20`, `LLM_TIMEOUT=90`입니다. 생성 횟수 제한은 금액 한도가 아니므로 공급자 측 예산 설정도 유지합니다.
3. 실제 공개 개인정보처리방침·이용약관·지원 페이지가 로그인 없이 열리는지 확인합니다. 호스팅 서비스의 기본 HTTPS 주소도 사용할 수 있으며 별도 도메인은 필수가 아닙니다. `PRIVACY_POLICY_URL`·`TERMS_OF_SERVICE_URL`은 운영자·모바일 빌드 설정이므로 백엔드 Settings나 API/worker Compose 환경에 전달하지 않습니다. 아래 세 환경 변수에는 실제 검증한 주소를 먼저 설정해야 합니다. 미설정이면 명령이 중단되며, 예시 주소를 실제 운영 주소로 간주하지 않습니다. 이후 검증을 통과시키고 SHA 이미지가 GHCR에 존재하는지 확인합니다.

```bash
: "${PROD_API_URL:?검증한 공개 HTTPS API 주소를 설정하세요}"
: "${PRIVACY_POLICY_URL:?실제 공개 HTTPS 개인정보처리방침 주소를 설정하세요}"
: "${TERMS_OF_SERVICE_URL:?실제 공개 HTTPS 이용약관 주소를 설정하세요}"
export PROD_API_URL PRIVACY_POLICY_URL TERMS_OF_SERVICE_URL
./scripts/check-env.sh --mode production --env-file infra/.env
./scripts/final-external-preflight.sh --env-file infra/.env --json
./scripts/run_backup_restore_rehearsal.sh
```

4. 확정한 서버에서만 SHA 배포와 상태 검사를 실행합니다. smoke는 새 합성 사용자·생성 요청을 만들 수 있습니다.

```bash
./scripts/deploy.sh --env-file infra/.env --image-tag <검증한-커밋-SHA> deploy
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
