# 수정 웨이브 — 2026-08-17 보안 감사 반송분

> 지시서: `docs/IMPLEMENTER_PROMPT_SECURITY_2026-08-17.md` · 감사 정본: `docs/SECURITY_AUDIT_2026-08-17.md`
> 기준 HEAD `71c3adb`. **61파일 staged, 커밋 없음** — CTO 감사(직접 red-proof 재현) 후 커밋·푸시.
> CTO 판정·결정사항 요약: `docs/CTO_REPORT_SECURITY_WAVE_2026-08-17.md`

## 요약

| 웨이브 | 티켓 | 상태 |
|--------|------|------|
| R0 | C1(iOS 결제 파손) + 멱등성 동반 + 후속 설계 | 코드 완료 · **실기기 관통 미실행**(오너) |
| R1 | H1·H2·H8·M7·M8·M9 + 동반 Low 4 | ✅ 완료 (실PG 게이트 6/6) |
| R2 | H3·M2·M3·M4·M5 + 동반 Low 3 | ✅ 완료 |
| R3 | H4·H5·M10·M11·M12 | ✅ 완료 (H4 **값 주입은 오너 결정** — §질문) |
| R4 | H9·M1·M6 + 자세 5 | ✅ 완료 (실 인증서 발급은 오너) |
| **R5** | **H6·H7** (지시서 누락분 — CTO 지시로 추가) | ✅ 완료 |

**게이트**

| # | 게이트 | 결과 |
|---|--------|------|
| 1 | `venv/bin/python -m pytest tests/` | **791 passed, 10 skipped, 0 failed** (기준 744 → +47) |
| 2 | `venv/bin/ruff check src/` | All checks passed |
| 3 | C1 워커 게이트 (실PG+Redis+MinIO) | **4 passed** (skip 아님) |
| 4 | 실 PostgreSQL FK 게이트 (신규) | **6 passed** (`E2E_PG_DATABASE_URL` 없으면 skip 구조) |
| 5 | `flutter analyze` / `flutter test` | No issues found / **289 passed** (기준 270 → +19) |
| 6 | `openapi.json` 재export diff | 독스트링만 — **API 표면 변경 없음** |
| 7 | iOS 실기기 샌드박스 IAP 관통 | ❌ **미실행** (§정직 보고) |
| — | alembic 단일 head | `b1c2d3e4f5a6` · 실PG downgrade→upgrade 왕복 검증 |
| — | 실PG FK 게이트 **CI 배선** | `ci.yml` 스텝 추가 + 정적 가드 3건(존재·env·순서) |

red-proof는 **29건 전부 실측**했다(수정 되돌림 → 지정 테스트 FAIL → 원복 diff 0 확인).

---

# R0 (🔴 출시 절대 차단) — iOS 결제 전량 파손

## R0-1 · iOS StoreKit1 강제

**증상.** `in_app_purchase_storekit` 0.4.8은 "StoreKit 2 is now the default for all devices
that support it"(CHANGELOG:59)이고 앱에 비활성 코드가 없었다(전역 grep 0건). → iOS 15+에서
`purchase.verificationData.serverVerificationData` 가 base64 앱 영수증이 아니라 **JWS**다.
`credits_screen.dart:800` 이 그 JWS를 `receipt_data` 로 보내고 `iap_verifier.py:94` 가 legacy
`/verifyReceipt` 로 포워드 → Apple 21002(malformed) → strict 예외 → 크레딧 미지급.
결제는 OS가 이미 캡처했고 앱은 검증 성공 후에만 finish 하므로 **과금된 채 pending 영구 정체**.

**수정.**
- `apps/mobile/lib/services/iap_platform_init.dart` (신규) — `IapPlatformInit.ensureStoreKit1()`
- `apps/mobile/lib/main.dart:52` — `runApp` 전, **SharedPreferences 초기화보다도 먼저** 호출
- `apps/mobile/pubspec.yaml:64` — `in_app_purchase_storekit: ^0.4.8` 직접 의존(lockfile 일치)

**지시서 정정 1건.** 지시서는 `InAppPurchaseStoreKitPlatformAddition.enableStoreKit1()` 이라고
썼는데, 0.4.8의 실제 API는 **`InAppPurchaseStoreKitPlatform.enableStoreKit1()` (static)** 이다
(`in_app_purchase_storekit_platform.dart:373`). 애드온에는 그 메서드가 없다.

**순서가 load-bearing.** 플러그인 등록은 `InAppPurchase.instance` **첫 접근**에서 일어나고
(`in_app_purchase.dart:34-42`), 등록 시점의 `_useStoreKit2` 플래그로 SK1/SK2 옵저버가 정해진다.
늦게 호출하면 무효다 — 그래서 `main.dart` 호출 위치 자체를 테스트로 봉인했다.

**red-proof.** `main.dart` 의 `await IapPlatformInit.ensureStoreKit1();` 제거
→ `security_wave_20260817_test.dart :: main.dart 가 SharedPreferences/IAP 접근 전에 강제한다` FAIL
(실측: `+9 -1`, 원복 후 289 passed).

## R0-2 · 가짜 transaction_id 제거 (멱등성)

**증상.** `credits_screen.dart:777` 이 `purchase.purchaseID ?? '${productID}-${now.ms}'` 로
시간 기반 가짜 id를 만들었다. 재시도마다 값이 달라져 Apple은 영구 검증 실패, Google은 서버
dedup 키가 매번 달라져 **이중 지급** 여지.

**수정 (`credits_screen.dart:777-786`).** id가 없거나 빈 문자열이면 검증을 **진행하지 않고**
pending 유지(다음 실행 purchaseStream 재전달로 재시도). `completePurchase` 도 호출하지 않는다
— 호출하면 미지급 상태로 대금이 영구 유실된다.

**red-proof.** 옛 `??` 폴백 복원 → `iap_purchase_flow_test.dart :: R0-2 purchaseID 부재…` 에서
`verifyCalls == 0` 기대가 깨져 FAIL.

## R0-3 · 후속 설계 (이번 스코프 아님, 티켓화 필요)

Apple은 legacy `verifyReceipt` 를 sunset 중이고, R0-1은 그 위에 얹은 **임시책**이다. 정공법은
백엔드를 **App Store Server API + JWS 서명 검증**으로 이관하는 것이다: 앱은 SK2의 signed
transaction(JWS)을 그대로 올리고, 서버는 Apple의 공개키(`/inApps/v1/notifications` 계열이 쓰는
X.509 체인)로 JWS 헤더의 인증서 체인을 Apple Root CA까지 검증한 뒤 payload의
`transactionId`·`productId`·`bundleId`·`expiresDate`·`environment` 를 신뢰한다. 현행 코드의
검증 결과 구조체(`IAPVerificationResult`)와 라우터 계약(`store_transaction_id` 정본 dedup,
`_subscription_expired` 가드, M5 bundle_id 대조)은 그대로 재사용 가능하므로, 교체 범위는
`iap_verifier._verify_apple` 한 함수와 앱의 `receipt_data` → `signed_transaction` 필드명뿐이다.
Google도 동일하게 RTDN signed payload 검증으로 맞추면 웹훅 서명 미검증(Deferred 항목)까지 함께
닫힌다. **이 이관 전에는 SK1 강제를 제거하면 안 된다.**

---

# R1 (🟠 아동 PII 파기권 — PIPA/COPPA)

공통 계약을 하나로 모았다: `consent.py :: purge_photo_derived_data()` — 철회와 '사진 동의 해제'가
**같은 경로**를 쓴다(두 벌 규칙이면 한 쪽이 샌다). 순서: ① Series FK 해제 → ② 키 수집 →
③ durable outbox 적재 → ④ 커밋 → ⑤ 커밋 성공 **후** 스토리지 파기.

## R1-1 (H1) · 철회 경로 Series FK 위반 500

**증상.** 단건 삭제(`characters.py:546`)는 `update(Series).values(character_id=None)` 를 하는데
철회 경로는 `Series` import조차 없이 `db.delete(character)` 만 했다. `Series.character_id` 는
ondelete 없는 하드 FK라 Postgres commit이 IntegrityError → **500, 매 재시도 동일 = 철회 영구 차단**.
악화: `delete_prefix` 가 commit **전**이라 첫 시도에서 아동 원본 사진은 이미 파괴됐는데 DB엔
동의가 active로 남았다.

**수정.** `data_deletion.py :: detach_series_from_characters()` (신규 공용 헬퍼) ·
`consent.py:221` 에서 캐릭터 삭제 전 호출 · 스토리지 파기를 커밋 **후**로 이동(§R1-5 outbox 경유).

**red-proof (실PG).** `detach_series_from_characters(...)` 제거 →
`test_pg_fk_erasure.py::test_revoke_with_series_completes_on_real_postgres` 가
`asyncpg.exceptions.ForeignKeyViolationError: update or delete on table "characters" violates
foreign key constraint "series_character_id_fkey" on table "series"` 로 FAIL.
**SQLite 스위트는 이 상태에서도 green** — 게이트가 실PG여야만 하는 이유의 실증.

## R1-2 (H2) · 다중 캐릭터 책 미파기

**증상.** `consent.py:179-181` 이 `Book.character_id`(스칼라 FK)만 봐서 `character_ids`(JSON 배열,
가족 다중) 참조 책을 놓쳤다 → 그 책들의 표지·페이지(아동 얼굴 렌더)가 잔존.

**수정.** `data_deletion.py :: collect_books_referencing_characters()` — 스칼라 FK + JSON 배열
양쪽 수집. JSON 배열 비교는 방언마다 문법이 달라 이식성이 없으므로 사용자 범위(작은 집합)를 읽어
파이썬에서 교집합 판정.

**red-proof (실PG).** JSON 배열 스캔 제거 →
`test_revoke_purges_multi_character_books_on_real_postgres` FAIL(book_b 잔존).

## R1-3 (H8) · from-photo/from-drawing 고아 아동 사진

**증상.** `characters.py:712` 가 아동 사진을 S3 업로드(외부 부작용) **후** DTO 검증·DB insert를
했다 → 검증 실패·DB 오류·멱등 race 패자에서 **캐릭터 행 없는 고아 사진**이 남고, 행이 없어
URL 역산이 불가능하므로 계정삭제·동의철회 어떤 경로로도 파기되지 않았다.

**수정 (`characters.py:712-727`, `:836-846`).** 업로드 **전에** fail-closed 파기 지시를 커밋해 두고
(선기록), 캐릭터가 실제로 살아남는 **바로 그 커밋**에서 `cancel_purge_task()` 로 취소한다.
별도 커밋으로 취소하면 그 사이 창에서 스윕이 **살아있는** 사진을 지운다 — 그래서 같은 트랜잭션이다.
스윕에는 `UNATTEMPTED_GRACE_SECONDS=15분` 유예를 둬(인라인 실행 이력이 없는 지시만) 진행 중 업로드
오파기를 막았다.

**red-proof.** 선기록 제거 →
`test_security_wave_20260817.py::test_orphan_guard_survives_failed_character_creation` FAIL.
반대 방향도 봉인(`test_orphan_guard_cancelled_on_successful_creation` — 성공 시 status='cancelled').

## R1-4 (M7) · 파생 텍스트 잔존

**증상.** `consent.py:189` 철회가 `jobs`·`story_drafts`·`image_prompts`(아동 얼굴 텍스트 묘사·이름)를
DB에 남겼다.

**수정.** `data_deletion.py :: collect_book_job_ids()` + `purge_job_artifacts()`, `consent.py:218,226`.

**🔎 실PG 게이트가 내 구현 버그를 잡았다.** 처음엔 `purge_book_generation_artifacts(db, book_ids)` 가
책 삭제 **후** `Book.job_id` 를 읽게 짜서 job_ids가 항상 비었다(= 조용한 no-op). SQLite 스위트에는
이 경로 테스트가 없어 통과했고, 실PG 게이트 첫 실행이 `assert [(37,), (38,)] == []` 로 잡았다.
→ 수집을 책 삭제 **전**으로 분리(`collect_book_job_ids`).

**red-proof (실PG).** `purge_job_artifacts(db, job_ids)` 제거 →
`test_revoke_purges_derived_text_on_real_postgres` FAIL.

## R1-5 (M8) · durable 파기 레코드

**증상.** `users.py:95` 계정삭제·철회의 스토리지 파기가 **커밋 후 in-memory 키**에만 의존 → 중단 시
영구 고아 + 재시도가 success 위장(unknown 결과 ≠ 성공).

**수정.**
- `models/db.py :: StoragePurgeTask` (신규 테이블, outbox) + 마이그레이션 `b1c2d3e4f5a6`
- `services/purge_queue.py` (신규): `enqueue_purge_keys/-prefix` · `run_purge_tasks` ·
  `sweep_pending_purges` · `cancel_purge_task`
- `job_monitor.py:80` — 모니터 루프에 스윕 배선(없으면 '기록만 되고 영원히 실행 안 되는 장부')
- 배선 지점: `users.py`(계정삭제) · `consent.py`(철회·동의해제) · `library.py`(단건삭제) ·
  `orchestrator.py`(실패 잡 이미지, §R3-5) · `characters.py`(고아 가드, §R1-3)
- 응답: 남은 실패가 있으면 `status="partial"` + `purge_retry_pending: true`

**red-proof.** ① outbox 적재 제거 → `test_revoke_writes_durable_purge_tasks_on_real_postgres` FAIL.
② `run_purge_tasks` 가 실패를 'done'으로 종결하게 변경 →
`test_purge_sweep_retries_interrupted_purge` FAIL(스윕이 대상을 못 찾음).

## R1-6 (M9) · photos=false 재-grant 파기

**수정 (`consent.py:107-110, 133`).** 재-grant가 사진 동의를 **해제**하면 철회와 동일 경로
(`purge_photo_derived_data`)로 파기. 판정은 새 행 기록 **전**에 한다(기존 활성 행 기준).

> ⚠ 규범 결정 필요 — §질문 Q1(즉시 파기 vs 유예). 현재는 **즉시 파기**로 구현했다.

**red-proof (실PG).** `if photos_revoked:` → `if False:` →
`test_photos_off_regrant_purges_on_real_postgres` FAIL.

## R1-7 (동반 Low) 4건

| 항목 | 수정 | red-proof |
|------|------|-----------|
| `core/consent.py:60` photos-only 게이트 통과 | `_has_active_photo_consent` 에 `granted` 결합 — photos는 필수 동의의 **하위 항목**이지 대체재가 아니다 | granted 결합 제거 → `test_photos_only_consent_does_not_open_photo_gate` FAIL |
| `library.py:222` 파기 실패를 무조건 success | outbox 경유 + `status="partial"`/`storage_delete_failures` 응답 | (H8 계약 — `test_data_deletion_fk.py` 실경계 스파이로 커버) |
| `voice_profiles.py:244` PATCH 파기 순서 | `previous_sample_url` 을 setattr 루프 **전**에 캡처. 예전엔 루프 뒤라 URL 교체+철회가 같은 요청에 오면 **새 파일을 지우고 옛 샘플을 남겼다**; 교체만 하는 요청도 옛 샘플이 영구 고아 | 캡처를 루프 뒤로 되돌림 → `test_voice_profile_patch_purges_old_sample_not_new` FAIL |
| `orchestrator.py:1377` fence 없는 write-back | `_fenced_image_update()` 조건부 UPDATE(CAS). rowcount==0이면 **내 산출물**을 고아로 인정해 파기. regenerate/inpaint 양쪽 적용 | 테스트 시임(`_RegenSession.fence_rowcount=0`)으로 패배 분기를 단일 프로세스에서 결정적 유발 |

---

# R2 (🟠 결제 정합)

## R2-1 (H3) · cancelled 구독 재활성

**증상.** `already_subscribed` 가드가 `get_active_subscription`(status ∈ {active, **cancelled**})을
써서, 잔여기간 내 cancelled 상태의 **신규 검증 결제**가 삼켜졌다 → 과금만 되고 권한 미지급.
웹훅 `_STATUS_RANK` 도 cancelled=2 sticky라 스토어의 'active' 통지가 조기 반환으로 버려졌다
(복구 수단이 수동 DB 개입뿐).

**수정.**
- `iap.py:293-300` — 가드를 `status == "active"` 로 한정
- `iap.py:342-348` — 재활성 시 `supersede_cancelled_subscription_for_plan()` 으로 잔여 cancelled 행을
  종료(entitlement 행이 둘로 갈리지 않게) 후 `create_subscription`
- `credits.py:400` — 위 헬퍼 신규
- `iap.py:397` — `_STATUS_RANK = {"refunded": 3, "expired": 3}` (터미널만 sticky) +
  `_apply_status_to_receipt` 에 `status=="active"` → cancelled 구독 복귀 분기

**red-proof.** ① `and active_subscription.status == "active"` 제거 →
`test_cancelled_subscription_is_reactivated_by_new_purchase` FAIL.
② `"cancelled": 2` 복원 → `test_active_webhook_restores_cancelled_subscription` FAIL.
반대 방향 봉인: `test_refunded_receipt_stays_sticky_against_active_webhook`(환불 부활 여전히 불가).

## R2-2 (M2) · clawback 이중 회수

**증상.** `credits.py:343` clawback이 트랜잭션 밖 check-then-write이고, refund/purchase에는 있는
부분 유니크가 **clawback에만 없었다**(alembic `f6a1b2c3d4e5` 확인).

**수정.** `models/db.py` + 마이그레이션 `b1c2d3e4f5a6` 에 `uq_credit_transactions_clawback`
(`user_key, reference_id` WHERE `transaction_type='clawback'`) 추가. `clawback_credits` 를
`refund_for_job` 과 동일 패턴으로 — SAVEPOINT(`begin_nested`)로 감싸 IntegrityError를 흡수해
호출자의 미커밋 작업(영수증 상태 갱신)을 폐기하지 않는다. pre-check에 `user_key` 조건도 추가.

**red-proof (실PG, raw SQL).** 인덱스 DROP 후 동일 `(user_key, reference_id)` clawback 2행 INSERT →
`INSERT 0 2`, `dup_rows = 2` (**이중 회수 실증**). `alembic downgrade -1 → upgrade head` 왕복 후
재실행 → `test_clawback_partial_unique_blocks_double_insert_on_real_postgres` 포함 6/6 pass.

## R2-3 (M3) · 환불 회수액을 실지급액에 연동

**증상.** `iap.py:469` 가 플랜 고정액(30)을 회수 → 0지급 영수증(restored/already_subscribed) 환불 시
무고한 사용자 크레딧 차감.

**수정.** `iap.py:426 _granted_subscription_credits()` — 이 영수증이 개설한 구독의
`credit_transactions(type='subscription', reference_id=str(subscription.id))` 합계를 상한으로.
`subscription_id` 없는 레거시 영수증은 0(미회수) — 무고한 차감보다 미회수가 낫고, 미회수는 로그로 관측된다.

**red-proof.** 고정액 30으로 되돌림 → `test_zero_grant_subscription_refund_does_not_claw_back` FAIL
(잔액 30 → 0).

## R2-4 (M4) · Google 무결제 구매 거부

**수정 (`iap_verifier.py:414`).** `purchaseType` 이 존재하면(0=라이선스 테스트, 1=프로모, 2=리워드)
운영에서 fail-closed 거부 — Apple sandbox 차단과 대칭. 테스트 훅은 `TESTING`/`ENABLE_TEST_HOOKS`.

**red-proof.** 가드 제거 → `test_google_license_test_purchase_rejected_in_production` FAIL.

## R2-5 (M5) · Apple bundle_id 검증

**수정.** `iap_verifier.py:160 _assert_apple_bundle_id()` + `config.apple_bundle_id` +
`.env.example`/`docker-compose.prod.yml` 배선. 기대값 미설정이면 검증 생략(하위호환)하되
**readiness가 `apple_bundle_id_missing` 으로 운영 배포를 막는다**(`main.py:409`) — '조용히 검증 안 함'을
남기지 않는다.

**red-proof.** 기대값 조회를 None으로 → `test_apple_bundle_id_mismatch_is_rejected` FAIL.

## R2-6 (동반 Low) 3건

| 항목 | 수정 | red-proof |
|------|------|-----------|
| `iap.py:71` 만료필드 부재 fail-open | `_subscription_expired(verification, is_subscription=True)` — 구독은 `expires_date_ms` **필수**(부재=만료). 부재는 유효함의 증거가 아니다 | `return bool(is_subscription)` → `return False` → `test_subscription_receipt_without_expiry_is_treated_as_expired` FAIL |
| `iap_verifier.py:395` orderId 부재 시 매칭 스킵 | 운영에서 거부(리플레이 dedup 정본 키 상실 방지) | 거부 제거 → `test_google_missing_order_id_is_rejected` FAIL |
| `iap.py:554` orphan 웹훅 인터리브 | **기존 `_reapply_orphan_events` 로 이미 커버됨** — 코드 확인 결과 verify/restore/already_subscribed 세 경로 모두에서 호출된다. 추가 수정 없음(§정직 보고) | — |

> ⚠ R2-6 부수효과: `_local_success`(dev/test 전용 무검증 경로)가 구독일 때 미래 만료를 채우도록
> 했다(`iap_verifier.py:508`). 안 하면 로컬 모드에서 구독이 **절대 생성되지 않는** 인위적 실패가 된다
> (운영에서는 `_local_success` 자체가 fail-closed로 막힌다).

---

# R3 (🟠 비용 DoS 가드레일)

## R3-1 (H4) · 예산 가드 배선 + 경고

**증상.** `daily_generation_budget=0`(기본) + `docker-compose.prod.yml`·`.env.example` **양쪽 미배선**
→ 직전 감사가 '출시 필수'로 승격한 완화책이 **값을 넣을 방법조차 없어서** 실제로 꺼져 있었다.

**수정.**
- `.env.example:181-191` — 값 산정 근거(권당 $0.32/$0.48, `감내 지출 ÷ 권당비용`)와 함께 배선
- `infra/docker-compose.prod.yml` — api·worker 양쪽에 `DAILY_GENERATION_BUDGET`
  (워커도 같은 Redis 카운터를 봐야 한다)
- `main.py:493-503, 526` — 프로덕션에서 0/미설정이면 `services.cost_budget: "disabled"` 노출 +
  readiness 프로브마다 **error 로그**. `warnings: ["cost_budget_disabled"]` 는 인증된 detailed에만
- `docs/DEPLOYMENT.md` — "Cost guardrail (H4)" 절 + Production safety rules 항목

**차단이 아니라 경고인 이유.** 지시서가 "경고"로 명시했고, 미설정만으로 503을 내면 기존 배포가
즉시 멈춘다. **값 산정은 오너 결정 → §질문 Q2.**

**red-proof.** cost_budget 판정 제거 → `test_readiness_reports_cost_budget_disabled_in_production` FAIL.

## R3-2 (H5) · 실비용 엔드포인트 전수 계량

**증상.** `create_book` 한 곳만 예산을 소비했다. retell(`books.py:1147`)·비전 캐릭터
(`characters.py:671`)·regenerate/inpaint(`books.py:739`)·시리즈·**오늘의 동화**가 모두 유료
LLM/이미지를 태우면서 카운터를 통과하지 않아, 예산을 켜도 우회되는 무계량 청구 채널이었다.

**수정.** `books.py:433 consume_generation_budget(endpoint=...)` 공용 헬퍼 + 8개 엔드포인트 배선:
`books.create` · `books.series` · `books.regenerate` · `books.inpaint` · `books.retell` ·
`characters.from_photo` · `characters.from_drawing` · `streak.today_generate`.
`streak.today_generate` 에는 `check_guardrails` 도 함께 배선했다(일일 한도조차 통과하지 않고 있었다).

**구조 불변식 테스트.** `test_every_paid_generation_endpoint_consumes_budget` — 목록의 어느 하나라도
호출이 빠지면 FAIL('한 곳만 고치고 나머지가 새는' 반복 결함을 구조로 차단).

**red-proof.** retell 호출 제거 → 위 테스트 FAIL.

## R3-3 (M10) · consume-after-validate

**증상.** 예산 소비가 요청검증·멱등·동의·소유권 검증 **전**이라, 비용 0인 무효 요청 스팸만으로
전역 카운터가 소진 → 가드레일이 전 사용자 DoS 벡터로 역전.

**수정.** `check_guardrails` 에서 예산 소비를 **분리**(그 함수는 선검증 단계라 무효 요청도 지난다).
`consume_generation_budget` 을 각 엔드포인트의 실비용 직전으로 이동.

**red-proof.** 호출을 `create_book` 첫 줄로 이동 →
`test_budget_is_consumed_after_validation_not_before` FAIL.

## R3-4 (M11) · per-user / 전역 큐 상한 분리

**수정.** `books.py:523` per-user 상한(429 `TOO_MANY_PENDING_JOBS`)을 전역 상한 **앞**에 추가.
기본값: `max_pending_jobs_per_user=10`, `max_pending_jobs=100 → 500`(전역은 워커 용량 신호).

> ⚠ 정직한 한계: X-User-Key는 클라이언트 발급이라 **키 로테이션으로 per-user 상한도 우회된다**.
> 이 값은 '단일 클라이언트의 사고성 폭주' 방어이고, 비용의 실질 상한은 여전히 H4의 전역 일일
> 예산이다 — 그래서 Q2 답이 load-bearing이다. 코드 주석·`.env.example` 에도 명기했다.

**red-proof.** per-user 분기 제거 → `test_per_user_pending_limit_does_not_block_other_users` FAIL
(victim이 503).

## R3-5 (M12) · 실패 잡의 고아 이미지 추적

**수정.**
- `models/db.py :: Job.image_keys` (JSON) + 마이그레이션
- `orchestrator.py:781 record_job_image_keys()` — 이미지 생성 직후 키 기록(실패 여부 무관)
- `orchestrator.py:246` — `mark_job_failed` 에서 그 키를 durable 파기 큐에 적재
- `data_deletion.py :: collect_job_image_keys()` — 계정삭제·철회·단건삭제가 중간 산출물까지 수집
  (계정삭제는 **책 없는 실패 잡**까지 덮도록 job 전수 조회, `users.py:70`)

---

# R4 (🟠 인프라 + ⚪ 자세)

| 항목 | 수정 | red-proof |
|------|------|-----------|
| **H9 TLS** `nginx.conf` | 80은 ACME 챌린지만 + 301 리다이렉트 / 443 `ssl` + `http2 on` + HSTS(`max-age=63072000; includeSubDomains`) + TLSv1.2/1.3 + OCSP stapling. `docker-compose.prod.yml` 에 `certbot` 서비스(12h 자동 갱신)·`certbot-webroot` 볼륨. `DEPLOYMENT.md` 에 "TLS termination" 절(발급 4단계 + 검증 3커맨드). **인증서 없으면 nginx가 기동하지 않는다 = 의도된 fail-closed(평문 배포 불가)** | `listen 443 ssl` 주석 처리 → `test_nginx_terminates_tls_with_hsts_and_redirect` FAIL |
| **M1 자격증명 저장** `user_service.dart` | `flutter_secure_storage`(iOS Keychain / Android EncryptedSharedPreferences)로 이관. `bootstrapUserKey()` 가 부팅 1회 실행: 보안저장소 read → 없으면 평문 이관(**보안 쓰기 성공 후에만** 평문 삭제 — 반대로 하면 계정 유실) → 없으면 신규 생성. 동기 `getUserKey()` 는 그 캐시를 읽고, 어떤 경로로도 **새 평문 자격증명을 만들지 않는다**. Android: `allowBackup="false"` + `data_extraction_rules.xml`(cloud-backup·device-transfer 양쪽 제외) | 평문 삭제 제거 → `M1 — 기존 평문 값을 …이관하고 평문을 삭제한다` FAIL |
| **M6 액세스 로그** `Dockerfile:68` | uvicorn CMD에 `--no-access-log`. 기본 액세스 로그가 `/share/<hex32>` 원문을 찍어 앱·nginx 마스킹을 한 줄로 무력화했다 | 플래그 제거 → `test_production_uvicorn_disables_access_log` FAIL |
| **`exceptions.py:331` 마스킹 이원화** | `_redact_path` 정본을 `core/utils.py :: redact_path` 로 이동, 로깅 5곳 전부 적용(`main.py` 4곳 + `exceptions.py` 3곳) | 한 곳을 `request.url.path` 로 되돌림 → `test_all_logging_paths_redact_share_tokens` FAIL |
| **부모 게이트** `parental_control_service.dart` | 두 자리 **덧셈** → 세 자리 × 한 자리 **곱셈**(타깃 7-9세 미학습 과정). 세션 로드에 `!elapsed.isNegative` 추가 — 시계 되돌림 시 음수 경과가 조건을 항상 만족해 세션이 **영구 유효**였다 | `!elapsed.isNegative &&` 제거 → `시계를 되돌려도 세션이 부활하지 않는다` FAIL |
| **`settings_screen.dart:570`** | 스크린타임 **한도 값** 변경도 부모 게이트 뒤로(토글만 게이트였다). 잠금 해제는 화면 단위(나가면 재잠금) | — |
| **`pronunciation.py:97`** | `assert_book_not_foreign` 을 evaluate·evaluate-audio 양쪽에 적용(형제 write 경로 불변식) | 호출 제거 → `test_pronunciation_rejects_foreign_book` FAIL |
| **`voice_profiles.py:176`** | `sample_audio_url` 이 `voice-samples/{user_key}/` 소속인지 검증. 이 URL은 나중에 역산돼 삭제 대상이 되므로, 미검증이면 **임의 객체 삭제 프리미티브**(타인 아동 사진 키 지정 → 프로필 삭제) | prefix 검사 제거 → `test_voice_profile_rejects_foreign_storage_url` FAIL |
| **`storage.py:131`** | `S3_LEGACY_PUBLIC_URLS`(콤마 구분) 도입 — 도메인/CDN 변경 시 그 이전 URL의 역산이 None이 되어 파기가 조용한 no-op이 되던 문제 | legacy 목록 제거 → `test_key_from_public_url_recognizes_legacy_bases` FAIL |

---

# 규범 결정 질문 (코드로 조용히 정하지 않은 것)

## Q1 — R1-6: 사진 동의 **해제** 시 파기 시점

`photos: true → false` 재-grant를 **즉시 파기**(철회와 동일)로 구현했다. PIPA의 '철회 시 지체 없이
파기' 의무와 정합하고, '해제했는데 얼굴은 남아 있음'이라는 의미 이원화를 없앤다.

**리스크:** 사용자가 실수로 껐다 켜면 **캐릭터·책이 이미 사라져 복구 불가**다(파기는 되돌릴 수 없다).
**대안:** 해제는 게이트만 닫고 N일 유예 후 파기(그동안 재동의하면 보존). 유예를 두려면 파기 예약
테이블과 재동의 시 취소 경로가 필요하다 — outbox(`StoragePurgeTask`)에 `scheduled_at` 을 추가하면
구조는 이미 있다.

**질문: 즉시 파기 유지인가, N일 유예인가(N=?).** 유예 선택 시 앱에 "N일 안에 다시 켜면 복구됩니다"
안내 문구(ko/en/ja)가 필요하다.

## Q2 — R3-1: `DAILY_GENERATION_BUDGET` 값

배선은 끝났지만 **기본값 0 = 여전히 꺼져 있다.** 값 산정은 실측 트래픽·감내 지출 기준의 오너 결정이다.

- 권당 실비용: 이미지 $0.02–0.05 × 9장 + LLM ≈ **$0.32** (재생성 여유 포함 ≈ $0.48)
- `budget = 감내 가능한 일일 최대 지출 ÷ 권당 비용`. 예) $150/일 → **300**

**질문 2-a: 초기 값은?** (미설정으로 GA하면 비용 폭증 무방비 — 직전 감사가 '출시 최소 조건'으로
승격한 항목이다.)
**질문 2-b: readiness를 경고가 아니라 차단(503)으로 승격할 것인가?** 지시서가 "경고"라 그대로 뒀다.
차단이면 값을 넣지 않은 배포가 물리적으로 불가능해진다(강하지만 기존 배포를 즉시 멈춘다).

---

# 스코프 밖 발견 (CTO 판단 필요)

## ✅ R5 — 감사 High 2건(H6·H7): 지시서 티켓에 없었으나 CTO 지시로 **같은 웨이브에서 수정**

`docs/SECURITY_AUDIT_2026-08-17.md` 는 **H1~H9 아홉 건**을 High로 확정했는데, 지시서 R0~R4가
다룬 것은 **일곱 건**이었다(H6·H7 누락). 1차 보고 후 CTO가 "H6·H7도 같은 웨이브로 수정"을
지시해 R5로 처리했다.

### H6 — retell 책이 원본과 S3 이미지 키 공유 → 삭제 시 삽화 전량 404

**증상.** `books.py:1189,1204` 가 `cover_image_url`·`image_url` 을 **그대로 복사**해 두 책이
동일 S3 객체를 가리켰다. 삽화는 `books/{id}/` prefix 밖(`images/{provider}/{uuid}`)에 있어
`collect_book_image_keys` 의 **URL 역산 파기**로만 지워지는데, 그 경로는 배타 소유를 가정한다
→ 원본/리텔 중 하나만 지워도 남은 책의 표지·전 페이지가 전부 404(사용자 데이터 손실).
**이번 웨이브가 이 문제를 악화시킨다**: R1이 파기를 durable outbox로 강화해 '실패해서 안
지워지던' 우연한 완화가 사라진다.

**수정 — 두 겹.**
1. **근본 원인(신규 생성분).** `books.py:1146 _copy_retell_image()` + `storage.py:299
   copy_object_to_new_key()` — 리텔이 S3 **서버측 copy**로 자기 사본(`images/retell/{book_id}/…`)을
   갖는다. 다운로드/업로드가 아니라 `copy_object` 라 대역폭·지연이 거의 없다. 복제 키는
   리텔 잡의 `image_keys` 에도 기록해(M12 인프라 재사용) 커밋 실패 시 파기가 도달한다.
   복사 실패는 **fail-closed**(500 + 멱등키 재시도) — 공유 상태로 만들지 않는다.
   우리 버킷 밖 URL은 역산·파기 대상이 아니라 공유 위험이 없어 그대로 둔다.
2. **방어(이미 만들어진 리텔).** `data_deletion.py :: collect_purgeable_image_keys()` 를
   세 삭제 경로(계정·철회·단건)의 **공통 진입점**으로 두고, 마지막에
   `_keys_referenced_by_other_books()` 로 **다른 책이 아직 참조 중인 키를 제외**한다.
   공유를 만드는 유일한 경로가 리텔이므로 후보를 `retelling_source_book_id` 링크(양방향)로
   한정해 전 테이블 스캔을 피한다. 계정 삭제는 리텔의 원본도 같은 사용자 소유라 제외 대상이
   없다(전부 삭제) — 과잉 보존으로 고아를 만들지 않는다.

**red-proof (4건, 전부 실측).**
- `still_referenced` 제외 무력화 → `test_deleting_retell_does_not_purge_shared_source_images` FAIL
- 동일 무력화 → `test_deleting_source_does_not_purge_images_used_by_retell` FAIL
- `_copy_retell_image` → `source.cover_image_url` 로 되돌림 →
  `test_retell_copies_images_to_its_own_keys` FAIL
- 반대 방향 봉인: `test_deleting_last_book_does_purge_its_images`(공유 없으면 원래대로 파기)

### H7 — streak '오늘의 동화'가 캐릭터 소유권·사진 동의 게이트 생략

**증상.** `streak.py:247` 이 `create_book` 이 강제하는 캐릭터 소유권 검증과 JIT 사진 동의
게이트를 모두 건너뛰었다 → **타인 캐릭터로 생성(IDOR)** + **동의 없는/철회된 아동 사진
캐릭터로 계속 생성**. 이 저장소의 반복 결함인 '규칙이 두 벌'이다.

**수정.** `books.py:433 enforce_book_spec_access(db, user_key, spec)` 로 소유권+동의 블록을
추출하고 `create_book`(`:676`)·`generate_today_story`(`streak.py:257`)가 **같은 코드**를 공유한다.

**red-proof (3건).** streak의 호출 제거 →
`test_today_generate_rejects_foreign_character`(403 기대가 200) ·
`test_today_generate_requires_photo_consent` ·
`test_every_book_creation_entrypoint_enforces_character_access`(구조 불변식) 각각 FAIL.
반대 방향 봉인: 동의를 받으면 200으로 통과(게이트가 기능을 죽이지 않는다).

## 기타 관측 (수정 안 함)

- **`_reapply_orphan_events` 는 이미 충분하다.** 지시서 R2-6이 "iap.py:554 orphan 이벤트 → 스윕/재적용"을
  요구했으나, 코드 확인 결과 verify·restore·already_subscribed 세 경로 모두에서 이미 호출된다
  (`iap.py:276, 325, 392`). 추가 수정 없이 계약 충족 — 없는 결함을 만들지 않았다.
- **테스트 계약 변경 4건(정직 보고).** 다음 기존 테스트는 '옛 결함을 고정하던' 것이라 갱신했다:
  `test_photos_consent_evaluated_independently_of_granted` → `test_photos_only_consent_does_not_open_photo_gate`
  (R1-7이 그 동작을 결함으로 판정) · `test_consent_photos_independent_of_granted`(동일) ·
  `test_revoke_closes_gate_for_photos_only_consent`(픽스처를 granted 포함으로) ·
  `test_refund_webhook_claws_back_subscription_credits`(원장 없는 비현실 픽스처 → 실제 지급 경로와
  동일하게 구성). 각각 반대 방향 봉인 테스트를 함께 추가했다.
- **`test_data_deletion_fk.py` 스파이 지점 이동.** 라우터 심볼 패치는 outbox 도입 후 '지시가 적재만 되고
  실행되지 않는' 회귀를 통과시킨다(false-green) → `src.services.storage` 실경계로 이동
  (`_spy_storage_deletes`).

---

# 정직 보고 — 못 한 것 / 검증되지 않은 것

1. **🔴 iOS 실기기 샌드박스 관통(게이트 7) 미실행.** R0의 관통 증거는 실기기 샌드박스가 유일하다.
   단위 테스트는 "SK1 강제 호출이 부팅 시점에 일어난다"와 "가짜 id를 만들지 않는다"만 증명하며,
   **`serverVerificationData` 가 실제로 legacy 영수증으로 돌아오는지, 백엔드 검증이 통과하는지는
   증명하지 못한다.** 지시서대로 "단위만 통과 = 미완"이다. 오너의 최종 E2E(실키·실기기)에
   `iOS 샌드박스 결제 → 서버 검증 성공 → 크레딧 지급` 을 반드시 포함해야 한다.
   `flutter build ios` **실빌드는 미실행**이다(Xcode 필요). 다만 `pod install` 은 실행해
   `ios/Podfile.lock` 에 `flutter_secure_storage (6.0.0)` 이 반영됐다(`in_app_purchase_storekit` 은
   transitive로 이미 있었다) — 과거 stale Podfile.lock 사건(PR#59)의 재발은 막았다. iOS 배포
   타깃은 13.0이고 SK1 강제는 그 이하 기기에도 안전하다(SK2 미지원 기기는 애초에 JWS 문제가 없다).
2. **TLS 실인증서 미발급.** nginx 설정·certbot 서비스·문서는 완료했으나 실제 발급은 도메인·DNS가
   필요한 오너 작업이다. **인증서 없이 `docker-compose.prod.yml` 을 올리면 nginx가 기동하지 않는다**
   (fail-closed 의도) — 배포 전 `DEPLOYMENT.md` "TLS termination" 절을 먼저 수행해야 한다.
3. **`DAILY_GENERATION_BUDGET` 은 배선만 됐고 여전히 0(비활성).** §Q2 답 없이는 H4가 실질적으로
   닫히지 않는다.
4. **R3-4 한계(위에 기술).** per-user 큐 상한은 키 로테이션으로 우회된다.
5. **실PG 게이트 범위.** R1 철회 cascade·R2-2 clawback만 실PG로 검증했다. 계정삭제(`users.py`)의
   FK 순서는 기존 SQLite 테스트(`test_data_deletion_fk.py`, PRAGMA FK on)에만 의존한다 —
   이번 웨이브가 그 경로의 FK 순서를 바꾸지 않아 범위에 넣지 않았다.
6. **부모 게이트 난이도는 경험적 판단이다.** '3자리 × 1자리 곱셈'이 7-9세에게 충분히 어렵다는
   근거는 교육과정 상식이지 실측이 아니다. 게이트는 보안 경계가 아니라 속도 방지턱이라는 성격도
   그대로다(계산기를 쓰면 누구나 통과).
7. **`storage_purge_tasks` 운영 관측 미배선.** pending/failed 누적을 알리는 알림·대시보드는 없다.
   `sweep_pending_purges` 가 완결 건수를 info 로그로만 남긴다 — 파기 미완이 장기 누적되면 규제
   리스크이므로 운영 알림 연결을 권고(별도 스코프).
8. **`max_pending_jobs` 기본값 100 → 500 상향은 용량 가정이다.** 실제 워커 수·처리량 기준으로
   오너가 조정해야 한다.
9. **H6: 이미 만들어진 리텔은 여전히 공유 상태다.** 방어층(`_keys_referenced_by_other_books`)이
   파기 시점에 보호하지만, 근본 해소(사본 보유)는 **이번 수정 이후 생성분에만** 적용된다.
   기존 리텔을 사본으로 마이그레이션하는 배치는 만들지 않았다(데이터 마이그레이션 = 별도 스코프).
   실효: 기존 리텔은 '둘 다 지워질 때까지 삽화가 남는다' — 404는 안 나지만, 리텔만 지워도
   공유 키가 남아 **원본이 지워질 때까지 파기가 지연**된다(파기 누락은 아니다).
10. **H6 fail-closed의 대가.** 리텔 중 S3 복사가 실패하면 500이고, 그 시점엔 LLM 리텔 비용과
   전역 예산 1건이 이미 소진됐다. 멱등키로 재시도 가능하지만 비용은 재소모된다.
   (공유 상태로 만드는 것보다는 낫다는 판단 — 다른 선택을 원하면 알려달라.)
11. **H6 저장소 사용량 증가.** 리텔 1권마다 삽화 9장이 복제된다(권당 수 MB). 리텔은 사용자
   개시 동작이라 폭증 경로는 아니지만, 스토리지 비용 모델에 반영이 필요하다.

---

# 변경 파일

**백엔드(신규 4)**: `src/services/purge_queue.py` · `alembic/versions/b1c2d3e4f5a6_security_wave_20260817.py` ·
`tests/test_pg_fk_erasure.py` · `tests/test_security_wave_20260817.py`
**백엔드(수정 19)**: `core/{config,consent,exceptions,utils}.py` · `main.py` · `models/db.py` ·
`routers/{books,characters,consent,iap,library,pronunciation,streak,users,voice_profiles}.py` ·
`services/{credits,data_deletion,iap_verifier,job_monitor,orchestrator,storage}.py` ·
`Dockerfile` · `.env.example` · 테스트 6(`conftest.py` 에 페이크 S3 `copy_object` 추가)

**모바일(신규 2)**: `lib/services/iap_platform_init.dart` · `test/security_wave_20260817_test.dart` ·
`android/app/src/main/res/xml/data_extraction_rules.xml`
**모바일(수정)**: `lib/main.dart` · `lib/services/{user_service,parental_control_service}.dart` ·
`lib/screens/{credits_screen,settings_screen}.dart` · `android/.../AndroidManifest.xml` ·
`pubspec.yaml`/`pubspec.lock` · `ios/Podfile.lock`(pod install) ·
`{linux,macos,windows}` 플러그인 registrant(자동 생성) · `test/iap_purchase_flow_test.dart`

**인프라·문서**: `infra/nginx/nginx.conf` · `infra/docker-compose.prod.yml` · `docs/DEPLOYMENT.md` ·
`packages/shared/schema/openapi.json`

---

# 재현 커맨드 (CTO 감사용)

```bash
cd apps/api
venv/bin/python -m pytest tests/ -q          # 781 passed
venv/bin/ruff check src/

export PG="postgresql+asyncpg://storybook:storybook123@localhost:5433/storybook"
E2E_PG_DATABASE_URL=$PG venv/bin/python -m pytest tests/test_pg_fk_erasure.py -q   # 6 passed

E2E_PG_DATABASE_URL=$PG E2E_REDIS_URL="redis://localhost:6379/5" \
  E2E_S3_ENDPOINT=http://localhost:9000 E2E_S3_ACCESS_KEY=minioadmin \
  E2E_S3_SECRET_KEY=minioadmin123 E2E_S3_BUCKET=storybook \
  venv/bin/python -m pytest tests/test_celery_worker_pg.py -q                      # 4 passed

cd ../mobile && /opt/homebrew/bin/flutter analyze && /opt/homebrew/bin/flutter test  # 289 passed
```

> ⚠ 로컬 docker의 Postgres는 **5433** 포트다(5432는 네이티브 postgres가 점유).
