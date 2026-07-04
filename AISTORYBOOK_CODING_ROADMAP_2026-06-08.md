# AI STORY BOOK — 코딩 실행 로드맵 (2026-06-08 갱신)

**문서 갱신 근거**: `OUTSOURCE_DEV_SPEC`/`FEATURE_ROADMAP`(2026-02-21)은 4개월 경과 stale. 아래는 코드 직접 정독으로 검증한 *현재* 상태 기준 재정렬판. 모든 경로는 검증됨. 공수 = 1인(Sterling)+AI코딩 기준.

## 0. 검증 요약 (코드에서 직접 확인 — 이게 정본)

| 클레임 | 검증 | 정확한 위치 |
|---|---|---|
| 월 크레딧 리필 크론 부재 (2개월차 매출 누수) | ✅ FATAL 확정 | `worker.py:21-34` beat_schedule 없음, `credits.py:239 create_subscription`만 1회 지급 |
| 오늘동화 `book_id=None` 빈 껍데기 | ✅ 확정 | `services/streak.py:445` (`get_today_story` 399행) |
| Character DB에 `reference_image_url` 컬럼 없음 | ✅ 확정 | `models/db.py:184-198` (master_description 텍스트만) |
| 기본 이미지=DALL-E 3 (seed/negative 무시) | ✅ 확정 | `core/config.py:50-52` `image_provider="openai", image_model="dall-e-3"` |
| FAL Flux Schnell 어댑터 이미 존재 (저원가 경로) | ✅ 호재 | `services/image.py:210-258` `fal-ai/flux/schnell`, seed/지원 |
| 서버 동의 미집행 | ✅ 확정 | `routers/users.py:76` (delete만), books/characters 0회 체크 |
| 분석/푸시 패키지 0 | ✅ 확정 | `pubspec.yaml` 무, `core/app_telemetry.dart`는 `developer.log` 로컬 스텁뿐 |
| 학습자산 생성됨, 리포트 노출 안 됨 | ✅ 확정 | orchestrator LEARNING_ASSETS(92) 생성 → `streak.py:586` 리포트는 `completion_rate`만 |
| 인증 의존성 패턴 존재 | ✅ 호재 (재사용) | `routers/books.py:14` `from src.core.dependencies import get_profile_id, get_user_key` |

**핵심 재정의**: 출시 블로커는 "API 키"가 아니라 *5개 끊긴 배선*. 전부 신규 빌드 아닌 *재배선*이라 1인+AI코딩 2주 가능.

---

## SPRINT L0 — 런치 게이트 (비협상, 4-5일) "출시하면 안 되는 버그부터 막는다"

### L0-1 · 월 크레딧 자동 리필 크론 [FATAL 매출누수]
- **작업**: Celery Beat 스케줄 추가. `worker.py:21` `conf.update`에 `beat_schedule` 블록 신설 → 일 1회(`crontab(hour=4, minute=0)`) `refill_monthly_credits` 태스크. 태스크는 `current_period_end <= now` 인 active 구독을 조회, `credits_per_month` 재지급 + `current_period_start/end` 1개월 롤포워드 (원자적 조건부 UPDATE로 중복지급 방지: `WHERE last_refill_period < current_period`).
- **파일**: `apps/api/src/worker.py`(beat 등록), `apps/api/src/services/tasks.py`(태스크 신설), `apps/api/src/services/credits.py`(`refill_subscription_credits` 메서드 신설), 마이그레이션 신규(`UserSubscription`에 `last_refill_at` 컬럼).
- **수용기준**: (1) Basic 구독 가입 후 `current_period_end`를 과거로 세팅 → 태스크 실행 → 크레딧 +10, period +1개월. (2) 같은 태스크 2회 실행 시 2차는 0 지급(멱등). (3) 테스트 `test_credits.py`에 멱등성·롤포워드 케이스 2개 추가.
- **공수**: 0.5일 (AI코딩). 배포 시 `celery beat` 프로세스 1개 추가 필요 → `DEPLOYMENT.md` 갱신.

### L0-2 · 분석 이벤트 배선 (8 이벤트) [측정 0 → GO-TO-LEARN 가능]
- **작업**: `pubspec.yaml`에 `firebase_analytics` 추가(또는 PostHog `posthog_flutter` — Firebase가 키즈 무료·간편). `app_telemetry.dart`의 `logInfo`를 `logEvent(name, params)`로 확장해 실제 sink 연결. 8개 핵심 이벤트만: `book_create_start`, `book_create_complete`, `book_open`, `book_complete`(완독), `today_story_open`, `paywall_view`, `purchase_success`, `streak_continue`.
- **파일**: `apps/mobile/pubspec.yaml`, `apps/mobile/lib/core/app_telemetry.dart`(sink 추가), 각 화면 호출부(`create_screen.dart`, `viewer_screen.dart`, `home_screen.dart`, `credits_screen.dart`).
- **수용기준**: Firebase DebugView에 8 이벤트 실시간 표시. 기존 `app_telemetry_test`(있으면) 그린 유지. 개인정보: 아동 식별자 미전송(`profile_id`는 해시).
- **공수**: 1일. **출시 전 필수** — 이거 없으면 출시해도 리텐션을 못 본다(GO-TO-GUESS 방지).

### L0-3 · 잠자리 로컬 푸시 1종 [습관 = 리텐션]
- **작업**: `flutter_local_notifications` 추가. 부모 설정 시각(기본 20:00)에 로컬 알림 1종: "오늘의 동화가 기다려요 📖". 서버 푸시 아님(FCM 키 불필요 = 출시 블로커 회피).
- **파일**: `apps/mobile/pubspec.yaml`, `apps/mobile/lib/core/notifications.dart`(신규), `settings_screen.dart`(시각 토글).
- **수용기준**: 설정 시각에 알림 1회, 탭 시 오늘동화로 딥링크. iOS/Android 권한 요청 1회.
- **공수**: 1일.

### L0-4 · 서버 동의 집행 + 출시 1형상 사진→캐릭터 OFF [PIPA 법적 리스크]
- **작업**: (a) `POST /v1/consent` 신설(서버 기록), `UserConsent` 생성 경로 추가(현재 delete만). (b) `core/dependencies.py`에 `require_consent` 의존성 신설 → `books.py`/`characters.py`의 생성 엔드포인트에 주입(기존 `get_user_key` 패턴 그대로). (c) 출시 1형상: `characters_screen.dart`의 사진 업로드 옵션을 피처플래그 OFF(텍스트·아이그림 캐릭터만 GO) → gpt-4o 비전 비용·아동사진 PIPA 리스크 동시 제거.
- **파일**: `apps/api/src/routers/users.py`(POST 추가), `apps/api/src/core/dependencies.py`(`require_consent`), `apps/api/src/routers/books.py`+`characters.py`(의존성 주입), `apps/mobile/lib/screens/characters_screen.dart`(플래그).
- **수용기준**: 동의 없는 user_key로 `POST /books` → 403. 동의 기록 후 200. 사진 업로드 UI 비노출. `test_books.py`에 403 케이스 추가.
- **공수**: 1일. **마케팅 전환**: "사진 서버 미저장·즉시폐기·전 이미지 이중검수"를 ProKidsBook 대비 안전 카피로.

**L0 산출물**: 매출누수 차단 + 측정 + 습관 + 법적 집행. **이게 진짜 출시 게이트.**

---

## SPRINT L1 — 리텐션·단위경제 핵심 (5-6일) "단일 최고 ROI 클러스터"

### L1-1 · 오늘동화 무료 공유 전환 + 생성/소비 분리 [최고 ROI 단일 변경]
- **작업**: `get_today_story`(streak.py:399)를 전 유저 공유 1일 1편으로. 서버가 하루 1회 *실제 book*을 생성·캐싱(`DailyStory.book_id` 채움) → 비용 유저수 무관 고정 1권($0.32 또는 저가모델 시 $0.003). `book_id=None`(streak.py:445) 제거. 무료한도 정책 분리: **생성=크레딧 차감, 소비(읽기·재독·오늘동화)=무제한 무료**(읽기 엔드포인트 크레딧 미차감 확인).
- **파일**: `apps/api/src/services/streak.py`(공유 생성+캐시), `apps/api/src/models/db.py`(`DailyStory.book_id` FK 활용), 일 1회 생성은 L0-1 beat에 `generate_daily_story` 태스크 추가.
- **수용기준**: 같은 날 N명 호출 → DB에 `DailyStory` 1행, 동일 `book_id` 반환(중복생성 0). 무료유저가 오늘동화 매일 읽어 스트릭 유지 가능. 읽기 호출 시 크레딧 불변.
- **공수**: 1.5일. **이 한 수가 리텐션·단위경제·습관 동시 해결.**

### L1-2 · 캐릭터 일관성 배선 (마스터 이미지 + reference_image_url) [#1 차별화 복구]
- **작업**: (a) `models/db.py:184 Character`에 `reference_image_url = Column(String(500), nullable=True)` 추가 + 마이그레이션. (b) 캐릭터 생성 시 '마스터 이미지' 1장 생성 → S3 저장 → `reference_image_url` 기록. (c) 기본 이미지 프로바이더를 레퍼런스 지원으로: `core/config.py:50` `image_provider="openai"`→ 레퍼런스 지원 경로(`image.py` 어댑터에 reference 주입). FAL Flux 경로(image.py:210)는 이미 seed 지원 → Flux Kontext/reference 변형으로 확장. 전 페이지 프롬프트에 `reference_image_url` 주입.
- **파일**: `apps/api/src/models/db.py`(컬럼), 마이그레이션 신규, `apps/api/src/services/photo_character.py`/`character` 생성부(마스터 이미지), `apps/api/src/services/image.py`(reference 주입 어댑터), `apps/api/src/core/config.py`(기본 프로바이더).
- **수용기준**: 시리즈 2권째 캐릭터 얼굴 시각 일관(수동 비교 + 동일 `reference_image_url` 주입 확인). 마이그레이션 up/down 통과. **못 고치면**: '캐릭터 일관성' 카피를 내리고 '연령최적화 한국어'로 단일화(못 지킬 약속이 가장 비싼 churn).
- **공수**: 2일.

### L1-3 · 품질 티어링 (무료=저가모델) [역마진 차단]
- **작업**: plan→provider 매핑. `image.py:25`의 프로바이더 선택을 plan 인자로 분기: free=`fal-ai/flux/schnell`($0.003, 이미 코딩됨 image.py:220), premium/POD=고품질(dall-e-3/gpt-image-1). plan enforcement는 `books.py:99 _enforce_free_plan_*`에 이미 존재 → 재사용. 포토캐릭터(gpt-4o 비전)는 premium 게이트.
- **파일**: `apps/api/src/services/image.py`(plan 분기), `apps/api/src/services/orchestrator.py`(plan 전달), `apps/api/src/routers/books.py`(plan 주입).
- **수용기준**: free 유저 생성 → Flux Schnell 호출. premium → dall-e-3. `test_image.py`에 plan별 프로바이더 케이스 2개.
- **공수**: 1일. **원가 가정 30배 오류(권당 $0.72→$0.003) 교정 = 생존 조건.**

---

## SPRINT L2 — 교육 증거 + 출시 (5-6일) "부모가 돈 내는 유일한 이유"

### L2-1 · 학습 측정 켜기 (answers 테이블 + 부모 성장카드) [잠긴 80% 자산 활성화]
- **작업**: (a) `answers` 테이블 1개 신설(`book_id, profile_id, page, question_id, correct, answered_at`). (b) 퀴즈 응답 기록 엔드포인트. (c) `streak.py:586 get_reading_report`의 `learning_progress`를 `completion_rate` 하나에서 → '이번 주 익힌 단어 N · 독해 정답률 % · 추정 읽기레벨'로 확장(orchestrator가 이미 JSONB로 쌓는 vocab/comprehension/quiz 활용). (d) `parent_dashboard_screen.dart`에 성장카드 1개 추가(신규 화면 0).
- **파일**: `apps/api/src/models/db.py`(`Answer`), 마이그레이션, `apps/api/src/routers/`(응답기록·리포트), `apps/api/src/services/streak.py:487-589`(리포트 확장), `apps/mobile/lib/screens/parent_dashboard_screen.dart`(카드).
- **수용기준**: 퀴즈 응답 → answers 기록 → 대시보드에 주간 단어수·정답률 표시. `test_streak.py` 리포트 케이스 갱신.
- **공수**: 2.5일. **RevenueCat: 부모 진척 리포트 = 구독유지 2-3배. 한국 부모 교육 증거 지갑 최강.**

### L2-2 · 카카오 성장카드 공유 [CAC≈0 바이럴]
- **작업**: 주간 성장카드를 이미지로 렌더 → 카카오 공유(`KAKAO_NATIVE_APP_KEY` 필요 — 유일 외부키). "우리 아이 이번 주 단어 12개 익힘" 카드.
- **파일**: `apps/mobile/lib/screens/parent_dashboard_screen.dart`, `apps/mobile/lib/core/share.dart`(신규).
- **수용기준**: 공유 버튼 → 카카오톡 카드 전송. 딥링크로 앱 설치 유입.
- **공수**: 1일 (카카오키 발급 후).

### L2-3 · 미실현 수익원 상수 추가 + 가격 앵커 [저난도 잔여]
- **작업**: `credits.py:16 SUBSCRIPTION_PLANS`에 family(₩19,900 디코이) 추가 + 크레딧팩 product 매핑. Basic ₩6,900→₩8,900 소폭 인상(한국 키즈 하단 탈출). IAP product ID 매핑(`iap_verifier.py`).
- **파일**: `apps/api/src/services/credits.py`(상수 3줄), `apps/api/src/services/iap_verifier.py`(product 매핑), `apps/mobile`(가격 표시).
- **수용기준**: 3티어(₩8,900/₩14,900/₩19,900) 앵커 노출. IAP 검증 product 인식.
- **공수**: 0.5일.

### L2-4 · 실 API E2E 스모크 + 스토어 제출 [최종]
- **작업**: `.env` Mock→실키 주입(`FINAL_USER_INPUT_REQUIRED.md` 목록), 1권 실생성 E2E 1회, Sandbox 결제 1회, 스토어 빌드 제출. **출시 1형상**: 사진→캐릭터·POD·분기·학교B2B OFF, '잠자리 한 권→낭독→완독 스트릭→주간 성장카드 공유' 단일 좁은 루프.
- **파일**: `.env`, `docs/DEPLOYMENT.md`.
- **수용기준**: 실 API로 1권 생성·낭독·완독·리포트 동작. 맘카페 100명 한국 소프트런칭.
- **공수**: 1일 (+ 스토어 리뷰 대기). **유료광고는 W4 리텐션·LTV>3×CAC 증명 전까지 금지.**

---

## 출시 후 백로그 (데이터로 결정, 우선순위만)
- **북극성 교체**: D30>40%(20배 환상) → **W4 리텐션 + 아이당 주간 완독 수 + 스트릭 길이**(교육은 episodic, 일간 리텐션 구조적으로 낮음).
- **포지셔닝**: Gemini Storybook(무료·무제한)을 *깔때기 상단*으로 — "Gemini는 장난감 책 1권, 우리는 한국어 읽기 *습관·성장 기록*". 종단 데이터에만 과금.
- **B2B 재정의**: 공교육 학교(붕괴, 채택 37%→19%) 대신 **독서학원 원장 1명**(B2B2C, 다자녀=학급/시리즈=커리큘럼, 코드 이미 지원).
- **출력 모더레이션**: substring 블랙리스트(orchestrator.py:586) → 이미지 검수 추가.
- **연간 vs 주간 플랜**: episodic 제품 → 주간/월간 갱신이 연간보다 유리할 수 있음. 데이터로 결정.

## 기술부채·스케일
- **브랜치 머지**: 작업 정본은 `codex/p0-p4-autonomous-20260221-1259`(main +3커밋, 미머지). 출시 전 main 머지 + 태그.
- **Celery Beat 신규 프로세스**: L0-1/L1-1이 beat 의존 → 배포 토폴로지 변경(worker + beat 분리). `DEPLOYMENT.md` 갱신 필수.
- **마이그레이션 4건 신규**: `last_refill_at`(L0-1), `reference_image_url`(L1-2), `answers` 테이블(L2-1) — 순서 의존성 주의.
- **S3 사진 고아 바이트**: 사진→캐릭터 OFF로 출시 시 회피, 재개 시 삭제 캐스케이드 필요.

## 일정 요약 (1인+AI코딩)
- **주 1 (L0)**: 4-5일 — 매출누수·측정·습관·동의. **진짜 출시 게이트.**
- **주 2 (L1)**: 5-6일 — 오늘동화 공유·캐릭터 일관성·티어링. **최고 ROI 클러스터.**
- **주 3 (L2)**: 5-6일 — 학습 증거·카카오 공유·가격·실API·제출.

**총 ~3주.** "무제한 AI 동화 생성기"(Gemini 무료에 패배)가 아니라 **"내 아이 한국어 읽기 성장이 눈에 쌓이는 부모용 동반자"** — 신규 빌드 아닌 *재배선*이라 지금 가능.

**검증 핵심 파일**: `apps/api/src/worker.py:21` · `services/credits.py:16,239` · `services/streak.py:399,445,586` · `models/db.py:184` · `core/config.py:50-52` · `services/image.py:210` · `routers/users.py:76` · `core/dependencies.py` · `apps/mobile/pubspec.yaml` · `lib/core/app_telemetry.dart`