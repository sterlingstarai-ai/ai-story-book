# AI Story Book — 외주 개발 명세서

> **문서 버전**: 1.0 | **작성일**: 2026-02-21
> **발주자**: [발주사명]
> **수주자**: [외주 개발사명]
> **현재 버전**: 0.3.2 (MVP v0.1 + v0.2 완료)

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [현재 시스템 현황](#2-현재-시스템-현황)
3. [Phase 0: 앱스토어 출시 필수 요건](#3-phase-0-앱스토어-출시-필수-요건)
4. [Phase 1: Critical/High 버그 수정](#4-phase-1-criticalhigh-버그-수정)
5. [Phase 2: 핵심 기능 추가](#5-phase-2-핵심-기능-추가)
6. [Phase 3: 차별화 기능](#6-phase-3-차별화-기능)
7. [Phase 4: 블루오션 기능](#7-phase-4-블루오션-기능)
8. [기술 가이드라인](#8-기술-가이드라인)
9. [검수 프로세스 및 인수 조건](#9-검수-프로세스-및-인수-조건)
10. [일정 및 마일스톤](#10-일정-및-마일스톤)
11. [부록: 파일 맵](#11-부록-파일-맵)

---

## 1. 프로젝트 개요

### 1.1 서비스 설명

AI Story Book은 **AI로 맞춤형 동화책을 생성**하는 모바일 앱입니다.

- 아이의 **사진을 캐릭터로 변환**하여 동화 주인공으로 등장
- **연령별(3-5/5-7/7-9세) 최적화**된 문체, 어휘, 교육 테마
- **시리즈 일관성**: 같은 캐릭터로 매일 새로운 동화
- **한국어 최우선** (영어 병행 지원)

### 1.2 기술 스택

| 구분 | 기술 |
|------|------|
| Frontend | Flutter (iOS + Android) |
| Backend | FastAPI (Python 3.11+) |
| Queue | Celery + Redis |
| Database | PostgreSQL |
| Storage | S3 호환 (Minio 로컬, R2/S3 운영) |
| AI | LLM (텍스트 생성) + Image API (이미지 생성) + Google TTS / ElevenLabs |
| CI/CD | GitHub Actions |
| 상태관리 | Riverpod (Flutter) |

### 1.3 모노레포 구조

```
ai-story-book/
├── apps/
│   ├── mobile/          # Flutter 앱 (iOS/Android)
│   │   ├── lib/
│   │   │   ├── main.dart
│   │   │   ├── screens/         # 화면별 위젯
│   │   │   ├── models/          # 데이터 모델
│   │   │   ├── services/        # API 클라이언트
│   │   │   ├── providers/       # Riverpod 상태 관리
│   │   │   └── theme/           # 디자인 토큰
│   │   ├── ios/
│   │   ├── android/
│   │   └── pubspec.yaml
│   └── api/             # FastAPI 백엔드
│       └── src/
│           ├── main.py
│           ├── models/          # Pydantic 모델
│           ├── core/            # 설정, 에러
│           ├── services/        # 비즈니스 로직
│           ├── prompts/         # Jinja2 프롬프트
│           └── routers/         # API 라우터
├── packages/shared/schema/      # JSON Schema
├── infra/                       # Docker, Nginx
└── docs/                        # 문서
```

### 1.4 현재 완성된 기능 (v0.1 + v0.2)

| 기능 | 상태 | 비고 |
|------|------|------|
| 책 생성 (주제/연령/스타일/테마/캐릭터) | 완료 | 표지 + 8페이지 |
| 페이지 재생성 (텍스트/이미지) | 완료 | |
| 캐릭터 시트 자동 생성/저장 | 완료 | |
| 사진 → 캐릭터 변환 | 완료 | image_picker |
| 시리즈 (같은 캐릭터 연속 생성) | 완료 | |
| PDF 내보내기 | 완료 | ReportLab |
| TTS 오디오 | 완료 | Google TTS + ElevenLabs |
| 공유하기 | 완료 | share_plus (URL/메시지/PDF) |
| 크레딧/구독 시스템 | 백엔드만 완료 | **프론트 접근 불가 (라우트 없음)** |
| 스트릭 (매일 읽기) | 백엔드만 완료 | **프론트 UI 없음** |
| 진행률 실시간 표시 | 완료 | |
| 서재 (내 책 목록) | 완료 | 최대 20권 고정 |

---

## 2. 현재 시스템 현황

### 2.1 앱스토어 출시 불가 사유 (100% 리젝)

다음 항목이 해결되지 않으면 Apple App Store / Google Play 모두 **심사 100% 리젝**됩니다.

| # | 사유 | 심각도 |
|---|------|--------|
| 1 | **IAP(인앱결제) 미연동** — 현재 매출 0원, 디지털 콘텐츠 판매 시 IAP 필수 | 리젝 |
| 2 | **개인정보처리방침 없음** — 앱스토어 필수 요구 사항 | 리젝 |
| 3 | **부모 동의 메커니즘 없음** — 아동 대상 앱 COPPA/KISO 위반 | 리젝 |
| 4 | **연령 게이트 없음** — 구매 화면 접근 시 부모 인증 필수 | 리젝 |
| 5 | **릴리스 서명 미설정** — debug key 사용 중 | 리젝 |
| 6 | **앱 아이콘 없음** — 기본 Flutter 아이콘 사용 중 | 리젝 |

### 2.2 발견된 버그 (10명 전문가 에이전트 분석)

- **Critical**: 4건
- **High**: 4건
- **Medium**: 2건
- **구조적 이슈**: 3건

### 2.3 미연결 기능

- `credits_screen.dart` 존재하나 `screens.dart`에서 export 안 됨, `main.dart`에 라우트 없음 → **접근 불가**
- 스트릭 API 전체 완성 (info/today/read/history/calendar) 되어 있으나 **프론트 UI 0%**
- `pubspec.yaml`에 Pretendard 폰트 **주석 처리**되어 있음

---

## 3. Phase 0: 앱스토어 출시 필수 요건

> **목표**: Apple App Store + Google Play 심사 통과에 필요한 최소 요건
> **예상 기간**: 2-3주
> **우선순위**: 최상 (이것 없으면 출시 불가)

---

### P0-1. 개인정보처리방침 + 이용약관

**요구사항**:
- 한국어/영어 개인정보처리방침 웹페이지 작성
- 이용약관 웹페이지 작성
- 아동 데이터 처리 관련 조항 포함 (COPPA/KISO 준수)
- 사진 데이터 처리 정책 명시 (캐릭터 생성용 사진)
- GitHub Pages 또는 별도 호스팅

**수정 파일**:
- 신규: `docs/privacy-policy.html` (또는 별도 URL)
- 신규: `docs/terms-of-service.html` (또는 별도 URL)
- `apps/mobile/ios/Runner/Info.plist` — Privacy Policy URL 추가
- `apps/mobile/android/app/src/main/AndroidManifest.xml` — 필요 시 수정

**검수 기준**:
- [ ] 한국어/영어 두 버전 존재
- [ ] 아동 데이터 관련 조항 포함
- [ ] 사진 처리 정책 명시
- [ ] URL 접근 가능 확인
- [ ] App Store Connect / Google Play Console에 URL 등록 가능

---

### P0-2. 부모 동의 메커니즘

**요구사항**:
- 앱 **최초 실행 시** 부모 동의 화면 표시
- 동의 없으면 앱 사용 불가
- 동의 항목: 개인정보 수집, 사진 사용, 데이터 처리
- 동의 상태 로컬 저장 (SharedPreferences)
- 설정에서 동의 철회 가능

**수정 파일**:
- 신규: `apps/mobile/lib/screens/consent_screen.dart`
- `apps/mobile/lib/main.dart` — 초기 라우팅 분기 추가
- `apps/mobile/lib/services/api_client.dart` — 동의 상태 확인 로직

**검수 기준**:
- [ ] 최초 실행 시 동의 화면 표시
- [ ] 동의 거부 시 앱 진입 불가
- [ ] 동의 후 재실행 시 동의 화면 안 나옴
- [ ] 설정에서 동의 철회 가능
- [ ] 동의 철회 시 데이터 삭제 프로세스 안내

---

### P0-3. 연령 게이트 (구매 화면 보호)

**요구사항**:
- 크레딧 구매/구독 화면 진입 시 **부모 인증** 필요
- 방식: 간단한 **수학 문제** (예: "34 + 57 = ?") 또는 생년월일 입력
- COPPA 가이드라인 준수

**수정 파일**:
- 신규: `apps/mobile/lib/widgets/age_gate_dialog.dart`
- `apps/mobile/lib/screens/credits_screen.dart` — 진입 시 age gate 호출

**검수 기준**:
- [ ] 구매 화면 진입 시 수학 문제 표시
- [ ] 틀리면 진입 불가
- [ ] 맞추면 진입 허용 (세션 동안 유지)
- [ ] 앱 재시작 시 다시 인증 필요

---

### P0-4. 데이터 삭제 기능

**요구사항**:
- 설정 화면에서 "내 데이터 모두 삭제" 버튼
- 확인 다이얼로그 2단계 (1차 확인 + 2차 "삭제" 텍스트 입력)
- 서버에 DELETE 요청 → 해당 user_key의 모든 데이터 삭제
- 로컬 데이터도 모두 삭제

**수정 파일**:
- 신규: `apps/mobile/lib/screens/settings_screen.dart`
- 신규: `apps/api/src/routers/users.py` — DELETE /v1/users/me 엔드포인트
- `apps/mobile/lib/main.dart` — /settings 라우트 추가

**검수 기준**:
- [ ] 설정 화면에서 삭제 버튼 존재
- [ ] 2단계 확인 후 삭제 실행
- [ ] 서버 데이터 완전 삭제 확인 (DB 조회)
- [ ] 로컬 데이터 삭제 확인
- [ ] 삭제 후 앱 초기 상태로 복귀

---

### P0-5. Apple IAP + Google Play Billing 연동

**요구사항**:
- Flutter `in_app_purchase` 패키지 연동
- 현재 `credits_screen.dart`의 목업 결제 → 실제 IAP로 교체
- 구독 상품: 베이직(₩6,900/월), 프리미엄(₩14,900/월)
- 크레딧 팩 상품: 1권(₩1,500), 5권(₩5,900), 10권(₩9,900)
- 서버 측 영수증 검증 (Receipt Validation)
- 구독 갱신/취소 처리

**현재 문제**:
- `apps/api/src/services/credits.py`에 구독 로직 있으나 실제 결제 연동 없음
- 프리미엄 플랜 가격이 원가보다 낮아 적자 (50권 원가 ≈ 22,500원 > 구독료 19,900원)

**구독 티어 (수정 적용)**:

| 플랜 | 가격 | 크레딧/월 | 기능 |
|------|------|-----------|------|
| 무료 | 0원 | 2권/월 | watercolor/cartoon 2스타일, 오디오X, PDFX |
| 베이직 | ₩6,900/월 | 10권 | 모든 스타일, PDF, 기본 TTS |
| 프리미엄 | ₩14,900/월 | 30권 | 모든 기능, 프리미엄 TTS, 우선 처리 |

**수정 파일**:
- `apps/mobile/pubspec.yaml` — `in_app_purchase` 패키지 추가
- `apps/mobile/lib/screens/credits_screen.dart` — IAP 연동 전면 재작성
- `apps/mobile/lib/screens/screens.dart` — credits_screen export 추가
- `apps/mobile/lib/main.dart` — `/credits` 라우트 추가
- 신규: `apps/mobile/lib/services/iap_service.dart` — IAP 래퍼
- `apps/api/src/services/credits.py` — 영수증 검증, 구독 티어 수정
- 신규: `apps/api/src/routers/iap.py` — 영수증 검증 엔드포인트

**검수 기준**:
- [ ] `credits_screen.dart`가 정상 접근 가능 (라우트 동작)
- [ ] Apple IAP Sandbox에서 구독 구매 성공
- [ ] Google Play 테스트에서 구독 구매 성공
- [ ] 서버 영수증 검증 통과
- [ ] 구독 후 크레딧 정상 충전
- [ ] 구독 취소 시 다음 결제일까지 유지 → 이후 무료 전환
- [ ] 크레딧 팩 구매 시 즉시 충전
- [ ] 무료 사용자 기능 제한 정상 동작 (2권/월, 2스타일만)
- [ ] 이미 구독 중인데 또 구매 시도하면 적절한 안내

---

### P0-6. 앱 아이콘 및 스플래시 스크린

**요구사항**:
- 앱 아이콘 디자인 + 적용 (`flutter_launcher_icons` 패키지)
- 스플래시 스크린 디자인 + 적용 (`flutter_native_splash` 패키지)
- iOS/Android 각각 규격 준수

**수정 파일**:
- `apps/mobile/pubspec.yaml` — 패키지 추가 + 설정
- 신규: `apps/mobile/assets/icon/` — 아이콘 이미지
- 신규: `apps/mobile/assets/splash/` — 스플래시 이미지

**검수 기준**:
- [ ] iOS 시뮬레이터에서 커스텀 아이콘 표시
- [ ] Android 에뮬레이터에서 커스텀 아이콘 표시
- [ ] 스플래시 스크린 표시 후 홈 화면 전환
- [ ] 기본 Flutter 아이콘 완전 제거

---

### P0-7. 앱 이름 통일 + 릴리스 서명

**요구사항**:
- 앱 이름: **"AI 동화책"** (한국어) / **"AI Story Book"** (영어)
- iOS: Info.plist CFBundleDisplayName 설정
- Android: AndroidManifest.xml android:label 설정
- 릴리스 서명 키 생성 및 설정 (keystore / certificate)

**수정 파일**:
- `apps/mobile/ios/Runner/Info.plist` — CFBundleDisplayName
- `apps/mobile/android/app/src/main/AndroidManifest.xml` — android:label
- `apps/mobile/android/app/build.gradle.kts` — signingConfigs 추가
- 신규: `apps/mobile/android/key.properties` (.gitignore에 추가)

**검수 기준**:
- [ ] iOS에서 앱 이름 "AI 동화책" 표시
- [ ] Android에서 앱 이름 "AI 동화책" 표시
- [ ] Release 빌드 성공 (서명 포함)
- [ ] key.properties가 .gitignore에 포함

---

### P0-8. Info.plist 권한 설명 + 스크린샷 준비

**요구사항**:
- iOS Info.plist에 카메라/갤러리 접근 권한 사유 명시
- 앱스토어 제출용 스크린샷 최소 5장 (iPhone 6.7", 6.5", iPad)
- 앱 설명문/키워드/카테고리 준비

**수정 파일**:
- `apps/mobile/ios/Runner/Info.plist` — NSCameraUsageDescription, NSPhotoLibraryUsageDescription
- 신규: `docs/appstore/` — 스크린샷, 설명문

**검수 기준**:
- [ ] 카메라 접근 시 한국어 권한 설명 표시
- [ ] 갤러리 접근 시 한국어 권한 설명 표시
- [ ] 스크린샷 5장 이상 준비 완료
- [ ] 카테고리: "Education" 설정

---

## 4. Phase 1: Critical/High 버그 수정

> **목표**: 사용자 경험을 심각하게 해치는 버그 제거
> **예상 기간**: 1주
> **우선순위**: 상

---

### P1-1. [Critical] 오디오 페이지 전환 시 계속 재생

**현상**: 페이지를 넘겨도 이전 페이지 오디오가 멈추지 않고 겹쳐서 재생됨
**위치**: `apps/mobile/lib/screens/viewer_screen.dart` (약 287번 줄)
**원인**: `PageView.onPageChanged` 콜백에서 오디오 정지 호출 없음

**수정 방법**:
```dart
// onPageChanged 콜백에 추가
_audioPlayer.stop();
```

**검수 기준**:
- [ ] 페이지 넘길 때 이전 오디오 즉시 정지
- [ ] 새 페이지에서 오디오 재생 버튼 누르면 해당 페이지 오디오만 재생
- [ ] 빠르게 여러 페이지 넘겨도 오디오 겹침 없음

---

### P1-2. [Critical] 언어 전환해도 오디오 원래 언어 재생

**현상**: 영어→한국어 전환 후 오디오 재생하면 여전히 영어 오디오 나옴
**위치**: `apps/mobile/lib/screens/viewer_screen.dart` (약 300번 줄)
**원인**: 오디오 URL 생성 시 현재 선택된 언어(`_selectedLanguage`)를 사용하지 않음

**수정 방법**:
```dart
// 오디오 URL 가져올 때 _selectedLanguage 파라미터 전달
final audioUrl = getAudioUrl(page, _selectedLanguage);
```

**검수 기준**:
- [ ] 한국어 선택 시 한국어 오디오 재생
- [ ] 영어 선택 시 영어 오디오 재생
- [ ] 재생 중 언어 전환 시 기존 오디오 정지 + 새 언어 오디오 재생

---

### P1-3. [Critical] 페이지 인디케이터 오버플로우

**현상**: 페이지 수가 많으면 (8페이지+표지 = 9개) 인디케이터 점이 화면 밖으로 넘침
**위치**: `apps/mobile/lib/screens/viewer_screen.dart` (약 219번 줄)

**수정 방법**:
- `smooth_page_indicator` 패키지 사용 또는
- 현재 페이지 번호만 텍스트로 표시 (예: "3/9")

**검수 기준**:
- [ ] 모든 페이지 수에서 인디케이터 정상 표시
- [ ] 화면 밖으로 넘치지 않음
- [ ] 현재 페이지 위치 시각적으로 명확

---

### P1-4. [Critical] TextEditingController 메모리 누수

**현상**: 캐릭터 화면에서 TextEditingController가 dispose되지 않아 메모리 누수
**위치**: `apps/mobile/lib/screens/characters_screen.dart` (약 268번 줄)

**수정 방법**:
```dart
@override
void dispose() {
  _nameController.dispose();
  // 다른 TextEditingController가 있으면 모두 dispose
  super.dispose();
}
```

**검수 기준**:
- [ ] `dispose()` 메서드에서 모든 Controller 정리
- [ ] 캐릭터 화면 반복 진입/이탈 시 메모리 증가 없음

---

### P1-5. [High] 숨긴 컨트롤이 터치 이벤트 가로챔

**현상**: 뷰어에서 컨트롤 숨김 상태에서도 보이지 않는 버튼이 터치를 가로챔
**위치**: `apps/mobile/lib/screens/viewer_screen.dart` (약 132번 줄)

**수정 방법**:
```dart
// AnimatedOpacity 외부에 IgnorePointer 추가
IgnorePointer(
  ignoring: !_controlsVisible,
  child: AnimatedOpacity(...)
)
```

**검수 기준**:
- [ ] 컨트롤 숨김 시 이미지/텍스트 영역 터치 정상 동작
- [ ] 컨트롤 표시 시 버튼 터치 정상 동작

---

### P1-6. [High] 크레딧 0인데 책 생성 시도 가능

**현상**: 잔액 0인 상태에서도 "만들기" 버튼이 활성화되어 API 호출 후 실패
**위치**: `apps/mobile/lib/screens/create_screen.dart` (약 32번 줄)

**수정 방법**:
- 생성 전 크레딧 잔액 조회 (`GET /v1/credits/balance`)
- 잔액 부족 시 전용 모달 표시 → 크레딧 구매 화면으로 유도

**검수 기준**:
- [ ] 크레딧 0일 때 "만들기" 누르면 잔액 부족 모달 표시
- [ ] 모달에서 "크레딧 구매" 버튼 → 크레딧 화면으로 이동
- [ ] 크레딧 있을 때는 정상 생성 진행

---

### P1-7. [High] 폴링 무한루프 위험

**현상**: 책 생성 상태 폴링이 최대 횟수/타임아웃 없이 무한 반복 가능
**위치**: `apps/mobile/lib/providers/providers.dart` (약 97번 줄)

**수정 방법**:
- 최대 폴링 횟수: 120회 (2초 간격 × 120 = 4분)
- 전체 타임아웃: 10분
- 초과 시 에러 메시지 표시 + 재시도 버튼

**검수 기준**:
- [ ] 4분 이상 폴링 시 사용자에게 안내 메시지
- [ ] 10분 초과 시 폴링 중단 + 에러 표시
- [ ] 재시도 버튼으로 수동 상태 확인 가능

---

### P1-8. [High] PDF 파일명 특수문자 크래시

**현상**: 책 제목에 `/`, `\`, `:` 등 특수문자 포함 시 PDF 저장 크래시
**위치**: `apps/mobile/lib/screens/viewer_screen.dart` (약 553번 줄)

**수정 방법**:
```dart
final sanitized = title.replaceAll(RegExp(r'[\\/:*?"<>|]'), '_');
```

**검수 기준**:
- [ ] 특수문자 포함 제목으로 PDF 저장 성공
- [ ] 파일명에 금지 문자 없음
- [ ] 한글, 영어, 숫자 제목 모두 정상

---

### P1-9. [Medium] URL 복사가 공유 시트 열림

**현상**: "URL 복사" 버튼 누르면 클립보드 복사 대신 공유 시트가 열림
**위치**: `apps/mobile/lib/screens/viewer_screen.dart` (약 646번 줄)
**원인**: `Clipboard.setData()` 코드가 **주석 처리**되어 있음

**수정 방법**:
- 주석 해제 + SnackBar로 "복사 완료" 표시

**검수 기준**:
- [ ] "URL 복사" 누르면 클립보드에 복사
- [ ] "복사 완료" SnackBar 표시
- [ ] 공유 시트 열리지 않음

---

### P1-10. [Medium] 로딩 팁 매초 깜빡거림

**현상**: 로딩 화면에서 팁 텍스트가 매초 변경되어 깜빡거림
**위치**: `apps/mobile/lib/screens/loading_screen.dart` (약 220번 줄)
**원인**: Timer 주기마다 랜덤 팁 재선택

**수정 방법**:
- `initState`에서 1회 랜덤 선택 후 고정
- 또는 10-15초 간격으로 변경

**검수 기준**:
- [ ] 팁 텍스트 안정적으로 표시 (깜빡임 없음)
- [ ] 변경 시 fade 애니메이션 적용

---

### P1-11. 바텀 네비게이션 3곳 중복 → 통합

**현상**: home_screen, library_screen, characters_screen에 동일한 바텀 네비 코드 ~150줄 중복
**위치**: 3개 파일

**수정 방법**:
- 신규: `apps/mobile/lib/widgets/app_shell.dart` — 공통 Scaffold + BottomNavigationBar
- 각 화면에서 바텀 네비 제거, AppShell로 감싸기

**검수 기준**:
- [ ] 바텀 네비 코드 1곳에만 존재
- [ ] 3개 탭 정상 전환
- [ ] 현재 탭 하이라이트 정상

---

### P1-12. 캐릭터 삭제 기능 없음

**현상**: 캐릭터를 생성할 수만 있고 삭제할 수 없음
**위치**: `apps/mobile/lib/screens/characters_screen.dart`

**수정 방법**:
- 캐릭터 카드 길게 누르기 → 삭제 확인 다이얼로그
- `DELETE /v1/characters/{id}` API 엔드포인트 추가 (존재하지 않으면)

**검수 기준**:
- [ ] 캐릭터 카드 long press → 삭제 다이얼로그
- [ ] 삭제 확인 후 서버/로컬 모두 삭제
- [ ] 해당 캐릭터로 만든 책은 유지 (캐릭터만 삭제)

---

### P1-13. TTS 속도 연령 미반영

**현상**: TTS 속도가 0.9로 고정, 3-5세 아이에게는 너무 빠름
**위치**: `apps/api/src/services/tts.py` (약 45번 줄)

**수정 방법**:
```python
AGE_SPEED_MAP = {
    "3-5": 0.65,
    "5-7": 0.80,
    "7-9": 0.90,
    "adult": 1.0,
}
```

**검수 기준**:
- [ ] 3-5세 책 오디오가 느리게 재생됨 (0.65)
- [ ] 7-9세 책 오디오가 보통 속도 (0.9)
- [ ] 연령 파라미터가 TTS 서비스에 전달됨

---

## 5. Phase 2: 핵심 기능 추가

> **목표**: 사용자 리텐션과 차별화를 위한 핵심 기능
> **예상 기간**: 2-3주
> **우선순위**: 상

---

### P2-1. 주인공 이름 개인화

**요구사항**:
- 책 생성 폼에 **"우리 아이 이름"** 입력 필드 추가
- 스토리 생성 시 주인공 이름으로 사용
- 캐릭터 선택과 연동 (캐릭터의 이름 우선 사용)

**수정 파일**:
- `apps/mobile/lib/screens/create_screen.dart` — 이름 입력 필드 추가
- `apps/mobile/lib/models/book_spec.dart` — `protagonistName` 필드 추가
- `apps/api/src/models/dto.py` — BookSpec에 protagonist_name 추가
- `apps/api/src/prompts/story.jinja2` — 프롬프트에 이름 반영

**검수 기준**:
- [ ] 이름 입력하면 동화 속 주인공이 해당 이름으로 등장
- [ ] 이름 미입력 시 기존처럼 동작
- [ ] 캐릭터 선택 + 이름 입력 동시 사용 가능

---

### P2-2. 한국 절기/시즌 테마 추가

**요구사항**:
- `BookTheme` enum에 추가: 설날, 추석, 어린이날, 크리스마스, 생활습관
- 현재 존재하는 테마: 우정, 가족, 모험, 자연, 과학, 시간여행, 동물, 공룡, 직업, 작품속으로

**수정 파일**:
- `apps/mobile/lib/models/book_spec.dart` — BookTheme enum 확장
- `apps/api/src/models/dto.py` — 서버 테마 enum 동기화
- `apps/api/src/prompts/story.jinja2` — 절기별 프롬프트 추가

**검수 기준**:
- [ ] Create 화면에서 새 테마 선택 가능
- [ ] 설날 테마 선택 시 설날 관련 동화 생성
- [ ] 생활습관 테마 (프롬프트에 있으나 Flutter enum에 없던 것) 추가

---

### P2-3. 온보딩 화면

**요구사항**:
- 3-4장 슬라이드 (앱 소개, 핵심 기능, AI 동화 예시, 시작하기)
- 최초 실행 시 1회만 표시
- 마지막 슬라이드에서 **첫 책 무료 생성** 유도
- 초기 보너스: **3 크레딧** (기존 10 → 3으로 축소)

**수정 파일**:
- 신규: `apps/mobile/lib/screens/onboarding_screen.dart`
- `apps/mobile/lib/main.dart` — 온보딩 라우팅
- `apps/api/src/services/credits.py` — 초기 보너스 10 → 3으로 수정

**검수 기준**:
- [ ] 최초 실행: 부모 동의 → 온보딩 → 홈
- [ ] 재실행 시 온보딩 스킵
- [ ] 초기 크레딧 3으로 확인
- [ ] 슬라이드 넘기기 + 건너뛰기 버튼

---

### P2-4. 스트릭 UI 위젯 (홈 화면)

**요구사항**:
- 홈 화면 상단에 **연속 읽기 스트릭** 카드 표시
- 오늘의 동화 추천 + 읽기 완료 시 스트릭 카운트 증가
- **API는 이미 전부 완성**되어 있음:
  - `GET /v1/streak/info` — 현재 스트릭 정보
  - `GET /v1/streak/today` — 오늘의 동화
  - `POST /v1/streak/read` — 읽기 기록
  - `GET /v1/streak/calendar` — 캘린더

**수정 파일**:
- 신규: `apps/mobile/lib/widgets/streak_card.dart`
- `apps/mobile/lib/screens/home_screen.dart` — 스트릭 카드 배치
- `apps/mobile/lib/providers/providers.dart` — 스트릭 provider 추가

**검수 기준**:
- [ ] 홈 화면에 "🔥 N일 연속 읽기" 카드 표시
- [ ] 오늘의 동화 표시 + 탭하면 뷰어로 이동
- [ ] 읽기 완료 시 스트릭 카운트 증가
- [ ] 캘린더 뷰에서 읽은 날 표시

---

### P2-5. 프린트 기능

**요구사항**:
- 뷰어 화면에서 **"인쇄하기"** 버튼 추가
- AirPrint (iOS) / Cloud Print (Android) 지원
- PDF 기반 인쇄

**수정 파일**:
- `apps/mobile/pubspec.yaml` — `printing` 패키지 추가
- `apps/mobile/lib/screens/viewer_screen.dart` — 인쇄 버튼 + 로직

**검수 기준**:
- [ ] 인쇄 버튼 탭 → 프린터 선택 다이얼로그
- [ ] PDF가 올바르게 인쇄됨
- [ ] 네트워크 프린터 검색 가능

---

### P2-6. 공유하기 UX 개선

**요구사항**:
- 뷰어 화면: 공유 버튼 위치 더 접근하기 쉬운 곳으로 이동
- 서재 화면: 각 책 카드에 공유 아이콘 추가
- 공유 시 책 표지 이미지 포함
- 카카오톡 딥링크 지원 (가능 시)

**수정 파일**:
- `apps/mobile/lib/screens/viewer_screen.dart` — 공유 버튼 위치/UX
- `apps/mobile/lib/screens/library_screen.dart` — 카드별 공유 버튼

**검수 기준**:
- [ ] 뷰어에서 공유 버튼 쉽게 접근 가능
- [ ] 서재에서 각 책 옆 공유 아이콘 동작
- [ ] 공유 시 표지 이미지 + 텍스트 포함
- [ ] URL 복사 정상 동작 (P1-9 수정 포함)

---

### P2-7. 크레딧 부족 풀스크린 모달

**요구사항**:
- 현재 SnackBar → **풀스크린 모달**로 변경
- "무료 크레딧 받기" (광고 시청/초대) + "구독하기" + "크레딧 구매" 옵션
- 시각적으로 매력적인 디자인

**수정 파일**:
- 신규: `apps/mobile/lib/widgets/credit_shortage_modal.dart`
- `apps/mobile/lib/screens/create_screen.dart` — 모달 호출

**검수 기준**:
- [ ] 크레딧 부족 시 풀스크린 모달 표시
- [ ] 3가지 옵션 버튼 정상 동작
- [ ] 모달 닫기 가능

---

### P2-8. 인앱 리뷰 요청

**요구사항**:
- `in_app_review` 패키지 사용
- 트리거 시점:
  - 첫 번째 책 완성 직후
  - 3일 연속 스트릭 달성 시

**수정 파일**:
- `apps/mobile/pubspec.yaml` — `in_app_review` 패키지 추가
- `apps/mobile/lib/screens/viewer_screen.dart` — 첫 책 완성 트리거
- 신규: `apps/mobile/lib/services/review_service.dart`

**검수 기준**:
- [ ] 첫 책 완성 후 인앱 리뷰 다이얼로그 표시
- [ ] 3일 스트릭 후 인앱 리뷰 다이얼로그 표시
- [ ] 한 번 표시 후 재표시 방지 (최소 30일 간격)

---

### P2-9. Pretendard 폰트 활성화

**요구사항**:
- 현재 `pubspec.yaml`에서 Pretendard 폰트가 **주석 처리**되어 있음
- 주석 해제 + 테마에 적용

**수정 파일**:
- `apps/mobile/pubspec.yaml` — 폰트 주석 해제
- `apps/mobile/lib/theme/` — 폰트 패밀리 적용

**검수 기준**:
- [ ] 앱 전체에서 Pretendard 폰트 적용 확인
- [ ] 한글/영어/숫자 모두 정상 표시
- [ ] 폰트 파일 존재 + 로딩 확인

---

### P2-10. 터치 타겟 확대 (아동 UX)

**요구사항**:
- 모든 인터랙티브 요소의 최소 터치 타겟: **64×64px** (현재 48px)
- 특히: 버튼, 탭, 캐릭터 선택 칩, 테마 칩

**수정 파일**:
- 전체 screens 디렉토리의 버튼/칩 크기 조정
- `apps/mobile/lib/theme/` — 기본 버튼 스타일 수정

**검수 기준**:
- [ ] 모든 버튼 최소 64px 높이
- [ ] ChoiceChip 터치 영역 충분
- [ ] 3-5세 아이가 탭하기 쉬운 크기

---

### P2-11. 수면 모드

**요구사항**:
- 뷰어에 "수면 모드" 토글 추가
- 활성화 시: 화면 밝기 50% → 자동 페이지 넘김 (TTS 끝나면) → 마지막 페이지 후 화면 끄기
- 배경음악 옵션 (자장가, 백색소음)
- 타이머 설정 (10분/20분/30분)

**수정 파일**:
- 신규: `apps/mobile/lib/widgets/sleep_mode_panel.dart`
- `apps/mobile/lib/screens/viewer_screen.dart` — 수면 모드 통합

**검수 기준**:
- [ ] 수면 모드 토글 동작
- [ ] TTS 자동 재생 + 페이지 자동 넘김
- [ ] 화면 밝기 감소
- [ ] 타이머 종료 시 오디오 정지

---

### P2-12. 읽기 완료 축하 애니메이션

**요구사항**:
- 마지막 페이지 읽기 완료 시 **confetti 애니메이션** + 별/스티커 획득 연출
- "다음 동화 만들기" / "서재로 가기" 버튼

**수정 파일**:
- `apps/mobile/pubspec.yaml` — `confetti_widget` 패키지 추가
- `apps/mobile/lib/screens/viewer_screen.dart` — 완료 시 축하 화면

**검수 기준**:
- [ ] 마지막 페이지 후 축하 애니메이션 재생
- [ ] "다음 동화 만들기" / "서재로" 버튼 동작
- [ ] 애니메이션이 과하지 않고 아이 친화적

---

## 6. Phase 3: 차별화 기능

> **목표**: 경쟁사 대비 차별화 및 장기 리텐션
> **예상 기간**: 1-2개월
> **우선순위**: 중

---

### P3-1. 따라 읽기 모드

**요구사항**:
- TTS 재생 시 현재 읽고 있는 **단어/문장 하이라이트** 동기화
- 아이가 따라 읽을 수 있도록 큰 글씨 + 하이라이트

**검수 기준**:
- [ ] TTS 재생과 텍스트 하이라이트 동기화
- [ ] 읽는 속도에 맞춰 하이라이트 이동

---

### P3-2. 이중언어 동시 표시

**요구사항**:
- 한국어/영어 텍스트를 나란히 또는 위아래로 표시
- 토글로 단일/이중 언어 전환

**검수 기준**:
- [ ] 한국어/영어 동시 표시 모드 동작
- [ ] 레이아웃이 깨지지 않음

---

### P3-3. 아이 프로필 (다자녀 지원)

**요구사항**:
- 자녀별 프로필 (이름, 나이, 선호 테마)
- 프로필별 서재 분리
- 프로필별 스트릭 분리

**검수 기준**:
- [ ] 최대 3명 자녀 프로필 생성
- [ ] 프로필 전환 시 서재/스트릭 분리
- [ ] 프로필별 맞춤 추천

---

### P3-4. 부모 대시보드

**요구사항**:
- 읽기 통계 (총 읽은 책 수, 평균 읽기 시간, 선호 테마)
- 학습 현황 (어휘 학습, 스트릭)
- 주간/월간 리포트

**검수 기준**:
- [ ] 대시보드에 주요 통계 표시
- [ ] 주간 리포트 생성

---

### P3-5. 화면 시간 제한

**요구사항**:
- 부모가 설정하는 일일 사용 시간 제한 (30분/1시간/2시간)
- 시간 초과 시 "오늘은 여기까지!" 화면 + 잠금

**검수 기준**:
- [ ] 시간 제한 설정 가능 (부모 인증 필요)
- [ ] 제한 시간 도달 시 잠금 화면

---

### P3-6. 카카오톡 공유 카드

**요구사항**:
- 카카오톡으로 공유 시 책 표지 + 제목 + CTA 버튼이 포함된 카드형 공유
- KakaoSDK 연동

**검수 기준**:
- [ ] 카카오톡 앱으로 카드형 메시지 공유
- [ ] 카드 탭 시 앱 설치/실행 유도

---

### P3-7. 크레딧 팩 + 리워드 광고

**요구사항**:
- 낱개 크레딧 팩 IAP (1권/5권/10권)
- 리워드 광고 시청 → 1크레딧 획득 (일일 3회 제한)

**검수 기준**:
- [ ] 크레딧 팩 구매 → 즉시 충전
- [ ] 광고 시청 완료 → 1크레딧 충전
- [ ] 일일 광고 횟수 제한 동작

---

### P3-8. 설정 화면

**요구사항**:
- 알림 설정 (잠자리 동화 시간 알림)
- 언어 설정
- 다크 모드 토글
- 앱 버전 정보
- 개인정보처리방침/이용약관 링크
- 데이터 삭제 (P0-4)
- 로그아웃 (향후)

**검수 기준**:
- [ ] 설정 항목 모두 동작
- [ ] 다크 모드 전환 시 전체 앱 테마 변경

---

### P3-9. 책 삭제/편집

**요구사항**:
- 서재에서 책 삭제 (좌측 스와이프 또는 편집 모드)
- 삭제 확인 다이얼로그

**검수 기준**:
- [ ] 서재에서 책 삭제 가능
- [ ] 삭제 후 목록 갱신

---

### P3-10. 서재 정렬/필터 + 페이지네이션

**요구사항**:
- 현재 20권 고정 → **무한 스크롤** (cursor 기반 페이지네이션)
- 정렬: 최신순/오래된순/이름순
- 필터: 테마별/연령별

**검수 기준**:
- [ ] 20권 이상 표시 가능
- [ ] 스크롤 시 추가 로딩
- [ ] 정렬/필터 동작

---

### P3-11. 오프라인 배너 + 에러 UX

**요구사항**:
- 네트워크 없을 때 상단 배너 "오프라인 상태입니다"
- 이미 다운로드된 책은 오프라인에서도 열람 가능
- API 에러 시 사용자 친화적 메시지

**검수 기준**:
- [ ] 비행기 모드에서 오프라인 배너 표시
- [ ] 캐시된 책 오프라인 열람 가능
- [ ] API 에러 시 기술적 메시지 대신 친절한 안내

---

## 7. Phase 4: 블루오션 기능

> **목표**: 시장 독점 차별화
> **예상 기간**: 3개월+
> **우선순위**: 하 (Phase 0-3 완료 후)

---

### P4-1. 분기형 스토리 (인터랙티브 선택지)

**요구사항**: 동화 중 선택지 2-3개 제시 → 선택에 따라 스토리 분기
**경쟁사 현황**: StoryBee만 보유, 한국 시장에는 없음

### P4-2. 가족 목소리 녹음

**요구사항**: 부모/할머니 목소리를 녹음 → TTS 대신 가족 목소리로 재생
**차별화**: 감성 극강, 경쟁사 없음

### P4-3. 아이 그림 → 캐릭터 변환

**요구사항**: 아이가 직접 그린 그림을 사진 찍으면 동화 캐릭터로 변환

### P4-4. 실물 동화책 인쇄 주문 (POD)

**요구사항**: 앱 내에서 실물 책 주문 → 배송
**수익 모델**: ₩15,000-25,000 (마진 ₩5,000-8,000)

### P4-5. 발음 연습 (STT)

**요구사항**: 아이가 동화를 따라 읽으면 음성 인식으로 발음 평가

---

## 8. 기술 가이드라인

### 8.1 코딩 규칙

| 항목 | 규칙 |
|------|------|
| 비동기 | `async/await` 사용 (콜백 금지) |
| 상태관리 | Riverpod 사용 유지 |
| 에러처리 | try-catch + 사용자 친화 메시지 (toast/dialog) |
| API 타임아웃 | 일반 30초, PDF/오디오 120초 |
| 네이밍 | Flutter: camelCase, Python: snake_case |
| 커밋 | Conventional Commits (feat:, fix:, refactor:) |
| 브랜치 | feature/P0-1-privacy-policy 형식 |

### 8.2 API 설계 원칙

- 기존 API 엔드포인트 유지 (하위 호환)
- 새 엔드포인트는 `/v1/` 네임스페이스 유지
- 공통 헤더: `X-User-Key: {uuid}` (필수)
- 에러 응답: `{"error_code": "...", "message": "..."}`

### 8.3 보안

- `.env`, secrets 파일 커밋 금지
- API 키 하드코딩 금지
- 사용자 입력 검증 필수
- SQL Injection / XSS 방지
- COPPA 준수 (아동 데이터 최소 수집)

### 8.4 테스트

- 새 기능마다 **단위 테스트** 필수
- API: `pytest apps/api/tests/`
- Flutter: `flutter test`
- 기존 테스트 **통과 유지** 필수

### 8.5 주의사항

- 이미지 병렬 생성 시 rate limit 고려 (동시 최대 3개)
- 캐릭터 시트 `master_description`은 모든 이미지 프롬프트에 필수 포함
- LLM 출력은 JSON Schema 검증 후 진행
- 페이지 재생성은 해당 페이지만 (전체 재생성 금지)

---

## 9. 검수 프로세스 및 인수 조건

### 9.1 검수 프로세스

```
Phase별 개발 → 내부 QA → 검수 요청 → 발주자 검수 → 보완 → 최종 인수
```

| 단계 | 담당 | 기간 |
|------|------|------|
| 1. 개발 완료 | 수주자 | Phase별 |
| 2. 내부 QA | 수주자 | 2-3일 |
| 3. 검수 제출 | 수주자 → 발주자 | 1일 |
| 4. 발주자 검수 | 발주자 | 3-5일 |
| 5. 보완 요청 | 발주자 → 수주자 | - |
| 6. 보완 완료 | 수주자 | 2-3일 |
| 7. 최종 인수 | 발주자 | 1일 |

### 9.2 검수 제출물 (Phase별)

수주자는 각 Phase 완료 시 다음을 제출해야 합니다:

1. **코드**: Git branch (main 머지 전, PR로 제출)
2. **변경 파일 목록**: 수정/신규 파일 전체 리스트
3. **테스트 결과**: 모든 테스트 통과 스크린샷/로그
4. **빌드 결과**: iOS/Android 릴리스 빌드 성공 증빙
5. **시연 영상**: 각 기능 동작 화면 녹화 (30초-1분/기능)
6. **체크리스트**: 본 문서의 검수 기준 항목별 통과 여부 자체 체크

### 9.3 Phase별 인수 조건

#### Phase 0 인수 조건
- [ ] 모든 P0 항목 검수 기준 100% 통과
- [ ] iOS 시뮬레이터에서 전체 플로우 동작 (설치 → 동의 → 온보딩 → 생성 → 결제)
- [ ] Android 에뮬레이터에서 전체 플로우 동작
- [ ] IAP Sandbox 테스트 통과
- [ ] 기존 테스트 100% 통과 유지
- [ ] Release 빌드 성공

#### Phase 1 인수 조건
- [ ] 모든 P1 항목 검수 기준 100% 통과
- [ ] 기존 테스트 + 신규 버그 수정 테스트 100% 통과
- [ ] 메모리 누수 없음 (DevTools 프로파일링)
- [ ] 오디오 관련 버그 재현 불가 확인

#### Phase 2 인수 조건
- [ ] 모든 P2 항목 검수 기준 100% 통과
- [ ] 스트릭 UI ↔ 백엔드 API 정상 연동
- [ ] IAP 크레딧 플로우 전체 동작
- [ ] 신규 기능별 단위 테스트 존재

#### Phase 3 인수 조건
- [ ] 구현 항목 검수 기준 100% 통과
- [ ] 성능 저하 없음 (앱 실행 시간, 메모리 사용량 기존 대비 120% 이내)
- [ ] 전체 테스트 통과

---

## 10. 일정 및 마일스톤

| Phase | 내용 | 예상 기간 | 마일스톤 |
|-------|------|-----------|----------|
| **Phase 0** | 앱스토어 필수 요건 | 2-3주 | 앱스토어 심사 제출 가능 상태 |
| **Phase 1** | 버그 수정 | 1주 | Critical/High 버그 0건 |
| **Phase 2** | 핵심 기능 | 2-3주 | 스트릭 UI, IAP, 온보딩 완료 |
| **Phase 3** | 차별화 기능 | 1-2개월 | 별도 협의 (항목 선별) |
| **Phase 4** | 블루오션 | 3개월+ | 별도 협의 |

### 권장 실행 순서

Phase 0 → Phase 1 → Phase 2는 **순차 진행** 필수.
Phase 3는 항목별 우선순위 협의 후 선별 진행.
Phase 4는 Phase 0-3 완료 후 별도 프로젝트로 진행.

### 커뮤니케이션

- 주 1회 진행 보고 (화상 또는 서면)
- 블로커 발생 시 즉시 알림
- PR 단위로 코드 리뷰 요청

---

## 11. 부록: 파일 맵

### Flutter 앱 주요 파일

| 파일 | 역할 | 주요 수정 Phase |
|------|------|-----------------|
| `apps/mobile/lib/main.dart` | 앱 진입점, 라우팅 | P0, P2 |
| `apps/mobile/lib/screens/viewer_screen.dart` | 책 뷰어 (공유/오디오/학습) | P1, P2 |
| `apps/mobile/lib/screens/create_screen.dart` | 책 생성 폼 | P1, P2 |
| `apps/mobile/lib/screens/home_screen.dart` | 홈 화면 | P2 |
| `apps/mobile/lib/screens/library_screen.dart` | 서재 | P3 |
| `apps/mobile/lib/screens/characters_screen.dart` | 캐릭터 관리 | P1 |
| `apps/mobile/lib/screens/credits_screen.dart` | 크레딧/구독 (**현재 접근불가**) | P0 |
| `apps/mobile/lib/screens/loading_screen.dart` | 로딩 | P1 |
| `apps/mobile/lib/screens/screens.dart` | 스크린 export (**credits 누락**) | P0 |
| `apps/mobile/lib/models/book_spec.dart` | BookSpec, BookTheme enum | P2 |
| `apps/mobile/lib/services/api_client.dart` | API 클라이언트 | P0 |
| `apps/mobile/lib/providers/providers.dart` | Riverpod providers | P1, P2 |
| `apps/mobile/lib/theme/` | 디자인 토큰 | P2 |
| `apps/mobile/pubspec.yaml` | 패키지 의존성 | P0, P2 |
| `apps/mobile/ios/Runner/Info.plist` | iOS 설정 | P0 |
| `apps/mobile/android/app/src/main/AndroidManifest.xml` | Android 설정 | P0 |
| `apps/mobile/android/app/build.gradle.kts` | Android 빌드 | P0 |

### Backend 주요 파일

| 파일 | 역할 | 주요 수정 Phase |
|------|------|-----------------|
| `apps/api/src/services/credits.py` | 크레딧/구독 로직 | P0, P2 |
| `apps/api/src/services/tts.py` | TTS 서비스 | P1 |
| `apps/api/src/services/orchestrator.py` | 생성 파이프라인 | P2 |
| `apps/api/src/services/streak.py` | 스트릭 서비스 (완성됨) | - |
| `apps/api/src/models/dto.py` | Pydantic 모델 | P2 |
| `apps/api/src/prompts/story.jinja2` | 스토리 프롬프트 | P2 |
| `apps/api/src/routers/` | API 라우터 | P0 |

---

## 계약 조건 메모

> 아래는 발주자가 별도로 작성/협의할 항목입니다.

- [ ] 총 계약 금액
- [ ] Phase별 분할 지급 조건
- [ ] 하자 보수 기간 (인수 후 N개월)
- [ ] 소스코드 소유권
- [ ] 유지보수 계약 (별도)
- [ ] Phase 3-4 항목 선별 및 추가 견적

---

*이 문서는 AI Story Book 프로젝트의 10명 전문가 에이전트 분석 결과를 기반으로 작성되었습니다.*
*문서 버전 1.0 — 2026-02-21*
