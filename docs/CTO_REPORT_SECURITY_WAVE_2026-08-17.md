# CTO 보고 — 2026-08-17 보안 감사 반송분 수정 웨이브

> 대상 감사: `docs/SECURITY_AUDIT_2026-08-17.md` (판정 ❌ 출시 차단 · Critical 1 + High 9)
> 지시서: `docs/IMPLEMENTER_PROMPT_SECURITY_2026-08-17.md` (+ 구두 추가지시 H6·H7)
> 상세 기술 로그: `docs/FIX_WAVE_SECURITY_2026-08-17.md`
> 기준 HEAD `71c3adb` · **61파일 staged, 커밋 없음** (+5,529 −360)

---

## 1. 판정

### 🟡 코드 레벨 차단 요인은 전부 해소. **출시 판정은 아직 ❌ — 오너 실환경 3건이 미완.**

감사가 지목한 **Critical 1 + High 9 + Medium 12** 전건에 코드 수정이 들어갔고,
**red-proof 29건을 전부 실측**했다(수정 되돌림 → 지정 테스트 FAIL → 원복 diff 0).

그러나 다음 3건은 **코드로 닫을 수 없는 항목**이고, 이 중 둘은 감사가 "이것 없이는 미완"이라고
명시한 것이다. 따라서 **출시 차단은 해제되지 않았다.**

| # | 미완 항목 | 왜 코드로 못 닫나 | 현재 상태 |
|---|-----------|-------------------|-----------|
| 1 | 🔴 **C1 iOS 결제 관통 검증** | 관통 증거는 실기기 샌드박스가 유일. 단위 테스트는 "부팅 시점에 SK1을 강제한다"만 증명하고 `serverVerificationData` 가 실제로 legacy 영수증으로 돌아오는지는 **증명하지 못한다** | 코드 수정 완료, **증거 0** |
| 2 | 🟠 **H4 예산 값 주입** | 값 산정이 오너 결정(§3 Q2). 배선은 끝났으나 **기본 0 = 여전히 비활성** | 배선 완료, **가드 꺼짐** |
| 3 | 🟠 **H9 TLS 실인증서** | 도메인·DNS가 필요한 실환경 작업 | 설정·자동갱신·문서 완료, **인증서 없음** |

> H9는 미완이지만 **위험은 낮췄다**: 인증서가 없으면 nginx가 기동하지 않도록 구성했다
> (의도된 fail-closed). 평문 배포가 물리적으로 불가능해졌다.

---

## 2. 감사 원장 대비 처리 현황

| 등급 | 감사 확정 | 수정 완료 | 미처리 | 비고 |
|------|-----------|-----------|--------|------|
| 🔴 Critical | 1 | 1 (코드) | — | 관통 검증 대기 |
| 🟠 High | 9 | 9 | — | H4·H9는 오너 액션 잔여 |
| 🟡 Medium | 12 | 12 | 0 | |
| ⚪ Low/자세 | 17 | 14 | **3** | 지시서 미티켓분 — §5 |
| 🔁 수용리스크 | 4 | — | 4 | 악화 없음(손대지 않음, 지시서 준수) |
| ⏸ Deferred | 5 | — | 5 | 제품 결정 |

**High 9건 개별:**

| | 항목 | 상태 |
|---|------|------|
| H1 | 동의 철회 Series FK 500 (철회권 영구 차단) | ✅ 실PG red-proof로 확정 |
| H2 | 다중 캐릭터 책 얼굴 미파기 | ✅ 실PG |
| H3 | cancelled 구독 재활성 불가 (돈 삼킴) | ✅ |
| H4 | 비용 예산 미배선 | ⚠️ 배선 완료 / **값 미주입** |
| H5 | retell·비전·regen 무계량 LLM | ✅ 8개 엔드포인트 전수 + 구조 불변식 |
| H6 | retell 이미지 키 공유 → 삭제 시 404 | ✅ (지시서 누락 → 추가지시로 처리) |
| H7 | streak 소유권·동의 게이트 생략 | ✅ (동상) |
| H8 | from-photo 고아 아동 사진 | ✅ |
| H9 | 프로덕션 TLS 부재 | ⚠️ 설정 완료 / **인증서 없음** |

---

## 3. CTO 결정이 필요한 사항 (4건)

코드로 조용히 정하지 않고 남겼다.

### Q1 — 사진 동의 **해제** 시 파기 시점 (R1-6 / M9)

현재 **즉시 파기**로 구현(철회와 동일 경로). PIPA '지체 없이 파기'와 정합하고 의미 이원화를 없앤다.
**리스크:** 실수로 껐다 켜면 캐릭터·책이 이미 사라져 복구 불가.
**대안:** N일 유예(그동안 재동의하면 보존). outbox(`StoragePurgeTask`)에 `scheduled_at` 만 추가하면
구조는 이미 있다. 유예 선택 시 안내 문구 ko/en/ja 필요.

**→ 즉시 파기 유지 / N일 유예(N=?)**

### Q2 — `DAILY_GENERATION_BUDGET` 값 (R3-1 / H4) **← 출시 차단 항목**

권당 실비용 ≈ **$0.32**(재생성 여유 포함 ≈ $0.48). `budget = 감내 일일 지출 ÷ 권당 비용`.
예) $150/일 → 300.

`X-User-Key` 는 클라이언트 발급이라 per-user 통제가 전부 키 로테이션으로 우회된다 —
**이 값이 청구서의 유일한 실질 상한이다.**

**→ 초기 값 = ? / readiness를 경고가 아니라 차단(503)으로 승격할 것인가?**
(지시서가 "경고"라 그대로 뒀다. 차단이면 값 없는 배포가 물리적으로 불가능해지지만
기존 배포가 즉시 멈춘다.)

### Q3 — H6 복사 실패 시 동작 (신규)

리텔 중 S3 복사가 실패하면 **fail-closed 500**으로 구현했다. 그 시점엔 LLM 리텔 비용과
전역 예산 1건이 이미 소진됐고, 멱등키 재시도는 가능하지만 비용은 재소모된다.
**대안:** 해당 페이지 삽화 없이 진행(품질 저하, 조용함) / 원본 URL 공유(= 원래 버그).

**→ fail-closed 유지 / 다른 선택?**

### Q4 — H6 기존 리텔 마이그레이션 (신규)

수정 후 생성분은 자기 사본을 갖지만 **이미 만들어진 리텔은 여전히 공유 상태**다.
파기 시점 방어층이 보호하므로 404는 나지 않지만, 리텔만 지워도 공유 키가 남아
**원본이 지워질 때까지 파기가 지연**된다(파기 누락은 아님).
기존 리텔을 사본으로 옮기는 배치는 만들지 않았다(데이터 마이그레이션 = 별도 스코프).

**→ 배치 필요 / 방어층으로 충분?**

---

## 4. 독립 검증 절차 (CTO 재현용)

### 4-1. 게이트 재실행

```bash
cd apps/api
venv/bin/python -m pytest tests/ -q          # 791 passed, 10 skipped, 0 failed
venv/bin/ruff check src/                     # All checks passed
venv/bin/python -m alembic heads             # b1c2d3e4f5a6 (단일 head)

export PG="postgresql+asyncpg://storybook:storybook123@localhost:5433/storybook"
E2E_PG_DATABASE_URL=$PG venv/bin/python -m pytest tests/test_pg_fk_erasure.py -q   # 6 passed

E2E_PG_DATABASE_URL=$PG E2E_REDIS_URL="redis://localhost:6379/5" \
  E2E_S3_ENDPOINT=http://localhost:9000 E2E_S3_ACCESS_KEY=minioadmin \
  E2E_S3_SECRET_KEY=minioadmin123 E2E_S3_BUCKET=storybook \
  venv/bin/python -m pytest tests/test_celery_worker_pg.py -q                      # 4 passed

cd ../mobile && /opt/homebrew/bin/flutter analyze && /opt/homebrew/bin/flutter test  # 289 passed
```

> ⚠ 로컬 docker Postgres는 **5433** 포트다(5432는 네이티브 postgres 점유).

### 4-2. 표본 red-proof (감사 우선순위 순 5건)

각각 "수정 되돌림 → 지정 테스트 FAIL → 원복" 이다. 전체 29건 목록은 FIX_WAVE 보고서에 있다.

| 우선 | 되돌릴 것 | FAIL해야 하는 테스트 |
|---|---|---|
| 🔴 C1 | `main.dart` 의 `await IapPlatformInit.ensureStoreKit1();` 삭제 | `security_wave_20260817_test.dart :: main.dart 가 …접근 전에 강제한다` |
| 🟠 H1 | `consent.py` 의 `detach_series_from_characters(...)` 삭제 | `test_pg_fk_erasure.py::test_revoke_with_series_completes_on_real_postgres` → **실 PG `ForeignKeyViolationError: series_character_id_fkey`** (SQLite 스위트는 이 상태에서도 green — 이게 실PG 게이트가 필요한 이유의 실증) |
| 🟠 H3 | `iap.py` 의 `and active_subscription.status == "active"` 삭제 | `test_cancelled_subscription_is_reactivated_by_new_purchase` |
| 🟠 H6 | `data_deletion.py` 의 `still_referenced = await _keys_referenced_by_other_books(...)` → `set()` | `test_deleting_retell_does_not_purge_shared_source_images` |
| 🟠 H7 | `streak.py` 의 `await enforce_book_spec_access(db, user_key, spec)` 삭제 | `test_today_generate_rejects_foreign_character` |

### 4-3. M2(clawback) — 인덱스 red-proof 주의

**모델 상수 rename으로는 재현되지 않는다.** 이미 PG에 만들어진 인덱스가 그대로 남기 때문이다.
실제로 확인하려면:

```bash
docker exec storybook-postgres psql -U storybook -d storybook -c "DROP INDEX uq_credit_transactions_clawback;"
docker exec storybook-postgres psql -U storybook -d storybook -c "
INSERT INTO credit_transactions (user_key, amount, balance_after, transaction_type, description, reference_id, created_at)
VALUES ('rp','-5',0,'clawback','rp','RP-1', now()), ('rp','-5',0,'clawback','rp','RP-1', now());"
#  → INSERT 0 2  (인덱스 없으면 이중 회수가 실제로 통과한다)

# 복구(마이그레이션 왕복 리허설 겸용)
docker exec storybook-postgres psql -U storybook -d storybook -c "DELETE FROM credit_transactions WHERE user_key='rp';"
DATABASE_URL=$PG TESTING=false venv/bin/python -m alembic downgrade -1
DATABASE_URL=$PG TESTING=false venv/bin/python -m alembic upgrade head
```

이 왕복은 이미 1회 실행해 성공을 확인했다.

---

## 5. 잔여 리스크 등록부 (정직 보고)

### 5-1. 출시 차단 (오너 액션)

| | 항목 | 조치 |
|---|------|------|
| 1 | **iOS 실기기 샌드박스 IAP 관통** | 최종 E2E에 `iOS 샌드박스 결제 → 서버 검증 성공 → 크레딧 지급` 포함 필수. `flutter build ios` 실빌드도 미실행(Xcode 필요) — 단 `pod install` 은 실행해 `Podfile.lock` 에 `flutter_secure_storage (6.0.0)` 반영 완료(과거 stale Podfile.lock 사건 PR#59 재발 방지) |
| 2 | **`DAILY_GENERATION_BUDGET` 값 주입** | §Q2 |
| 3 | **TLS 인증서 발급** | `DEPLOYMENT.md` "TLS termination" 절 4단계 + 검증 3커맨드 |

### 5-2. 감사 Low 중 **미티켓·미수정 3건**

지시서 티켓에 없어 손대지 않았다. 전부 감사서에 등재된 항목이다.

| 항목 | 내용 | 판단 |
|------|------|------|
| `books.py:264` | 크레딧 차감이 잡 상태전이와 별도 트랜잭션 → 크래시 창에서 무성 크레딧 유실(대사 경로 없음) | 사용자 손해 방향. 빈도 낮음 |
| `books.py:895` | 인페인트 마스크 업로드에 **크기·콘텐츠타입 검증 없음** + 파기 경로 부재(영구 고아) | 업로드 DoS 표면 + 스토리지 고아. `_validate_and_read_image` 같은 기존 헬퍼 재사용으로 저비용 |
| `iap.py:614` | 웹훅 인증이 쿼리스트링 토큰 허용 → **nginx 액세스 로그에 시크릿 평문 기록** | ⚠️ 이번 웨이브의 M6(`--no-access-log`)는 **앱 측만** 막았다. nginx `/v1/` location은 여전히 `$request`(쿼리 포함)를 로깅한다. 코드는 이미 `X-Webhook-Token` 헤더를 우선하므로, 쿼리 폴백 제거 또는 해당 location `access_log off` 로 저비용 마감 가능 |

**→ 후속 소웨이브 권고. 특히 `iap.py:614` 는 이번 M6 수정이 "로그 토큰 유출을 닫았다"고
읽히기 쉬우므로, 절반만 닫혔다는 사실을 명시한다.**

### 5-3. 설계 한계 (수정했으나 완전하지 않음)

| 항목 | 한계 |
|------|------|
| **R3-4 per-user 큐 상한** | X-User-Key 로테이션으로 우회된다. '단일 클라이언트 폭주' 방어이고, 비용의 실질 상한은 H4다 → Q2가 load-bearing |
| **H6 기존 리텔** | 여전히 공유 상태(방어층이 보호). §Q4 |
| **H6 저장소** | 리텔 1권마다 삽화 9장 복제 — 스토리지 비용 모델 반영 필요 |
| **부모 게이트 난이도** | '3자리 × 1자리 곱셈'이 7-9세에게 충분히 어렵다는 건 교육과정 상식이지 실측이 아니다. 계산기를 쓰면 누구나 통과(속도 방지턱 성격은 그대로) |
| **`storage_purge_tasks` 관측** | pending/failed 누적 알림·대시보드 없음. 파기 미완 장기 누적은 규제 리스크 → 운영 알림 연결 권고(별도 스코프) |
| **`max_pending_jobs` 100→500** | 워커 용량 가정. 실측 기준 조정 필요 |
| **실PG 게이트 범위** | R1 철회 cascade·R2-2 clawback만 실PG. 계정삭제 FK 순서는 SQLite 테스트에만 의존(이번 웨이브가 그 순서를 바꾸지 않아 범위 제외) |

### 5-4. 계약 변경 (감사 확인 필요)

기존 테스트 **4건이 '옛 결함을 고정'하고 있어** 갱신했다. 각각 반대 방향 봉인을 함께 추가했다.

- `test_photos_consent_evaluated_independently_of_granted` → photos-only 동의가 사진 게이트를
  여는 것을 '정상'으로 주장하던 테스트. R1-7이 그 동작을 결함으로 판정 → 반전.
- `test_consent_photos_independent_of_granted` (동일 클래스)
- `test_revoke_closes_gate_for_photos_only_consent` — 픽스처를 granted 포함으로
- `test_refund_webhook_claws_back_subscription_credits` — 원장 없는 비현실 픽스처를
  실제 지급 경로와 동일하게 재구성(M3가 회수액 정본을 원장으로 바꿨으므로)

또한 `test_data_deletion_fk.py` 의 스파이 지점을 라우터 심볼 → `src.services.storage` **실경계**로
옮겼다. outbox 도입 후에는 라우터 심볼 패치가 '지시가 적재만 되고 실행되지 않는' 회귀를
통과시키기 때문이다(false-green).

---

## 6. 이번 웨이브에서 감사 방법론상 짚을 것

1. **실PG 게이트가 구현 버그를 직접 잡았다.** R1-4 초안이 `job_ids` 를 책 삭제 **후**에 읽어
   파기가 조용한 no-op이었다. SQLite 스위트는 해당 경로 테스트가 없어 통과했고, 실PG 게이트
   첫 실행이 `assert [(37,),(38,)] == []` 로 잡았다.
   → **파기·FK 클래스는 실PG 게이트 없이는 false-green이 기본값**이라는 지시서의 판단이 맞았다.

2. **지시서 API 오류 1건.** `InAppPurchaseStoreKitPlatformAddition.enableStoreKit1()` 은 존재하지
   않는다. 0.4.8 실제 API는 `InAppPurchaseStoreKitPlatform.enableStoreKit1()` (static)이고,
   **호출 시점이 load-bearing**이다(플러그인 등록이 `InAppPurchase.instance` 첫 접근에서 발생)
   → 호출 위치 자체를 테스트로 봉인했다.

3. **지시서가 감사 High 2건(H6·H7)을 누락했다.** 스코프 규칙에 따라 1차에서는 수정하지 않고
   보고서에 명시 → 추가지시로 처리. 감사서와 지시서 사이에 **원장 대조 단계**가 없으면 이런
   누락이 조용히 통과한다.

4. **H6 수정 방향은 스토리지 레이아웃 확인이 결정했다.** "prefix 삭제로 지워지겠지"라는 가정이
   틀렸다 — 삽화는 `books/{id}/` 밖 `images/{provider}/{uuid}` 에 있어 **URL 역산으로만** 지워진다.
   그 확인이 '사본 보유 + 역산 시 공유 참조 제외' 두 겹 설계로 이어졌다.

---

## 7. 커밋 계획

전부 staged, 커밋 없음(프로젝트 정책: Claude는 staged까지, 커밋·푸시는 오너).

- 61파일 / +5,529 −360
- 제안 커밋 분할: ①백엔드 보안수정+마이그레이션 ②모바일(R0·M1·부모게이트) ③인프라·문서
  — 단일 커밋도 무방(감사 단위가 하나)
- **CI 배선 포함**: 작업 중 실PG FK 게이트가 `ci.yml` 에 없어 **조용히 skip될 상태**임을 발견해
  스텝을 추가했다(C1 게이트보다 **앞** — FK 게이트는 `alembic upgrade head`, C1은 `create_all`).
  게이트가 다시 무력화되지 않도록 `test_ci_workflow_gates.py` 에 정적 가드 3건을 추가했다
  (스텝 존재 · `E2E_PG_DATABASE_URL` 주입 · 실행 순서). red-proof 실측 완료.
- CI 첫 가동에서 확인할 것: 위 스텝이 실제로 6건을 **실행**하는지(skip 0)
