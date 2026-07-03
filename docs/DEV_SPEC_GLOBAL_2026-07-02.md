# AI Story Book — 글로벌 전환 개발 명세서 (DEV SPEC)

> **용도·독자**: 이 문서는 **구현 개발자에게 전달하여 구현을 지시하는 계약 문서**다. 개발자는 이 문서만 보고 착수·구현·자가검수할 수 있어야 하며, 검수 기준은 사후 협상이 아니라 이 문서에 사전 고정된 명령·케이스다.
> **작성**: 2026-07-02, CTO(Claude). 모든 코드 좌표는 **브랜치 `fix/launch-blockers-audit-triage-20260628` (HEAD `9ef043f`) 기준 2026-07-02 실측**이다.
> **버전**: v1.1 — v1.0을 4렌즈 적대 검증(사실 대조·완결성·설계 반증 2종, 클레임 157건 검증)에 태워 생존 반증 31건을 반영한 판본. 주요 정정: 에러 계약(기존 envelope 재사용으로 재설계), 환불 정책(무환불 화이트리스트로 반전 + 멱등 fence), 스토리 언어 축(feat 브랜치 수동 선택기 반영), jurisdiction 하향 금지, A1 pass-bar 연령밴드 오기 정정, M0 절차 구체화.
> **커밋 해시 주의**: 본문 해시들은 M0-01 히스토리 정리로 재작성된다. M0-01 완료 시 구→신 SHA 매핑표를 부록 C로 추가하고, 이후 참조는 커밋 제목을 병기한다.

---

## 0. 정본(canonical) 규칙 — 먼저 읽을 것

1. **구현 현황 서술은 코드가 정본**이다. 이 저장소의 문서 다수가 stale이므로 아래만 신뢰하라.
   - **신뢰**: 이 문서(v1.0), `docs/A1_LIVE_PASSBAR_2026-06-27.md`, `docs/MARKET_RESEARCH_GLOBAL_2026-06-27.md`, `docs/FOUNDER_DECISIONS_PENDING.md`(단 §1의 결정 반영으로 일부 해소됨), `docs/FINAL_USER_INPUT_REQUIRED.md`.
   - **stale — 근거로 인용 금지** (M0에서 `archived/`로 이동 또는 재작성): 루트 `CLAUDE.md`(버전·env 이름·MVP 범위 전부 코드와 불일치 — 예: `OPENAI_API_KEY`는 코드가 읽지 않는 이름이며 정본은 `LLM_API_KEY`, `apps/api/src/core/config.py:46-55`), `COST_MODEL.md`(권당 $0.025 전제 — A2 gemini 기준 ≈$0.35로 ~14배 괴리), `QUALITY_BASELINE.md`·`TEST_AND_COVERAGE_REPORT.md` 등 루트 품질 문서 9종(2026-01-21~26자, "테스트 11파일" vs 실측 37파일·400케이스).
2. **규범적 클레임(법정 고지·계약 사실·규제)은 코드가 정본이 아니다.** 코드와 법무 결정이 충돌하면 **작업 중단 후 보고**한다. 현재 알려진 충돌 1건: §3.4.1의 consent en/ja 선반영(커밋 `1657d52`).
3. 이 문서와 코드가 충돌하면(좌표 어긋남 등): 사소한 드리프트는 코드를 따르고 문서에 정정 노트를 남긴다. 설계 의도 차원의 충돌은 CTO에 보고한다.

### 0.1 게이트 실측 베이스라인 (2026-07-02, 로컬 macOS)

| 게이트 | 결과 | 명령 |
|---|---|---|
| API 테스트 | **400 passed / 0 fail / 0 skip** (91s) | `cd apps/api && ./venv/bin/python -m pytest tests/ -q` |
| API 린트 | ruff All checks passed | `cd apps/api && ruff check src/ tests/` |
| 모바일 테스트 | **182 passed** | `cd apps/mobile && flutter test` |
| 모바일 통합 | 2 passed (macOS에선 `-d flutter-tester` 필수) | `flutter test integration_test/ -d flutter-tester` |
| 모바일 분석 | No issues | `flutter analyze` |

**회귀 조항(전 마일스톤 공통)**: 위 수치는 하한선이다. 어떤 WP도 기존 테스트를 깨거나 수를 줄일 수 없다(의도적 삭제는 WP 명세에 기재된 경우만).

---

## 1. 확정된 결정과 그 파급 (2026-07-02 창업자 결정)

| # | 결정 | 파급 |
|---|---|---|
| R1 | **시장방향 = 글로벌(영어권 1차)** | `docs/MARKET_RESEARCH_GLOBAL_2026-06-27.md`가 제품 방향 정본이 된다. 상충하는 구문서(`AISTORYBOOK_MASTERWORK_2026-06-08.md`의 "한국 단독·COPPA 범위 제거")는 방향 서술에 한해 폐기. 단 마스터워크의 **게이트 구조(G0~G4)와 A1 게이트는 유지**. |
| R2 | **법무 사인오프 전 ko-only 해제** | consent/법정고지의 en/ja **개발·번역 작업은 즉시 진행 가능**. 단 이것은 "법무 검토 불요"가 아니다 — **스토어 제출 전 법무 사인오프 게이트는 유지**되고(§9), 그때 코드 변경이 0이 되도록 §3.4의 카피-데이터 분리 구조로 만든다. 커밋 `1657d52`(consent en/ja 선반영)는 이 결정으로 **소급 승인**되어 원복 불요. |
| R3 | **실키(라이브 API 키)는 나중 주입** | 모든 개발·테스트·CI는 키 0개로 완결되어야 하고(현재도 그러함 — §3.2), 키 주입 시 **코드 변경 0**으로 라이브 전환된다. 신규 외부 연동(VPC, analytics 등)도 전부 같은 시임 규칙(§3.2.4)을 따른다. |
| R4 | **i18n 방법 = ko 정본 → 번역 확장** (CTO 재량 확정) | 기존 확립 패턴 유지: ko 문자열이 정본(byte-exact), en/ja는 같은 PR에서 키 동반. UI 로케일은 기기 추종(§3.3). |

**여전히 열린 결정**은 §10에 모았다. 개발자는 §10을 임의로 선결하지 말 것.

---

## 2. 현재 상태 실측 (2026-07-02) — 무엇이 어디에 있나

### 2.1 스택
- **모바일**: Flutter + Riverpod 2.4.9(수동 선언, codegen 미사용), Navigator 1.0 `onGenerateRoute`(`apps/mobile/lib/main.dart:315-454`), dio 단일 `ApiClient`. 화면 18개(`apps/mobile/lib/screens/screens.dart`). i18n = 표준 gen-l10n, ARB ko/en/ja 각 728키.
- **API**: FastAPI 0.115 + SQLAlchemy 2.0 async(asyncpg) + Alembic 12개 마이그레이션 + Redis(레이트리밋/Celery) + S3호환 스토리지. 라우터 16개, 엔드포인트 69개(`apps/api/src/main.py:514-611`). 잡은 기본 in-process BackgroundTasks(`USE_CELERY=false`), 프로덕션 compose에 Celery 워커.
- **인증**: 자기선언 `X-User-Key`(UUID) 헤더가 유일한 신원(`apps/api/src/core/dependencies.py:15-49`). 실계정 없음 — §10-D7 참조.

### 2.2 브랜치 토폴로지 (git 실측)

```
main = 7d63133 (= origin/main, CI green 2026-06-13)
├── fix/launch-blockers-audit-triage-20260628  ← 현 체크아웃, main+10커밋
│     ⚠️ origin에 브랜치 없음 = 이 디스크가 유일본. CI 0회(로컬 게이트만 green).
│     내용: IAP 우회차단(32db9c1)·GDPR삭제FK(acaa2e1)·공유토큰프록시(42dc9fe)·
│           ja학습자산(ebd113d)·consent/콘텐츠 l10n(1657d52)·성장리포트 l10n(36f9898)·
│           IAP복원감사(9ef043f) + 문서 3커밋(f2a0c20 아티팩트 ~7MB 바이너리 포함)
└── feat/global-multilang-product-rollout-20260622 = PR #45, main+23커밋
      origin 동기, CI green(run 28278026581, 2026-06-27), OPEN·MERGEABLE
      내용: 경쟁흡수 P0~P2(연령밴드·캐릭터퍼스트·시리즈책장·리텔·인페인트·
            스트릭 실물보상·지역 POD 가격) + 스토리 언어 zh/es(13ec793)
```
- 두 브랜치 merge-base = main. 공통 변경 20파일 중 **실제 충돌은 `apps/mobile/lib/screens/create_screen.dart` 1건**(`git merge-tree` 실측). 단 gen-l10n 생성물이 텍스트 병합되므로 머지 후 재생성 필수.
- 미추적 파일: 디렉터리별 `AGENTS.md` 7개(2026-07-02 생성, 런타임 영향 0).

### 2.3 확인된 결함 (정찰에서 CONFIRMED — M1·M2의 근거)
1. **[치명] en/ja 데이터 삭제 불가**: `apps/mobile/lib/screens/settings_screen.dart:324`가 삭제 확인 입력을 하드코딩 `'삭제'`와 비교. 힌트는 지역화된 `settingsDeleteKeyword`(en=`Delete`, ja=`削除`)를 보여주므로 en/ja 사용자는 삭제 확인이 영원히 실패. GDPR/PIPA 삭제권 파손 + 스토어 심사 차단급.
2. **[치명] 파이프라인 실패 무환불**: `apps/api/src/services/orchestrator.py:171-189`의 `mark_job_failed`에 환불 코드 없음. `refund_for_job` 호출처는 `job_monitor.py:190` 1곳뿐(스턱잡만). LLM 타임아웃·이미지 실패 등 시스템 귀책 실패에서 사용자 크레딧 소실.
3. **[높음] JIT 사진동의 다이얼로그 한국어 하드코딩**: `apps/mobile/lib/core/photo_consent.dart:29-47` — 아동 얼굴사진 국외이전 법정고지가 en/ja 사용자에게 한국어로 노출. l10n 키(`consentPhotoDisclosure`)가 이미 있는데 이 경로는 미사용.
4. **[높음] photo_character fail-open**: `apps/api/src/services/photo_character.py:108-112, 152-159, 396-398` — 라이브 모드에서 vision 응답 JSON 파싱 실패 시 mock 캐릭터를 조용히 반환.
5. **[중간] 한국어 하드코딩 잔존**: `api_error.dart` userMessage 15곳, `providers.dart:619,621,678,863,869`, `iap_service.dart:20,33`, `kakao_share_service.dart:38-129`, 알림 채널명(`notification_scheduler.dart:114-115`), `main.dart:120` title, `characters_screen.dart:1121` 성격 칩, 서버 403 consent 메시지(`apps/api/src/core/consent.py:68-70`), 공개 공유 HTML `lang="ko"`(`apps/api/src/routers/shares.py:126-135,184,212-214`).
6. **[중간] 402 결제 안내가 서버 한국어 메시지 원문 + 부분문자열 분기**: `create_screen.dart:136-143`, `viewer_screen.dart:815-823`.
7. **[중간] iOS 심사 표면**: `Info.plist` 권한 문구·`CFBundleDisplayName`이 한국어 고정, `ko/en/ja.lproj` 없음(`apps/mobile/ios/Runner/Info.plist:7-8,31-36`).
8. **[중간] JIT consent echo**: `photo_consent.dart`가 `getConsent` 실패 시 빈 맵 폴백 → `grantConsent(privacy:false, dataProcessing:false, photos:true)` 전송 가능 — 서버 supersede 로직상 기존 granted를 false 행으로 대체할 이론적 경로.
9. **[중간] 스토리지 파기 best-effort**: 계정삭제·동의철회 시 S3 삭제 실패가 성공 응답으로 처리(`users.py:96-134`, `consent.py:168-173`) — 재시도 없음.
10. **[낮음] 공유 표면 잔여 갭**: `/share/*`는 **앱(ASGI) 레벨** 레이트리밋 없음(`main.py:527`). 단 nginx에는 IP 기반 `limit_req`가 이미 있다(`infra/nginx/nginx.conf:112-114`, 커밋 42dc9fe) — 남은 갭은 **토큰별 남용 캡, nginx 우회 배포 시 무방비, 만료 상한**이다. 요청 `expires_in_days=0`은 이미 30일로 폴백되나(`shares.py:69`), config `SHARE_DEFAULT_EXPIRY_DAYS=0` 운영 설정 시 무기한(`expires_at=NULL`, `db.py:226`)이 가능하고 요청 상한이 `le=365`(`shares.py:39`)로 과대.

### 2.4 CI 구조 (실측)
- 워크플로 1개 `.github/workflows/ci.yml`: push[main, develop]+PR→main만 트리거(피처 브랜치는 PR 없이 CI가 안 돈다). Python 3.11 / Flutter 3.38.7 고정.
- 게이트: ruff → check-env(ci) → alembic 실Postgres → pytest cov≥40% → live E2E(키 0개) → 골든 하니스 / flutter analyze·test·integration·cov≥25% / phase-gate(APK debug 포함) / Trivy(**soft**)·Gitleaks(hard).
- 로컬 venv Python 3.9.6 ≠ CI 3.11 (로컬 green ≠ CI green 보증).

---

## 3. 목표 아키텍처

### 3.1 언어 축 3개를 혼동하지 말 것

| 축 | 현재 | 목표 | 결정 로직 |
|---|---|---|---|
| **UI 로케일** | ko/en/ja (기기 추종 전용, `MaterialApp`에 `locale:` 없음) | ko/en/ja 유지. **기기 추종이 정본** — 수동 전환 도입하지 않는다 | Flutter 기본 localeResolution. 미지원 기기 → en 폴백(템플릿 순서) |
| **스토리(생성물) 언어** | fix 브랜치 현재: UI 로케일 추종(`create_screen.dart:73`). **단 feat 브랜치(13ec793)가 create 화면에 5언어 수동 선택기(ko/en/ja/zh/es ChoiceChip, 기본값=UI 로케일)를 도입** — M0-05 머지 후에는 수동 선택이 정본 | 머지 후 = **수동 선택 유지(기본값 UI 로케일)**. 단 **zh/es 칩은 §10-D5 결정 전까지 조건부 비노출**(서버 Language enum의 zh/es 허용은 유지) — M0-05에 지시 포함 | `BookSpec.language` = 선택기 값 |
| **법정고지 언어** | ko 정본 + en/ja 번역(1657d52) | ko 정본 유지 + 시장별 카피 모듈(§3.4). **ko 원문 byte 변경 = 법무 영역, 개발자 임의 수정 금지** | jurisdiction(§3.4.2) × locale |

- 설정 화면의 언어 드롭다운(`settings_screen.dart:459-473`, ko/en만)은 UI 로케일을 바꾸지 않는 죽은 설정이다 → **WP-M1-07에서 제거**.
- **신규 문자열 규칙**: 모든 신규 UI 문자열은 ko/en/ja 3키 동반이 머지 조건(§5의 parity 게이트가 기계 검증).

### 3.2 실키 시임 (deferred live-key seam) — 현재 90%, 남은 10%

#### 3.2.1 현재 완성돼 있는 것 (재구현 금지 — 그대로 쓴다)
| 시임 | env 스위치 | 키 부재 시 | 근거 |
|---|---|---|---|
| LLM 텍스트 | `LLM_PROVIDER`=openai/anthropic/mock, `LLM_API_KEY` | fail-closed(LLMError) | `llm.py:48-57, 67-71` |
| 이미지 | `IMAGE_PROVIDER`=openai/**gemini**/replicate/fal/mock, `IMAGE_API_KEY` | fail-closed | `image.py:58-69` |
| TTS | `TTS_PROVIDER`=google/elevenlabs/**mock**(기본) | mock | `tts.py`, `config.py:61-64` |
| STT | `STT_PROVIDER`=**mock**(기본) | mock | `config.py:67` |
| IAP 검증 | `IAP_VERIFICATION_MODE`=**local**(기본)/hybrid/strict | local=fail-open, readiness가 503 차단 | `iap_verifier.py:83-89`, `main.py:420-453` |
| POD 인쇄 | `POD_MODE`=**local**(기본)/hybrid/strict, Printful 키 | local | `config.py:90` |
| 스토리지 | S3 호환(로컬 minio) | mock 이미지 경로는 S3 자체 불필요 | `image.py:472-475` |

CI 전체가 키 0개로 완결(pytest + 실서버 E2E + 골든 하니스, `ci.yml:93-115`). readiness(`/health/ready`)가 라이브 provider 키 누락·IAP 비strict를 unhealthy로 차단.

#### 3.2.2 남은 갭 (이번 명세의 작업 대상)
1. `env.schema.json`이 코드 대비 stale: `IMAGE_PROVIDER` enum에 gemini 없음(`env.schema.json:55`), `IAP_WEBHOOK_SECRET`·`ALLOW_UNVERIFIED_SUBSCRIBE`·`SHARE_BASE_URL` 부재, CORS 기본값 충돌 → WP-M0-06.
2. photo_character fail-open(§2.3-4) → WP-M2-07.
3. readiness 503이 실제 트래픽 차단으로 배선되는지 미검증(nginx/deploy) → WP-M3-04.
4. A1 `--live` 실행에 S3/minio 기동이 필요한데 런북에 없음(미기동 시 placeholder→FAIL로 키 비용만 소모, `golden_prompts_harness.py:56-58`) → WP-M3-02.
5. 골든셋 4편·사진 캐릭터 0편 — pass-bar 요구(15편+사진1편) 미달로 **지금 키를 넣어도 A1 판정 불성립** → WP-M3-01.

#### 3.2.3 라이브 전환 절차 (키 주입 시 — 코드 변경 0)
```bash
# 1) 백엔드 .env: LLM_PROVIDER=openai LLM_API_KEY=... IMAGE_PROVIDER=gemini IMAGE_API_KEY=...
# 2) 검증: ./scripts/check-env.sh --mode production && curl :8000/health/ready → 200
# 3) A1 실측(§9-H1): ./scripts/run_a1_live.sh   # WP-M3-02가 만드는 원커맨드
```

#### 3.2.4 신규 외부 연동의 시임 규칙 (전 WP 공통 계약)
1. 도메인 코드는 인터페이스만 호출한다. provider 선택은 env, 기본값은 mock.
2. mock은 실물과 **산출 스키마 parity**(형태 동일, 값은 결정론).
3. **릴리스/프로덕션 모드에서 mock 잠입 금지**: 신규 시임은 readiness 체크에 등록한다(`main.py:389-510` 패턴).
4. 라이브 어댑터의 원격 오류는 **fail-closed**(mock 폴백 금지 — §2.3-4가 반례).
5. env 추가 시 `env.schema.json` + `.env.example` + `check-env.sh` 3곳 동기(§5 게이트가 검증).

### 3.3 에러 메시지 계약 — 서버는 코드, 클라이언트는 문구

**중요 — 스키마를 신설하지 마라.** 서버에는 이미 표준 envelope이 있다: `apps/api/src/core/exceptions.py:216-227`이 `{"detail": msg, "error": {"code", "message", "details"}, "request_id"}`를 방출하고, 클라 `api_error.dart:25-40`이 이미 `error.code`를 파싱한다. 문제는 스키마가 아니라 **code가 뭉툭한 것**(402가 전부 `PAYMENT_REQUIRED`, `exceptions.py:66-74`)이라 클라가 한국어 message 부분문자열로 세부 분기한다는 점이다(§2.3-6).

WP-M1-04의 실제 작업 = **기존 envelope 유지 + code 세분화 + 클라 code→l10n 매핑**. 포맷 파라미터는 신설 필드가 아니라 기존 `details`를 재사용한다.

| code | HTTP | 뜻 (발생지) | 클라 l10n 키(신설) |
|---|---|---|---|
| `PLAN_LIMIT_MONTHLY` | 402 | 무료 월 생성 한도 (`books.py:46-132`) | `errPlanLimitMonthly` |
| `PLAN_STYLE_LOCKED` | 402 | 무료 스타일 제한 | `errPlanStyleLocked` |
| `PLAN_FEATURE_PDF` / `PLAN_FEATURE_AUDIO` | 402 | 유료 기능 | `errPlanFeaturePdf` / `errPlanFeatureAudio` |
| `CREDIT_INSUFFICIENT` | 402 | **크레딧 부족·차감 실패** (`books.py:223,233`) — 클라가 현재 별도 모달(`createCreditShortageTitle`)로 분기하는 경로이므로 code 없이는 구현 불가 | `errCreditInsufficient` (기존 크레딧 모달 유지) |
| `CONSENT_PHOTOS_REQUIRED` | 403 | 사진동의 필요 (`core/consent.py:68-70`) | `errConsentPhotosRequired` |
| `RATE_LIMIT_EXCEEDED` | 429 | 레이트리밋 — **기존 code 그대로**(`exceptions.py:94-103`), 신설 금지 | `errRateLimited` |
| (기존 `ErrorCode` 잡 실패 코드) | — | 잡 상태 폴링용 | 기존 매핑 유지 |

- 클라 `ApiError`는 `code`→l10n 매핑 우선, 미지의 code는 일반 문구 폴백. **서버 `message`를 UI에 원문 표시하는 경로를 전부 제거한다** (`message`는 ko 유지 — 디버그·로그용).
- **예상된 무효화(버그 아님)**: `PAYMENT_REQUIRED`를 세분 code로 바꾸면 기존 단언이 깨진다 — `tests/test_phase_new_endpoints.py:567,608,814,818,826`, `tests/test_error_responses.py:62` 등. WP-M1-04에서 이 단언들을 새 code로 갱신하는 것은 §0.1 회귀 조항의 예외로 승인한다(갱신 목록을 PR에 첨부).
- 앱이 스토어 미출시 + 모노레포 동시 변경이므로 구앱 호환 창은 불요(검증 확인됨).

### 3.4 글로벌 컴플라이언스 아키텍처

#### 3.4.1 원칙: 법무 카피는 코드가 아니라 데이터
- 법정고지·동의 문구는 **버전드 카피 리소스 + `consent_version`**으로 관리한다. 법무 사인오프는 (a) 카피 텍스트 승인 (b) `consent_version` 증가로 반영되며 **비즈니스 로직 코드 변경이 없다**.
- 카피 리소스는 표면별로 2계층이다: **클라 표면 = l10n ARB 키**, **서버 렌더 표면(공유 HTML·PDF·AI 라벨) = 버전드 서버 카피 모듈 `apps/api/src/core/legal_copy.py`(신설, 언어별 상수 dict)**. 둘 다 레지스트리 관리 대상이며, G2 게이트 허용목록에 `legal_copy.py`가 들어간다. "코드 변경 0"은 정확히는 "카피 리소스 파일 외 변경 0"이다 — M4 DoD 리허설은 양 표면 각 1건씩 검증한다.
- **ko 카피가 정본**. en/ja(및 이후 es)는 번역본이며, 로케일×시장×표면별 사인오프 상태를 `docs/LEGAL_COPY_REGISTRY.md`(WP-M4-04 신설)에 표로 관리한다.
- 알려진 규범 충돌 1건의 처치: 커밋 `1657d52`가 C1(법무 사인오프 후 적용)을 앞질러 en/ja consent를 반영했으나, R2 결정으로 **개발 반영은 소급 승인**. 단 레지스트리에 해당 카피를 `서명 전(pre-signoff)` 상태로 기재하고, **스토어 제출 게이트(§9-H4)에서 사인오프를 요구**한다.

#### 3.4.2 시장(jurisdiction)별 동의 모듈 — consent v3 (WP-M4)
시장조사 정본(§규제, `MARKET_RESEARCH_GLOBAL_2026-06-27.md:33-37`)에 따라 동의 요구가 시장별로 다르다. 번역이 아니라 **정책 분기**로 설계한다:

| jurisdiction | 필수 동의 셋 | 특이 요건 |
|---|---|---|
| `KR` | privacy, data_processing (+photos 선택) — 현행 v2와 동일 | PIPA 만14세 미만 보호자 동의, 국외이전 고지(+C2 별도동의는 실계약 확정 후) |
| `US` | + `ai_training`(별도), `third_party_sharing`(별도) | **COPPA 2025: 아동 사진=생체정보 → VPC 필수**(§3.4.3) |
| `EU_UK` | + GDPR Art.8 연령, AADC | AI Act 생성물 라벨링(WP-M4-06) |
| `OTHER` | US 셋 준용(보수적 기본) | — |

- **jurisdiction 결정 — 하향 금지 규칙**: 최초 동의 화면에서 거주 지역 1회 질문(기기 지역을 기본값 제안), `user_consents.jurisdiction`에 저장. 단 **유효 jurisdiction은 "자기선언"과 "기기/스토어 국가 신호" 중 더 엄격한 동의 셋을 요구하는 쪽**이다 — 선언으로 요구를 상향할 수는 있어도 하향할 수는 없다(US 신호 사용자가 KR을 선택해 COPPA 셋을 우회하는 fail-open 차단). KR이 최약 셋이므로 이 규칙이 없으면 자기선언은 COPPA 우회 버튼이 된다.
- **스키마**(신규 마이그레이션): `user_consents`에 `jurisdiction VARCHAR(8) NOT NULL`, `ai_training BOOLEAN NULL`, `third_party_sharing BOOLEAN NULL`, `cross_border BOOLEAN NULL` 추가. **신규 boolean 3종은 NULL 허용이 의도된 설계다: NULL=질문받지 않음, false=명시 거부** — 이 구분이 없으면 KR→US 이주 사용자 게이트가 오동작한다(기존 컬럼들의 NOT NULL default false 관례를 따르지 말 것). 기존 행 백필: `jurisdiction='KR'`, boolean 3종=NULL. 현행 supersede 패턴(`consent.py:76-95`) 유지.
- **집행**: 기존 서버 게이트 5진입점(`characters.py:544,620`, `books.py:575,577,815`)은 그대로 두고, 게이트 내부가 jurisdiction별 필수 셋을 평가하도록 `core/consent.py`만 확장.

#### 3.4.3 VPC(검증가능 보호자 동의) 시임 — US 출시 게이트
현행 부모 게이트는 두 자릿수 덧셈(`parental_control_service.dart:23,71-78`) — COPPA VPC가 아니다. R1(글로벌) 결정으로 VPC는 법적 요구사항이 됐다.
- **설계**: `VPC_PROVIDER` env = `mock`(기본)/`card`(카드 마이크로트랜잭션)/외부 벤더. 인터페이스 + mock 구현 + 게이트 배선까지 지금 만들고(WP-M4-03), 실 provider는 키·벤더 계약(§9) 후 드롭인.
- **최소 계약(M4-03에서 이대로 고정)**: 신규 403 code `VPC_REQUIRED`(§3.3 표 준용) + `POST /v1/vpc/challenge`(챌린지 생성) / `POST /v1/vpc/verify`(검증) + 검증 상태는 `user_consents` 아닌 별도 `parental_verifications` 테이블(user_key, method, verified_at, expires_at). mock provider는 항상 챌린지를 생성하고 고정 코드(`000000`)만 승인한다. 클라는 `VPC_REQUIRED` 수신 시 VPC 플로우 화면으로 라우팅.
- **초기 배선 표면**: US jurisdiction + 사진 업로드·공유 링크 생성·음성 프로필. KR은 현행 게이트 유지(PIPA는 VPC 요구 없음).
- ⚠️ **스코프 유보 — H4 법무 자문 결정 사항**: 위 3개 표면은 최소 집합이다. 아동 이름·생년월(`child_profiles`, `db.py:419-425`), 지속 식별자(X-User-Key), analytics 이벤트 수집도 COPPA상 VPC 대상일 수 있으며, US 필수 동의(ai_training 등)를 비검증 화면에서 받는 것의 적법성도 미해결이다. **VPC 게이트 표면 목록은 하드코딩하지 말고 설정(상수 리스트)으로 두어 H4 결정으로 확장 가능하게 구현하라.** (§11 리스크 등록부에 대응 행 있음)
- 산수 게이트는 VPC가 아니라 "성인 확인 UX"로 강등해 유지(비민감 액션용).

#### 3.4.4 방침·라벨링·파기
- 개인정보처리방침·약관: `docs/privacy-policy.{ko,en}.html` 존재하나 **어디서도 서빙 안 됨** + 본문에 국외이전 조항 0건 + 도메인 불일치(`aistorybook.com` vs `.app`). → API 정적 서빙 `/legal/{doc}/{locale}` + 도메인 단일 env(`LEGAL_BASE_URL`) + 조항 갱신(카피는 법무, 배선은 개발). Kids 카테고리는 방침 URL 필수라 스토어 차단 해소 항목.
- AI 생성물 라벨링(EU AI Act·KR AI기본법): 공유 공개 페이지·PDF에 "AI로 생성된 콘텐츠" 표기 1줄(l10n).
- 파기 의무: S3 삭제 실패 재시도 큐(WP-M2-08). 아동 얼굴 포함 책의 공유 무기한 금지(WP-M2-05).

---

## 4. 마일스톤 & 작업 패키지 (WP)

> 규칙: WP는 순서대로. **한 PR = 한 WP = 한 변경 유형**(버그·기능·리팩터 혼합 금지). 각 WP의 "검수"는 개발자 자가검수 명령이며 PR 본문에 출력 첨부.

### M0 — 통합·정본화 (목표: "통합 그린 빌드"라는 것을 처음으로 만든다)

| WP | 작업 | 상세 | 검수 |
|---|---|---|---|
| M0-01 | fix 브랜치 히스토리 정리 | **(0) 리라이트 전 백업 필수**: `git branch backup/pre-rewrite-20260702 && git bundle create ../aisb-backup-20260702.bundle --all` (이 브랜치는 디스크 유일본, §11). **(1)** `f2a0c20`은 브랜치 **첫 커밋**이라 드랍 시 이후 9커밋 SHA가 전부 재작성된다. 커밋 구성 실측: 바이너리 23개(PDF 4.17MB 등) + `.md` + `.html` 6개(MASTERWORK, design-mockups 5) + **`.gitignore` 3줄 추가**(`.aisb_workings.json`, `.playwright-mcp/`, `apps/mobile/macos/Podfile.lock` — 셋 다 디스크 실존, 이 3줄이 유일한 ignore 근거). 처리: 바이너리·`.html`은 `~/Desktop/ai-story-book-artifacts/`로 이동(저장소 밖), **`.md` 문서와 `.gitignore` 3줄은 새 커밋으로 보존**. **(2)** 완료 후 구→신 SHA 매핑표를 이 문서 부록 C에 기록(특히 `1657d52`, `9ef043f` 후신) | `git log --stat main..HEAD`에 바이너리·html 0건; `git check-ignore .aisb_workings.json` 성공; 백업 브랜치·번들 존재; §0.1 게이트 재실행 green; 부록 C 작성 |
| M0-02 | AGENTS.md 7개 + 이 명세서 커밋 | `chore:` 커밋 1개 | `git status --short` 빈 출력 (M0-01의 .gitignore 보존이 전제) |
| M0-03 | fix 푸시 + PR + CI | **푸시·PR·머지는 창업자 승인 후 실행**(이 프로젝트 정책). PR 본문에 로컬 게이트 출력 첨부 | CI 전 잡 green (첫 CI 통과 — 로컬 3.9.6 vs CI 3.11 스큐 검증 포함) |
| M0-04 | fix → main 머지 | 승인 후 | main CI green |
| M0-05 | PR #45(feat) 통합 | **리베이스 금지 — merge로 통합하라**: feat는 create_screen 변경 커밋 7개·l10n 변경 커밋 15개를 포함해 23커밋 리베이스는 같은 파일 충돌이 커밋마다 재발한다. `git merge main`(feat 브랜치에서) 1회 3-way가 옳다(merge-tree 실측 충돌 1건). **create_screen.dart 충돌의 실내용**: fix 측 = 402 에러 코드 분기·크레딧 모달 처리 / feat 측 = 연령밴드 UI + **5언어 수동 스토리 언어 선택기**(13ec793). 해소 원칙: **양쪽 모두 보존 + zh/es 칩만 조건부 비노출**(§3.1, D5 전까지; 서버 enum은 유지). 이후 `flutter gen-l10n` 재생성 → analyze/test. PR #45 미체크 게이트 중 "스트릭 보상 머니경로 적대검토"를 이 WP에서 수행해 결과 첨부(나머지는 §9·§10) | CI green + `flutter gen-l10n` 후 diff 0 + 위젯 테스트: 402 분기 생존·연령밴드 생존·언어 선택기에 zh/es 미노출 + 스트릭 보상 경로 리뷰 노트 |
| M0-06 | 문서 정본화 | `env.schema.json`을 `config.py` 실측과 동기(gemini enum, `IAP_WEBHOOK_SECRET`·`ALLOW_UNVERIFIED_SUBSCRIBE`·`SHARE_BASE_URL` 추가, CORS 기본 `''`); 루트 `CLAUDE.md` 재작성(현행 스택·명령·env 정본); **stale 문서 이동 대상 = 루트의 리포트류 `.md` 전부**: `QUALITY_BASELINE, TEST_AND_COVERAGE_REPORT, CODE_AUDIT_REPORT, CODE_REVIEW_REPORT, CODE_SMELLS, DEPLOYMENT_READINESS, PREDEPLOY_REPORT, SECURITY_REPORT, LOAD_TEST_REPORT, LONG_RUN_ANALYSIS, OVERNIGHT_REPORT, POSTMORTEM, REPO_SNAPSHOT, API_CONTRACT_REPORT, OPERATION_PLAYBOOK` → `archived/2026-01/` (경계 판단이 애매한 파일은 CTO 질문); `COST_MODEL.md` v2(gemini $0.35/권 기준, §10-D1 주석) | env-parity 게이트(§5-G4) 통과; `grep -c 'OPENAI_API_KEY' CLAUDE.md` = 0; 루트 `ls *.md`에 위 목록 0건 |

**M0 DoD**: fix+feat가 모두 반영된 main에서 CI 전 잡 green = 이 저장소 최초의 통합 그린 빌드.

### M1 — 글로벌 차단 결함 (버그만; 전부 §2.3에 좌표 있음)

| WP | 작업 | 상세 | 검수 (긍정·부정 짝) |
|---|---|---|---|
| M1-01 | 삭제 확인 키워드 버그 | `settings_screen.dart:324` `== '삭제'` → `== l.settingsDeleteKeyword` | 위젯 테스트 3건 신설: ko `'삭제'` 성공 / en `'Delete'` 성공 / en `'삭제'` 입력 시 **거부** |
| M1-02 | JIT 사진동의 l10n | `photo_consent.dart:29-47` 하드코딩 제거. ⚠️ **카피 정본 주의**: 현행 다이얼로그 ko 문구와 기존 ARB `consentPhotoDisclosure` 값이 **자구가 다르다**(거부권 문장·종결 질문 유무·불릿 구조). 자구 차이도 법정고지 영역이므로 통일하지 말 것 — **신규 키 `photoConsentDisclosureDialog`를 만들어 현행 다이얼로그 ko 문구를 byte-exact 보존**하고 en/ja 번역을 동반한다(두 카피의 통일 여부는 H4 법무에서 결정, 레지스트리에 양쪽 기재). 제목·버튼도 키 신설 | ko/en/ja 위젯 테스트; **문자열 리터럴 내** 한글 0건(주석·독스트링 제외 — G2 스크립트와 동일 기준); ko 렌더 결과가 기존과 byte 동일한 골든 문자열 테스트 |
| M1-03 | 하드코딩 한국어 스윕 | §2.3-5 전 항목: `api_error.dart` 15곳, `providers.dart` 5곳, `iap_service.dart`·`kakao_share_service.dart` 사유, 알림 채널명, `main.dart:120` → `onGenerateTitle`, `characters_screen.dart` 성격 칩(표시=l10n, **AI 페이로드 값은 ko 유지** — 라벨/값 분리), `env_config.dart:36-37` 예외 메시지 등 **목록 외 잔존은 G2 스크립트 출력이 정본**(§2.3-5는 대표 목록이지 전수가 아님) | §5-G2 게이트 green; flutter test ≥182 유지 |
| M1-04 | 에러 계약 전환 | §3.3대로: 서버 402/403 code 세분화(`books.py:46-132,223,233,419-468`, `core/consent.py:68-70`; 429는 기존 `RATE_LIMIT_EXCEEDED` 유지) + 클라 `ApiError` code 매핑 + 부분문자열 분기 제거(`create_screen.dart:136-143`, `viewer_screen.dart:815-823`) + §3.3의 "예상된 무효화" 테스트 단언 갱신 | API 계약 테스트: 각 code별 응답 스냅샷(크레딧 부족→`CREDIT_INSUFFICIENT` 포함); 클라: en 로케일 402 → 영어 문구 + 크레딧 부족은 크레딧 모달로 분기 위젯 테스트; `grep -rn "'월 '\|'스타일'\|'오디오'" lib/screens` = 0; 갱신된 기존 단언 목록 PR 첨부 |
| M1-05 | 공유 공개 페이지 다국어 | `shares.py:126-135,184,212-214` HTML을 책 `language` 기반 lang/문구로. 카피는 §3.4.1의 서버 카피 모듈(`legal_copy.py` 또는 인접 `share_copy` dict)에 두고 G2 허용목록에 등록. **폴백 규칙 2건 필수**: (a) 책 없음/만료/철회 페이지(`_not_available_html`, 현재 `lang="ko"` 고정)는 `Accept-Language` 최선일치 → en 폴백 (b) dict 미보유 언어(zh/es 책 — M0-05 후 서버 enum 허용)는 en 폴백(KeyError 500 금지) | 테스트 짝: en 책→`lang="en"`+영어 CTA / ko 책 기존 스냅샷 / **만료 토큰+`Accept-Language: ja`→ja 페이지 / zh 책→en 폴백(500 아님)** |
| M1-06 | iOS/Android 스토어 표면 | `ko.lproj/en.lproj/ja.lproj` InfoPlist.strings(권한 문구), `CFBundleDisplayName` 로케일화, Android 알림 채널명 l10n | 시뮬레이터 en에서 권한 다이얼로그 영어 확인(스크린샷 첨부); `plutil -lint` 통과 |
| M1-07 | 죽은 언어 설정 제거 | `settings_screen.dart:459-473` 드롭다운 제거(+서버 `language` 필드는 유지하되 미사용 표기) | analyze 0; 설정 화면 위젯 테스트 갱신 |

**M1 DoD**: §5-G2(한국어 하드코딩 게이트)·G3(l10n parity 게이트)가 CI에 추가되어 green.

### M2 — 머니·신뢰 하드닝 (돈·아동 데이터 경로)

| WP | 작업 | 상세 | 검수 |
|---|---|---|---|
| M2-01 | 파이프라인 실패 환불 | **환불 판정은 "무환불 화이트리스트" 방식이다(코드 열거 방식 금지)**: 무환불 = `SAFETY_INPUT`(사용자 귀책) **단 1개**, **나머지 전부 환불 — `UNKNOWN` 포함**(fail-refund). 근거: `run_step`이 스텝 타임아웃·트랜지언트 최종 실패를 전부 `ErrorCode.UNKNOWN`으로 래핑(`orchestrator.py:140-146`)하고 캐치올도 UNKNOWN(`orchestrator.py:383-385`)이라, 환불 코드를 열거하면 가장 흔한 시스템 실패가 무환불로 남는다. 배선 위치: `mark_job_failed`(orchestrator.py:171-189) + **Celery 경로 `tasks.py:23-38`(`_mark_job_failed_async` — orchestrator를 우회하므로 같은 환불 헬퍼를 별도 배선, soft_time_limit 킬 포함)**. **멱등 fence 2건 필수**: (a) `refund_for_job`(credits.py:218-263)은 unique 제약 없는 check-then-write라 동시 발동(monitor 배치 커밋 창 vs mark_job_failed) 이중 환불 가능 → `CreditTransaction`에 `(reference_id, transaction_type='refund')` 부분 unique 인덱스 추가(마이그레이션) (b) `mark_job_done`(orchestrator.py:192-208)이 failed를 무조건 done으로 덮어씀 → 현재 상태 재확인 fence 추가(환불된 잡의 늦은 성공 = "책+환불" 이중 취득 차단) | 단위 테스트: 타임아웃(UNKNOWN) 실패→잔액 복원 / SAFETY_INPUT→미복원 / SAFETY_OUTPUT→복원 / 같은 잡 이중 실패→환불 1회 / **동시 발동(monitor+orchestrator 세션 분리) 시뮬레이션→DB unique로 1회** / failed 잡에 mark_job_done→done 전이 거부 / Celery 경로 실패→환불 |
| M2-02 | 부분실패 책 표식 | ⚠️ 재생성은 **현재도 전면 무크레딧**(books.py:697-778에 과금 코드 0)이므로 "무크레딧 허용"은 no-op이다. 이 WP의 실제 내용: (a) placeholder 페이지 판정을 기존 `_is_placeholder_image_url`(orchestrator.py:691-692) 재사용으로 조회 가능하게 하고 (b) **placeholder 재생성도 M2-03 캡에 포함**(면제 시 "고의 실패→무제한 재생성" 악용 표면) (c) 목적: §10-D6에서 재생성이 유료화되더라도 placeholder 페이지는 무료 유지되도록 판정 근거를 마련 | 테스트: placeholder 페이지 식별 API/필드 동작; 캡 계수에 placeholder 재생성 포함 확인 |
| M2-03 | 재생성 남용 캡 | 페이지 재생성(books.py:697-778, 현재 무크레딧·무캡)에 일일 캡(env `DAILY_REGEN_LIMIT_PER_USER`, 기본 30, placeholder 포함) | 캡 도달 시 429 `RATE_LIMIT_EXCEEDED`; 테스트 짝(30회째 허용/31회째 거부) |
| M2-04 | IAP 합성 txn id 검증 | `credits_screen.dart:720-721`이 purchaseID null 시 타임스탬프 합성 → 서버 정본은 store 검증 후 `store_transaction_id`(iap.py:189-221)임을 확인하고, 클라는 purchaseID null이면 verify **보류+재시도**(합성 ID 전송 제거) | strict 모드 계약 테스트: 합성 ID로 이중 지급 불가 재확인; 클라 단위 테스트 |
| M2-05 | 공유 표면 보호 | 전제 정정: nginx에 IP `limit_req`가 이미 있다(nginx.conf:112-114) — 이 WP는 **앱 레벨 토큰별 캡**(nginx 우회 배포·IP 분산 대비). 가용성 회귀 금지: **이미지 프록시만 Redis 실패 시 fail-closed**(S3 비용 방어), **HTML 페이지는 인프로세스 폴백 리미터로 fail-open**(공유 바이럴 루프는 현재 Redis 무의존인데 하드 의존 신설로 전체 다운 금지). 만료 상한: 실제 구멍은 요청 0(이미 30일 폴백, shares.py:69)이 아니라 **config `SHARE_DEFAULT_EXPIRY_DAYS=0` 경로와 요청 상한 `le=365`(shares.py:39)** — `SHARE_MAX_EXPIRY_DAYS`(기본 90)로 양쪽 클램프, `expires_at=NULL` 생성 경로 전면 차단 | 테스트 짝: 정상 조회 허용/토큰별 과량 429; Redis 다운 시 HTML 200·이미지 프록시 503; 요청 365일→90 클램프; config 0이어도 NULL 미생성 |
| M2-06 | JIT consent echo 수정 | `photo_consent.dart`: `getConsent` 실패 시 grant를 보내지 않고 에러 UI(fail-closed); 서버에 photos만 갱신하는 부분 API 추가 검토 대신 **기존 동의값 fetch 성공시에만 echo** | 단위 테스트: getConsent 실패→grant 미호출; 기존 granted 보존 회귀 테스트(서버) |
| M2-07 | photo_character fail-closed | `photo_character.py:108-112,152-159,396-398` — 라이브 provider에서 파싱 실패 시 `LLMError` raise(재시도 대상), mock 반환은 `LLM_PROVIDER=mock`일 때만 | 테스트: 라이브 모드 + 비정상 JSON → 4xx/5xx 에러(mock 캐릭터 저장 0건) |
| M2-08 | 파기 재시도 큐 | S3 삭제 실패를 `storage_purge_backlog` 테이블에 기록, job_monitor 주기에서 재시도(3회 후 알럿 로그) | 테스트: 삭제 실패 주입→백로그 기록→재시도 성공 시 소거 |

**M2 DoD**: 돈·아동데이터 경로 테스트 신설 ≥15건, pytest ≥415.

### M3 — 실키 시임 마감 + A1 실측 준비 (키는 여전히 0개)

| WP | 작업 | 상세 | 검수 |
|---|---|---|---|
| M3-01 | 골든셋 확장 | `docs/qa/golden-prompts.json` 4편 → **연령밴드 3×5=15편 + 사진 캐릭터 멀티페이지(≥6p) 1편**(pass-bar §1 표본 요구). ⚠️ **정본 정정**: pass-bar 문서(`A1_LIVE_PASSBAR_2026-06-27.md:10`)의 연령밴드 표기 "3-5/6-8/9-11"은 **오기**다 — 코드 `TargetAge` enum은 `3-5/5-7/7-9/adult`뿐(`apps/api/src/models/dto.py:20-23`, feat 브랜치 동일). **코드 enum을 따르고**(6-8/9-11로 만들면 422 전량 거부), 이 WP에서 pass-bar 문서의 해당 표기도 정정하라. 사진 엔트리는 라이선스-프리 아동 스톡/합성 이미지로 구조 완성(실아이 사진은 창업자 제공 시 교체). ko/en 커버 | 구조 하니스(mock) green; 엔트리 수 검증 `python -c "...len==16"`; pass-bar 문서 정정 diff |
| M3-02 | A1 원커맨드 런북 | `scripts/run_a1_live.sh` 신설: minio(docker-compose) 기동 확인→env 검증→`apps/api/scripts/golden_prompts_harness.py --live --report-dir results/golden`(하니스 실경로 주의 — 루트 `scripts/`가 아님)→산출물 경로 출력. **S3 미기동이면 실행 전 중단**(키 비용 보호) | 키 없이 실행 시 명확한 사전 실패; mock으로 드라이런 green |
| M3-03 | 시임 검증 게이트 2종 | (a) env-0 프로덕션 빌드가 안전 기본값으로 기동 차단되는지(readiness) (b) 코드 env 참조 ↔ `env.schema.json`+`.env.example` 양방향 일치 스크립트 `scripts/check-env-parity.sh` → CI 편입 | CI green; 고의 불일치 주입 시 게이트 red 확인 |
| M3-04 | readiness→트래픽 배선 검증 | `infra/nginx/nginx.conf`·deploy가 `/health/ready` 503을 실제로 차단하는지 실측. 안 되어 있으면 nginx 헬스체크/deploy 게이트 배선 (IAP fail-open의 유일 방어가 이것) | compose 기동 상태에서 `IAP_VERIFICATION_MODE=local`+운영 플래그 → 외부 요청 차단 실측 로그 |
| M3-05 | analytics 시임 확정 | 기존 드롭인 구조(B3) 유지 확인 + 이벤트 스키마를 `docs/ANALYTICS_EVENTS.md`로 고정(growth_viewed 등 기존 이벤트 전수 목록화) | 문서-코드 이벤트명 diff 0 (grep 스크립트) |

**M3 DoD**: "키 0개 → CI+로컬 전 게이트 green" 유지 + "키 주입 → §3.2.3 절차만으로 라이브" 체크리스트 통과. **여기까지 끝나면 A1 실측은 창업자 키 투입만 남는다(§9-H1).**

### M4 — 글로벌 컴플라이언스 (설계는 §3.4)

| WP | 작업 | 검수 |
|---|---|---|
| M4-01 | consent v3 마이그레이션 — §3.4.2의 컬럼·NULL 의미론·백필 값 그대로(jurisdiction `'KR'` NOT NULL, boolean 3종 NULL 허용) | alembic up/down 왕복 테스트(CI 실Postgres); 기존 v2 행 판독 회귀; **NULL(미질문) vs false(거부) 구분 테스트** |
| M4-02 | jurisdiction별 필수 셋 평가(`core/consent.py` 확장, §3.4.2 하향 금지 규칙 포함) + 동의 화면 시장 분기(거주 지역 1회 질문) | 시장별 테스트 매트릭스: KR 기존 플로우 회귀 0 / US에서 ai_training 미동의 시 사진 기능 403 / **US 신호+KR 선언 → US 셋 적용(하향 차단)** / EU_UK 연령 게이트 |
| M4-03 | VPC 시임 — §3.4.3의 최소 계약 그대로(`VPC_REQUIRED` code, `/v1/vpc/challenge`·`/v1/vpc/verify`, `parental_verifications` 테이블, mock=고정코드 `000000` 승인, 게이트 표면은 설정 리스트) | `VPC_PROVIDER=mock` E2E: US+사진 업로드→403 `VPC_REQUIRED`→challenge→verify(`000000`)→업로드 성공; KR→미발동; 오코드 verify→거부; readiness에 US 출시 모드 시 mock 차단 등록 |
| M4-04 | `docs/LEGAL_COPY_REGISTRY.md` 신설(로케일×시장×**표면(클라 ARB/서버 legal_copy.py)**×카피 버전×사인오프 상태) + consent en/ja 카피(커밋 "fix(mobile): localize content + consent screen…", 구 `1657d52` — 부록 C의 신 SHA로 기재) pre-signoff 기재 + M1-02의 JIT 카피 양본 기재 | 문서 존재 + consent_version 매핑 표와 코드 상수 일치 |
| M4-05 | 방침·약관 서빙 `/legal/*` + `LEGAL_BASE_URL` 단일화 + 설정/공유의 URL 참조 교체. ⚠️ **순서 단서**: 방침 본문에 국외이전 조항이 0건(실측 — 앱 내 고지와 모순)이므로 **H4 사인오프 전에는 프로덕션 도메인 노출 금지(스테이징 한정)** — 조항 없는 방침이 공식 URL로 나가면 고지-방침 불일치가 공개된다 | curl 각 locale 200(스테이징); 도메인 grep 스윕: `aistorybook.com` 하드코딩 0건 |
| M4-06 | AI 생성물 라벨링(공유 페이지·PDF 1줄 표기) — 서버 렌더 표면이므로 **ARB가 아니라 §3.4.1의 서버 카피 모듈(`legal_copy.py`)** 사용 | 스냅샷 테스트 3로케일(공유 HTML·PDF 각각) |

**M4 DoD**: KR 사용자 경험 회귀 0(기존 플로우 그대로) + US/EU 분기 테스트 green. 법무 카피 교체가 코드 변경 0으로 가능함을 카피 1건 교체 리허설로 증명.

### M5 — 스토어/배포 준비 (개발자 가능분만; 사람 게이트는 §9)

| WP | 작업 | 검수 |
|---|---|---|
| M5-01 | 버전·서명 체계: `pubspec` 버전 전략(0.1.0+1→1.0.0 로드맵), Android `key.properties` 문서화, iOS/Android 번들ID 불일치(`com.storybook.aiStoryBook` vs `com.storybook.ai_story_book`) 영향 조사(카카오 SDK·딥링크) 후 정합 | release 빌드(서명키 없이 검증 가능한 데까지) + 조사 보고 |
| M5-02 | 스토어 제출 체크리스트 코드화: `scripts/store-preflight.sh`(방침 URL 200 **+ 방침 본문 국외이전 조항 존재 grep + LEGAL_COPY_REGISTRY 사인오프 상태 파싱**, Kids 요건, PROD_API_URL, IAP 상품 ID 정합, 스크린샷 매트릭스 ko/en/ja) — HTTP 200만 보면 조항 없는 방침도 green이 되므로 내용 검사 필수 | 스크립트가 현재 미비 항목(국외이전 조항 0건 포함)을 정확히 red로 출력 |
| M5-03 | `docs/FINAL_USER_INPUT_REQUIRED.md` 갱신(AdMob 제거 반영 — 광고는 삭제됐는데 문서에 잔존, `pubspec` ads 0건 실측; VPC·analytics 키 추가) | preflight와 문서 항목 1:1 |

---

## 5. 검증 게이트 (CI 편입 목록)

| # | 게이트 | 상태 | 명령 |
|---|---|---|---|
| G1 | 기존 CI 전 잡 (§2.4) | 유지 | `.github/workflows/ci.yml` |
| G2 | **한국어 하드코딩 게이트** (M1 신설) | 신설 | `scripts/check-hardcoded-korean.sh` — **문자열 리터럴만 검사(주석·독스트링 제외 필수** — 한글 포함 파일이 dart 34·py 56개인데 대부분 주석이라 주석 포함 시 영구 red**)**. 허용목록은 글롭으로 고정: `lib/l10n/**` / `lib/models/book_spec.dart`(AI 페이로드 라벨) / `apps/api/src/core/legal_copy.py`(서버 법정·공유 카피 모듈, §3.4.1) / `apps/api/src/prompts/**` / `**/tests/**`·`**/test/**` / **서버 에러 `message` 문자열(ko 유지가 §3.3 계약)** — 이 목록 밖 한글 리터럴 0건 |
| G3 | **l10n parity 게이트** (M1 신설) | 신설 | ARB 3파일 키 집합 동일성 + ICU placeholder 정합 (`scripts/check-l10n-parity.py`) |
| G4 | **env parity 게이트** (M3-03) | 신설 | 코드 env 참조 ↔ `env.schema.json` ↔ `.env.example` 양방향 |
| G5 | CI 트리거 확장 | M0-03에서 | `push: [main, develop]` → `push: [main]` + `pull_request: [main]` 유지하되, **모든 작업 브랜치는 PR을 열어 CI를 태우는 것을 규칙화**(문서화) |
| G6 | 커버리지 임계 | M2 종료 시 상향 | API 40→50%, Flutter 25→30% (신규 코드로 인한 하회 방지 확인 후) |
| G7 | Trivy soft→hard 검토 | §10-D8 | 현재 `exit-code '0'`(ci.yml:336-343) |

**금지 사항 (전 WP 공통)**
1. `.env`·시크릿·실키 커밋 금지(Gitleaks가 잡지만, 애초에 만들지 말 것). 로그에 키·토큰·`X-User-Key` 원문 금지(기존 리댁션 패턴 유지 — `main.py:85-89`).
2. **ko 법정 카피 byte 변경 금지**(consent·국외이전 고지) — 법무 영역. 필요 시 CTO 경유.
3. 서버 에러 `code` 값(§3.3)은 출시 후 변경 금지 계약.
4. `settings.testing` 등 테스트 우회 플래그를 프로덕션 경로에 노출 금지.
5. 페이지 재생성은 해당 페이지만(전체 재생성 API 신설 금지 — 비용 폭발 경로).
6. §10의 열린 결정을 코드로 선점 금지(예: 읽기성장 리포트에 과금 게이트를 임의 추가하지 말 것).
7. 스토어 제출·프로덕션 배포·git push/머지는 창업자 승인 후.

---

## 6. 파라미터 표

**가변(env — 설정화 대상, 기본값은 코드 정본 `config.py`)**: `LLM_PROVIDER`/`LLM_API_KEY`/`LLM_MODEL`, `IMAGE_PROVIDER`/`IMAGE_API_KEY`, `TTS_PROVIDER`+키, `STT_PROVIDER`+키, `IAP_VERIFICATION_MODE`+Apple/Google 자격, `IAP_WEBHOOK_SECRET`, `ALLOW_UNVERIFIED_SUBSCRIBE`, `POD_MODE`+Printful 자격, S3 6종, `SHARE_BASE_URL`, `LEGAL_BASE_URL`(신설), `VPC_PROVIDER`(신설), `DAILY_REGEN_LIMIT_PER_USER`(신설), `SHARE_MAX_EXPIRY_DAYS`(신설), 레이트리밋·잡 한도류.

**고정(하드코딩 유지 — 바꾸려면 CTO 승인)**: 에러 code 문자열(§3.3), `consent_version` 진행 규칙, 연령밴드 3-5/5-7/7-9, A1 pass-bar 임계(C1 <60% KILL·≥80% GO·S1 무관용), 크레딧 차감=책 생성 1, jobs `(user_key, idempotency_key)` unique, `store_transaction_id` 정본 dedup.

---

## 7. 검수 제출물 (매 WP)

1. PR(1 WP = 1 PR) + 변경 파일 목록
2. §0.1 게이트 전체 출력(수치 포함) + 해당 WP 검수 명령 출력
3. UI 변경 시 ko/en/ja 3로케일 스크린샷
4. 신규/변경 테스트 목록(긍정·부정 짝 여부 표기)
5. 심각도: P0(머니·아동데이터·삭제권) 즉시 보고, P1(게이트 red) 24h 내 수정, P2 스프린트 내

---

## 8. 파일→역할→Phase 맵 (착수용 최소 지도)

| 파일 | 역할 | 주 Phase |
|---|---|---|
| `apps/api/src/core/config.py` | env 정본(전 시임 스위치) | M0/M3 |
| `apps/api/src/main.py` | 라우터 마운트·readiness·보안헤더·리댁션 | M2/M3 |
| `apps/api/src/services/orchestrator.py` | 생성 파이프라인(A~H)·실패 처리 | M2-01/02 |
| `apps/api/src/services/credits.py` | 원자 차감·멱등 환불·clawback | M2-01 |
| `apps/api/src/routers/books.py` | 생성·재생성·402 한도 | M1-04/M2-03 |
| `apps/api/src/routers/iap.py` + `services/iap_verifier.py` | IAP 검증·웹훅 | M2-04 |
| `apps/api/src/routers/shares.py` | 공개 공유·토큰 프록시 | M1-05/M2-05 |
| `apps/api/src/core/consent.py` + `routers/consent.py` | 동의 게이트·기록 | M4 |
| `apps/api/src/services/photo_character.py` | 사진→캐릭터(vision) | M2-07 |
| `apps/api/src/qa/golden_harness.py` + `apps/api/scripts/golden_prompts_harness.py` | 골든/A1 하니스 (루트 `scripts/` 아님) | M3-01/02 |
| `apps/api/src/core/exceptions.py` | 에러 envelope 정본(§3.3) | M1-04 |
| `apps/mobile/lib/screens/settings_screen.dart` | 삭제 확인·설정 | M1-01/07 |
| `apps/mobile/lib/core/photo_consent.dart` | JIT 사진동의 | M1-02/M2-06 |
| `apps/mobile/lib/core/api_error.dart` + `services/api_client.dart` | 에러 표시 계약 | M1-03/04 |
| `apps/mobile/lib/l10n/*.arb` (728키×3) | UI 문자열 정본(ko) | M1 전반 |
| `apps/mobile/lib/services/parental_control_service.dart` | 부모 게이트(산수) | M4-03 |
| `.github/workflows/ci.yml` + `scripts/phase-gate.sh` | 게이트 | M0/M3/M5 |

---

## 9. 사람(창업자)만 할 수 있는 것 — 코드로 대체 불가

> **H1이 최우선이다.** 이 명세의 전 마일스톤은 "A1이 GO"라는 가정 위에 있다. A1은 $6~10·1회 실측으로 이 가정을 확정하는 **가장 싼 결정적 테스트**인데 2026-06-13 제기 후 미실행 상태다. M3-01/02 완료 즉시 실행을 강력 권고한다(개발과 병렬 가능하나, KILL이 나오면 그 위 작업의 상당수가 무효가 된다).

| # | 항목 | 내용 |
|---|---|---|
| H1 | **A1 실키 실측** | LLM/이미지 키 1세트 투입 → `./scripts/run_a1_live.sh` → pass-bar(§고정) 대입 판정. GO 전 마케팅·스토어 제출 금지 |
| H2 | A2 이미지 provider 확정 | gemini(얼굴보존 유일) 확정 여부 + 폴백 정책 — wedge #1과 원가($0.35/권)가 종속 |
| H3 | git push·PR 머지·배포 승인 | M0-03 이후 반복 발생 |
| H4 | **법무 사인오프** | en/ja 법정 카피(§3.4.1 레지스트리), 국외이전 실계약 사실 확인(C2 — 계약 없으면 현행 고지가 허위 기재), 방침 국외이전 조항, COPPA 자문 |
| H5 | VPC 방식·벤더 선정 | §3.4.3 — US 출시 전 |
| H6 | 스토어·인프라 자격 | Apple/Google 개발자 계정, IAP 상품 콘솔 등록, `IAP_VERIFICATION_MODE=strict` 키들, Printful, analytics(firebase/posthog 택1), `DEPLOY_ENABLED`, 도메인 확정 |

---

## 10. 열린 결정 (창업자) — 개발자는 선점 금지

| # | 결정 | 기본값(결정 전 코드 동작) |
|---|---|---|
| D1 | 읽기성장 리포트를 글로벌 BM으로 유지·과금 게이트 배선? (현재 전면 무료, 마스터워크 BM의 전제였던 외부 권위 척도 매핑도 부재 — `growth.py:5-30`) | 무료 유지, 과금 배선 안 함 |
| D2 | 사진 캐릭터 홈/생성 메인 CTA 승격(구 D1) | 현행 유지 |
| D3 | dependabot major 6건 + open PR #46~#55 | 보류 |
| D4 | 공유 링크 최대 만료(90일 상한 제안 — M2-05) | 90일로 구현, 조정 가능 |
| D5 | es/zh 노출 시점(코드는 feat 머지로 유입, UI 비노출) | 비노출 |
| D6 | 재생성 크레딧 정책(현행 무료+캡 vs 차감) | 무료+일 30캡 |
| D7 | 계정 시스템(Sign in with Apple/Google) 도입 시점 — 현행 X-User-Key는 기기 분실=데이터 유실, UUID 유출=전체 탈취. VPC(부모 확인)와 묶으면 자연스러움 | 1차 출시는 현행+IAP 복원, 로드맵만 유지 |
| D8 | Trivy/safety soft→hard | soft 유지 |

---

## 11. 리스크 등록부

| 리스크 | 심각도 | 완화 |
|---|---|---|
| **fix 브랜치가 디스크 유일본**(원격 0, 머니·법무 커밋 포함) | 치명 | M0-01~03을 다른 어떤 작업보다 먼저. 완료 전 이 맥북 백업 유지 |
| A1 KILL 가능성(얼굴 일관성 <60%) — 이 경우 wedge #1 재설계 | 치명 | H1 조기 실행. M1~M2는 A1 결과와 무관하게 유효(버그·머니·법무)하므로 선행 배치했다 |
| COPPA VPC 미비 상태로 US 출시 | 치명 | §9-H4/H5 게이트. M4-03 완료 전 US 스토어 제출 금지 |
| **VPC 스코프 축소 리스크**: M4-03의 게이트 표면(사진·공유·음성)은 최소 집합 — 아동 이름·생년월(`child_profiles`)·지속 식별자(X-User-Key)·analytics 수집이 스코프 밖이고, US 필수 동의가 비검증 화면에서 수집됨. **"M4-03 완료 = US 컴플라이언스 완결"로 오독 금지** | 높음 | H4 COPPA 자문이 최종 범위를 결정(§3.4.3 유보 조항). 게이트 표면을 설정 리스트로 구현해 확장 비용 최소화 |
| consent en/ja 카피가 pre-signoff 상태로 배포 경로에 존재 | 높음 | 레지스트리 관리 + 스토어 제출 게이트(H4). ko 정본 보존으로 롤백 용이 |
| 국외이전 고지의 기재 사실(위탁 계약) 미확정 | 높음 | H4. 확인 전 KR 마케팅 확대 금지 |
| 두 브랜치 통합 회귀(l10n 생성물·create_screen) | 높음 | M0-05 절차(재생성+diff 0 게이트) |
| 로컬 Python 3.9.6 vs CI 3.11 스큐 | 중간 | M0-03에서 첫 CI로 검증; 개발자는 3.11 venv 재구성 권장 |
| 원가 정본 부재($0.025~0.35 3문서 불일치) | 중간 | M0-06 COST_MODEL v2. 가격 결정(D1)은 그 후 |
| 예상된 무효화: M1-04가 `PAYMENT_REQUIRED` 단언 테스트를(§3.3 목록), M4 consent v3가 기존 consent 테스트 일부를 의도적으로 대체 | 예상됨 | 버그 아님 — 각 WP 명세·PR에 대체 목록 기재 |

---

## 부록 A. 빠른 재개 명령

```bash
cd /Users/jmac/Desktop/ai-story-book
git log --oneline -5 && git status --short          # 상태
cd apps/api && ./venv/bin/python -m pytest tests/ -q # API 게이트
cd ../mobile && flutter analyze && flutter test      # 모바일 게이트
flutter test integration_test/ -d flutter-tester     # macOS 통합 테스트
```

## 부록 B. 이 명세가 근거한 실측 소스
- 2026-07-02 7에이전트 정찰(git 토폴로지·백엔드·모바일·시임·법무·게이트·시장) — 세션 워크플로 `wf_1ea07ee1-101`
- 로컬 게이트 실행 실측(§0.1), `git merge-tree` 충돌 실측, gh PR/CI run 실측
- v1.0 → v1.1: 4렌즈 적대 검증(`wf_f95f0869-b86`, 클레임 157건 대조·생존 반증 31건 반영)

## 부록 C. 커밋 SHA 매핑표 (M0-01 완료 시 개발자가 기입)

| 구 SHA | 커밋 제목 | 신 SHA |
|---|---|---|
| `f2a0c202c47105c2d31e773ca0b440657a23b288` | chore: preserve masterwork + design/competitor reference artifacts (local only) | `8f8c3d51e328f0b3cecf607c42f4ddf51e9c4805` |
| `c87e800a20b4b34c3b08d19fbe12b25ba7cd1174` | docs: A1 실키 --live 품질 합격선(pass-bar) 사전 정의 — GO/KILL/CONDITIONAL 임계 | `249d0fd387158bda5a7a97e268b285bbbe018582` |
| `51bce95fc83286cb4e57e115bf9192cf0046cd22` | docs: 글로벌 시장조사 — AI 동화앱 경쟁/규제/wedge (조건부 GO, 영어권 1차) | `8979edc2f13c5cef759ed1b76cff6d7488ff8c72` |
| `32db9c15bfc54bee6d5889f6157281d9120dd755` | fix(iap): close monetization-bypass cluster (F1/F2/F3 + refund/webhook) | `5d2b92e4e1ee070350bd400acbec0d9b905ee323` |
| `acaa2e12cd4f09e81a16a8526dd345cb744f8f49` | fix(deletion): close GDPR/erasure FK gaps + scope deletable child PII (F8/N5/N6/N7) | `1fd94965278c27ced94a4e4b88ff3526ee21050f` |
| `42dc9fe60dca6e244181d1406bc7ced6a278005e` | fix(share): nginx /share route + tokened image proxy + token log redaction (F5/N3/N4) | `96e1fc0b316c65e534129ad5e7a1b6d87a0793db` |
| `ebd113dad928165360ec9f890d237d96ad0ca3ba` | fix(release): ja learning assets + preflight aligned to no-ads/PROD_API_URL (N11/F10) | `556b31d035690d0a0d24d521d338871f15777849` |
| `1657d52799729d837b54cb8cbff8cf40ab9b4fb2` | fix(mobile): localize content + consent screen + parent-gated share (N8/F9/N9/F6/F7/N10) | `84c0485fbbff6311f9ffefabcac92baf9fea48f8` |
| `36f98987b0abc13f492431c86318930cb5c1f532` | fix(mobile): fully localize reading-growth report screen (N10 complete) | `bbceefb30a36fc6d3e1ed11ef83dbe8f714688f7` |
| `9ef043f53c1f038c1e191d92983b9db4d3e0def9` | fix(iap): record correct previous user_key in restore audit payload | `e88fb66b7ab53339320f344679c7d48e57aec966` |
