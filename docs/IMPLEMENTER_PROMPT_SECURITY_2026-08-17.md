# 구현자 핸드오프 — 2026-08-17 보안 감사 반송분 (원샷)

> 감사 정본: `docs/SECURITY_AUDIT_2026-08-17.md` (판정 ❌ 출시 차단, Critical 1 + High 9).
> 이 문서 하나를 구현자에게 그대로 주면 된다. 각 티켓의 전체 맥락은 감사 리포트에서 확인한다.

현재 `/Users/jmac/Desktop/ai-story-book` 저장소(HEAD `71c3adb`, 워킹 트리 clean에서 시작)에서
2026-08-17 CTO 보안 감사 반송분을 원샷으로 수정하라. 아래 스코프는 CTO가 확정한 것이다.
스코프 임의 축소·확대 금지. 발견한 스코프 밖 결함은 수정하지 말고 보고서에 별도 섹션으로.

---

## 0. 절대 규칙
- `.env`·secrets 접근 금지, 비밀정보 출력 금지 (`.env.example`은 허용).
- 커밋·푸시 금지. 완료 시 전부 `git add`(staged)까지만. 커밋은 CTO 감사 후.
- API 표면 변경 시 `packages/shared/schema/openapi.json` 재export 동반(diff 검증).
- 신규 사용자 노출 문자열은 ko/en/ja 3개 `.arb` 동시 + `flutter gen-l10n`. 봉투 에러코드는
  UPPER_SNAKE + `core/errors.py` 정본 경유(라우터에서 HTTPException 봉투 수제 금지).
- 최소 변경. 각 수정에 **red-proof**(수정을 되돌리면 어느 테스트가 FAIL하는지, 원복 diff 0)를
  반드시 첨부. "완료"는 게이트 green + red-proof가 있을 때만. 못 한 것은 못 했다고 쓴다.
- **아동 PII·FK·파기 경로는 SQLite 테스트가 FK-off로 구조적으로 못 잡는다**(`data_deletion.py`
  독스트링). 이 클래스는 반드시 **실 PostgreSQL FK 위반 재현 게이트**로 검증하라.
- false-green 금지: 헬퍼 단위테스트 ≠ 엔드포인트 검증, HTTP 200 ≠ 잡 완주/실제 파기.

---

## R0 (🔴 출시 절대 차단): iOS 결제 전량 파손
현상: `in_app_purchase_storekit 0.4.8`은 iOS 15+에서 StoreKit2가 기본(CHANGELOG:59)이고 앱에
비활성화 코드가 없다 → `purchase.verificationData.serverVerificationData`가 base64 앱 영수증이
아니라 **JWS**다. `credits_screen.dart:800`이 그 JWS를 `receipt_data`로 보내고, 백엔드
`iap_verifier.py:94`가 legacy `/verifyReceipt`로 포워드 → Apple 21002(malformed) → strict 예외 →
크레딧 미지급. 결제는 OS가 이미 캡처 → **과금됨, 트랜잭션 pending 영구 정체**.

- **R0-1 (즉시 언블록, 권장)**: 앱 시작 시 StoreKit1을 강제한다. 플러그인 0.4.8의
  `InAppPurchaseStoreKitPlatformAddition.enableStoreKit1()`을 iOS IAP 초기화 전에 호출(`iap_service.dart`
  초기화 또는 앱 부트, `Platform.isIOS` 가드, `getPlatformAddition`로 애드온 획득). 이러면
  `serverVerificationData`가 legacy 영수증으로 복귀해 **백엔드 무변경으로 즉시 정합**. 미지원(iOS<15) 분기 처리.
- **R0-2 (동반 필수, `credits_screen.dart:777`)**: `purchaseID` 부재 시 시간기반 가짜 `transaction_id`
  생성 제거 — 멱등성 파괴(Apple 영구 검증실패·Google 이중지급 여지). purchaseID 없으면 검증을
  진행하지 말고 pending 유지(다음 실행 재전달로 재시도).
- **R0-3 (전략적 후속, 설계만)**: 백엔드를 App Store Server API + JWS 서명 검증(Apple 공개키로
  signed transaction 검증)으로 이관하는 설계를 보고서에 1개 단락으로 남겨라(verifyReceipt는 Apple이
  sunset 중). 이번엔 R0-1로 언블록, 후속 티켓 명시.

검수: 단위(iOS SK1 초기화 애드온 호출 스파이, R0-2 가짜 id 미생성). **관통 증거는 실기기 샌드박스가
유일** — 진행 중인 최종 E2E(실키)와 병합해 "iOS 샌드박스 결제 → 서버 검증 성공 → 크레딧 지급"을
실기기로 관통 확인. 단위만 통과=미완, "완료"로 보고 금지.

---

## R1 (🟠 아동 PII 파기권 — PIPA/COPPA 직결)
공통: 파기(스토리지 delete)는 반드시 로컬 커밋 성공 **후**로. 외부 부작용 먼저→로컬 커밋 나중(orphan)
금지. unknown 파기 결과를 success로 위장 금지(H8 계약: 실패키 표면화).

- **R1-1 (H1, `consent.py` revoke ~207)**: 캐릭터 삭제가 Series FK를 nullify하지 않아 Postgres commit이
  IntegrityError 500 → 철회 영구 차단. 단건 삭제 경로(`characters.py:546` H7)가 이미 하는
  `update(Series).where(Series.character_id==id).values(character_id=None)`를 철회 경로에도 적용(`Series`
  import 추가). `character_ids`(JSON) 참조 책도 정리. `delete_prefix`를 commit 성공 **후**로 이동
  (현재 commit 전이라 첫 실패 시 아동 사진 이미 파괴).
- **R1-2 (H2, `consent.py:179-181`)**: 철회 시 삭제 대상 책 수집이 `Book.character_id`(스칼라)만 봐서
  `character_ids`(다중 캐릭터 가족책) 참조 책을 놓침 → 아동 얼굴 렌더 잔존. `character_ids` 배열 포함
  책도 수집 대상에 편입.
- **R1-3 (H8, `characters.py:712`)**: from-photo/from-drawing이 아동 사진을 DB 커밋 전 S3 업로드 →
  실패 시 고아(행 없어 URL 역산 불가=파기 불가). 로컬 fail-closed 레코드 선기록 또는 커밋 성공 후
  업로드로 재정렬. 실패 경로에서 업로드분 정리.
- **R1-4 (M7, `consent.py:189`)**: 철회가 `jobs`·`story_drafts`·`image_prompts`(아동 얼굴 텍스트 묘사·이름)를
  DB에 잔존. 철회 cascade에 이 파생 텍스트 파기 포함.
- **R1-5 (M8, `users.py:95`)**: 계정삭제·철회 스토리지 파기가 커밋 후 in-memory 키에만 의존 → 중단 시
  영구 고아 + 재시도 success 위장. durable 파기 레코드(outbox/파기 대기 테이블) 또는 재구동 시 재파기
  가능한 멱등 경로. 파기 미완을 success로 응답하지 않음.
- **R1-6 (M9, `consent.py:91`)**: `photos=false` 재-grant가 기수집 아동 사진·파생물 미파기 → 철회
  의미론 이원화. 항목 해제 시에도 해당 데이터 파기(revoke와 동일 경로 재사용). **규범 결정 필요**
  (즉시 파기 vs 유예)이면 코드로 조용히 정하지 말고 보고서 질문으로.
- **R1-7 (동반 Low)**: `consent.py:60` photos-only 동의행(granted=false)이 사진 게이트 통과 → 게이트에
  granted 결합. `library.py:222` 단건삭제가 파기 실패를 무조건 success 응답(H8 계약 적용).
  `voice_profiles.py:244` PATCH 파기 순서 버그(교체 전 샘플 잔존). `orchestrator.py:1377` 동시 재생성
  fence 없는 `image_url` write-back 고아.

테스트: **실 PostgreSQL FK 게이트 필수** — 사진동의→from-photo→series→revoke가 500 없이 완주하고
캐릭터·책·이미지·파생텍스트가 실제 파기됨을 실PG로 검증. red-proof: Series nullify를 되돌리면 실PG에서
IntegrityError로 FAIL. 다중캐릭터 책 파기(R1-2)도 실PG 재현.

---

## R2 (🟠 결제 정합)
- **R2-1 (H3, `iap.py:287` + `credits.py:401`)**: cancelled 구독 재활성 경로 부재. `already_subscribed`
  가드를 `status=='active'`로 한정(get_active_subscription의 cancelled 포함이 verify 경로를 삼킴).
  cancelled + 신규 검증 결제는 재활성(기존 cancelled 종료 후 create_subscription). 웹훅 `_STATUS_RANK`에서
  cancelled를 'active' 통지로 복귀 가능하게(터미널 refunded/expired만 sticky).
- **R2-2 (M2, `credits.py:343`)**: clawback이 트랜잭션 밖 check-then-write. refund/purchase는 부분 유니크
  인덱스가 있으나 **clawback 타입은 없다**(alembic `f6a1b2c3d4e5` 확인). expand-then-contract 마이그레이션으로
  `uq_credit_transactions_clawback`(reference_id, WHERE transaction_type='clawback') 부분 유니크 추가 +
  clawback을 refund_for_job과 동일 멱등 패턴으로. 실PG 리허설로 중복 차단 확인.
- **R2-3 (M3, `iap.py:469`)**: 구독 환불 clawback이 '실지급액' 아닌 플랜 고정액 회수 → 0지급
  영수증(restored/already_subscribed) 환불 시 무고한 크레딧 차감. 회수액을 '이 영수증이 실제 지급한
  액수'(credit_transactions 원장 참조)로 연동. 0지급이면 0회수.
- **R2-4 (M4, `iap_verifier.py:388`)**: Google `purchaseType=0`(라이선스/테스트 구매)이 운영에서 무결제
  지급 → Apple sandbox 차단과 비대칭. 운영(strict)에서 purchaseType=0을 fail-closed 거부(Apple 21007과
  대칭). 테스트 훅은 ENABLE_TEST_HOOKS 게이트로만.
- **R2-5 (M5, `iap_verifier.py:149`)**: Apple 영수증 bundle_id를 추출만·미검증 → master shared secret 하
  타 앱 영수증 수용. 기대 bundle_id(config)와 대조해 불일치 시 거부.
- **R2-6 (동반 Low)**: `iap.py:71` `_subscription_expired`가 expires_date_ms 부재를 '만료 아님'으로 처리 →
  구독 항목은 필드 필수로 강제. `iap_verifier.py:395` Google orderId 부재 시 매칭 스킵 → 리플레이 dedup
  무력화(orderId 부재 거부/대체 식별자). `iap.py:554` verify/웹훅 인터리브 orphan 이벤트 → 스윕/재적용.

테스트: 취소→재결제 재활성 통합테스트(H3). clawback 동시 중복 실PG로 이중회수 0(M2 red-proof: 인덱스
제거하면 이중 INSERT). Google purchaseType=0 운영 거부 단위(M4).

---

## R3 (🟠 비용 DoS 가드레일)
- **R3-1 (H4, `config.py:130` + 배포)**: 전역 일일 예산(`daily_generation_budget`)이 기본 0=비활성 +
  `docker-compose.prod.yml`·`.env.example` 미배선 → 직전 감사가 '출시 필수'로 승격한 완화책이 실제로
  꺼져 있음. `.env.example`·docker-compose.prod에 env 배선 추가(**기본값 산정은 오너 결정** — 실측 트래픽
  기준, 보고서에 질문). readiness가 프로덕션에서 0/미설정 시 경고.
- **R3-2 (H5, `books.py:1147` retell / `characters.py:671` 비전 / `books.py:739` 커버리지)**: retell·비전
  캐릭터·regenerate·inpaint가 크레딧·전역예산 미계량 유료 LLM 경로. 실비용 발생 엔드포인트 전수에
  `consume_daily_generation_budget`(+크레딧 정책) 적용. "한도 검사 엔드포인트별 전수" 구조 불변식 테스트.
- **R3-3 (M10, `books.py:458`)**: 전역 예산이 요청검증·멱등·동의·소유권 검증 **전**에 소진
  (consume-before-validate) → 비용0 무효요청 스팸으로 전 사용자 429. 예산 consume을 모든 선검증 통과 **후**
  (실제 비용 발생 직전)로 이동.
- **R3-4 (M11, `books.py:492`)**: `max_pending_jobs`가 전 사용자 합산 전역 카운터 → 큐 100건으로 전 사용자
  503. per-user 상한과 전역 상한 분리(전역은 훨씬 크게) 또는 per-user 큐 한도.
- **R3-5 (M12, `orchestrator.py:482`)**: 생성 잡 실패 시 S3 영속 이미지가 추적불가 고아. 잡-이미지 키를
  잡 레코드에 기록해 실패·삭제 시 파기 도달 가능하게.

---

## R4 (🟠 인프라 + ⚪ 자세 — 배치 처리)
- **H9 (`nginx.conf:57`)**: 프로덕션 TLS 종단(cert 자동화)+HSTS+HTTP→HTTPS 리다이렉트 배선 +
  DEPLOYMENT.md 절차. **배포 인프라라 오너 실환경과 병행** — 코드/설정 배선까지, 실제 인증서는 오너.
- **M1 (`user_service.dart:13`)**: X-User-Key를 `flutter_secure_storage`(iOS Keychain/Android Keystore)로
  이관 + 기존 SharedPreferences 평문값 마이그레이션(감지→이관→평문 삭제) + Android allowBackup 백업 제외.
- **M6 (`Dockerfile:64`)**: uvicorn CMD에 `--no-access-log` 추가(앱 AccessLogMiddleware가 마스킹된 액세스로그
  이미 발행). 라이브 컨테이너 로그에 `/share/<hex32>` 0건 게이트.
- **`exceptions.py:331`**: 예외 핸들러 5곳이 `_redact_path` 우회 → path 원문 로깅. 전 로깅 경로에 `_redact_path` 적용.
- **`parental_control_service.dart:71`**: 부모 게이트를 두 자리 덧셈에서 강화(생년 4자리 등 아동이 못 푸는 것)
  + 통과 세션을 기기시계 되돌림에 견고하게. `settings_screen.dart:570` 스크린타임 한도 변경도 부모 게이트 뒤로.
- **`pronunciation.py:97` / `voice_profiles.py:176`**: book_id·sample_audio_url 소유권/prefix 검증 추가
  (형제 경로 `assert_book_not_foreign` / storage prefix 소속 검증). IDOR 봉인.
- **`storage.py:131`**: `key_from_public_url`이 현재 prefix만 인식 → 과거 도메인 prefix 목록도 인식(파기 no-op 방지).

---

## 스코프 밖 (건드리지 말 것)
- Deferred(제품결정): 광고보상 서버검증·POD 수금·IAP 웹훅 스토어 어댑터·출력 이미지 모더레이션·
  IAP 웹훅 JWS/RTDN 서명(R0-3과 함께 후속 설계). 수용리스크 4종(공개URL·rate-limit fail-open·Swagger·str(e))은
  악화 없음 — 손대지 말 것.
- 규범 결정 필요 지점(R1-6 철회 파기 시점, R3-1 예산 값)은 코드로 조용히 정하지 말고 보고서 질문 섹션으로.

---

## 완료 게이트 (전부 green이어야 "완료")
1. `cd apps/api && venv/bin/python -m pytest tests/` (전체, 회귀 0)
2. `venv/bin/ruff check src/`
3. C1 워커 게이트: `E2E_PG_DATABASE_URL`/`E2E_REDIS_URL`/`E2E_S3_*` 설정 후 `pytest tests/test_celery_worker_pg.py` (skip 아님)
4. **실 PostgreSQL FK 게이트**: R1(철회 cascade)·R2-2(clawback 유니크)를 실PG로 재현(SQLite로는 못 잡는 클래스 — 신규 테스트가 실PG 없으면 skip 구조).
5. `cd apps/mobile && flutter analyze && flutter test` (회귀 0)
6. `openapi.json` 재export diff 검증(API 표면 변경분 반영).
7. iOS 실기기 샌드박스 IAP 관통(R0) — 최종 E2E와 병합, 실기기 증거.

---

## 보고서 양식
`docs/FIX_WAVE_SECURITY_2026-08-17.md`:
- 티켓별: 증상 → 수정(file:line) → red-proof(무엇을 되돌리면 어느 테스트가 어떻게 FAIL, 원복 diff 0) →
  증거(게이트 출력·실PG 재현 로그)
- 게이트 결과표(수치 명기), 정직 보고 섹션(못 한 것·스킵·스코프밖 발견), 규범 결정 질문(R1-6·R3-1) 별도 정리.
- 전부 staged, 커밋 금지. CTO가 감사(직접 red-proof 재현) 후 커밋·푸시한다.
