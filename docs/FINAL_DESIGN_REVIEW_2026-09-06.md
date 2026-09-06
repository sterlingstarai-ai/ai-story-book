# 앱 전체 최종 디자인 검토 — 2026-09-06

**앱 전체 화면의 디자인 구현과 자동 회귀 검사를 마쳤다. Flutter 검사 474개와 정적 분석, iOS·Android에서 각각 5개 네이티브 검사, 실제 서버 의존성 E2E가 통과했다.** 이 문서는 현재 구현과 증거의 범위를 기록하며, 스토어 등록·운영 출시 승인 문서는 아니다. [최종 검사 기록](acceptance/2026-09-06-final-design/verification.json)에 실행 범위와 소스 해시를 보존했다.

기존의 수채화 동화, 밝은 종이 배경, 보라색 강조를 유지했다. 홈과 읽기 화면에 한정했던 앞선 수정을 설정·프로필·온보딩·결제 상태·복구·미디어 관리까지 확장했고, 다크 모드와 작은 화면에서도 내용을 읽고 마지막 동작을 수행할 수 있도록 정리했다.

[비공개 화면 갤러리](acceptance/2026-09-06-final-design/gallery.html)에서 네이티브 실행 화면, 최종 위젯 렌더, 수정 전 화면을 나누어 볼 수 있다. 갤러리와 원본은 로컬 검토 자료이며 외부에 게시하지 않았다. 기존의 주요 읽기 화면 개선은 [앞선 디자인 검토](DESIGN_REVIEW_2026-09-06.md)에 기록되어 있다.

공동 확인용 iOS 앱은 격리 API `http://127.0.0.1:18080`에 연결하고 기존 8쪽 동화의 첫 페이지로 열어두었다. [최종 홈](acceptance/2026-09-06-final-design/18-home-final.jpg), [동화 첫 페이지](acceptance/2026-09-06-final-design/19-reader-final.jpg)는 자동 테스트 앱을 종료한 뒤 일반 앱을 직접 조작해 기록한 화면이다. 기존 동화와 그림을 사용했으며 새 유료 AI 호출은 없었다.

## 화면 범위

현재 화면 구현은 20개다. `buildAppRoute`에 등록된 이름 있는 경로 18개와 계정 복구·부분 수정의 직접 화면 전환 2개를 합한 수치다. 모든 화면이 별개의 이름 있는 라우트라는 뜻은 아니다.

| 화면 | 진입 경로 | 이번 최종 검토의 핵심 |
|---|---|---|
| 시작 게이트 | `/startup` | 계정 초기화·동의·온보딩으로 이어지는 기존 순서와 실패 복구 유지 |
| 필수 동의 | `/consent` | 긴 고지와 선택 항목 스크롤, 작은 화면 최종 동작, 라이트·다크 대비. 법적 동의 문구는 변경하지 않음 |
| 온보딩 | `/onboarding` | 처음 시작하는 안내와 이동 버튼, 큰 글씨에서의 배치 |
| 홈 | `/` | 최근 동화 읽기 우선, 만들기 동선, 독서 기록과 다크 모드 카드 대비 |
| 동화 만들기 | `/create` | 추천 예시, 사용 가능한 그림체, 긴 선택 라벨, 64px 터치 영역, 키보드 스크롤·재시도 |
| 생성 진행 | `/loading` | 이야기·그림 검사·보완 상태 안내, 내부 단계명 차단, 기존 작업 상태 재조회, 동작 줄이기 |
| 동화 읽기 | `/viewer` | 제목과 그림 분리, 긴 본문·학습 카드 스크롤, 명시적 완독, 신고·지원되는 오디오 동선 |
| 서재 | `/library` | 긴 제목·필터·책 메뉴, 빈 화면의 만들기 버튼, 오류 후 기존 목록 유지 |
| 캐릭터 | `/characters` | 이름·특징과 사진·그림 선택을 구분한 안내, 빈 화면 버튼 겹침 제거, 역할·성격 선택과 최종 버튼 |
| 크레딧·이용 상태 | `/credits` | 로딩 실패를 잔액 0으로 표시하지 않음, 재시도, 기존 이용권 정보, 비활성 구매 상태 구분 |
| 설정 | `/settings` | 저장 버튼 접근성, 저장 성공 후 테마 반영, 지원되지 않는 설정 숨김, 공개 정책 링크의 실제 구성 상태 표시 |
| 프로필 | `/profiles` | 빈 상태와 불러오기 실패 구분, 생년월·이름 입력, 등록·취소 시 입력창 수명, 기본 크기·좁은 화면 확인 |
| 부모 리포트 | `/parent-dashboard` | 좁은 통계 카드, 월간 차트 가로 스크롤, 오류에서 재시도 |
| 성장 기록 | `/reading-growth` | 긴 통계·비교·등급·공유 동선, 세 언어의 작은 화면과 다크 모드 |
| 가족 목소리 | `/voice-profiles` | 파일 업로드 우선, 링크 입력 접기, 실패 재시도, 등록 창 종료 안정성, 비활성 상태에서도 기존 자료 관리 유지 |
| 분기 동화 | `/branch-story` | 내부 노드 키 제거, 긴 선택지 줄바꿈, 이전 선택·처음부터 버튼 접근 |
| 발음 연습 | `/pronunciation-practice` | 평가 중 중복 요청 차단, 파일 선택 실패 복구, 긴 결과와 최종 동작 |
| 실물책 주문 | `/pod-order` | 기능 지원 여부 확인 후 진입, 조회 실패 재시도, 수량·견적·주소 입력과 최종 버튼 |
| 계정 복구 | 설정 등에서 직접 전환 | 복구 안내·입력·진행·오류 상태와 작은 화면 접근성 |
| 그림 부분 수정 | 읽기 화면에서 직접 전환 | 이미지·선택 영역·설명 준비 전 적용 차단, 키보드와 스크롤, 실패 복구·중복 요청 방지 |

화면 목록은 [화면 소스 폴더](../apps/mobile/lib/screens/)와 [경로 등록 코드](../apps/mobile/lib/main.dart)에서 확인할 수 있다. 기능 비활성 상태를 숨기거나 준비되지 않았다고 표시한 화면은 실제 외부 기능이 출시 준비를 마쳤다는 의미가 아니다.

## 공통 요소와 오버레이

- **테마·문자·버튼:** 화면별 고정 색상을 공통 팔레트로 정리했다. 라이트·다크 배경에서 주요 텍스트 색상 대비를 검사했고, 공통 주·보조 버튼은 높이 64px을 최소값으로 삼아 긴 글씨가 필요할 때 늘어나게 했다. 앱 바, 아이콘 버튼, 입력 필드와 선택 요소도 함께 정리했다.
- **하단 메뉴:** 선택 상태와 라벨 대비, 터치 영역, 현재 탭을 반복 눌렀을 때의 이동을 정리했다.
- **입력 창·시트:** 보호자 확인, 프로필·목소리 등록, 캐릭터 소스 선택, 크레딧 부족 안내, 내용 신고 등에서 스크롤과 최종 버튼 접근을 확인했다. 입력 컨트롤러는 창의 종료 애니메이션까지 유지하도록 수명을 바로잡았다.
- **읽기 오버레이:** 본문·오디오·따라 읽기·단어·퀴즈·완독·신고 메뉴의 가림과 클릭 영역을 검토했다. 서버에서 지원하지 않는 오디오·실물 주문 기능을 사용할 수 있는 것처럼 노출하지 않는다.
- **사용 시간 잠금:** 세 언어·두 테마에서 안내와 보호자 연장 동작이 짧은 화면 밖으로 사라지지 않도록 확인했다.
- **대기·오류 상태:** 개인정보가 담길 수 있는 예외 원문과 내부 단계명을 일반 안내에 노출하지 않으며, 빈 데이터와 조회 실패를 구분한다. 상태를 모르는 생성 작업은 같은 작업을 재조회해 중복 생성·비용을 피한다.

관련 구현은 [공통 위젯](../apps/mobile/lib/widgets/), [공통 테마](../apps/mobile/lib/utils/app_theme.dart), [색상·크기 기준](../apps/mobile/lib/utils/constants.dart)에 있다. 보호자 확인, 사진 사용 직전 동의, 프로필 소유권, 기존 영수증 검증과 연령별 제한을 완화하지 않았다.

## 검토 방식과 화면 증거

소비자 관점, 시각 디자인, UI/UX 관점을 나누어 에이전트가 검토했고, 구현·자동 검사·화면 캡처 확인을 함께 수행했다. 이는 실제 소비자를 모집한 인터뷰나 사용성 조사, 외부 전문가의 공식 인증이 아니다.

| 증거 종류 | 확인할 수 있는 것 | 확인 범위의 한계 |
|---|---|---|
| 수정 전 네이티브 캡처 | 원래 홈·설정·프로필·리포트에서의 색상·레이아웃 문제 | 과거 상태이며 현재 앱의 최종 화면이 아님 |
| 최종 위젯 렌더 | 앱 테마와 Pretendard를 사용한 작은 화면·큰 글씨·오류·다크 모드 비교 | 위젯 시험 환경의 데이터·플러그인 대역을 사용. 시스템 키보드·이모지·기기 플러그인 동작을 증명하지 않음 |
| iOS 실행 화면 | 실제 iOS 앱에서 HTTP 흐름을 실행하며 저장한 앱 화면 | 현재 새 시나리오 진행 중. 일부 캡처 존재만으로 전체 통과를 선언하지 않음. OS 전체 화면 캡처와도 구분 |
| 일반 위젯 회귀 | 실제 폰트보다 폭이 큰 시험용 폴백 글꼴에서도 넘침·동작 검증 | 실제 기기의 모든 글꼴·설정·해상도 조합을 대신하지 않음 |

실제 폰트 검사에서 통과했던 영어 캐릭터 라벨이 일반 전체 검사에서는 넘치는 문제가 발견되어, 라벨을 남은 폭 안에서 줄바꿈하도록 보완했다. 최종 상태는 일반·실제 폰트 검사 양쪽에서 다시 확인했다. 빈 캐릭터 화면의 중앙 생성 버튼을 FAB가 덮던 문제 역시 캡처 확인 후 수정했다.

대표 화면:

| 비교 대상 | 화면 증거 |
|---|---|
| 다크 모드 일관성 | [수정 전 홈](acceptance/2026-09-06-final-design/04-home-dark-before.jpg), [최종 홈 렌더](acceptance/2026-09-06-final-design/widget-renders/reading-home-dark-short.png) |
| 캐릭터 생성 | [빈 화면](acceptance/2026-09-06-final-design/widget-renders/creation-characters-empty-light.png), [역할 선택](acceptance/2026-09-06-final-design/widget-renders/creation-character-form-dark.png), [최종 버튼](acceptance/2026-09-06-final-design/widget-renders/creation-character-form-end-dark.png) |
| 프로필 입력 | [수정 전](acceptance/2026-09-06-final-design/06-profile-dialog-before.jpg), [402px 기본 크기](acceptance/2026-09-06-final-design/widget-renders/parent-profile-dialog-402.png), [800px 검증](acceptance/2026-09-06-final-design/widget-renders/parent-profile-dialog-800.png) |
| 입력·신고 | [목소리 등록](acceptance/2026-09-06-final-design/widget-renders/creation-voice-dialog-dark.png), [부분 수정과 키보드](acceptance/2026-09-06-final-design/widget-renders/creation-inpaint-keyboard-dark.png) |
| 긴 정보·학습 | [월간 차트](acceptance/2026-09-06-final-design/widget-renders/parent-report-chart-Brightness.dark.png), [단어 카드 스크롤](acceptance/2026-09-06-final-design/widget-renders/reading-viewer-vocabulary-scrolled-dark-short.png) |
| 통과한 iOS HTTP 흐름 | [동의](acceptance/2026-09-06-final-design/native-renders/ios/01-consent.png), [생성 화면](acceptance/2026-09-06-final-design/native-renders/ios/05-create.png), [읽기](acceptance/2026-09-06-final-design/native-renders/ios/08-reader.png) |
| 통과한 Android HTTP 흐름 | [동의](acceptance/2026-09-06-final-design/native-renders/android/01-consent.png), [읽기](acceptance/2026-09-06-final-design/native-renders/android/08-reader.png), [다크 모드 설정](acceptance/2026-09-06-final-design/native-renders/android/13-settings-dark.png) |

## 작은 화면·언어·테마 검사 범위

기본 스트레스 조건은 **320×480 논리 픽셀, 글자 배율 1.4**다. 표시 유무만 확인하지 않고 스크롤 후 최종 버튼에 닿는지, 선택지가 잘리는지, 키보드가 열린 상태에서 입력과 종료가 가능한지도 검사했다.

| 검사 묶음 | 언어·테마와 조건 |
|---|---|
| 공통 입력·버튼·사용 시간 잠금 | 한국어·영어·일본어 × 라이트·다크, 320×480·1.4배 |
| 캐릭터 역할·성격 폼 | 한국어·영어·일본어 × 라이트·다크, 320×480·1.4배. 일반 폴백 글꼴과 실제 폰트 양쪽 확인 |
| 성장 기록 | 한국어·영어·일본어 × 라이트·다크, 320×480·1.4배. 각 섹션과 최종 동작까지 스크롤 |
| 동화 생성 선택 | 세 언어의 다크 모드·작은 화면. 기존 생성 옵션·권한·오류 회귀와 함께 확인 |
| 설정·동의·온보딩·프로필·복구·크레딧·주문·부모 리포트 | 한국어의 라이트·다크·320×480·1.4배를 중심으로 검토. 프로필 창은 402×874·800×1000의 기본 글씨도 추가 확인 |
| 읽기·서재·목소리·분기·부분 수정 | 긴 본문·제목·선택지, 오류, 비활성 기능, 키보드, 최종 버튼에 대한 상태별 검사 |

모든 20개 화면의 모든 데이터 상태를 세 언어·두 테마·모든 기기에서 전수 실행한 것은 아니다. 위 표는 실제 수행한 조합을 나타낸다. 관련 검사: [공통 요소](../apps/mobile/test/shared_design_final_test.dart), [생성·캐릭터·미디어](../apps/mobile/test/creation_final_design_test.dart), [보호자 관리](../apps/mobile/test/parent_final_design_test.dart), [읽기·성장](../apps/mobile/test/reading_design_accessibility_test.dart).

## 검증 결과

| 검사 | 확인 결과 | 근거 |
|---|---|---|
| Flutter 전체 회귀 | **474개 통과**, 줄 커버리지 **61.95%** (8,250/13,317줄) | [전체 로그](acceptance/2026-09-06-final-design/flutter-suite.log), [최종 기록](acceptance/2026-09-06-final-design/verification.json) |
| Flutter 정적 분석 | **문제 없음**, 도구 보고 20.2초 | [분석 로그](acceptance/2026-09-06-final-design/flutter-analyze.log) |
| 실제 PostgreSQL 회귀 | **14개 통과**: 계정 복구 4개, PostgreSQL/Celery 10개 | [런타임 결과](acceptance/2026-09-06-final-design/runtime/result.json), [JUnit](acceptance/2026-09-06-final-design/runtime/runtime-tests.xml) |
| 실제 Redis·Celery·비공개 MinIO/S3 HTTP 여정 | 통과. 생성 작업 전달·완료·소유자 읽기, 서명 다운로드, 익명/타 계정 차단, 서명 변조·만료, 공유 철회 등을 확인했고 자원을 정리함 | [런타임 결과](acceptance/2026-09-06-final-design/runtime/result.json) |
| iOS 26.5 Simulator | 기존 네이티브 회귀 **4개 통과**, 새 로컬 HTTP 전체 여정 **1개 통과** | [HTTP 최종 로그](acceptance/2026-09-06-final-design/native-http-e2e.log), [기존 회귀 로그](acceptance/2026-09-06-final-design/ios-native-regression.log) |
| Android API 36.1 Emulator | 기존 네이티브 회귀 **4개 통과**, 새 로컬 HTTP 전체 여정 **1개 통과** | [HTTP 최종 로그](acceptance/2026-09-06-final-design/android-native-http-e2e.log), [기존 회귀 로그](acceptance/2026-09-06-final-design/android-native-regression.log) |
| 공개 정책 URL 사전검사 | **56개 통과**, CI 환경 구성 검사 통과. 실제 URL 배포 검증은 미완료 | [최종 기록](acceptance/2026-09-06-final-design/verification.json) |

두 플랫폼의 새 여정은 필수 동의(사진 선택 동의 제외) → 온보딩 → 가상 테스트 프로필 → 기본 12쪽 생성 → 표지·본문 이미지 다운로드와 표시 → 3쪽 이어 읽기 → 새 보호자 확인 후 신고 접수 → 명시적 완독 → 서재 → 다크 모드 저장·서버 확인 → 주간·월간 부모 리포트 → 크레딧·캐릭터 화면을 확인했다. 고유한 테스트 계정을 사용하고 종료 시 삭제했다. 기존 4개 검사는 신규·재방문 경로, 보호자 확인과 기기의 Keychain/Keystore 저장·복구·삭제를 확인한다.

새 여정을 개발하는 과정에서 실제 프로필 등록 창의 intrinsic 크기 오류를 발견해 수정했고, 기본 402×874 및 800×1000 회귀를 추가했다. 이후 버튼 찾기·가상 목록 스크롤·테스트 SemanticsHandle 종료 처리의 테스트 코드 문제도 수정했다. 보존한 iOS 결합 실행 로그에는 기존 4개 통과와 새 테스트의 종료 처리 실패가 함께 있으며, 해당 새 테스트는 수정 후 별도 최종 실행에서 통과했다. 이 결합 실행의 실패 이력은 별도 보존했다.

런타임 E2E는 실제 PostgreSQL·Redis·Celery·비공개 S3를 사용했지만 AI 생성과 전체 삽화 검토는 명시적인 모의 공급자다. 네이티브 HTTP 여정은 SQLite와 비공개 MinIO를 사용하는 별도 로컬 API에 연결하며, 생성된 단색 그림과 본문 역시 모의 응답이다. 실제 AI 모델의 응답 품질, 낭독·발음 공급자, 스토어 결제·복원이나 운영 서버 승인 증거로 해석하지 않는다. 모의 공급자 설정에서 운영 준비 상태가 거부되는 것도 해당 검사에서 확인한 의도된 결과다.

## 출시 전 남은 확인

1. 사용자와 최종 앱 화면을 함께 확인한다. 자동·에뮬레이터 검사는 완료했지만 사용자의 공동 검토와 출시 결정은 남아 있다.
2. 운영 공개 API·TLS·비공개 저장소와 실제 개인정보처리방침·이용약관·지원 페이지를 구성한다. 공개 정책 주소는 `PRIVACY_POLICY_URL`·`TERMS_OF_SERVICE_URL`을 명시적으로 모바일 빌드에 전달한다. 호스팅 기본 HTTPS 주소를 사용할 수 있으며, 별도 도메인 구매는 필수가 아니다. 기존 Vercel·Supabase 계정을 활용하는 [앱 전용 구성안](APP_ONLY_HOSTING_PLAN.md)을 마련했으며 새 프로젝트 연결·운영 배포는 하지 않았다.
3. 실제 12쪽 동화의 내용·삽화 품질, 아동 대상 서비스의 AI 공급자 정책과 필요한 데이터 처리 설정을 별도 검증한다. 코드 검사나 모의 생성 성공으로 이 항목을 완료 처리하지 않는다.
4. 활성화할 외부 기능에 한해 실기기·실계정 결제/복원, 음성·파일 선택·공유·알림 등 기기 경계를 확인한다. 비활성 기능을 출시 완료로 표시하지 않는다.
5. 사용자의 사전 등록 보류 방침을 유지한다. 스토어 앱 등록·업로드·최종 제출·운영 배포는 이번 디자인 완료에 포함되지 않는다.

공개 링크의 구성 검사만 통과해도 최종 출시 판정은 계속 `launch_ready=false`다. 실제 공개 페이지가 로그인 없이 열리는지 확인해야 한다. 배포 준비의 최신 절차는 [RELEASE_PREPARATION.md](RELEASE_PREPARATION.md), 전체 출시와 콘텐츠 품질 판정은 [LAUNCH_STATUS.md](LAUNCH_STATUS.md) 및 [ILLUSTRATION_QUALITY_GATE.md](ILLUSTRATION_QUALITY_GATE.md)를 함께 확인한다.
