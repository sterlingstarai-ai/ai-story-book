# 앱 등록 전 검토 패키지 — 2026-09-06

2026-09-07 최종 API는 두 참조와 저장본 교정 검증 도구를 포함한 Python3.11 전체 **1,924개 통과·21개 건너뜀·실패0, 커버리지77.26%**다. [최종 API 증거](acceptance/2026-09-07-dual-reference-api-final/result.json). 아래 모바일 산출물은 변경하지 않았으며 실제 그림 품질·운영 연결·서명/스토어 상태는 [최신 출시 현황](LAUNCH_STATUS.md)을 따른다.

앱 등록·업로드·공개 배포 전에 공동 화면 검토를 할 수 있도록 로컬 빌드, 네이티브 화면 검증, 지원 페이지 구현을 준비했다. **이 패키지는 출시 승인이나 스토어 제출 가능한 최종 바이너리를 뜻하지 않는다.** 운영 API와 승인된 정책 URL이 연결되지 않은 release 산출물은 컴파일·서명 구조 검사용이다. 최종 판단은 [출시 상태](LAUNCH_STATUS.md)와 [사진 캐릭터 처리 흐름](PHOTO_CHARACTER_FLOW.md)을 함께 따른다.

## 준비한 파일

| 항목 | 위치와 상태 |
|---|---|
| Android release AAB | `apps/mobile/build/app/outputs/bundle/release/app-release.aab`; 기존 비공개 업로드 키로 서명, Play Billing 8.0.0, target SDK 36 |
| Android release APK | `apps/mobile/build/app/outputs/flutter-apk/app-release.apk`; 같은 최종 소스의 로컬 서명 검증본, 설치·업로드하지 않음 |
| iOS release 앱 | `apps/mobile/build/ios/iphoneos/Runner.app`; 코드 서명 없는 컴파일 검증본, 빈 앱 제품 폴더에서 재생성, 40.3MB |
| 지원·삭제 안내 사이트 | `apps/public-site/`; `/`, `/support/`, `/delete-account/`, `/privacy/`, `/terms/` |
| 사이트 생성 도구 | `scripts/build_public_support_site.py`; 실제 연락처·정책 승인 증거가 없으면 공개용 출력 생성 중단 |
| 네이티브 규격 캡처 | `scripts/capture_store_review.py`; 새 작업 전용 임시 시뮬레이터에서 JPEG 원본 캡처, 크기 변경 없음 |
| 스토어 설명/절차 | `docs/appstore/`; 복구 코드 설명, 무료 제한 베타 범위, 현행 캡처·삭제 URL 요건 반영 |
| 로컬 증거 | Git 제외 `docs/acceptance/2026-09-06-pre-registration-package/`의 `verification.json`, 로그·화면·해시 |

앱 버전은 `1.0.0+1`이다. 기존 아이콘의 원본과 iOS 마케팅 아이콘은 1024×1024이며 투명 픽셀이 없다. 한국어·영어·일본어 ARB는 각각 981개 키로 일치한다. 등록 계정·서명 신원·키 값은 이 문서에 기록하지 않는다.

## 자동 검증의 범위

최신 백엔드 전체 검사는 API **1,848개 통과·21개 건너뜀·0개 실패**이며, 추가로 현재 페이지/확정 캐릭터 바이트가 OpenAI multipart와 Gemini 참조 요청에 정확히 들어가는 모의 HTTP 회귀 **10개**도 통과했다. Python 3.12.12 줄 커버리지 **76.96%**, 전체 `src/tests` Ruff·OpenAPI/모바일 계약·환경 계약 검사를 통과했다. 실제 PostgreSQL/Celery 회귀 **21개는 별도의 새 격리 환경에서 건너뜀 없이 통과**했고, 합성 입력으로 대표 그림 승인 → 본문12쪽 → 소유권·공유·삭제와 전체 HTTP 여정까지 확인하고 임시 자원을 정리했다. 전체 검사의 21개 건너뜀과 격리 실행의 21개 통과는 같은 대상이며 중복 합산하지 않는다. [최신 API·실제 의존성 검증 증거](acceptance/2026-09-06-final-api-gate/result.json). 모의 AI 기술 검증은 실제 삽화 품질·아동 사진 닮음·운영 배포나 스토어 승인을 대체하지 않는다.

이전에 검증한 모바일 전체 520개 검사·64.22% 커버리지의 소스 목록과 대조했을 때 당시 146개 모바일 소스는 일치했다. 그 후 결제 의존성 변경은 [Billing 8 검증](acceptance/2026-09-06-billing8/result.json)의 집중 검사·새 AAB로 확인했다. 이 패키지의 release/native 설정 집중 검사 30개, 지원 페이지·캡처 도구 검사 22개, 최종 Flutter 분석은 통과했다. 과거 전체 커버리지 값을 새 변경의 커버리지로 재해석하지 않는다.

후속으로 크레딧 거래 시각·구독 갱신 날짜를 기기의 현지 시간으로 표시하도록 수정하고, 날짜 전용 값과 현지 시각 값은 유지하는 회귀 2개를 추가했다. 이 수정까지 포함한 모바일 전체 검사를 다시 실행해 **522개 통과·실패 0개**, 커버리지 **64.2345%**(8,874/13,815줄), 정적 분석 **문제 0개**를 확인했다. 테스트 42초, 분석 8.7초이며 검사 전후 149개 소스·의존성 파일이 일치했다. 같은 최종 소스로 release APK **67.6MB**(79.4초), AAB **53.5MB**(8.1초), iOS 무서명 앱 **40.3MB**(37.3초)를 다시 빌드했고 모두 종료 코드 0이다. Android 두 산출물의 서명 무결성과 실제 포함 Billing 8을 다시 확인했다. 새 산출물 해시는 [최종 패키지 증거](acceptance/2026-09-06-pre-registration-package/verification.json)를 따른다. 날짜 표시만 바뀌어 앞선 네이티브 배치 캡처는 재촬영하지 않았으며, 이를 변경 후의 새 네이티브 실행으로 기록하지 않는다.

기존 `final_product_flow_test.dart`를 실제 iOS 런타임에서 실행했다. 동의 → 온보딩 → 프로필 → 12쪽 생성 → 읽기 → 문제 신고/접수 → 완독 → 서재 → 다크 모드 → 부모 대시보드 → 크레딧 → 캐릭터 화면까지 확인한다. 서버는 격리된 로컬 HTTP이며 AI는 mock, 계정은 실행마다 새 가상 계정이다. 테스트 종료 후 해당 가상 계정만 삭제한다. 사진, 실결제, 알림, OS 평점 요청은 이 여정의 검증 범위가 아니다.

첫 iPhone 실행에서 OS 평점 요청 창이 앱 위를 가리는 것을 원본 캡처로 발견했다. 제품의 평점 기능은 유지하고, 테스트에만 주입 가능한 평점 서비스를 사용해 외부 창이 없는 최종 화면을 다시 확보했다. 초기 캡처 묶음은 검토 이력이며 최종본으로 선택하지 않는다. 최종 iPhone 여정은 2분49초, iPad는 3분30초에 통과했고 각각 17장을 저장했다. 검증 전용 임시기기 3대와 수신기를 모두 정리했으며 기존 로컬 API와 개인 책은 보존했다.

iOS 증분 산출물에서 현재 의존성에 없는 옛 광고·웹뷰 리소스가 남은 것도 발견했다. 현재 고정된 Podfile.lock을 유지한 상태로 Pod 설치를 확인하고, 생성된 iOS 앱 제품 폴더 두 개만 비워 다시 빌드했다. 날짜 수정 후에도 같은 방식으로 재생성해 제거된 SDK 리소스가 없고, 현재 포함된 개인정보 매니페스트 16개임을 다시 확인했다. 기존 개인정보 매니페스트를 편집하거나 Android 산출물을 지우지 않았다.

| 화면 묶음 | 원본 규격 | 용도 |
|---|---|---|
| `iphone-69-v2/` | 1320×2868 JPEG | 6.9인치 iPhone 배치·동작·규격 검토 |
| `ipad-13/` | 2064×2752 JPEG | 13인치 iPad 배치·동작·규격 검토 |

캡처별 수·해시·실행 결과·정리 여부는 `verification.json`과 각 `capture-manifest.json`에 기록한다. 그림이 단색 mock인 화면은 **판매용 홍보 자산으로 사용할 수 없다**. 최종 운영 연결과 공동 검토 후 공개 가능한 샘플 책으로 실제 홍보 화면을 선택해야 한다. 개인 아동 사진과 개인 선물 동화는 스토어 제출용으로 복사하지 않는다. iPhone 6.9인치와 iPad 13인치는 현재 [Apple 필수 캡처 규격](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/)에 맞는다.

## 지원·삭제 페이지

로컬에서 320/390px 모바일과 1280px 데스크톱 화면을 직접 확인했다. 가로 넘침이 없고 주요 이동 링크는 최소 64px 높이이며 외부 폰트·스크립트·폼 서버·분석 호출은 없다. 비공개 검토본에는 실제 연락처와 미승인 정책 원문을 넣지 않았다. 최종 브라우저 콘솔 오류는 0개이며 검토 후 브라우저와 전용 HTTP 서버를 종료했다.

공개용 생성에는 실제 지원 이메일, 공개 HTTPS 사이트 주소, 운영자의 연락처 확인, 승인된 개인정보처리방침·약관 HTML과 SHA-256이 필요하다. 정책은 승인된 바이트를 그대로 복사한다. 빈 예시 설정으로 실제 공개용 생성 명령을 실행했을 때 `VERIFIED_SUPPORT_CONTACT_REQUIRED`로 차단되고 출력 폴더가 생성되지 않는 것을 확인했다. 승인 플래그는 운영자의 확인 기록이며 도구가 법적 승인이나 문의 수신 가능성을 대신 검증하지 않는다. 자세한 사용법은 [지원 사이트 README](../apps/public-site/README.md)를 따른다.

앱 밖 삭제 안내는 이메일로 요청을 시작하는 동선이다. 비밀번호·복구 코드·아이 사진을 보내지 않도록 안내한다. 접수 후 안전한 계정 소유 확인, 실제 삭제, 처리 결과 통지까지 검증해야 운영 완료다. Google은 해당 앱에 앱 밖에서도 삭제를 요청할 수 있는 링크를 요구하며 이메일 요청 방식을 허용한다. 이 앱의 복구 가능한 계정 기능을 고려해 삭제 경로를 준비했다는 것은 제품 구조에 근거한 판단이다. [Google 계정 삭제 요건](https://support.google.com/googleplay/android-developer/answer/13327111?hl=en)

## 공동 검토 후 이어지는 실제 출시 단계

1. 운영 API·비공개 미디어 저장소·작업자 환경을 연결하고 실제 준비 상태, 소유권·삭제·복구를 검증한다. 모바일 새 빌드에 `PROD_API_URL`, `PRIVACY_POLICY_URL`, `TERMS_OF_SERVICE_URL`을 명시한다. 임의 주소를 넣어 release 실행 제한을 우회하지 않는다.
2. 실제 운영자 정보와 지원 연락처, 최종 승인 정책을 공개 HTTPS로 게시한다. 앱·스토어 정책 링크와 지원/삭제 요청 링크가 로그인 없이 열리고 실제 응답 가능한지 확인한다. [Apple 개인정보 입력](https://developer.apple.com/help/app-store-connect/manage-app-information/manage-app-privacy/), [지원 URL 요건](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information/)
3. 공동 앱 검토를 완료한 뒤 iOS 배포 서명·프로비저닝과 스토어 앱 등록을 진행한다. 이번 로컬 읽기 검사에서 일치하는 유효 프로필과 사용 가능한 코드 서명 신원은 확인되지 않았다. Apple 포털의 최종 등록·권한 상태는 이 검사로 증명하지 않는다.
4. 최신 release 바이너리에서 앱과 포함 SDK의 실제 데이터 수집을 기준으로 App Privacy/Data Safety, 연령·대상 이용자, AI 생성/신고 항목을 작성한다. SDK 개인정보 매니페스트의 존재만으로 앱 전체 개인정보 답변이 완료되는 것은 아니다. [Apple 필수 사유 API 설명](https://developer.apple.com/documentation/bundleresources/describing-use-of-required-reason-api)
5. 운영 연결본의 기기 설치와 네이티브 파일/공유/권한 동선, Android 16KB 환경 실행, 필요한 테스트 트랙을 확인한다. 현재 AAB의 64비트 ELF 정렬 검사와 빌드는 실제 16KB 기기 실행을 대신하지 않는다. [Android 16KB 안내](https://developer.android.com/guide/practices/page-sizes)
6. 개인 Google 개발 계정의 적용 여부를 콘솔에서 확인한다. 2023-11-13 이후 생성된 해당 개인 계정은 최소 12명이 14일 연속 참여한 비공개 테스트가 필요할 수 있다. 자동 E2E로 이 기간이나 참여자를 대체하지 않는다. [개인 계정 테스트 요건](https://support.google.com/googleplay/android-developer/answer/14151465?hl=en)

이번 무료 제한 베타에서는 신규 구매를 계속 비활성화한다. 결제 의존성의 버전 요건은 충족하도록 준비했지만, 유료 상품 등록·실결제·환불·복원 검증은 유료 출시 전 단계로 따로 수행한다. [Google Billing 지원 기한](https://developer.android.com/google/play/billing/deprecation-faq.html)
