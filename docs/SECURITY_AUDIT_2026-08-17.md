# 보안 감사 — AI Story Book 전체 코드베이스 (2026-08-17)

> CTO 적대적 보안 감사. HEAD `71c3adb`. 스코프: **전체 코드베이스**(백엔드 20.5K LOC + 모바일 + infra), 보안 중심.
> 방법: 13차원 병렬 finder → 각 finding 3렌즈(code/trigger/impact) 반증 검증(하나라도 반증 시 기각) → CTO 독립 ground-truth 재확정.
> 원시 66건 → 3렌즈 생존 53건 → 중복 제거 후 아래. **헤드라인 CRITICAL은 멀티에이전트가 재실행 중 떨어뜨렸고 CTO 독립검증이 붙잡음**(§방법 참조).

## 판정

**❌ 출시 차단.** Critical 1 + High 9(중복 제거 후). 대부분 **돈(iOS 결제 전량 파손·구독 재활성 불가·비용 가드 무배선)**과 **아동 PII 파기권(동의 철회 500·likeness 잔존)**에 집중. 인증 코어(크레딧 원자 차감·CORS·데이터삭제 FK 정리·SSRF allowlist)는 견고.

| 등급 | 신규 확정(중복 제거) | 성격 |
|------|------|------|
| 🔴 Critical | 1 | iOS 결제 전량 파손(출시 차단) |
| 🟠 High | 9 | 돈 삼킴·아동 PII 파기 실패·비용 가드 무배선·TLS 부재 |
| 🟡 Medium | 12 | IAP 비대칭 지급·clawback 이중회수·예산 우회·로그 PII |
| ⚪ Low/자세 | 18 | IDOR·고아 스토리지·부모게이트 약함·웹훅 자세 |
| 🔁 수용리스크 재확인 | 4 | 악화 없음(공개URL·rate-limit fail-open·Swagger·str(e)) |
| ⏸ Deferred(제품결정) | 5 | 광고보상·POD수금·웹훅 어댑터·출력 모더레이션 |

---

## 🔴 CRITICAL — 출시 차단

### C1. iOS 인앱결제 전량 파손 — StoreKit2 JWS를 legacy verifyReceipt로 전송 → 과금되나 크레딧 미지급 `[CTO ground-truth 확정]`
**파일**: `apps/mobile/lib/screens/credits_screen.dart:800` · `apps/api/src/services/iap_verifier.py:94-113`

- `in_app_purchase_storekit 0.4.8`(pubspec.lock)의 CHANGELOG:59 — **"BREAKING CHANGE: StoreKit 2 is now the default for all devices that support it."** 앱 어디에도 StoreKit2 비활성화 코드 없음(전역 grep 0건). → iOS 15+에서 `purchase.verificationData.serverVerificationData`는 **base64 앱 영수증이 아니라 JWS(서명된 트랜잭션 JWT)**.
- 모바일이 그 JWS를 `receipt_data`로 백엔드에 전송(credits_screen.dart:800) → 백엔드 `_verify_apple`가 `apple_iap_verify_url`(= `https://buy.itunes.apple.com/verifyReceipt`, legacy)로 그대로 포워드(iap_verifier.py:94-100).
- legacy verifyReceipt는 ASN.1 앱 영수증을 기대 → JWS는 **status 21002(malformed)** 반환 → `_post_apple_receipt`가 예외 → **strict 모드(프로덕션 기본)에서 전파** → `/v1/iap/verify` 실패.
- 모바일은 서버 검증 성공 후에만 트랜잭션을 finish(credits_screen.dart:807 주석) → 검증이 항상 실패하므로 **크레딧 미지급, 트랜잭션 pending 영구 정체**(재실행마다 동일 JWS 재전송 → 동일 실패). 결제는 OS가 이미 캡처 → **과금됨**.

**영향**: iOS 유료 사용자 100%가 돈을 내고 아무것도 못 받고, 상태가 영구 pending. 앱스토어 환불 폭주·심사 리젝·평점 붕괴. **출시 차단.**

**수정(택1, 제품 결정)**:
- (A) 빠른 언블록: 앱에서 StoreKit1로 되돌린다 — `in_app_purchase_storekit`의 SK1 강제 옵션(플랫폼 애드온) 사용. 단 Apple이 legacy verifyReceipt를 sunset 중이라 임시책.
- (B) 정공법(권장): 백엔드를 **App Store Server API + JWS 서명 검증**(Apple 공개키로 JWT 검증)으로 이관. StoreKit2 표준 경로. Google도 동일하게 signed 트랜잭션 검증.
- 검수: **실기기 샌드박스**에서 iOS 결제→크레딧 지급까지 관통 확인(현재 최종 E2E가 실키/실기기 대기 중이므로 이 경로가 반드시 포함돼야 함).

> ⚠ 관련 저강도 동반결함(§L, credits_screen.dart:777): `purchaseID` 부재 시 시간기반 가짜 `transaction_id` 생성 → Apple은 영구 검증 실패, Google(orderId 부재 구매)은 재시도마다 값이 바뀌어 **멱등성 파괴로 이중 지급 여지**. C1 수정 시 함께 처리.

---

## 🟠 HIGH

### H1. 동의 철회가 시리즈 연결 캐릭터에서 FK 위반 500 → 보호자 철회권 영구 차단 `[CTO 실측]`
`apps/api/src/routers/consent.py:207` (revoke)
- 단건 삭제 경로(`characters.py:546`, H7 주석)는 `update(Series).where(character_id==...).values(character_id=None)`로 단방향 FK를 명시 해제하는데, **철회 경로는 `Series` import조차 없이** `db.delete(character)`만 함. `Series.character_id`는 하드 FK(`db.py:97`, ondelete 없음).
- 사진 캐릭터로 시리즈를 만든 사용자가 철회 → Postgres commit이 `IntegrityError` → **500, 매 재시도 동일 = 철회 영구 차단**(PIPA/COPPA 파기의무 불이행 + 철회 의사표시 미기록).
- 악화: 캐릭터 스토리지 파기(`delete_prefix`)가 commit **전**에 실행 → 첫 시도에서 아동 원본 사진은 이미 삭제됐는데 DB엔 동의 active로 잔존, `source_image_url`은 깨진 파일 지시. (SQLite 테스트는 FK-off라 구조적으로 못 잡음 — `data_deletion.py` 독스트링이 명시.)
- **수정**: 철회 경로도 캐릭터 삭제 전 `Series`(및 `character_ids` 참조 책) FK를 nullify/정리. 스토리지 파기를 commit 성공 **후**로 이동(orphan 방지). 실PG FK 게이트로 회귀 봉인.

### H2. 동의 철회가 다중 캐릭터 책(character_ids)의 아동 얼굴 이미지를 파기하지 않음 → likeness 영구 잔존 `[3렌즈 92/90/88]`
`apps/api/src/routers/consent.py:179-181`
- 철회 시 삭제 대상 책을 `Book.character_id.in_(...)`(스칼라 FK)로만 수집 → 캐릭터를 `character_ids`(JSON 배열, 가족 다중)로 참조하는 책은 누락. 그 책들의 표지·페이지(아동 얼굴 렌더)가 파기되지 않고 잔존.
- **수정**: 삭제 대상 수집에 `character_ids` 배열 포함 책도 편입.

### H3. 취소(cancelled) 구독 재활성 경로 전무 → 재결제가 삼켜져 과금만 되고 권한 미지급 `[3렌즈 92/85/85 + CTO 확인]`
`apps/api/src/routers/iap.py:287` · `services/credits.py:401`
- `status="active"` 할당은 `create_subscription` 한 곳뿐(cancelled→active 전이 부재). `already_subscribed` 가드(iap.py:287)가 `get_active_subscription`(status ∈ {active, **cancelled**})을 사용 → 잔여기간 내 cancelled 동일플랜이면 신규 검증 결제도 구독 미생성·미지급.
- 웹훅 경로도 `_STATUS_RANK`(cancelled=2 > active=1) sticky로 'active' 통지를 조기 반환, 동기화 블록은 cancelled/expired/refunded만 처리.
- **트리거**: `/v1/credits/cancel-subscription`(서버 취소, 스토어 자동갱신은 유지)이 서버-cancelled/스토어-active 괴리를 자체 생산 → 이후 갱신 청구가 서버 잔여기간 내 도착하면 삼켜짐. 자가치유·서버복구 수단 없음(수동 DB 개입).
- **수정**: `already_subscribed`를 status=='active'로 한정, cancelled+신규검증결제는 재활성. sticky는 터미널(refunded/expired)만.

### H4. 비용 DoS 가드레일(S4 일일 예산)이 기본 비활성 + 전 배포 산출물 미배선 → 직전 감사 '출시 필수' 완화책이 실제로 꺼져 있음 `[CTO 실측]`
`apps/api/src/core/config.py:130` · `infra/docker-compose.prod.yml` · `apps/api/.env.example`
- `daily_generation_budget: int = 0`(기본), `cost_budget.py:43` `limit<=0 → 통과(True)`. docker-compose.prod·`.env.example` **양쪽 미배선**(grep 0건).
- 직전 감사(2026-07-29 #1)에서 CTO가 "X-User-Key 로테이션 무한 3크레딧 → 무제한 LLM/이미지 청구서, **출시 전 최소 조건 = 전역 예산 가드레일**"로 수용리스크에서 **필수로 승격**한 항목. 코드는 있으나 기본 배포에서 **비활성 + 값 주입 불가** → GA하면 비용 폭증 무방비.
- **수정**: 배포 템플릿·`.env.example`·docker-compose.prod에 실측 기반 값 배선 + readiness가 프로덕션에서 0/미설정을 경고. (값 산정은 오너 결정.)

### H5. retell·비전 캐릭터·regenerate/inpaint가 크레딧·전역예산 미적용 유료 LLM 경로 → 예산 가드 우회 `[CTO 실측(retell) + 3렌즈]`
`books.py:1147`(retell) · `characters.py:671`(from-photo/drawing 비전 LLM) · `books.py:739`(regenerate/inpaint 커버리지 갭)
- retell 경로에 `use_credit`·`consume_daily_generation_budget` 호출 0건(create_book :458은 둘 다 호출). 비전 캐릭터 생성·페이지 재생성·인페인트도 동일하게 예산 미계량.
- 설령 H4 예산을 켜도 이 경로들은 카운터를 통과하지 않아 **전역 상한을 우회하는 무계량 청구 채널**. X-User-Key 무제한이라 볼륨 무제한.
- **수정**: 실비용 발생 엔드포인트 전수에 예산 consume(+크레딧 정책) 적용. "한도 검사 엔드포인트별 전수" 게이트.

### H6. retell 책이 원본과 S3 이미지 키 공유 → 둘 중 하나 삭제 시 남은 책 삽화 전량 404 `[CTO 실측]`
`apps/api/src/routers/books.py:1189,1204`
- retell은 텍스트만 재생성하고 `cover_image_url=source.cover_image_url`·`image_url=src_page.image_url`을 **그대로 복사**(동일 S3 객체 참조). 단건 삭제(`collect_book_image_keys`→파기)는 배타 소유 가정 → 원본/리텔 중 하나 삭제 시 공유 객체 파기 → 남은 책 표지·전 페이지 404.
- **수정**: retell 시 이미지 객체 복제(별도 키) 또는 참조카운트, 삭제 시 공유 참조 확인.

### H7. streak '오늘의 동화 생성'이 캐릭터 소유권·사진 동의 게이트 생략 (create_book과 두 벌 규칙 드리프트) `[3렌즈 93/90/82]`
`apps/api/src/routers/streak.py:247`
- `/v1/streak/today/generate`가 create_book이 강제하는 캐릭터 소유권 검증과 JIT 사진 동의 게이트를 모두 건너뜀 → 타인 캐릭터로 생성 시도 + 동의 없는 아동 사진 캐릭터로 생성 가능.
- **수정**: create_book과 동일한 소유권·동의 게이트를 공용 헬퍼로 추출해 양 경로 공유.

### H8. from-photo/from-drawing이 아동 사진을 DB 커밋 전 S3 업로드 → 실패 시 어떤 파기 경로도 닿지 않는 고아 아동 사진 `[3렌즈 95/90/74]`
`apps/api/src/routers/characters.py:712`
- 아동 사진을 S3 업로드(외부 부작용) 후 DTO 검증·DB insert(로컬 커밋). 검증 실패·DB 오류·멱등 race 패자 시 **캐릭터 행 없는 고아 사진** 잔존 → 계정삭제·동의철회로도 파기 불가(행이 없어 URL 역산 불가).
- **수정**: fail-closed 로컬 레코드 선기록(또는 outbox/멱등키)로 복구 가능하게, 또는 커밋 성공 후 업로드.

### H9. 프로덕션 엣지(nginx) TLS 미구성 — HTTP 평문 전용 `[3렌즈 96/85/60]`
`infra/nginx/nginx.conf:57` · `docs/DEPLOYMENT.md`
- 443 리스너 전체 주석 처리, HTTP→HTTPS 리다이렉트·HSTS·인증서 자동화 부재, DEPLOYMENT.md에 TLS 절차 0회. X-User-Key(유일 자격증명)·아동 콘텐츠가 평문 전송.
- **수정**: TLS 종단(cert 자동화)+HSTS+리다이렉트 배선 및 배포 문서화. (배포 인프라라 오너 실환경 작업과 병행.)

---

## 🟡 MEDIUM

| # | 파일:라인 | 요약 | 렌즈 |
|---|-----------|------|------|
| M1 | `mobile/.../user_service.dart:13` | X-User-Key(유일 bearer)를 평문 SharedPreferences 저장 + Android allowBackup 백업 포함 → 기기이전/백업 탈취 시 계정 탈취. Keychain/Keystore 미사용 | 96/90/89 |
| M2 | `services/credits.py:343` | `clawback_credits` 트랜잭션 밖 check-then-write, clawback 타입만 부분유니크 인덱스 부재 → 동시 중복 환불 웹훅에서 크레딧 이중 회수 | 95/88/85 |
| M3 | `routers/iap.py:469` | 구독 환불 clawback이 '실지급액' 아닌 플랜 고정액 회수 → 0지급 영수증(restored/already_subscribed) 환불 시 무고한 크레딧 차감 | 92/88/85 |
| M4 | `services/iap_verifier.py:388` | Google 라이선스/테스트 구매(purchaseType=0)를 운영에서 무결제로 크레딧·구독 지급 (Apple sandbox 차단과 비대칭) | 95/90/85 |
| M5 | `services/iap_verifier.py:149` | Apple 영수증 bundle_id 추출만·미검증 → master shared secret 하 타 앱 영수증 수용(cross-app 리플레이) | 95/82/85 |
| M6 | `apps/api/Dockerfile:64` | 프로덕션 uvicorn 기본 액세스 로그가 공유 토큰 전문 기록 → 앱·nginx의 capability URL 마스킹 무력화(로그 접근자 무인증 재생) | 92/93/88 |
| M7 | `routers/consent.py:189` | 동의 철회가 잡·스토리초안·이미지프롬프트(아동 얼굴 텍스트 묘사·이름)를 DB에 잔존 | 95/93/85 |
| M8 | `routers/users.py:95` | 계정삭제·철회 스토리지 파기가 커밋 후 in-memory 키에만 의존 → 중단 시 아동 PII 영구 고아 + 재시도가 success 위장(unknown 결과≠성공) | 93/90/85 |
| M9 | `routers/consent.py:91` | photos=false 재-grant(동의 항목 해제)가 기수집 아동 사진·파생물 미파기 → 철회 의미론 이원화(PIPA) | 95/92/82 |
| M10 | `routers/books.py:458` | 전역 예산이 요청검증·멱등·동의·소유권 검증 **전**에 소진(consume-before-validate) → 비용0 무효요청 스팸으로 전 사용자 429 유발(가드레일이 DoS 벡터로 역전) | 96/78/80 |
| M11 | `routers/books.py:492` | `max_pending_jobs`가 전 사용자 합산 전역 카운터 → 공격자가 큐 100건 채워 전 사용자 503(공유자원 고갈) | 95/88/72 |
| M12 | `services/orchestrator.py:482` | 생성 잡 실패 시 이미 S3 영속화된 이미지가 추적불가 고아로 잔존(정리·기록 없음, 아동 얼굴 파생 포함) | 93/90/70 |

---

## ⚪ LOW / 자세

- `routers/books.py:264` — 크레딧 차감/환불이 잡 상태전이와 별도 트랜잭션 → 크래시 창에서 무성 크레딧 유실(대사 경로 없음)
- `routers/iap.py:554` — verify/웹훅 커밋 인터리브 시 orphan 웹훅 이벤트 영구 미적용(재적용 스킵+스윕 없음)
- `core/exceptions.py:331` — 예외 핸들러 5곳이 `_redact_path` 우회 → 공유 토큰이 구조화 로그로 유출(마스킹 규칙 이원화)
- `routers/books.py:895` — 인페인트 마스크 업로드에 크기/콘텐츠타입 검증 없음 + 파기 경로 부재(영구 고아)
- `routers/library.py:222` — 단건 책 삭제가 스토리지 파기 실패(아동 likeness 잔존)를 무조건 success 응답
- `routers/voice_profiles.py:244` — 음성 프로필 PATCH 파기 순서 버그(교체 전 샘플 잔존, 철회+교체 동시 시 새 파일을 오파기)
- `routers/voice_profiles.py:176` — `sample_audio_url`이 호출자 prefix 소속인지 미검증 → 파기 시 임의 버킷 객체 삭제 프리미티브(IDOR)
- `services/orchestrator.py:1377` — 동시 재생성/인페인트 시 fence 없는 `image_url` write-back → 아동 likeness 고아
- `routers/iap.py:614` — 웹훅 인증이 쿼리스트링 정적 토큰 허용 + nginx 액세스 로그 기록, 타임스탬프 창·본문 서명 없음
- `routers/pronunciation.py:97` — 발음 평가가 book_id 소유권 미검증(형제 write 경로 IDOR 불변식 누락)
- `services/iap_verifier.py:395` — Google 응답 orderId 부재 시 트랜잭션 매칭 스킵 → 리플레이 dedup 무력화
- `routers/iap.py:71` — `_subscription_expired`가 expires_date_ms 부재를 '만료 아님'으로 처리(fail-open 여지)
- `services/storage.py:131` — `key_from_public_url`이 현재 prefix만 인식 → 도메인 변경 시 기존 전 객체 파기가 조용히 no-op
- `mobile/.../credits_screen.dart:777` — purchaseID 부재 시 시간기반 가짜 transaction_id → 멱등성 파괴(C1 동반, 위 참조)
- `mobile/.../parental_control_service.dart:71` — 부모 게이트가 두 자리 덧셈(앱 타깃 7-9세가 통과 가능) + 통과 세션 30분 영속(시계 되돌림 취약)
- `mobile/.../settings_screen.dart:570` — 스크린타임 일일 한도 변경·저장이 부모 게이트 밖(토글만 게이트)
- `core/consent.py:60` — photos-only 동의 행(granted=false)이 사진 게이트 통과 → 필수 동의 없이 아동 사진 수집

## 🔁 수용 리스크 재확인 (악화 없음 — 로드맵 유지)
- `services/storage.py:347` — 아동 사진·가족 음성이 만료 없는 무인증 공개 URL(presigned 미사용). **오너 버킷 ACL 확인 미완**(prior #2). 서버 내부 read·프록시가 공개접근에 의존해 '비공개 전환(런북 정상상태)'이 기능을 조용히 파괴하는 tension 존재.
- `core/rate_limit.py:117` — 레이트리미터 Redis 장애 fail-open(prior #8). 전역 예산과 동일 Redis 공유 = 단일 장애점.
- `main.py:203` / `nginx.conf:155` — Swagger/OpenAPI 무인증 공개(prior #10).
- `services/iap_verifier.py:285` — IAP 업스트림 오류 시 str(exc) 원문이 400 details로 노출(정찰 표면).

## ⏸ Deferred (제품 결정 — 결함 아님)
- 광고 보상 지급(`db.py:571` AdRewardLog만 존재, 서버검증 엔드포인트 없음) · POD 결제 수금(`pod.py:154`) · IAP 취소/환불 동기화가 커스텀 웹훅 스키마 의존(스토어 어댑터 부재, `iap.py:48`) · IAP 웹훅 Apple JWS/Google RTDN 서명 미검증(`iap.py:597`) · 생성 이미지 출력(비주얼) 모더레이션 미배선(`orchestrator.py:933`).

---

## 견고 확인 (반증으로 기각되었거나 직접 확인)
- **크레딧 원자 차감**: `use_credit`이 `WHERE credits >= amount` 조건부 UPDATE로 동시 이중차감 차단(DB 직렬화). 환불은 `uq_credit_transactions_refund` 유니크+앱체크 이중.
- **CORS**: 프로덕션에서 `*`+credentials·미설정 모두 빈 origin fail-closed(main.py:278). (콤마목록 내 순수 '*'만 미차단 = 오설정 의존 저위험, §rejected.)
- **데이터 삭제 FK 정리**: `purge_book_children`가 자식 테이블 전수 + `collect_book_image_keys`로 이미지 키 역산 파기.
- **SSRF**: `_is_url_allowed` 도메인 allowlist + 사설IP/루프백/DNS실패 fail-closed. (단 `storage.py`·`pdf.py` 두 벌 정의 드리프트는 자세 항목.)
- **IAP 만료 리필**: `expires_date_ms` 추출 존재(C1/MA1 수정 유지).

## 방법 & 한계 (정직 보고)
- 13차원 finder(authz·money-credits·money-iap·pii-consent·injection-ssrf·failopen·webhook·share·ratelimit·storage·config-cors·mobile·cross-cutting) × 각 finding 3렌즈 반증. 66 원시 → 53 생존(80% 통과율 — 오탐 사전확률 보정이 유효했음).
- **⚠ 멀티에이전트 비결정성**: 헤드라인 C1(iOS IAP)이 워크플로 **재실행 중 finder 재추출로 최종 출력에서 누락**됐다. CTO가 별도로 ground-truth(플러그인 CHANGELOG·JWS 포맷·백엔드 legacy 경로) 확정해 보존. → **자동 감사 출력을 단일 정본으로 신뢰하지 말 것**의 실증. C1·H1·H4·H5·H6은 CTO가 직접 file:line·외부 사실로 재확정, 나머지는 3렌즈 검증값(표의 conf).
- 미실행: 실키/실기기 라이브 재현(최종 E2E 대기), 실PG FK 위반 실증(H1은 코드+독스트링 근거로 확정).

## 권장 수정 순서
1. **C1(iOS 결제)** — 출시 절대 차단. StoreKit2 signed-transaction 검증으로 백엔드 이관(또는 SK1 강제 임시책) + 실기기 샌드박스 관통 검수. credits_screen.dart:777 멱등성 동반 수정.
2. **H1·H2·H8·M7·M8·M9(아동 PII 파기권)** — 동의 철회/삭제 경로의 FK 정리·다중캐릭터 책·고아 사진·파생 텍스트·durable 파기 레코드. 규제(PIPA/COPPA) 직결.
3. **H3·M2·M3·M4·M5(결제 정합)** — 구독 재활성·clawback 이중회수·환불액 연동·Google 테스트구매·bundle_id 검증.
4. **H4·H5·M10·M11(비용 DoS)** — 예산 가드 배선·활성화 + 무계량 LLM 경로 전수 계량 + consume-after-validate.
5. **H9·M1·M6 + 자세(L)** — TLS·모바일 자격증명 보안저장·로그 토큰 마스킹.
