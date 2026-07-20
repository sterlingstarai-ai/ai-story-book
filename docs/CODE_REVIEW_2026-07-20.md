# AI Story Book — 전체 코드베이스 적대적 감사 (2026-07-20)

> 방법: 11개 도메인 파인더 + 갭 라운드 → dedup → **모든 finding 3렌즈(code/trigger/impact) 적대 반증, critical/high는 2차 독립 머더보드**. 141개 에이전트 실행.

> 원시 140건 → dedup 93건 → **확정 86건 / 기각 7건**.

> 확정 분포: 🔴 치명 3 · 🟠 높음 28 · 🟡 보통 34 · ⚪ 낮음 21


---


## 🔴 CRITICAL — 출시 차단

### 1. IAP 복원(restore) 분기가 1회 결제를 무한 수익화 — 복원마다 월간 크레딧 재지급 + 이전 소유자 구독 미취소 + 락 부재 동시 복원 이중 발급
`apps/api/src/routers/iap.py:204`  · src: money-credits, iap-webhooks

- **주장**: store_transaction_id가 동일한 기존 영수증을 다른 user_key가 재검증하면 restore 분기(198-221행)에 결함 3개가 겹친다. (a) existing.user_key를 호출자로 재바인딩하고 create_subscription(services/credits.py:421-429)을 호출하는데, 이는 매번 새 Subscription 행을 만들며 plan_info['credits_per_month'](premium 30개)를 add_credits로 지급한다 — reference_id가 매번 새 subscription.id라 어떤 유니크 제약에도 걸리지 않아 지급 횟수 제한이 전혀 없다. (b) previous_user_key가 보유한 기존 active 구독을 취소하지 않아 1회 결제로 서로 다른 user_key에 active 구독이 무한 증식하고, periodic_credits(services/periodic_credits.py:83-137)가 각 행에 매 30일 크레딧을 영구 리필한다 — 재바인딩으로 영수증 소유자가 마지막 key로 바뀌므로 이후 환불 웹훅은 옛 구독을 건드리지 못해 orphan-active로 영구 면역. (c) 복원 분기는 락/CAS 없는 SELECT 후 UPDATE라(영수증이 이미 존재해 store_transaction_id UNIQUE도 안 걸림) 동시 두 restore 요청이 모두 성공해 이중 구독이 발급된다. user_key는 X-User-Key 헤더로 클라이언트가 임의 UUID로 완전 통제(core/dependencies.py:15-26).
- **트리거**: 유료 구독 1건 보유 사용자가 같은 receipt_data(Apple)/purchase_token(Google)으로 user_key A→B→A→B(또는 신규 UUID 반복) 교대로 POST /v1/iap/verify 호출 — 스토어는 같은 영수증을 몇 번이든 verified로 재검증(iap_verifier.py:136,215). 두 기기(재설치·기기변경) 동시/순차 복원의 정상 사용자도 복원 때마다 중복 지급.
- **영향**: 단일 결제(₩14,900)로 크레딧·구독 무한 발행(호출당 premium 30크레딧, 권당 원가 ~$0.48) + 다수 active 구독의 매월 영구 리필 + 환불 웹훅 면역 — 직접적·자동화 가능한 무제한 매출 손실.
- **재현**: 1) X-User-Key=A로 premium 영수증 verify → sub A active, +30. 2) X-User-Key=B로 동일 영수증 verify → status=restored, sub B active, B에 +30, sub A는 여전히 active. 3) A로 재호출 → 다시 restored, A에 +30. 반복으로 무한 지급. select(Subscription).where(status='active')가 다수 행 반환, grant_due_refills가 전부 리필. 병렬 restore(B,C 동시)로 이중 구독도 확인.
- **수정**: 복원 시 영수증 행을 SELECT ... FOR UPDATE(또는 소유권 조건부 UPDATE CAS)로 직렬화하고, 이전 소유자의 active/cancelled 구독 만료 처리 + 새 구독 생성/재활성을 단일 트랜잭션으로 수행. restore 경로는 구독 재활성만 하고 크레딧 재지급 생략(create_subscription에 grant_credits 파라미터), 또는 구독 크레딧 지급 reference_id를 store_txn+기간(f"{store_txn}:{period_start}")으로 바꾸고 부분 유니크 인덱스로 기간당 1회 지급을 DB에서 강제.

### 2. 파이프라인 최종 실패(mark_job_failed) 시 크레딧 미환불 — job_monitor는 이미 failed인 잡을 다시 안 봐 실패마다 유저 크레딧 영구 소실
`apps/api/src/services/orchestrator.py:171`  · src: money-credits, orchestrator-jobs, silent-failures

- **주장**: 잡 생성 시 크레딧 1개를 선차감(_create_job_with_credit, reference_id=job_id, routers/books.py:242)하지만, 오케스트레이터의 정상 실패 경로인 mark_job_failed(orchestrator.py:171-189, start_book_generation 381/385행 catch에서 호출)와 tasks.py:23-38 _mark_job_failed_async는 refund_for_job을 호출하지 않는다. refund_for_job의 호출처는 큐 등록 실패(books.py:519)와 job_monitor._mark_job_failed(job_monitor.py:190)뿐인데 monitor의 스캔 쿼리(91-118행)는 status in ('queued','running')만 조회하므로 워커가 직접 failed로 마킹한 잡은 영원히 환불 대상이 아니다. job_monitor.py:186 주석('silent 크레딧 손실을 막는다')이 보여주듯 실패 잡 환불이 설계 의도인데 가장 흔한 실패 경로에만 빠져 있다.
- **트리거**: 프로덕션에서 SAFETY_INPUT 거부, LLM 429/5xx/JSON 불량, 이미지 25% 초과 실패(orchestrator.py:675), SAFETY_OUTPUT, STORAGE_UPLOAD_FAILED, DB_WRITE_FAILED, soft_time_limit 도달 등 모든 인-파이프라인 최종 실패 → mark_job_failed → 환불 없음.
- **영향**: 돈 손실: 실패한 생성 1건당 유료 크레딧 1개 무단 소모. LLM/이미지 API 일시 장애 시간대에는 그 시간대 모든 유저의 크레딧이 조용히 증발 — 출시 직후 환불 CS·스토어 리뷰 리스크 직결. 같은 실패라도 모니터가 잡으면 환불되고 정상 경로면 안 되는 비일관 처리.
- **재현**: 크레딧 1개 유저로 POST /v1/books (LLM mock이 5xx 반환 또는 이미지 4회 연속 실패하도록) → 잡 status=failed 확인 → credit_transactions에 usage(-1, reference_id=job_id)만 있고 refund 없음, user_credits.credits==0. job_monitor 다음 사이클에도 환불 없음.
- **수정**: orchestrator.mark_job_failed와 tasks._mark_job_failed_async에서 잡 실패 커밋과 같은 트랜잭션으로 credits_service.refund_for_job(user_key, job_id) 호출(이미 멱등 헬퍼 존재). SAFETY_INPUT 실패에 과금 유지가 제품 결정이라면 해당 코드만 예외로 명시.

### 3. IAP: 서버 검증 실패 시에도 finally에서 completePurchase — 소모성 결제 영구 유실
`apps/mobile/lib/screens/credits_screen.dart:771`  · src: mobile-flutter

- **주장**: _handlePurchaseUpdate가 verifyIap 실패(네트워크 오류·서버 5xx·검증 거부)와 무관하게 finally 블록에서 무조건 iapService.completePurchase(purchase)를 호출한다. 스토어 트랜잭션이 finish/acknowledge되면 재전달이 중단되므로, 서버가 크레딧을 지급하지 못한 소모성 크레딧팩 결제는 복구 경로가 없다(소모성은 restorePurchases 대상이 아님). Android는 buyConsumable(autoConsume: true)(iap_service.dart:57)라 스트림 도착 시점에 이미 소비되어 같은 문제가 상시 존재.
- **트리거**: 사용자가 크레딧팩 구매 → 스토어 결제 성공 → POST /v1/iap/verify 호출 순간 네트워크 순단·서버 일시 장애 → catch에서 '검증 실패' 스낵바 → finally에서 completePurchase 실행.
- **영향**: 사용자가 돈을 냈는데 크레딧 미지급, 앱·서버 어느 쪽에도 재시도 수단 없음(트랜잭션 소멸). 출시 직후 환불 요청·별점 테러 직결되는 돈 유실.
- **재현**: credits 화면에서 credit_pack_5 구매 → verifyIap 요청을 프록시로 차단(또는 서버 다운) → '결제 검증 실패' 표시 → 앱 재시작해도 purchaseStream에 해당 트랜잭션 재전달 없음(이미 completed) → 크레딧 0 증가.
- **수정**: completePurchase를 verifyIap 성공 후에만 호출(검증 실패 시 pending 유지 → 다음 실행에서 재전달·재검증). autoConsume을 false로 바꾸고 서버 검증 성공 후 소비. 미검증 트랜잭션 로컬 큐 저장 후 재시도.


## 🟠 HIGH

### 4. 운영 compose가 TTS/STT를 mock 기본값으로 배포 + readiness가 tts/stt 미검사 — 무음 가짜 오디오·가짜 발음점수가 성공으로 서빙 (silent fallback 금지 규범 위반)
`apps/api/src/core/config.py:64`  · src: silent-failures, docs-ops

- **주장**: tts_provider/stt_provider 기본값이 'mock'(config.py:64,70)이고 infra/docker-compose.prod.yml:46,110은 TTS_PROVIDER=${TTS_PROVIDER:-mock}으로 운영에서도 mock을 기본 주입한다(STT는 아예 미주입). TTSService._get_provider(tts.py:201-210)·STTService._get_provider(stt.py:178-184)는 미지/오타 값도 조용히 Mock으로 폴백한다. main.py의 readiness(434-437)는 llm/image 키만 검사하고 tts/stt는 게이트하지 않는다. DEPLOYMENT.md '운영에서 silent fallback 금지, 누락 설정은 명시적 기능 비활성 또는 배포 실패로 표면화' 규범(115-121행)과 충돌하고, 운영 런북 §7 live-key 대기 목록에도 TTS/STT가 없어 배포 게이트 어디에도 걸리지 않는다.
- **트리거**: 운영 env에 TTS_PROVIDER/STT_PROVIDER 미설정 또는 오타(예: 'eleven-labs') 상태로 배포 — readiness는 healthy.
- **영향**: 유료(무료플랜 차단) 오디오 기능이 16바이트 무음 MP3를 생성·S3 업로드·page.audio_url에 영구 저장(성공 마킹, 이후 캐시돼 재생성도 안 됨). 발음 평가는 고정 목업 문장('이것은 목업 발화 문장입니다')과 대조 채점되어 pronunciation_logs에 가짜 점수 축적. 모두 silent — 스토어 리뷰 리스크.
- **재현**: TTS_PROVIDER 미설정으로 기동 → /health/ready 200 healthy → POST /v1/books/{id}/audio → page.audio_url_ko가 무음 스텁 MP3 URL로 저장됨.
- **수정**: testing=False에서 tts_provider/stt_provider가 'mock'이거나 인식 불가 값이면 readiness unhealthy(_build_readiness_payload에 추가) + _get_provider는 미지 값에 raise(폴백 금지). prod compose 기본값 'mock' 제거(의도적으로 끌 거면 원격 config로 기능 플래그 명시 비활성).

### 5. 글로벌 제품인데 모든 '하루/월' 경계가 KST(UTC+9) 고정 — 비한국 사용자 스트릭·일일/월간 한도·리포트 전면 오작동 (규범 충돌: 보고 후 결정)
`apps/api/src/core/utils.py:9`  · src: time-streak, db-migrations

- **주장**: LOCAL_TZ_OFFSET=+9h 고정이 to_local_date/local_today/local_day_bounds_utc/local_month_bounds_utc 전부를 지배하고, 이 헬퍼가 스트릭 판정(services/streak.py:134,244,288,451), 읽기 리포트(streak.py:545), 오늘의 동화 회전(streak.py:452), 무료플랜 일일/월간 생성 한도(routers/books.py:444,95)에 모두 쓰인다. user_settings에 timezone 컬럼이 없고(models/db.py:416-430) 사용자별 하루 경계 수단이 전무하다. CLAUDE.md가 선언한 '글로벌·다국어 제품'과 정면 충돌하며, docs/FOUNDER_DECISIONS_PENDING.md에 타임존 관련 보류 결정도 없어 유예된 제품 결정이 아니라 한국우선 시절 잔재 설계 결함이다.
- **트리거**: KST 외 시간대 사용자의 모든 POST /v1/streak/read, GET /v1/streak/info, GET /v1/streak/today, POST /v1/books(무료 한도). 예: 미 서부(UTC-7) 사용자는 현지 오전 8시에 '하루'가 리셋된다.
- **영향**: 핵심 리텐션 기능 파손: (a) 매일 읽어도 스트릭 끊김 — LA 사용자가 월 오전 7시(KST 월 23:00), 화 오전 9시(KST 수 01:00)에 읽으면 days_since=2로 스트릭 리셋. (b) 현지 하루 중간에 read_today가 false로 뒤집혀 이중 유도/혼란. (c) 무료 일일 생성 한도가 현지 한낮에 리셋되어 하루 2배 생성 가능(비용 누수) 또는 저녁에 오차단. (d) 주간/월간 부모 리포트 날짜 귀속 오류, 마일스톤 보상 시점 왜곡.
- **재현**: 월요일 07:00 PDT(UTC 14:00, KST 월 23:00) POST /v1/streak/read → streak=1. 화요일 09:00 PDT(UTC 16:00, KST 수 01:00) POST /v1/streak/read → days_since=(수-월)=2 → current_streak가 1로 리셋. 또한 07:50/08:10 PDT 사이에 GET /v1/streak/info의 read_today가 true→false로 뒤집힘.
- **수정**: 규범 충돌이므로 보고 후 결정: (a) user_settings에 timezone(IANA) 컬럼 추가(온보딩/기기 수집, 기본 Asia/Seoul), local_* 헬퍼 4종에 tz 파라미터를 추가해 호출부(streak·books 한도·리포트)가 사용자 타임존을 전달하도록 일괄 변경(DST는 zoneinfo로, 고정 offset 덧셈 금지 — read_date는 이미 UTC라 마이그레이션 불필요), 또는 (b) 출시 범위를 KST 기준으로 명시(문서 갱신).

### 6. 스토리 언어 5개(ko/en/ja/zh/es) vs 오디오·발음 표면은 ko/en만 — ja/zh/es 책은 한국어 보이스로 합성된 오디오가 영구 캐시
`apps/api/src/routers/books.py:1316`  · src: silent-failures, contract-consistency, mobile-flutter

- **주장**: 계약 Language enum과 스토리 생성은 ko/en/ja/zh/es를 지원하지만: (a) 오디오 일괄 생성 _generate_audio_pages는 text_by_language['ko'] = text_ko or text로 폴백(books.py:1315-1320)하므로 ja/zh/es 책(text_ko 없음)은 원문이 'ko' 슬롯으로 들어가 TTS가 ko-KR 보이스로 합성(tts.py:51-54, ko/en 외 미지원)하고 결과가 audio_url_ko·audio_url에 성공으로 영구 저장·캐시된다. (b) 페이지 오디오 조회는 language 패턴 ^(ko|en)$(books.py:1395)로 ja 요청 시 422. (c) 발음 평가도 ko/en 외 400 거부(pronunciation.py:135-136). (d) 모바일 뷰어 _selectedLanguage는 'ko' 기본·ko/en 토글뿐이고 BookResult 모델에 책 언어 필드가 없어 책의 실제 언어로 요청 자체가 불가(viewer_screen.dart:67,670,908). (e) 발음 연습 화면은 evaluatePronunciationAudio를 language:'ko' 고정으로 호출(pronunciation_practice_screen.dart:131)해 en 책조차 한국어 STT로 전사·채점된다.
- **트리거**: 일본어 UI(공식 l10n) 사용자가 ja 책을 만들고 낭독/발음 버튼을 누름 — 출시 타깃 시장의 1차 경로. zh/es도 동일.
- **영향**: 5개 지원 스토리 언어 중 3개에서 낭독이 알아들을 수 없는 오디오로 동작(3-5세 비독자에겐 유일한 소비 수단 파손), 유료 TTS 비용 소모 + 잘못된 결과가 캐시되어 이후에도 계속 제공. 발음 연습은 엉터리 전사·저점으로 pronunciation_logs 오염. 글로벌 핵심 기능이 신규 3개 언어에서 전부 파손.
- **재현**: language=ja로 책 생성 → 오디오 생성/재생 → Google TTS 페이로드가 languageCode=ko-KR + 일본어 텍스트로 전송됨 확인, audio_url_ko에 저장. GET .../audio?language=ja → 422. 영어 문장 발음 평가 → 한국어 음차 전사·점수 급락.
- **수정**: audio/pronunciation의 language 허용값을 Language enum과 일치시키고 TTS 언어 코드 매핑(ja-JP/cmn-CN/es-ES) 추가, 오디오 합성 시 책의 language를 기본 슬롯으로 사용(text_by_language에 book.language: page.text). 지원 외 언어는 오디오 미생성+asset_status 명시. 책 응답에 language 필드 추가(BookResult 파싱 포함), 뷰어·발음 화면이 책 언어를 전달. 계약도 함께 갱신.

### 7. IAP 웹훅이 트랜잭션과 무관하게 '사용자의 최신 구독'을 취소/만료 — 업그레이드 후 옛 구독 알림이 현재 유료 구독을 죽임
`apps/api/src/routers/iap.py:353`  · src: money-credits, iap-webhooks

- **주장**: _apply_webhook_status는 cancelled/expired/refunded 처리 시 해당 영수증(transaction)과 연결된 구독이 아니라 select(Subscription).where(user_key==receipt.user_key).order_by(created_at.desc())의 첫 행 — 즉 그 사용자의 가장 최근 구독 — 의 status를 바꾸고 expired/refunded면 current_period_end를 now-1s로 강제한다. 영수증→구독 연결(FK/subscription_id)이 없어 어느 상품의 알림인지 구분하지 못해 임의 매칭된다.
- **트리거**: 사용자가 basic(영수증 T1) 구독 후 premium(영수증 T2)으로 업그레이드하면 create_subscription이 서버측 basic을 cancel하지만, 스토어는 이후 T1에 대해 expired/refunded 알림을 정상 발송 → 웹훅이 T1 영수증을 찾고 '최신 구독' = 방금 결제한 premium을 expired 처리.
- **영향**: 돈을 내고 있는 현재 구독의 entitlement 즉시 소멸(current_period_end=now-1s) + periodic_credits 월간 리필 중단(사용자 대면 장애·환불/CS). 반대 방향으로는 옛 free 구독 행이 최신일 때 유료 구독 알림이 free 행에 적용되어 유료 구독이 취소 동기화에서 누락(환불됐는데 리필 지속)될 수도 있다.
- **재현**: user_key U: iap/verify(subscription_basic, T1) → iap/verify(subscription_premium, T2) → POST /v1/iap/webhook/apple {transaction_id: T1, status: "expired"} → subscriptions에서 premium 행이 status=expired, period_end<now가 됨을 확인. 이후 get_active_subscription(U)이 None 반환.
- **수정**: IAPReceipt에 subscription_id 컬럼을 추가해 verify/restore 시 생성한 Subscription.id를 기록하고, 웹훅은 그 구독만 갱신한다(연결이 없으면 receipt.product_id의 plan이 일치하고 store_transaction_id/period가 대응하는 구독으로 한정).

### 8. IAP 웹훅이 미기록 트랜잭션에 200 'ignored' 반환 + 클라이언트 transaction_id로만 조회 — 환불/취소 결정 영구 유실(무한 크레딧 리필)
`apps/api/src/routers/iap.py:331`  · src: money-credits, iap-webhooks, silent-failures

- **주장**: _apply_webhook_status는 IAPReceipt.transaction_id(클라이언트가 보낸 값)로만 영수증을 조회하고, 없으면 {"status":"ignored"}를 HTTP 200으로 반환한다(331-336행). 리플레이 방지 정본 키는 store_transaction_id인데 웹훅 조회는 이 컬럼을 쓰지 않는다. Apple ASSN/Google RTDN은 2xx를 받으면 전달 완료로 간주해 재시도하지 않으므로: (a) 실제 스토어 환불 통지는 구매를 스토어 식별자(original_transaction_id/orderId = store_transaction_id 컬럼)로 식별해 조회 미스 → 200 ignored → 영구 유실. (b) 구매 직후 /verify 미호출 상태(앱 크래시)나 verify 커밋 직전 도착 등 순서 역전에서도 영수증 부재 → 200 ignored → 이후 restore로 entitlement 획득해도 환불 사실 영영 미반영. (c) 자동갱신 거래(원거래와 다른 tx id)의 취소/환불도 동일 유실. 코드 주석(346-347)이 스스로 'refunded 누락 시 periodic_credits가 매월 영구 리필'이라 명시한 바로 그 누락 경로다. 전역 규칙의 'not-ready에 2xx → provider 재시도 사멸 → 결정 유실' 클래스.
- **트리거**: (a) 스토어 알림이 store 식별자로 도착하는 정상 운영 경로. (b) 구매 직후 클라이언트 크래시/네트워크 단절 상태에서 환불·만료 웹훅 선도착. (c) 자동갱신 거래의 취소/환불 웹훅.
- **영향**: 환불된 구독이 active로 남아 periodic_credits(1시간 주기)가 매 30일 크레딧을 계속 지급 — buy→refund 후 무한 무료 크레딧(직접 매출 손실). 크레딧팩 환불 회수도 누락. 웹훅 페이로드 미보존으로 감사 흔적도 없음.
- **재현**: verify로 영수증 기록(transaction_id=client T, store_transaction_id=STORE X) 후 body={transaction_id:'STORE X',status:'refunded'} 전송 → 200 'ignored', 구독 여전히 active. 또는 영수증 행 없이 webhook refunded → 200 ignored → 이후 같은 T로 verify → verified·지급, 환불 미반영.
- **수정**: 조회를 transaction_id와 store_transaction_id 양쪽으로 확장. 미기록 트랜잭션에는 재시도 가능한 5xx를 반환하거나 orphan 웹훅 이벤트를 별도 테이블에 적재해 verify 시점·주기 배치에서 재적용(reconciliation). 환불류 보안 상태는 sticky 처리.

### 9. POD 주문 생성 신뢰성 결함 — 멱등성 전무(X-Idempotency-Key 미지원·unique 없음) + 외부 부작용 먼저→로컬 커밋 나중 + 타임아웃(unknown outcome)을 확정 실패로 간주 → 실물 이중·고아 주문
`apps/api/src/routers/pod.py:88`  · src: pod-orders

- **주장**: (a) POST /v1/pod/orders는 멱등성 키를 받지 않고(openapi.json 계약도 x-user-key만 선언), order_id는 요청마다 uuid 신규 생성(108행), pod_orders에는 PK 외 unique 제약이 없다(db.py:487-509) — CLAUDE.md 규범('멱등성: X-Idempotency-Key — POST 생성 계열')과 충돌하며 books 라우터에는 동일 인프라가 이미 존재(books.py:546-563). (b) create_pod_order는 110행에서 Printful 주문을 먼저 생성한 뒤 134-135행에서 로컬 PodOrder를 커밋한다 — 커밋 실패 시 Printful draft만 남고 로컬 레코드 없음(복구 경로 없음). (c) pod_provider.py:234-238은 httpx 타임아웃(결과 미상)을 ValidationError(확정 실패)로 변환하고 hybrid는 이를 삼켜 _local_create 폴백(68-74) — Printful에 실제 생성됐을 수 있는 draft와 provider_order_id=None인 로컬 주문이 이중 존재한다.
- **트리거**: 모바일 dio 30초 타임아웃(api_client.dart:31-32) 내 응답 지연(Printful 최대 20초 + DB) → 클라이언트 에러 표시 → 사용자가 '주문하기' 재탭(_isSubmitting은 요청 종료 후 해제라 재시도 차단 못 함). 또는 Printful 성공 직후 DB 장애로 commit 실패, Printful 응답 20초 초과 + hybrid.
- **영향**: 동일 사용자의 실물책 주문이 로컬 2건 + Printful draft 2건, 또는 로컬 없는 고아 draft — 운영 확정 절차가 draft를 확정하면 실물 다중 발송·다중 청구(되돌릴 수 없는 물리적 이행) 또는 로컬 기록·청구 없는 실물 발송(원가 손실).
- **재현**: Printful 스텁 15초 지연 주입 → 클라이언트 타임아웃 후 동일 payload POST 2회 → pod_orders 2행 + Printful /orders 호출 2회(external_id 상이). 스텁 응답 25초 지연 → hybrid POST → 로컬 sync_source='local', provider_order_id=None인데 스텁 저장소엔 주문 존재.
- **수정**: X-Idempotency-Key 수용 + pod_orders에 (user_key, idempotency_key) unique 추가·충돌 시 기존 주문 반환(openapi.json 갱신). 로컬 fail-closed 레코드(status='pending_submit')를 외부 호출 전에 먼저 커밋 → Printful 생성 → 같은 행에 provider_order_id 갱신. 타임아웃은 'submit_unknown' 상태로 남기고 external_id 조회(GET /orders/@{external_id})로 대사하는 복구 경로 추가.

### 10. 계정 삭제의 스토리지 파기 실패가 이중으로 삼켜져 항상 'success·실패 0' 보고 — 아동 사진·음성 잔존이 관측 불가
`apps/api/src/routers/users.py:129`  · src: silent-failures

- **주장**: delete_book_files(storage.py:255-257)와 delete_prefix(storage.py:334-336)는 ClientError를 내부에서 삼키고 raise하지 않으므로, users.py:96-127의 try/except가 세는 storage_failures는 실제 실패에도 항상 0이다(예외 카운팅 코드가 데드코드). 응답은 항상 status:'success', storage_delete_failures:0. DB 행(book/character id)은 이미 삭제된 뒤라 실패한 S3 키를 복구할 장부도 없다. consent 철회 경로(consent.py:156-163)도 동일.
- **트리거**: DELETE /v1/users/me 실행 중 S3/R2 일시 장애·권한 오류·네트워크 단절 — 삭제는 수십~수백 객체의 다건 호출이라 부분 실패 확률이 높다.
- **영향**: PIPA/GDPR 삭제권 행사에 '완전 삭제 성공'을 보고하지만 아동 사진(characters/*)·가족 음성(voice-samples/*)·책 이미지가 S3에 무기한 잔존. 로그 외 어떤 채널로도 감지·재시도 불가 → 규제 위반이 침묵 속에 누적.
- **재현**: storage delete_objects를 ClientError로 패치 후 DELETE /v1/users/me → 응답 storage_delete_failures==0, status=='success'인데 S3 객체는 그대로 남음.
- **수정**: delete 헬퍼가 실패를 raise하거나 (성공수, 실패키목록)을 반환하도록 변경, users.py는 실패 시 삭제 장부(키 목록) 영속화 + 재시도 배치. 실패가 있으면 응답 status를 partial로.

### 11. series 관련 FK(ON DELETE 없음) 미처리 — 계정 삭제는 Series를 Book보다 먼저 DELETE, 캐릭터 삭제는 series.character_id 미해제 → IntegrityError 500으로 erasure 영구 실패
`apps/api/src/routers/users.py:85`  · src: db-migrations

- **주장**: 마이그레이션 7f3d2c4b6a10이 만든 FK 2개(books.series_id→series.id, series.character_id→characters.id, 둘 다 ON DELETE 없음=NO ACTION)를 삭제 경로들이 처리하지 않는다. (a) delete_my_data(users.py:85-86)가 delete(Series)를 delete(Book)보다 먼저 실행 — 시리즈에 속한 책이 남은 상태에서 부모 행을 지우면 Postgres가 즉시 IntegrityError → DELETE /v1/users/me가 항상 500. (b) delete_character(characters.py:419)는 db.delete(character)만 호출 — Book 쪽은 relationship으로 nullify되지만 Series는 단방향 relationship(models/db.py:109)이라 ORM이 인지 못해 commit에서 IntegrityError → 500(420-438행이 InternalServerError로 변환). tests/test_data_deletion_fk.py에 series 시나리오가 전혀 없어 미검출.
- **트리거**: 시리즈 기능(핵심 차별화 #2, orchestrator.py:1237-1244에서 Series 생성·책에 series_id 저장)을 한 번이라도 쓴 사용자의 DELETE /v1/users/me, 또는 시리즈를 만든 캐릭터의 DELETE /v1/characters/{id} — 일반 사용 경로.
- **영향**: 해당 사용자의 계정/데이터 삭제가 항상 500으로 실패(재시도 무의미) — 아동 사진·음성 등 PII 전체가 삭제 요청에도 잔존(GDPR/PIPA 삭제권 불이행). 사진 파생 캐릭터의 '삭제=원본 즉시 파기' 약속(PIPA 근거 주석 440-444행)도 이행 불가.
- **재현**: FK 활성 DB(Postgres 또는 PRAGMA foreign_keys=ON SQLite)에서: 캐릭터 생성 → 그 캐릭터로 시리즈 책 1권 생성 → DELETE /v1/users/me → delete(Series)에서 IntegrityError 500. 별도로 DELETE /v1/characters/{id} → commit IntegrityError → 500 '캐릭터 삭제에 실패했습니다'.
- **수정**: users.py에서 delete(Book)을 delete(Series)보다 먼저 실행(85↔86 교환) 또는 Series 삭제 전 update(Book).values(series_id=None). delete_character 전에 update(Series).where(character_id==id).values(character_id=None) 추가(또는 FK에 ON DELETE SET NULL 마이그레이션). test_data_deletion_fk.py에 시리즈 포함 케이스 추가.

### 12. run_step이 LLMError 전체를 비재시도 처리 — LLM_TIMEOUT·LLM_JSON_INVALID·SAFETY_OUTPUT 재시도 규범 미이행 (RETRYABLE_ERRORS 데드코드)
`apps/api/src/services/orchestrator.py:120`  · src: orchestrator-jobs

- **주장**: run_step의 예외 순서가 asyncio.TimeoutError→TransientError→'except StoryBookError: raise'→Exception인데, llm.py는 HTTP 408/429/5xx를 LLMError(LLM_TIMEOUT)(llm.py:93-107), 파싱/검증 실패를 LLMError(LLM_JSON_INVALID)(llm.py:400-413)로 던지고 LLMError는 StoryBookError 서브클래스이므로 즉시 재-raise되어 retries=2 설정이 전혀 적용되지 않는다. errors.py의 RETRYABLE_ERRORS/RETRY_COUNTS/is_retryable(errors.py:22-110)은 어디서도 참조되지 않는 데드코드이고, TransientError는 코드베이스 어디서도 raise되지 않는다. SAFETY_OUTPUT도 규범표는 2회 재시도인데 SafetyError 즉시 중단이다. CLAUDE.md 규범 에러코드 표(LLM_TIMEOUT ✅2회, LLM_JSON_INVALID ✅2회, SAFETY_OUTPUT ⚠️2회) 위반.
- **트리거**: OpenAI/Anthropic이 429 또는 일시적 5xx를 반환하거나, LLM이 스키마에 안 맞는 JSON을 1회 출력(가장 흔한 LLM 실패 모드) → 스토리/캐릭터시트/이미지프롬프트 단계에서 백오프 재시도 없이 잡 전체 즉시 실패.
- **영향**: 일시적 장애가 그대로 사용자 실패로 전파(재시도로 흡수 가능했던 실패). 크레딧 미환불 결함과 결합해 크레딧 손실까지 이어짐. 레이트리밋 상황에서 실패율 급증.
- **재현**: llm mock을 첫 호출에 LLMError(LLM_JSON_INVALID), 두 번째 호출에 정상 응답을 반환하도록 패치 → run_step(retries=2)로 generate_story 실행 → 규범상 성공해야 하나 현재 코드는 1회 시도 후 즉시 LLM_JSON_INVALID로 실패.
- **수정**: run_step의 StoryBookError 분기에서 is_retryable(e.code)이면 last_exc에 담아 재시도 루프를 계속하고, 비재시도 코드만 즉시 raise. 최종 실패 시 UNKNOWN이 아니라 last_exc의 코드를 보존.

### 13. 잡 상태 write-back에 fence 없음 — monitor가 SLA 실패+환불한 잡을 살아있는 워커가 done으로 뒤집어 '책+환불' 이중 지급
`apps/api/src/services/orchestrator.py:204`  · src: orchestrator-jobs, silent-failures

- **주장**: update_job_status(152-168)·mark_job_done(192-210)·mark_job_failed(171-189)는 현재 status/소유권/시도 세대를 재확인하지 않고 무조건 덮어쓴다. Job 테이블(models/db.py:21-54)에 fencing 토큰이 없다. 한편 job_sla_seconds=600(config.py:111) < Celery hard time_limit=720(tasks.py:74)이라 10~12분 사이에 '규칙상 아직 합법적으로 실행 중'인 잡이 존재하고, monitor는 created_at<now-600이면 SLA_BREACH로 실패 처리+크레딧 환불한다(job_monitor.py:129-137,190). 환불 회수(clawback) 경로도 없다.
- **트리거**: 큐 대기 2분+생성 9분 같은 평범한 느린 잡(이미지 저속/재시도 페이지당 90s×3회): 10분 시점 monitor 틱(5분 주기)이 SLA_BREACH 실패+환불 커밋 → 11분에 워커가 package_book 완료 → mark_job_done이 failed→done으로 덮어씀. 반대 방향: acks_late 재전달로 done 잡 재실행 시 update_job_status가 done→running으로 되돌린 뒤 실패 마킹.
- **영향**: 돈 손실: 유저가 완성된 책과 크레딧 환불을 동시에 받음(권당 원가 ~$0.48 + 크레딧 1개, 회수 로직 없음). 상태 무결성 파괴: failed↔done 플립으로 클라이언트 폴링이 실패 화면 후 완료를 표시하거나 그 반대. 멀티 인스턴스에서 재현 빈도 증가.
- **재현**: job_sla_seconds=5로 설정, generate_story에 10초 sleep 주입 → 모니터 1회 실행(failed+refund 트랜잭션 생성 확인) → 태스크 완료 대기 → Job.status=='done'이고 credit_transactions에 usage+refund 둘 다 존재(usage 1, refund 1, 책 1권 = 순비용 0).
- **수정**: 모든 write-back을 조건부 UPDATE로: mark_job_done/update_job_status는 WHERE status='running'(또는 기대 상태+retry_count 일치)일 때만 갱신하고 0행이면 stale로 간주해 중단·로그. monitor의 SLA 실패도 같은 조건부 UPDATE + 환불은 상태 전이가 실제 성공한 경우에만. done 전이 성공 시 기존 refund가 있으면 clawback_credits로 회수.

### 14. PDF 이미지 SSRF 허용목록에 s3_public_url 호스트 누락 — 운영 CDN/공개도메인 구성에서 전 삽화가 빠진 PDF를 성공 반환
`apps/api/src/services/pdf.py:250`  · src: silent-failures

- **주장**: pdf.py의 _is_url_allowed는 ALLOWED_IMAGE_DOMAINS | {s3_endpoint 호스트}만 허용(249-250)하는 반면, 책 이미지 URL은 항상 f"{settings.s3_public_url}/{key}"로 저장된다(storage.py:295). storage.py의 동일 가드(52-53)는 s3_public_url 호스트를 포함하지만 pdf.py는 누락. 차단 시 _fetch_image가 None을 반환하고(282-284) _draw_content_page는 이미지를 조용히 생략한다(153-158).
- **트리거**: s3_public_url 호스트 ≠ s3_endpoint 호스트인 운영 구성 — R2 공개 도메인(pub-*.r2.dev)·커스텀 CDN 도메인 등 CLAUDE.md가 명시한 'R2/S3 운영'의 전형적 구성. GET /v1/books/{id}/pdf 호출.
- **영향**: 유료 PDF 내보내기가 표지·본문 삽화가 전부 빠진 텍스트-only PDF를 HTTP 200으로 반환. 경고 필드 없음(로그만). 결제 사용자 전원에게 동일 발생하므로 기능 전면 불능과 동일.
- **재현**: S3_ENDPOINT=https://minio:9000, S3_PUBLIC_URL=https://cdn.example.com로 설정 → 책 생성 후 PDF 내보내기 → 모든 _fetch_image가 'Image URL not allowed' 경고 후 None → 이미지 없는 PDF.
- **수정**: pdf.py에서 storage.py의 _is_url_allowed를 재사용하거나 허용목록에 s3_public_url 호스트 추가. 추가로 이미지 로드 실패 페이지 수가 0보다 크면 5xx 또는 응답 헤더/본문에 열화 명시.

### 15. Printful 실주문 금액을 KRW로 환산해 저장하면서 통화 라벨은 'USD'로 기록 (금액 기록 1300배 오염)
`apps/api/src/services/pod_provider.py:167`  · src: pod-orders

- **주장**: pod_provider.py:167에서 Printful costs.total(USD)을 `_cost_to_krw`(269-274, ×1300 하드코딩)로 KRW 정수로 환산하고, 168에서 currency는 Printful 원통화('USD')를 그대로 반환한다. routers/pod.py:115-116이 이 쌍을 `effective_total`/`effective_currency`로 pod_orders에 영속 — 예: Printful 원가 $25 주문이 total_price=32500, currency='USD'로 저장된다. 같은 행의 unit_price/shipping_fee는 지역 테이블 값(예: US 20/5 USD 주요단위)이라 한 행 안에서 단위·통화가 불일치한다(unit_price×qty+shipping_fee ≠ total_price).
- **트리거**: POD_MODE=hybrid/strict + Printful 설정 유효 상태에서 Printful 주문 생성이 성공하는 모든 경로. 사용자 1명이 POST /v1/pod/orders 1회 호출하면 즉시 발생.
- **영향**: 실물 주문의 영속 금액 레코드(청구·환불·정산의 근거)가 통화 불일치로 오염. GET /v1/pod/orders/{id}가 이 값을 그대로 반환하므로 사용자 앱에 '32500 USD' 표시. 코드 주석상 결제/확정은 이 레코드를 보는 별도 운영 절차에서 수행되므로 잘못된 금액으로 청구될 실질 경로 존재.
- **재현**: Printful mock이 {result:{id:1, status:'draft', costs:{total:'25.00', currency:'USD'}}} 반환하도록 스텁 → POST /v1/pod/orders → DB에서 SELECT total_price, currency, unit_price, shipping_fee → (32500, 'USD', 20, 5) 확인.
- **수정**: 환율 환산 제거: Printful 금액은 원통화·원단위 그대로 저장하고 currency도 동일 소스에서 저장. 지역 견적(unit_price/shipping_fee)과 provider 실비는 별도 컬럼(quoted_* vs provider_*)으로 분리. 환산이 필요하면 환산 시점·환율을 함께 기록.

### 16. Printful 주문 payload 불완전 — 필수 city/state_code 미전송(모바일은 수집조차 안 함)으로 실주문 전멸 + 사용자 책 아트워크·파일 참조 전무(전 주문 동일 고정 sync_variant_id)
`apps/api/src/services/pod_provider.py:147`  · src: pod-orders

- **주장**: 두 가지가 겹쳐 Printful 실연동 이행이 코드로는 불가능하다. (a) _build_printful_recipient(246-267)는 name/address1/zip/country_code/phone만 전송하고 city·state_code·address2를 누락한다 — Printful Orders API는 recipient.city 필수, US/CA는 state_code도 필수라 실제 주문 생성이 400으로 거부된다. 라우터의 _normalize_shipping_address(62-85)는 city/state/line2를 보존하지만 recipient 빌더가 버리고, 모바일 폼(pod_order_screen.dart:25-29, 68-73)은 city/state/line2 입력 필드 자체가 없다. hybrid에서는 create 실패가 ValidationError로 잡혀 _local_create로 조용히 폴백(pod_provider.py:68-74)해 사용자·응답 모두 '주문 접수 성공'으로 보인다(provider_order_id=None). (b) 주문 items는 전역 설정값 PRINTFUL_SYNC_VARIANT_ID 하나와 quantity뿐(144-155행)으로, 사용자별 책(PDF·이미지) 파일 참조(files/printfile URL, book_id)가 주문 어디에도 실리지 않는다 — Printful sync variant는 스토어에 미리 업로드된 고정 디자인 상품이므로 확정 시 모든 고객에게 동일 디자인이 인쇄된다.
- **트리거**: POD_MODE=hybrid/strict + Printful 키 투입 후 모든 실주문. city가 필수 아닌 국가에서 통과되더라도 line2 누락 주소로 오배송, draft 확정 시 고정 디자인 인쇄.
- **영향**: Printful 연동이 출시 상태 그대로는 단 한 건도 올바르게 성공할 수 없음. hybrid 운영 시 '주문이 접수되었습니다'가 뜨지만 provider 주문이 생성되지 않아 실물이 영원히 미발송되는 조용한 미이행. 확정된 주문은 사용자의 동화책이 아닌 스토어 기본 디자인으로 인쇄·발송(잘못된 실물 이행 + 원가 손실 + 환불).
- **재현**: Printful 스텁이 city 부재 시 400 반환하도록 설정 → hybrid로 POST /v1/pod/orders(US 주소) → 200 + sync_source='local' + provider_order_id=None. 스텁이 받은 payload 검사 → items에 files/책 식별자 부재, sync_variant_id는 모든 주문에서 동일.
- **수정**: 모바일 폼에 city/state/line2 추가(ko/en/ja arb + gen-l10n), 서버 recipient에 address2/city/state_code 매핑 + US/CA state 필수 검증. 주문 items에 책의 인쇄용 PDF를 files(printfile URL)로 첨부하거나 최소 book_id·pdf_url을 주문 메모로 전달하고 아트워크 미첨부 주문은 확정 불가 상태로 구분. hybrid 폴백 주문은 'pending_provider' 등으로 구분 저장해 성공 위장 제거.

### 17. daily_stories.date 유니크 제약 없는 check-then-insert — 동시 요청 시 중복 행 생성 후 /streak/today가 하루 종일 전 사용자 500 (MultipleResultsFound)
`apps/api/src/services/streak.py:461`  · src: time-streak, db-migrations

- **주장**: get_today_story가 트랜잭션 밖 SELECT(455-461)로 오늘 row 부재를 확인한 뒤 INSERT(480-486)한다. daily_stories.date는 non-unique 인덱스뿐이라(models/db.py:324-336, 마이그레이션 2dd3344558db도 unique=False) 멀티 인스턴스/동시 요청이 같은 날(today_start로 정규화된 동일 값) row를 2개 이상 만들 수 있고, 이후 모든 조회의 scalar_one_or_none()이 MultipleResultsFound 예외를 던진다. CLAUDE.md 전역 규칙의 'CAS/트랜잭션 밖 check-then-write' 버그 클래스 그대로.
- **트리거**: KST 자정(15:00 UTC) 직후 홈 화면 진입 버스트 — GET /v1/streak/today는 앱 홈에서 호출되는 전 사용자 공용 엔드포인트라 새 날의 첫 요청이 여러 API 레플리카에 동시 도달하는 것이 일상. 사용자 수에 비례해 매일 발생 확률 누적.
- **영향**: 중복 row가 생긴 날은 GET /v1/streak/today와 POST /v1/streak/today/generate(routers/streak.py:146,186)가 그 날 내내 전 사용자 500 — 오늘의 동화(핵심 리텐션 루프) 전면 장애. 다음 날 자정에 자동 복구되지만 임의의 날에 재발.
- **재현**: 오늘의 DailyStory row가 없는 상태에서 GET /v1/streak/today 2개를 병렬 발사 → 둘 다 scalar_one_or_none()=None → 둘 다 INSERT+commit 성공(제약 없음) → 세 번째 GET이 MultipleResultsFound로 500. 단일 프로세스에서도 select 이후 insert 이전에 다른 세션이 동일 date 행을 insert하도록 side-effect 주입으로 재현.
- **수정**: daily_stories.date에 유니크 인덱스 추가(신규 alembic revision + 모델 __table_args__, 기존 중복 정리 포함) + INSERT를 try/except IntegrityError로 감싸 rollback 후 재조회. 방어적으로 조회를 .order_by(DailyStory.id).limit(1)+first()로 바꿔 기존 중복 데이터에도 500이 나지 않게.

### 18. JIT 사진 동의: getConsent 실패 시 기존 필수 동의를 false로 되써서 서버 동의 레코드 파기
`apps/mobile/lib/core/photo_consent.dart:17`  · src: mobile-flutter

- **주장**: ensurePhotoConsent가 getConsent() 실패 시 catch로 빈 맵을 사용하고(17-19행), 이후 grantConsent(privacy: consent['privacy']==true, ...)로 privacy=false·dataProcessing=false를 전송한다(56-60행). 서버 POST /v1/consent(routers/consent.py grant_consent)는 기존 비철회 행을 supersede하고 요청값 그대로 새 행을 만들므로, 사용자의 기존 필수 동의(granted=true) 레코드가 granted=false 행으로 대체된다. '서버의 기존 값을 echo한다'는 주석 의도가 실패 경로에서 깨진다.
- **트리거**: 사진 캐릭터 만들기 진입 순간 GET /v1/consent가 네트워크 순단·429·5xx로 실패 → (이미 사진 동의가 있어도) 동의 다이얼로그 재표시 → 사용자가 '동의' 탭 → 파괴적 overwrite 전송.
- **영향**: 필수 동의(개인정보·데이터처리)가 사용자 모르게 철회 처리됨 — GET /v1/consent가 granted=false 반환, 동의 감사추적(PIPA/COPPA 증빙) 손상. 서비스는 데이터 처리를 계속하므로 '미동의 상태에서 처리'라는 컴플라이언스 모순 기록이 남는다.
- **재현**: 동의 완료 계정으로 characters 화면 → 기내모드 토글로 GET /v1/consent만 실패시킴 → 사진 선택 → 동의 다이얼로그에서 '동의' → 서버 user_consents에서 기존 granted행 revoked_at 세팅 + privacy=false 새 행 생성 확인.
- **수정**: getConsent 실패 시 진행하지 말고 fail-closed로 중단(에러 스낵바 + 재시도). 또는 서버에 photos만 갱신하는 부분 갱신(PATCH) 경로를 추가해 필수 동의 echo 의존 제거.

### 19. JIT 사진 동의 다이얼로그(PIPA 법정 고지)가 한국어 하드코딩 — en/ja 사용자에게 읽을 수 없는 동의
`apps/mobile/lib/core/photo_consent.dart:29`  · src: mobile-flutter

- **주장**: 아동 얼굴 사진 사용 동의 다이얼로그의 제목·PIPA 5요소 고지 본문·'취소'/'동의' 버튼이 전부 한국어 리터럴이다. 프로젝트 규칙('모든 사용자 노출 문자열 ko/en/ja .arb 동시 추가, 하드코딩 금지') 위반이며, 동일 고지의 l10n 버전(consentPhotoDisclosure)은 이미 arb에 존재한다.
- **트리거**: 영어·일본어 로캘 사용자가 사진/그림으로 캐릭터 만들기 진입(characters_screen.dart:274, character_source_sheet.dart:125).
- **영향**: 아동 사진(민감정보) 국외이전·보유기간 고지를 읽을 수 없는 언어로 제시하고 동의를 받음 → 동의의 유효성(고지 후 동의) 훼손, COPPA/GDPR 관점 법적 리스크. UX상으로도 글로벌 출시 품질 결함.
- **재현**: 기기 언어 영어 → Characters → 사진으로 만들기 → 한국어 다이얼로그 표시 확인.
- **수정**: 다이얼로그 문자열을 AppLocalizations 키(신규 3종 + 기존 consentPhotoDisclosure 재사용)로 교체하고 flutter gen-l10n 재생성.

### 20. 모바일이 생성 계열 POST(/v1/books·시리즈·오늘의 동화)에 X-Idempotency-Key를 전혀 보내지 않음 — 재시도 시 크레딧 이중 차감
`apps/mobile/lib/providers/providers.dart:909`  · src: contract-consistency, mobile-flutter

- **주장**: 계약(openapi.json POST /v1/books의 x-idempotency-key)과 백엔드(books.py:559-574 멱등 dedup, CLAUDE.md '공통 헤더' 규정)는 멱등키를 지원하지만, 모바일의 유일한 책 생성 경로 BookCreationNotifier.createBook은 api.createBook(spec)을 idempotencyKey 없이 호출한다(ApiClient.createBook의 idempotencyKey 파라미터는 어느 호출부에서도 사용되지 않고, 키가 null이면 헤더 미전송 — api_client.dart:109-112). 시리즈 생성(library_screen.dart:479 createSeriesBook)·오늘의 동화(generateTodayStory)도 동일하게 키가 없다. 서버는 헤더가 있을 때만 중복 차단하고 잡 생성 시점에 크레딧을 차감한다.
- **트리거**: POST /v1/books가 서버에서 처리됐지만 응답이 30초 receiveTimeout·네트워크 순단으로 클라이언트에 도달 못함 → '생성 실패' 스낵바 → 사용자가 만들기 버튼 재탭. 로딩 화면 4분 타임아웃 후 '다시 만들기'(/create) 경로와 결합하면 확률 상승.
- **영향**: 같은 책 2회 생성 + 크레딧 2회 차감(권당 생성원가 ~$0.48 중복) — 유료 사용자 돈 손실이 사용자 과실 없이 발생. 서재 중복.
- **재현**: POST /v1/books 응답을 30초 이상 지연시키는 프록시 설정 → 앱에서 책 생성 → 클라이언트 타임아웃 에러 → 다시 생성 탭 → /v1/credits/transactions에 '책 생성' 차감 2건, jobs 2건 확인(X-Idempotency-Key가 없어 서버 dedup 미동작).
- **수정**: 생성 시도마다 uuid.v4() 멱등키를 만들어 createBook/createSeriesBook/generateTodayStory에 전달하고, 같은 시도 재제출(타임아웃 후 재탭)에는 같은 키 재사용. 백엔드 series/today 엔드포인트에도 get_idempotency_key 의존성 추가.

### 21. 클라이언트 타임아웃 예산이 서버 처리시간과 불일치 — 생성 폴링 4분(SLA 10분) + 장시간 동기 엔드포인트 일괄 30초 → 허위 실패·중복 생성
`apps/mobile/lib/providers/providers.dart:878`  · src: mobile-flutter

- **주장**: (a) jobPollingProvider가 2초 간격 폴링에 maxAttempts=120을 두어 약 4분에 TimeoutException을 던진다 — hardTimeout(10분·CLAUDE.md 전체 잡 SLA와 일치)은 maxAttempts가 항상 먼저 발화해 죽은 코드다. 예외 메시지도 한국어 하드코딩이며 loading_screen.dart:82가 error.toString()을 그대로 노출한다. (b) Dio receiveTimeout 30초(api_client.dart:32)가 모든 호출에 적용되는데, POST /retell(요청 내 동기 LLM 전권 재작성, books.py:1076), POST /characters/from-photo·from-drawing(요청 내 동기 이미지 생성, characters.py:554), GET .../audio(요청 내 TTS 합성)는 실서비스에서 30초를 상회할 수 있다 — 타임아웃 시 클라이언트는 실패 표시하지만 서버는 완주해 리소스를 만들고, 재시도용 멱등키도 없다.
- **트리거**: 이미지 재시도(페이지당 90초×3회 백오프)로 4분을 넘기는 정상 생성(스펙상 10분 허용); 실 LLM/이미지 프로바이더 지연 상황에서 리텔·사진 캐릭터 생성 실행.
- **영향**: 진행 중인 정상 잡을 실패 화면으로 표시 → '다시 만들기'가 신규 생성 유도 → 크레딧 추가 차감·서재 중복·체감 실패율 부풀림. 리텔 중복 책·아동 사진 파생 캐릭터 중복 업로드(민감 데이터 증식)·서버 비용 낭비. en/ja 사용자에게 'TimeoutException: 생성이 지연되고...' 한국어 원문 노출.
- **재현**: 이미지 프로바이더 지연 주입으로 총 5분짜리 잡 생성 → 로딩 화면이 4분에 에러 표시 → 서버 잡은 이후 done 전환 확인. 프로바이더 35초 지연 → 리텔 실행 → 클라 '리텔 실패' 스낵바, 서버 books에는 새 책 생성 → 재시도 시 중복.
- **수정**: maxAttempts를 hardTimeout(10분)과 일치시키거나 제거하고 경과시간 기준 단일 예산 사용, 타임아웃 메시지는 l10n 키로 교체. 장시간 엔드포인트별 Options(receiveTimeout: 120s) 오버라이드 + 해당 POST들에 멱등키 도입(근본적으로는 서버를 잡 큐 방식 202+폴링으로 전환 보고).

### 22. 시리즈 '다음 권'이 원작의 스타일·연령대를 버리고 watercolor/5-7로 생성됨
`apps/mobile/lib/screens/library_screen.dart:479`  · src: contract-consistency

- **주장**: 계약·백엔드 SeriesNextRequest는 style/target_age/language를 받지만(dto.py:456-458 기본값 watercolor/5-7/ko), 모바일 _createNextVolume은 characterId/topic/seriesId/previousBookId만 전송한다. 백엔드 start_series_generation은 prev_book에서 language만 상속하고(orchestrator.py:1265-1267) style·target_age는 요청 기본값을 그대로 쓴다.
- **트리거**: 사용자가 서재에서 watercolor가 아닌 스타일(예: 3d)·다른 연령대(예: 7-9)의 책으로 '다음 권 만들기' 실행 — 시리즈 기능의 일반 사용 경로.
- **영향**: 크레딧 1개를 소모해 만든 다음 권이 원작과 다른 그림체(watercolor)와 다른 연령 문체(5-7)로 나옴. '캐릭터 일관성 + 시리즈'라는 핵심 차별화 기능이 시각적으로 깨진 결과물을 유료로 제공.
- **재현**: 1) style=3d, target_age=7-9, language=en 책 생성. 2) 서재에서 다음 권 생성(주제 입력). 3) 생성된 책의 style이 watercolor, target_age가 5-7로 저장됨을 GET /v1/books/{id}/detail로 확인(언어만 en 상속).
- **수정**: 모바일: createSeriesBook에 latest의 style/targetAge(및 language)를 전달. 백엔드(심층 방어): start_series_generation에서 prev_book이 있으면 language처럼 style/target_age도 prev_book 값으로 상속하고 요청 명시값만 우선.

### 23. POD 주문 화면 견적·금액 표기가 KR 가격(18000+3000)·KRW 하드코딩 — 서버의 국가별 가격·통화를 무시해 비KR 사용자 금액 오표시
`apps/mobile/lib/screens/pod_order_screen.dart:49`  · src: pod-orders, contract-consistency

- **주장**: pod_order_screen.dart:49의 `int get _estimatedTotal => (18000 * _quantity) + 3000;`이 배송 국가와 무관하게 KR 가격으로 견적을 계산하고, l10n 문자열(app_localizations_en.dart:908 'Est. $amount KRW', ja '見込み ...ウォン', podOrderPaymentAmount의 '원/ウォン/KRW' 접미사 — app_ko/ja/en.arb 289·301행)이 통화를 KRW로 고정한다. 서버는 국가별 가격(routers/pod.py:49-59 KR=18000/3000 KRW, US=20/5 USD, JP=2500/500 JPY, 기타 USD)으로 별도 산출하고 응답에 currency를 담아 주지만 모바일은 이를 무시한다.
- **트리거**: country에 KR 이외(US/JP 등)를 입력하는 모든 글로벌 사용자가 주문 화면을 열고 주문하는 즉시 — 글로벌 출시의 정상 경로(국가 입력란 기본값만 'KR').
- **영향**: 불가역 실물 주문 직전 표시 금액이 실제 기록·청구 예정액과 통화·액수 모두 다름 — 미국 사용자는 'Est. 21,000 KRW'를 보고 주문했는데 서버 기록은 25 USD, 주문 후 화면엔 '25원'으로 표시(약 1/1400 오표시). 가격 오인 유도로 결제 분쟁·환불·스토어 리젝 리스크. 서버가 지역 가격을 구현(P1-6)했는데 클라이언트가 KR 가격을 중복 하드코딩한 이중 소스.
- **재현**: POD 화면에서 country=US, 수량 1 → 견적 '21,000원'류 표시 → 주문 생성 → 서버 응답 total_price=25, currency=USD → 화면 '결제금액: 25원' 표시 확인.
- **수정**: 주문 전 견적은 서버에 위임(GET /v1/pod/quote?country=&quantity= 추가 또는 국가 입력 시 서버 가격표 조회)하고, 표시 문자열에서 통화 접미사 하드코딩을 제거해 서버가 준 currency로 포맷(l10n 파라미터에 currency 추가, ko/en/ja 동시 수정 + gen-l10n).

### 24. 계정 삭제 확인 키워드가 '삭제' 하드코딩 — en/ja 사용자는 데이터 삭제 불가
`apps/mobile/lib/screens/settings_screen.dart:322`  · src: mobile-flutter

- **주장**: 2차 삭제 확인이 textController.text.trim() == '삭제' 로 한국어 리터럴과 비교된다. 그러나 입력창 힌트와 버튼 라벨은 l.settingsDeleteKeyword(en: "Delete", ja: "削除")로 로컬라이즈되어 있어, en/ja 사용자가 화면에 보이는 키워드를 입력하면 항상 불일치. 프롬프트(en: type "삭제")를 그대로 따르려 해도 한국어 IME가 없으면 '삭제'를 입력할 수 없다.
- **트리거**: 영어·일본어 로캘 사용자가 설정 → 계정/데이터 삭제 → 최종 확인 다이얼로그에서 힌트에 표시된 "Delete"/"削除" 입력.
- **영향**: 비한국어 사용자의 계정·데이터 삭제(DELETE /v1/users/me)가 사실상 불가능 — GDPR/PIPA 삭제권 및 App Store 계정 삭제 요건(5.1.1(v)) 위반 소지. 아동 데이터 앱이라 리스크 증폭.
- **재현**: 기기 언어 영어로 설정 → Settings → 삭제 플로우 진행 → "Delete" 입력 → 'The confirmation text does not match.' 반복, 삭제 진행 불가.
- **수정**: 비교를 textController.text.trim() == l.settingsDeleteKeyword 로 변경하고, settingsFinalConfirmPrompt(en/ja)의 '삭제' 표기도 로컬 키워드 플레이스홀더로 교체.

### 25. 배포 설정 배관 드리프트 — prod compose allowlist에 IMAGE_MODEL·STT·POD/PRINTFUL·ADMIN_API_KEY 등 미전달 + infra/.env.example·check-env에 readiness 필수 IAP 변수 누락·죽은 변수 4종
`infra/docker-compose.prod.yml:40`  · src: docs-ops

- **주장**: (a) api/worker 서비스는 IMAGE_PROVIDER·IMAGE_API_KEY 등만 전달하고 IMAGE_MODEL을 전달하지 않는다 — services/image.py:214는 gemini 경로에서 settings.image_model(기본 'dall-e-3')을 URL에 직접 사용하므로, 문서(apps/api/.env.example:81-83, FOUNDER_DECISIONS_PENDING.md A2)가 권장하는 IMAGE_PROVIDER=gemini + IMAGE_MODEL 구성 시 '.../models/dall-e-3:generateContent' 호출로 전량 실패(readiness는 image_api_key 존재만 봐 통과). 같은 allowlist에서 STT_PROVIDER/STT_API_KEY/GOOGLE_STT_API_KEY, POD_MODE/PRINTFUL_*, ADMIN_API_KEY(누락으로 운영 /v1/credits/add 항상 403), SHARE_BASE_URL도 누락. (b) readiness(main.py:361-387)가 운영 필수로 요구하는 APPLE_IAP_SHARED_SECRET/GOOGLE_PLAY_*·IAP_WEBHOOK_SECRET이 infra/.env.example에 전혀 없고 check-env.sh production 필수목록(34-45행)에도 없다. (c) 반대로 템플릿의 ENVIRONMENT·LOG_LEVEL·RATE_LIMIT·SECRET_KEY는 config.py에 대응 필드가 없는(extra='ignore') 죽은 변수다(실제 변수명은 RATE_LIMIT_REQUESTS/RATE_LIMIT_WINDOW).
- **트리거**: DEPLOYMENT.md 절차대로 infra/.env.example을 채워 check-env(PASS) → deploy하는 첫 운영 배포, 또는 gemini 이미지 프로바이더 채택 배포, 또는 운영자가 RATE_LIMIT=30으로 리밋을 올렸다고 믿는 순간.
- **영향**: gemini 채택 시 모든 책 생성이 이미지 단계에서 실패(재시도 소진 후 환불 폭주). STT는 구성 자체가 불가라 발음 연습 영구 mock. admin 크레딧 지급 불가. check-env를 통과한 배포가 다운타임을 거친 맨 끝 readiness에서 iap_* missing으로 실패하고 그 상태로 서비스는 계속 떠서 IAP 구매·웹훅 전부 거부되는 반쪽 장애 런칭. RATE_LIMIT 조정은 조용한 no-op.
- **재현**: infra/.env에 IMAGE_MODEL=gemini-3-pro-image-preview 추가 후 `docker compose --env-file infra/.env -f infra/docker-compose.prod.yml config | grep IMAGE_MODEL` → 출력 없음. infra/.env.example 복사·실값 입력 → check-env production 통과 → 배포 후 /health/ready → 503 + missing_keys에 iap_* 노출.
- **수정**: api·worker environment에 IMAGE_MODEL=${IMAGE_MODEL:-dall-e-3}·STT_PROVIDER/STT_API_KEY/GOOGLE_STT_API_KEY·POD_MODE/PRINTFUL_*·ADMIN_API_KEY(api)·SHARE_BASE_URL(api) 패스스루 추가. 템플릿에 IAP_VERIFICATION_MODE/APPLE_IAP_SHARED_SECRET/GOOGLE_PLAY_*/IAP_WEBHOOK_SECRET/ADMIN_API_KEY/USE_CELERY 섹션 추가, 죽은 변수 제거(또는 RATE_LIMIT_REQUESTS로 개명), check-env PRODUCTION_REQUIRED_VARS에 IAP 3종 추가.

### 26. 페이지 텍스트 재생성(rewrite_page_text)에 언어 미전달 — 비한국어 책이 피드백 재작성 시 한국어로 뒤바뀔 수 있음
`apps/api/src/services/llm.py:562`  · src: gap:Global multilang generation layer (the orphaned 'i18n lens'): prompt templates, i18n core, golden harness

- **주장**: call_text_rewrite는 spec.language를 받고도(orchestrator.py:1093에서 book.language로 spec 구성) 프롬프트에 전혀 사용하지 않는다. rewrite_page_text.system.jinja2에는 출력 언어 지시가 없고(다른 스토리 계열 템플릿은 language_name 지시 있음), user_prompt(562-572행)는 전부 한국어 지문이다. en/ja/zh/es 책의 revised_text가 어느 언어로 나올지 미정의이며, 한국어 지문이 지배적이라 한국어 회귀 가능성이 높다.
- **트리거**: 비한국어 책 소유자가 페이지 텍스트 재생성(mode=text/both + feedback)을 호출 → orchestrator.regenerate_page(1100행) → call_text_rewrite.
- **영향**: 영어 책 한가운데 한국어 페이지가 삽입되는 사용자 가시적 손상. text_en/text_ko 이중언어 컬럼도 갱신하지 않아(orchestrator.py:1103은 page.text만 씀) 이중언어 표시·기존 오디오와 본문이 어긋난 채 남는다.
- **재현**: language=en 책 생성 → POST /v1/books/{id}/pages/1/regenerate (mode=text, feedback="make it shorter") → 렌더된 user_prompt에 영어 유지 지시가 전혀 없음을 확인(코드 확인만으로 결정적). 라이브에서는 revised_text 언어가 보장되지 않음.
- **수정**: generate_story와 동일하게 language/language_name을 템플릿에 전달하고 시스템 프롬프트에 '모든 revised_text는 {{ language_name }}로 작성' 규칙 추가. 재작성 시 해당 페이지 text_ko/text_en 동기화(또는 무효화)도 함께.

### 27. 출력 안전성 검사(moderate_output)가 ja/zh/es에서 사실상 no-op — 신규 출시 언어 3종에 아동 안전망 부재
`apps/api/src/services/orchestrator.py:776`  · src: gap:Global multilang generation layer (the orphaned 'i18n lens'): prompt templates, i18n core, golden harness

- **주장**: moderate_output은 _MOD_FORBIDDEN_KO(759행, 한국어 표현 목록)와 _MOD_FORBIDDEN_EN_RE(752-757행, 영어 단어 경계 정규식)만 검사한다. 일본어·중국어·스페인어 금칙어 목록이 전혀 없어, 출시 언어 5종 중 3종(ja/zh/es)의 생성 텍스트는 출력 안전성 게이트를 무조건 통과한다(796행 return True). 파이프라인 설계 스펙 G단계(출력 안전성 검사)가 신규 언어에서 공백.
- **트리거**: 언어를 ja/zh/es로 지정한 모든 책 생성(POST /v1/books, /v1/streak/today/generate 등). 글로벌 롤아웃의 헤드라인 경로가 곧 트리거.
- **영향**: LLM이 ja/zh/es로 폭력·성적 표현을 생성해도(프롬프트 인젝션·모델 일탈·입력 모더레이션 우회 시) 출력 검사에서 걸러지지 않고 아동에게 그대로 노출된다. ko/en이라면 차단됐을 동일 내용이 언어만 바꾸면 통과 — 아동 대상 제품의 안전 규제·스토어 심사 리스크.
- **재현**: spec.language=ja로 스토리 생성 후 story.pages[].text에 '殺す'/'銃' 등 일본어 폭력 표현을 포함시켜 moderate_output(story, image_urls)을 호출하면 True를 반환한다(한국어 '죽여'·영어 'kill'이면 False). 단위 테스트로 즉시 재현 가능.
- **수정**: 언어별 금칙 목록(ja/zh/es) 추가 또는 비(ko/en) 언어는 LLM 기반 출력 모더레이션(언어 파라미터 전달)으로 라우팅. 최소한 story.language가 커버리지 밖이면 fail-open이 아니라 LLM 검사로 폴백.

### 28. 오늘의 동화 DAILY_THEMES가 한국어 전용 — 비한국어 사용자 홈 화면에 매일 한국어 토픽 노출 + 비한국어 생성의 시드도 한국어
`apps/api/src/services/streak.py:22`  · src: gap:Global multilang generation layer (the orphaned 'i18n lens'): prompt templates, i18n core, golden harness

- **주장**: DAILY_THEMES(22-93행)의 name·topics가 모두 한국어 고정 문자열이고 언어 차원이 없다. GET /v1/streak/today(routers/streak.py:154-159)·GET /v1/streak/themes(284-293행)가 이를 그대로 반환하며, 모바일 home_screen.dart:524·531이 themeName/topic을 원문 그대로 표시한다. POST /v1/streak/today/generate(routers/streak.py:196-204)는 request.language가 en/ja/zh/es여도 spec.topic에 한국어 토픽('새 친구 사귀기')을 넣는다. time-streak·db-migrations 파인더가 i18n 렌즈로 명시 이관한 항목.
- **트리거**: 비한국어 로케일 사용자가 홈 화면 진입(매일) 또는 오늘의 동화 생성. 스트릭은 리텐션 핵심 루프라 노출 빈도 최상.
- **영향**: 영어·일본어 UI 한복판에 매일 한국어 문자열 노출(글로벌 제품 1면). 생성 측은 LLM이 한국어 토픽을 이해해 목표 언어로 쓰긴 하나 topic 표시·기록이 한국어로 남고, 언어별 문화 맥락(예: '설날') 부적합 토픽이 그대로 시드됨.
- **재현**: GET /v1/streak/today → {"theme":"friendship","theme_name":"우정","topic":"새 친구 사귀기"} 를 en 로케일 앱이 그대로 렌더(home_screen.dart:524,531). POST /today/generate {language:"en"} → BookSpec.topic이 한국어임을 코드로 확인.
- **수정**: DAILY_THEMES를 언어 키드 구조(theme id + 언어별 name/topics)로 확장하거나, API는 theme/topic id만 내리고 표시 문자열은 모바일 .arb(ko/en/ja)로 이동. /today/generate는 request.language에 맞는 토픽 문자열로 시드.

### 29. get_today_story의 check-then-write 레이스 + daily_stories.date 유니크 제약 부재 — 중복 행 생성 시 당일 내내 500
`apps/api/src/services/streak.py:455`  · src: gap:Global multilang generation layer (the orphaned 'i18n lens'): prompt templates, i18n core, golden harness

- **주장**: get_today_story는 트랜잭션 보호 없이 '오늘 행 조회(455-461) → 없으면 insert(480-486)'를 수행한다. daily_stories.date에는 유니크 제약이 없고(models/db.py:330, alembic 2dd3344558db는 unique=False 인덱스만 생성) 멀티 레플리카 API에서 하루 첫 요청이 동시에 오면 중복 행이 생긴다. 이후 모든 호출의 scalar_one_or_none()(461행)이 MultipleResultsFound 예외를 던진다.
- **트리거**: 로컬 자정(KST) 직후 두 API 인스턴스가 동시에 GET /v1/streak/today 또는 POST /today/generate 처리 — 푸시 알림·아침 사용 피크로 현실적.
- **영향**: 중복이 한 번 생기면 그날 하루 종일 전 사용자에 대해 /streak/today와 /today/generate가 500 — 리텐션 핵심 기능 전면 장애. 데이터도 이론상 두 개의 '오늘의 동화'로 갈라진다.
- **재현**: 빈 daily_stories 상태에서 get_today_story를 두 세션이 동시에 실행(테스트: insert 직전 barrier 주입) → 행 2개 → 세 번째 호출이 MultipleResultsFound로 폭발.
- **수정**: daily_stories.date(로컬 일자 정규화 값)에 UNIQUE 제약 추가 + INSERT ... ON CONFLICT DO NOTHING 후 재조회(또는 IntegrityError 캐치 후 재조회)로 멱등화.

### 30. iOS 카카오톡 공유 100% 불능 — LSApplicationQueriesSchemes 미선언
`apps/mobile/ios/Runner/Info.plist:4`  · src: gap:Mobile native platform config (iOS Info.plist / AndroidManifest / store-review surface)

- **주장**: Info.plist에 LSApplicationQueriesSchemes(kakaolink 등)와 CFBundleURLTypes(kakao{APP_KEY})가 전혀 없어, kakao_flutter_sdk_common iOS 플러그인의 isKakaoTalkSharingAvailable 구현(KakaoFlutterSdkCommonPlugin.swift:105, UIApplication.shared.canOpenURL("kakaolink://send"))이 카카오톡 설치 여부와 무관하게 항상 false를 반환한다. CocoaPods는 앱 Info.plist에 키를 주입하지 못하므로 앱이 직접 선언해야 한다(Android는 플러그인 manifest의 <queries>가 머지되어 문제없음 — iOS만 깨짐).
- **트리거**: KAKAO_NATIVE_APP_KEY를 dart-define으로 넣은 iOS 릴리스 빌드에서, allow_kakao_share=on 사용자(기본값 true, viewer_screen.dart:1615)가 뷰어 공유 시트의 '카카오톡' 버튼 탭 → kakao_share_service.dart:117 isKakaoTalkSharingAvailable → 항상 false.
- **영향**: 출시 시점 iOS 전 기기에서 카카오톡 공유(핵심 한국 시장 바이럴 경로)가 '카카오톡 공유를 사용할 수 없는 기기입니다'로 100% 실패. 버튼은 노출되므로(isConfigured=true) 사용자는 매번 실패를 경험.
- **재현**: iOS 실기기 + 카카오톡 설치 → flutter build ios --dart-define=KAKAO_NATIVE_APP_KEY=<키> → 책 뷰어 → 공유 → 카카오톡 탭 → 항상 실패 스낵바. (단위 재현: canOpenURL은 LSApplicationQueriesSchemes에 없는 스킴에 대해 무조건 false — Apple 문서 명세)
- **수정**: Info.plist에 카카오 공식 문서의 LSApplicationQueriesSchemes 배열(kakaolink, kakaotalk 계열)과 CFBundleURLTypes에 kakao{NATIVE_APP_KEY} URL 스킴을 추가.

### 31. iOS 화면 자동잠금 시 오디오 내레이션·수면 모드 즉사 — UIBackgroundModes audio·wakelock 부재
`apps/mobile/ios/Runner/Info.plist:64`  · src: gap:Mobile native platform config (iOS Info.plist / AndroidManifest / store-review surface)

- **주장**: 앱은 페이지 오디오 내레이션(viewer_screen.dart:916 just_audio setUrl)과 hands-off 수면 모드(10~60분 타이머 + 오디오 완료 시 자동 페이지 넘김, viewer_screen.dart:937-999)를 제공하지만 Info.plist에 UIBackgroundModes(audio)가 없고 pubspec에 wakelock 계열 플러그인도 없다. iOS는 백그라운드 오디오 모드 미선언 앱을 화면 잠금 시 suspend시키므로 오디오·Dart 타이머·자동 넘김이 전부 정지한다.
- **트리거**: iOS 사용자가 수면 모드를 켜고 손을 떼면(수면 모드의 정의된 사용법) 기기 자동잠금(기본 1~2분) 발생 → 앱 suspend.
- **영향**: 취침 동화 앱의 핵심 플로우(수면 모드·오디오 듣기)가 시작 1~2분 만에 매번 중단 — 사용자가 반드시 그리고 반복적으로 겪는 사용자 가시 결함.
- **재현**: iOS 기기 자동잠금 1분 설정 → 오디오 있는 책 열기 → 수면 모드 시작 → 무터치 대기 → 잠금과 동시에 내레이션·자동 넘김 정지, 잠금 해제 전까지 재개 안 됨.
- **수정**: 제품 결정에 따라 택1: (a) Info.plist UIBackgroundModes에 audio 추가 + AVAudioSession playback 카테고리 구성(audio_session 패키지)으로 잠금 중 재생 유지, 또는 (b) 수면 모드/재생 중 wakelock_plus로 자동잠금 방지.


## 🟡 MEDIUM

### 32. api-test 잡의 pytest 종료코드가 `| tee`로 마스킹되어 테스트 실패에도 잡이 green
`.github/workflows/ci.yml:100`  · src: gap:CI release-gate workflow content

- **주장**: `pytest tests/ -v --cov=src --cov-report=xml 2>&1 | tee test-output.log` 스텝은 shell 미지정이라 GitHub Actions 기본 셸 `bash -e {0}`(pipefail 없음)로 실행된다. 파이프 종료코드는 마지막 명령 tee(항상 0)이므로 pytest 실패가 삼켜지고, 스텝 성패는 다음 줄 `coverage report --fail-under=40`에만 달린다. 실패한 테스트도 코드를 실행하므로 커버리지는 거의 떨어지지 않아, 테스트 실패 시에도 'API Tests + Coverage' 잡이 green이 된다. 현재는 phase-gate 잡이 `pytest tests -q`를 마스킹 없이 중복 실행해(scripts/phase-gate.sh:48, set -euo pipefail) 우연히 2차 방어가 존재하지만, api-test 잡 자체의 게이트 의미는 거짓이며 phase-gate가 required check에서 빠지거나 수정되는 순간 머지 게이트가 소실된다.
- **트리거**: money/IAP 경로 회귀(예: test_payment_integrity.py·test_iap_hardening.py 실패)를 포함한 어떤 PR이든 main으로 올리면 이 스텝이 실행된다.
- **영향**: false-green 릴리스 게이트: 'API Tests + Coverage' green 신호가 테스트 통과를 의미하지 않음. 브랜치 보호가 이 잡만 required로 걸려 있으면 결제·IAP 회귀가 테스트 실패 상태로 main에 머지되어 출시 이미지로 빌드·배포된다. 감사가 의존하는 '테스트 통과' 주장 전체가 이 스텝에선 무효.
- **재현**: 로컬에서 `bash -ec 'false | tee /tmp/x; echo alive rc=$?'` → `alive rc=0` 출력(마스킹 확인). CI에서는 apps/api/tests의 아무 테스트에 `assert False`를 넣은 PR을 올리면 api-test 잡의 이 스텝이 성공(green)으로 뜨고 coverage report만 실행되는 것을 확인.
- **수정**: 해당 스텝 run 첫 줄에 `set -o pipefail` 추가 또는 스텝에 `shell: bash` 명시(명시 시 `-eo pipefail` 적용). 동일 수정을 flutter-test 잡의 3개 tee 스텝에도 적용.

### 33. flutter integration_test 실패가 CI 전체에서 완전 무게이트 (tee 마스킹 + 중복 실행 부재)
`.github/workflows/ci.yml:162`  · src: gap:CI release-gate workflow content

- **주장**: `flutter test integration_test/ 2>&1 | tee integration-output.log`도 기본 셸(pipefail 없음)이라 종료코드가 tee의 0으로 덮인다. pytest 마스킹과 달리 이 통합 테스트(StartupGate→동의→온보딩→홈 라우팅 여정)는 phase-gate 잡에서도 재실행되지 않고(phase-gate.sh는 `flutter test`와 flutter-ui-preflight.sh만 실행, integration_test/ 미포함), 이후 lcov 임계 스텝도 이 테스트의 결과를 반영하지 않는다. 즉 통합 테스트 실패는 CI 어디에서도 빌드·머지를 막지 못한다.
- **트리거**: 온보딩·동의·홈 라우팅 여정을 깨뜨리는 어떤 mobile PR이든 flutter-test 잡에서 이 스텝을 통과(green)한다.
- **영향**: 첫 실행 온보딩/동의 여정이 깨진 앱이 모든 CI 게이트를 green으로 통과해 스토어 출시 빌드로 이어질 수 있다. 통합 테스트가 존재한다는 사실 자체가 거짓 안전감을 만든다(작성·유지 비용만 내고 게이트 효과 0).
- **재현**: apps/mobile/integration_test/ 내 테스트 하나에 `expect(1, 2)`를 넣은 PR 생성 → flutter-test 잡의 'Run integration tests' 스텝이 성공으로 표시되고 잡 전체가 green인 것을 확인.
- **수정**: 스텝에 `shell: bash` 명시 또는 `set -o pipefail` 추가. 추가로 실패 시 integration-output.log가 업로드 아티팩트 목록(flutter-test-logs)에 빠져 있으므로 path에 포함 권장.

### 34. flutter analyze / flutter test --coverage 종료코드도 tee로 마스킹 (phase-gate 중복이 현재 유일한 방어)
`.github/workflows/ci.yml:152`  · src: gap:CI release-gate workflow content

- **주장**: 152행 `flutter analyze 2>&1 | tee analyze-output.log`와 156행 `flutter test --coverage 2>&1 | tee test-output.log` 모두 기본 셸이라 실패가 마스킹된다. flutter-test 잡의 실질 게이트는 lcov 25% 임계 스텝뿐이며, analyze 에러나 위젯 테스트 실패는 커버리지가 25% 이상인 한 잡을 red로 만들지 못한다. 현재는 phase-gate 잡(phase-gate.sh:53-61)이 동일 명령을 set -euo pipefail 하에 중복 실행해 실질 차단이 유지되나, 이는 우연한 중복이지 설계된 방어가 아니다.
- **트리거**: analyze 에러 또는 위젯 테스트 실패를 포함한 mobile PR이 flutter-test 잡을 통과한다(커버리지 25% 이상 유지 시).
- **영향**: flutter-test 잡 단독으로 false-green. phase-gate가 required check가 아니거나 phase-gate.sh가 변경되면 analyze 에러·테스트 실패가 머지 가능. codecov에 올라가는 'flutter' 플래그 커버리지도 실패한 스위트의 부분 커버리지를 정상 데이터처럼 업로드한다.
- **재현**: widget 테스트 하나를 실패시키고 커버리지를 25% 이상으로 유지한 PR → flutter-test 잡의 두 스텝이 모두 green, 잡 성패는 lcov 임계에만 좌우됨을 확인.
- **수정**: 두 스텝(152·156행)에 `shell: bash` 명시 또는 `set -o pipefail` 추가.

### 35. 취약점 스캔이 전부 비차단: safety는 `|| echo`, Trivy는 exit-code '0'
`.github/workflows/ci.yml:77`  · src: gap:CI release-gate workflow content

- **주장**: 77행 `safety check -r requirements.txt --output text || echo "Security check completed with warnings"`는 취약점 발견은 물론 safety 도구 자체가 깨져도(예: deprecated `safety check` 서브커맨드 제거, 네트워크 실패) 무조건 성공한다. 343행 Trivy repo 스캔도 `exit-code: '0'`으로 advisory, 393-399행 빌드 이미지 스캔도 exit-code 미지정(기본 0)으로 SARIF 업로드만 한다. 결과적으로 CI에서 blocking 보안 게이트는 Gitleaks 하나뿐이며, 의존성/이미지 CVE는 어떤 심각도든 출시를 막지 못한다.
- **트리거**: requirements.txt에 CRITICAL CVE가 있는 버전이 들어오거나 기존 의존성에 신규 CVE가 공개된 상태에서 main push → build 잡이 이미지를 빌드·푸시하고 deploy가 진행된다.
- **영향**: 아동 대상 글로벌 서비스가 이미 알려진 CRITICAL 취약점을 가진 채 출시될 수 있고, CI 로그에는 'Security check completed with warnings'라는 성공 메시지만 남아 아무도 인지하지 못한다(에러를 성공으로 삼킴 클래스).
- **재현**: requirements.txt에 알려진 취약 버전(예: 구버전 aiohttp) 추가 PR → api-test 잡의 safety 스텝이 green으로 통과하는 것을 확인. 또는 로컬에서 `safety check ... || echo ok; echo $?` → 항상 0.
- **수정**: safety 스텝의 `|| echo ...` 제거(정책상 advisory로 둘 거면 continue-on-error: true로 명시해 UI에 노출), Trivy repo/이미지 스캔에 severity CRITICAL 기준 `exit-code: '1'` 설정.

### 36. concurrency cancel-in-progress가 진행 중인 프로덕션 배포를 취소해 부분 배포/다운 상태를 남길 수 있음
`.github/workflows/ci.yml:11`  · src: gap:CI release-gate workflow content

- **주장**: concurrency group `CI-refs/heads/main` + `cancel-in-progress: true`가 PR뿐 아니라 main push 런(=build·deploy 잡 포함)에도 적용된다. 배포 SSH 스텝이 서버에서 deploy.sh deploy(내부 순서: pull → stop_services → start_services → migrate → health, scripts/deploy.sh:244-251)를 실행하는 도중 두 번째 머지가 push되면 첫 런이 취소된다. 러너가 죽으면 SSH 세션이 끊기고 원격 스크립트가 SIGHUP으로 중단될 수 있어, `compose down` 완료 후 `up` 이전 또는 마이그레이션 도중에 끊기면 프로덕션이 정지·불완전 상태로 방치된다. 다음 런의 deploy까지 CI 전체(테스트+빌드, 수십 분)가 다시 걸린다.
- **트리거**: 출시 후 흔한 시나리오: 두 PR을 연달아 머지(또는 hotfix push)하면 두 번째 push가 첫 push의 in-flight deploy 잡을 취소한다.
- **영향**: 프로덕션 API 다운타임(다음 런 완료까지 수십 분) 또는 half-deploy 상태(구서비스 정지 + 신서비스 미기동, 마이그레이션 부분 적용). 사용자 전면 장애.
- **재현**: DEPLOY_ENABLED 환경에서 main에 커밋 2개를 몇 분 간격으로 push → 첫 런이 Deploy 스텝 실행 중 취소되는 것을 Actions UI에서 확인, 서버에서 `docker compose ps`로 서비스 정지 상태 확인.
- **수정**: deploy(및 build) 잡에 별도 concurrency 지정: `concurrency: { group: deploy-production, cancel-in-progress: false }`. 워크플로 레벨 group은 PR 취소용으로 유지하되 `github.event_name == 'pull_request'`일 때만 cancel-in-progress 되도록 분리.

### 37. aquasecurity/trivy-action@master 가변 ref 핀 — packages:write 토큰 보유 잡에서 실행되는 서드파티 액션
`.github/workflows/ci.yml:337`  · src: gap:CI release-gate workflow content

- **주장**: trivy-action이 337행(security-scan)과 394행(build)에서 `@master`로 참조된다. 특히 build 잡은 `permissions: packages: write` 토큰을 갖고 ghcr 로그인(docker/login-action이 토큰을 러너에 저장) 이후에 이 액션을 실행한다. 액션 저장소 master 브랜치가 오염되면(supply-chain) 해당 커밋이 즉시 이 파이프라인에서 실행되어 GITHUB_TOKEN(packages:write)을 탈취해 ghcr의 출시 이미지(api/worker:latest)를 오염시킬 수 있다. 다른 액션들은 전부 태그 핀(v2~v6)인데 이것만 가변 브랜치다.
- **트리거**: main push마다 build 잡이 실행되며 매번 trivy-action의 최신 master 커밋을 받아 실행한다. 공격자 개입 없이도 master의 breaking change로 게이트가 임의 시점에 깨질 수 있다.
- **영향**: 최악: 출시 컨테이너 이미지 공급망 오염(아동 대상 서비스의 프로덕션 이미지 변조). 최소: 서드파티 master 변경으로 CI가 예고 없이 깨지거나 스캔이 조용히 무력화.
- **재현**: 코드 변경 없이 재현 확인: 337·394행이 `@master`임을 확인하고, build 잡의 permissions(21행 packages: write)과 실행 순서(ghcr login → trivy-action)를 대조. 과거 tj-actions/changed-files 사건과 동일 패턴.
- **수정**: 두 곳 모두 릴리스 태그 또는 커밋 SHA로 핀(예: `aquasecurity/trivy-action@0.28.0` 혹은 `@<full-sha>`).

### 38. 이미지 취약점 스캔이 push 이후 실행되고 비차단 — 취약 이미지가 이미 :latest로 공개·배포 진행
`.github/workflows/ci.yml:393`  · src: gap:CI release-gate workflow content

- **주장**: build 잡은 369-391행에서 api/worker 이미지를 `push: true`로 ghcr에 `:latest`와 `:sha` 태그로 먼저 푸시한 뒤, 393-399행에서 스캔한다. 스캔은 exit-code 미지정(trivy-action 기본 '0')이라 CRITICAL이 발견돼도 잡이 성공하고, deploy 잡은 build 성공만 보고(needs: [build]) `$GITHUB_SHA` 이미지를 프로덕션에 배포한다. '외부 부작용 먼저 → 검증 나중' 클래스: 스캔이 아무것도 되돌리거나 막지 못한다.
- **트리거**: CRITICAL CVE가 포함된 베이스 이미지/의존성으로 main push → 이미지 푸시 → 스캔(결과 무시) → 자동 배포.
- **영향**: 알려진 CRITICAL 취약점을 가진 이미지가 (1) 공개 레지스트리에 :latest로 게시되고 (2) 프로덕션에 배포된다. SARIF는 Security 탭에 쌓이지만 아무 플로우도 막지 않아 출시 후에도 방치되기 쉽다.
- **재현**: 취약 베이스 이미지(예: 구버전 python:3.11 태그)로 Dockerfile 변경 후 main push → build green·deploy 진행, Security 탭에만 결과가 쌓이는 것을 확인.
- **수정**: load: true로 로컬 빌드 → 스캔(exit-code '1', severity CRITICAL) → 통과 시에만 push하는 순서로 재배열. 최소한 스캔을 blocking으로 바꾸고 deploy가 스캔 통과에 의존하게.

### 39. 버전 표기 1.0.0 통일 구멍 — 런타임 API가 0.2.0 서빙(.env APP_VERSION 잔재) + 모바일 설정화면 0.1.0+1 기본값·CI 0.3.2 미배선
`apps/api/src/core/config.py:22`  · src: contract-consistency, mobile-flutter

- **주장**: (a) config.py 기본값·.env.example·커밋된 openapi.json은 모두 1.0.0이지만 settings.app_version이 환경변수(APP_VERSION)로 오버라이드 가능해 이 머신의 로컬 .env가 0.2.0을 주입한다 — 실측: `from src.core.config import settings` → app_version=0.2.0, app.openapi() != 커밋된 계약(diff는 version 한 줄). (b) 모바일 설정 화면 _appVersion은 String.fromEnvironment('APP_VERSION', defaultValue: '0.1.0+1')(settings_screen.dart:20)인데 릴리스 빌드에 --dart-define=APP_VERSION을 전달하는 스크립트·문서가 리포에 없다(APP_VERSION 언급은 API용 ci.yml·run_live_e2e.sh뿐이며 그마저 '0.3.2'). pubspec은 1.0.0+1로 통일(94cb839)됐지만 이 화면은 별도 소스. CLAUDE.md '버전 1.0.0 통일' 규범과 충돌.
- **트리거**: 구버전 .env를 복사해 쓰는 모든 환경(로컬·배포 서버 .env 재사용)에서 API 기동; --dart-define 없이 스토어 릴리스 빌드 → 설정 화면 '버전' 항목.
- **영향**: /health·/health/ready·openapi가 0.2.0을 보고해 출시 버전 게이트·모니터링·스토어 심사 대응 시 버전 식별이 틀어짐. 계약 신선도 테스트(test_openapi_contract)가 이 환경에서 항상 실패해 진짜 계약 드리프트 신호를 소음으로 만듦. 출시 앱 설정에 v0.1.0+1 표기 — CS·리뷰 혼선.
- **재현**: apps/api에서 `TESTING=1 venv/bin/python -c "from src.core.config import settings; print(settings.app_version)"` → 0.2.0(커밋된 openapi.json info.version은 1.0.0). flutter build를 --dart-define 없이 수행 후 설정 화면 → 'v0.1.0+1'.
- **수정**: 로컬/배포 .env의 APP_VERSION을 1.0.0으로 갱신(또는 APP_VERSION env 오버라이드 제거·코드 상수 정본화), DEPLOYMENT.md에 버전은 코드가 정본임을 명시. 모바일은 package_info_plus로 pubspec 버전을 런타임 조회해 단일 정본화(차선: defaultValue 1.0.0+1 + 빌드 문서 dart-define 명시 + ci.yml 0.3.2→1.0.0).

### 40. /health/detailed·/health/ready가 무인증 공개 — 내부 메트릭과 '빠진 보안 설정 목록(missing_keys)'을 외부에 노출
`apps/api/src/main.py:508`  · src: auth-surface, docs-ops

- **주장**: detailed_health_check(main.py:508~511)와 ready_health_check(499~505)에 인증·rate limit이 전혀 없고, nginx location /health는 prefix 매칭이라 /health/detailed·/health/ready 모두 공개 프록시된다(nginx.conf:79-84). 응답은 rate limit 설정값·job_sla·image_max_concurrent·provider 이름(llm/image)·job 큐 메트릭을, 미설정 시엔 missing_keys(iap_mode_not_strict, iap_webhook_secret_missing, iap_store_credentials_missing 등)까지 반환한다. apps/api/.env.example:48은 '/health/detailed에 ADMIN_API_KEY 필요'라고 서술하지만 코드에 그런 검증이 없다(문서-코드 불일치). 매 호출마다 DB(SELECT 1)+Redis ping+job 메트릭 쿼리를 무스로틀 수행.
- **트리거**: 인터넷에서 GET /health/detailed 또는 /health/ready 직접 호출(외부 접근 차단이 없으면 공개).
- **영향**: 공격자가 결제 검증 태세(iap_mode_not_strict → 영수증 위조 시도 가치, 웹훅 시크릿 부재 → 상태변조 대상 선정)·큐 적체·프로바이더·튜닝 파라미터를 정찰 가능. 무스로틀 DB/Redis 접촉으로 소규모 증폭 표면.
- **재현**: 운영 구성으로 기동 후 인증 헤더 없이 curl /health/detailed → 200 + jobs/config 전체. curl /health/ready(시크릿 미설정 시) → 503 + missing_keys=[iap_webhook_secret_missing,...].
- **수정**: /health/detailed에 X-Admin-Key(hmac.compare_digest) 검증 추가(credits/add 패턴 재사용), nginx는 location = /health, = /health/live, = /health/ready만 공개하고 detailed는 내부망 한정. 공개 /health/ready 응답에서 missing_keys 상세를 제거하고 boolean만. 상세 경로에 rate limit 부여.

### 41. 모델↔마이그레이션 드리프트: books.retelling_source_book_id의 self-FK가 마이그레이션 체인에 없음
`apps/api/src/models/db.py:140`  · src: db-migrations

- **주장**: 모델은 retelling_source_book_id = Column(String(60), ForeignKey("books.id"))로 FK를 선언하지만, 이 컬럼을 추가한 마이그레이션 c9d0e1f2a3b4(42-48행)는 컬럼만 추가하고 FK 제약을 만들지 않는다. 체인의 다른 어떤 리비전도 이 FK를 생성하지 않으므로 Postgres 실 DB에는 제약이 없고, alembic autogenerate가 add_foreign_key diff를 낸다(개념적 검증).
- **트리거**: 리텔(POST /v1/books/{id}/retell, books.py:1103에서 링크 설정) 사용 후 원본 책을 DELETE /v1/library/{book_id}로 삭제 — purge_book_children(data_deletion.py)도 retelling_source_book_id를 정리하지 않는다.
- **영향**: 리텔 변형 책들이 존재하지 않는 book id를 가리키는 고아 포인터로 잔존(연령 변형 묶음 정합성 훼손). 이후 모델대로 FK를 붙이는 순간 (a) 기존 고아 행 때문에 마이그레이션 실패, (b) purge 누락 때문에 원본 책 삭제가 FK 위반으로 실패하기 시작하는 지뢰. 테스트(SQLite create_all)는 모델 기준 FK가 생겨 실 DB와 다른 스키마로 통과하는 검증 사각지대도 있음.
- **재현**: 빈 Postgres에 alembic upgrade head → books 테이블에 retelling_source_book_id FK 부재 확인; alembic revision --autogenerate가 create_foreign_key diff 생성. 리텔 책 생성 → 원본 삭제 → retelling_source_book_id dangling.
- **수정**: 신규 마이그레이션으로 FK 추가(ON DELETE SET NULL 권장, 기존 고아 행 선행 NULL 정리) + purge_book_children에 update(Book).where(Book.retelling_source_book_id.in_(book_ids)).values(retelling_source_book_id=None) 추가.

### 42. 재생성·리텔·인페인트 경로 결함 묶음 — 입력/출력 모더레이션 전면 우회 + call_text_rewrite 스키마 미검증 + feedback/draft 부재 시 무동작을 done으로 위장
`apps/api/src/routers/books.py:1076`  · src: orchestrator-jobs, silent-failures

- **주장**: 안전검사(B·G 단계)는 최초 생성 파이프라인에만 존재한다. (a) retell_book은 call_story_retext 결과를 검사 없이 새 책으로 저장하고(books.py:1076-1119), regenerate_page는 사용자 feedback(자유 텍스트)을 입력 모더레이션 없이 LLM에 전달한 뒤 결과를 출력 모더레이션 없이 저장하며(orchestrator.py:1100-1103), inpaint는 사용자 region_prompt를 무검사로 이미지 프롬프트에 결합한다(books.py:855, orchestrator.py:1166-1180) — 재생성 이미지도 출력 검사 없음. (b) call_text_rewrite(llm.py:553-577)는 parse_json_response를 쓰지 않고 raw json.loads만 수행(마크다운 펜스 미제거·타입 미검증 — 'LLM 출력은 무조건 JSON Schema 검증' 규범 위반)하며, revised_text가 null이면 page.text=None → pages.text NOT NULL(db.py:173) 위반, 키가 없으면 rewrite_result.get("revised_text", page.text)가 원문 유지를 성공 처리. (c) regenerate_page 텍스트 분기는 `if draft_db and feedback:`(orchestrator.py:1088)일 때만 동작 — feedback 없이(Optional, dto.py:362) 호출하거나 retell로 만든 책(StoryDraftDB 행 없음)이면 조용히 no-op 후 regen 잡이 'done' 처리된다.
- **트리거**: 완성 책 보유 사용자가 feedback='늑대가 토끼를 잡아먹는 무서운 장면으로'/region_prompt에 부적절 내용을 넣어 재생성·인페인트 호출; retell LLM이 연령 변환 중 부적절 표현 생성; mode=text에 feedback 생략; anthropic 프로바이더가 ```json 펜스로 응답.
- **영향**: 아동 콘텐츠 안전 게이트를 우회하는 콘텐츠 변형 경로 3개 — 원 생성이라면 차단됐을 폭력·성인 표현이 책 본문에 저장·공유(book_shares 공개 링크) 가능(스토어 심사·브랜드 리스크). 사용자가 재생성 완료(done)를 확인했는데 텍스트가 그대로인 silent no-op(무한 재시도·CS). anthropic 설정 시 텍스트 재생성 항상 실패.
- **재현**: feedback에 _MOD_FORBIDDEN_KO 표현(예: '살해') 포함 재생성 → LLM 반영 revised_text가 검사 없이 page.text로 커밋(같은 텍스트를 moderate_output에 넣으면 False). mode=text·feedback 없이 재생성 → regen 잡 done, page.text 불변. retell 책 job_id로 mode=text+feedback → 동일 no-op.
- **수정**: feedback/region_prompt에 입력 모더레이션, 재생성·리텔 결과에 moderate_output 적용 후 저장(실패 시 SAFETY_OUTPUT으로 잡 failed). call_text_rewrite를 parse_json_response(RewriteResult pydantic)로 검증, revised_text 부재/공백/비문자열 가드. 라우터에서 mode∈{text,both}이면 feedback 필수(422), draft_db 부재 시 명시 에러로 regen 잡 failed 처리.

### 43. 시리즈 생성은 프로덕션(USE_CELERY=true)에서도 API 프로세스 BackgroundTasks로 실행 — 재시작 시 유실·좀비 경로 직행
`apps/api/src/routers/books.py:1010`  · src: orchestrator-jobs

- **주장**: create_book/오늘의동화는 schedule_book_generation을 통해 use_celery면 Celery로 보내지만, create_series_next는 무조건 background_tasks.add_task(start_series_generation, …)로 API 프로세스에서 10분짜리 생성 파이프라인을 실행한다(ORM 객체 character/prev_book을 그대로 넘기는 구조라 Celery 직렬화 불가가 원인으로 보임). 인페인트/재생성도 동일하게 in-process지만 이 둘은 짧은 작업이고, 시리즈는 full 생성이라 노출이 가장 크다.
- **트리거**: 프로덕션 배포/오토스케일 다운/컨테이너 재시작 중 시리즈 생성 진행 → in-process 태스크 소멸 → 잡 running 정체 → 좀비 재큐 경로(~105분 후 실패). 평상시에도 uvicorn 워커가 10분간 생성 부하(이미지 다운로드·S3 업로드)를 떠안아 API 지연 유발.
- **영향**: 시리즈 크레딧을 지불한 잡이 배포 때마다 유실(105분 후에야 환불), Celery 워커 스케일링·time_limit 보호를 전혀 받지 못함, API 응답성 저하.
- **재현**: USE_CELERY=true 환경에서 POST /v1/books/series/next 직후 API 컨테이너 재시작 → Celery 워커 큐에 태스크가 없고 잡이 running으로 정체됨을 확인.
- **수정**: start_series_generation을 Celery 태스크화: request dict·character_id·prev_book_id만 직렬화해 넘기고 태스크 안에서 재조회. schedule_book_generation과 동일한 enqueue 실패 환불 래퍼 재사용.

### 44. 운영에서 누구나 호출 가능한 POST /v1/credits/subscribe(plan=free)가 유료 구독을 즉시 소멸시키고(+2 크레딧 지급) 스토어 결제는 계속됨
`apps/api/src/routers/credits.py:193`  · src: money-credits

- **주장**: 유료 플랜 가드(193-200행)는 plan != 'free'에만 적용되므로 free는 운영에서 항상 통과한다. 활성 premium 사용자가 plan='free'로 호출하면 existing.plan != 'free'라 already_subscribed에 걸리지 않고 create_subscription('free')로 진행 — create_subscription(services/credits.py:402-405)은 기존 유료 구독을 status='cancelled'+current_period_end=now로 즉시 종료시키고(잔여 결제 기간 소멸) free 구독을 만들며 2크레딧을 지급한다. '/cancel-subscription은 기간 만료까지 사용 유지'라는 자체 계약(라우터 265행 메시지)과도 모순.
- **트리거**: X-User-Key만 있으면 되는 공개 API 표면. 클라이언트 UI의 플랜 화면에서 free 선택/실수 탭, 또는 임의 스크립트 호출. 스토어(Apple/Google) 자동갱신 결제는 서버 상태와 무관하게 계속 청구된다.
- **영향**: 결제 완료된 잔여 구독 기간의 entitlement가 즉시 소멸(사용자 금전 피해·환불 분쟁), periodic_credits의 해당 유료 구독 리필도 중단. 부가로 free 구독은 periodic_credits가 영구 리필하는 active 행으로 남는다.
- **재현**: verify로 premium 활성화(period_end=+30d) → POST /v1/credits/subscribe {"plan":"free"} → subscriptions: premium(status=cancelled, period_end=now), free(active) + credit_transactions에 +2 bonus. GET /v1/credits/status가 free만 반환.
- **수정**: subscribe에서 활성 유료 구독 보유 시 free 전환을 거부(또는 유료 기간 만료 후 예약 전환)하고, create_subscription의 기존 구독 종료를 '즉시 period_end=now'가 아니라 상태만 cancelled로 남겨 기간 만료까지 entitlement를 유지한다.

### 45. 구독 환불(webhook refunded) 시 지급된 월간 크레딧 미회수 — 크레딧팩만 clawback
`apps/api/src/routers/iap.py:367`  · src: money-credits

- **주장**: 환불 clawback은 receipt.product_id in CREDIT_PACK_PRODUCTS인 경우에만 수행된다. 구독 상품 환불은 구독 status만 expired로 바꾸고 create_subscription이 지급했던 credits_per_month(premium 30개)는 회수하지 않는다. 346행 주석이 '무한 무료 크레딧' 방지를 명시하며 리필 중단은 막았지만 최초 지급분 회수는 누락.
- **트리거**: 사용자가 구독 결제 → 30크레딧 지급 → 즉시 소비 또는 보유 → 스토어에 환불 요청(Apple 앱 내 환불 플로우) → 웹훅 refunded 수신. 재구매·재환불 반복 시 매 사이클 30크레딧이 무비용 적립.
- **영향**: 환불 사이클당 premium 30크레딧(생성 원가 ~$14 상당) 무상 취득. 스토어 환불 승인 정책이 빈도를 제한하지만 1회성 남용은 확실히 가능 — 매출 누수.
- **재현**: verify(subscription_premium) → +30 → webhook {status:"refunded"} → subscriptions.status=expired이지만 user_credits.credits는 30 유지, clawback 트랜잭션 없음.
- **수정**: webhook refunded 처리에서 구독 상품도 credits_service.clawback_credits(amount=해당 구독 지급분, reference_id=store_txn 기반)를 호출한다(이미 멱등 헬퍼 존재). 미사용분만 회수할지(현 clawback은 0 클램프로 이미 부분 대응) 정책 확인.

### 46. credit_transactions 멱등성이 DB로 미강제(milestone 부분 유니크뿐) — refund 이중 환불·admin purchase 이중 지급 가능 + reference_id 인덱스 부재 풀스캔
`apps/api/src/services/credits.py:275`  · src: money-credits, orchestrator-jobs, db-migrations

- **주장**: credit_transactions의 유니크 제약은 milestone bonus 부분 인덱스(models/db.py:282-295)뿐이라 다른 타입의 멱등성이 전부 앱 코드 check-then-write에 의존한다. (a) refund_for_job은 '기존 refund 존재' SELECT(275-284) 후 add_credits INSERT — main.py:168이 모든 API 프로세스에서 job_monitor를 시작하므로 uvicorn 워커 N개×레플리카 M개의 5분 주기 스캔이 겹치면(장애 직후 스턱 잡 다발 시점) 두 세션이 같은 job_id에 둘 다 '환불 없음'을 읽고 둘 다 +1 커밋(_mark_job_failed에 잡 클레임도 없음). (b) 관리자 지급 /v1/credits/add(routers/credits.py:301)는 transaction_id를 필수로 받지만 재제출을 막는 로직이 앱·DB 어디에도 없어 재전송 시 N중 지급. (c) 부가로 reference_id 인덱스 자체가 없어(models/db.py:306) refund/clawback/milestone 멱등성 조회가 테이블 성장에 비례해 풀스캔.
- **트리거**: 멀티 레플리카 job_monitor의 동시 스캔(장애 직후), 운영자 CS 보상 처리 중 타임아웃/더블클릭 재전송, 외부 정산 스크립트 재처리.
- **영향**: 잡당 크레딧 초과 환불(무상 발행, 장애 시 체계적 발생), 같은 외부 결제 1건에 크레딧 N중 지급(운영 실수형 금전 손실), 감사 시 동일 reference_id 다중 행으로 정합성 훼손. 수개월 내 웹훅/모니터 경로 지연으로 발전하는 잠복 성능 결함.
- **재현**: 두 세션으로 동시에 refund_for_job(job_X) 진입 → 둘 다 already 체크 통과 → commit 2회 성공 → refund(reference_id=job_X) 2행, 잔액 +2. X-Admin-Key로 POST /v1/credits/add {amount:10, transaction_id:"pay_1"} 2회 → 잔액 +20, purchase 2행.
- **수정**: 부분 유니크 인덱스 (reference_id[, user_key]) WHERE transaction_type='refund' 및 (user_key, reference_id) WHERE transaction_type='purchase' 추가, refund_for_job/add 엔드포인트에서 IntegrityError를 '이미 처리됨'으로 흡수(milestone 패턴 재사용). Index(reference_id, transaction_type)도 추가. 부수적으로 job_monitor 실패 전이를 조건부 UPDATE(claim)로.

### 47. create_subscription의 활성 구독 1개 보장이 DB 제약 없는 check-then-write — 동시 요청 시 활성 구독 2행 생성, periodic_credits가 매월 이중 지급
`apps/api/src/services/credits.py:402`  · src: money-credits, db-migrations

- **주장**: create_subscription은 get_active_subscription SELECT 후 새 행 INSERT를 하며, subscriptions(models/db.py:259-274, 마이그레이션 2dd3344558db)에는 (user_key) WHERE status='active' 류의 부분 유니크 제약이 없다. 동시 두 호출이 서로의 미커밋 행을 못 보고 둘 다 active 행을 만든다. 이후 periodic_credits.grant_due_refills(periodic_credits.py:84)는 active 구독을 행 단위로 리필하므로 두 행 모두 매월 credits_per_month를 지급한다. IAP 웹훅 취소/환불(iap.py:353-358)은 created_at 최신 1행만 종료시켜 나머지 활성 행은 환불 후에도 영구 리필.
- **트리거**: 서로 다른 store_transaction_id의 두 IAP verify/restore 요청 동시 처리(예: 앱 시작 시 복원 verify와 신규 구매 verify 병렬 — iap_receipts 유니크는 거래 단위라 못 막음), /credits/subscribe(free)와 verify의 동시 실행. 멀티 레플리카에서 확률 상승.
- **영향**: 사용자 1명에게 활성 구독 2행 → 월간 크레딧 영구 이중 지급(매출 누수), /credits/status 표시 혼란, 웹훅 '최신 구독' 선택 버그와 결합 시 오동작 증폭.
- **재현**: 두 세션에서 create_subscription(U,'basic')와 create_subscription(U,'premium')을 동시 커밋(get_active_subscription 조회 직후 다른 세션이 완료하도록 side-effect 주입) → active 2행 → grant_due_refills 1주기 후 두 행 각각 지급 확인.
- **수정**: 부분 유니크 인덱스 (user_key) WHERE status='active' 추가(모델 __table_args__ + 마이그레이션, 기존 중복 정리 선행) + create_subscription에서 IntegrityError 시 기존 활성 구독 재조회/취소 후 재시도(또는 SELECT ... FOR UPDATE 직렬화). 웹훅 취소도 활성 전 행 대상으로 변경.

### 48. 사용자 노출 문자열 한국어/₩ 하드코딩 전역 — 서버 플랜명·features·에러 메시지 + 모바일 에러·폴백·알림·타이틀 (글로벌 l10n 규칙 위반)
`apps/api/src/services/credits.py:17`  · src: contract-consistency, mobile-flutter

- **주장**: (a) 서버: SUBSCRIPTION_PLANS의 name('무료/베이직/프리미엄')·features(한국어 문장)·price(KRW 정수)가 API 응답으로 그대로 내려가 en/ja UI 플랜 카드에 표시되고(credits_screen.dart:441-517), 가격 접미사는 3개 로캘 모두 '₩{price}' 하드코딩(app_en.arb:741 등) — 실제 청구는 스토어 현지 가격이라 표시·청구 불일치. 서버 에러 메시지(exceptions.py 한국어 고정, Accept-Language 미고려)도 402 '크레딧이 부족합니다...' 등이 그대로 스낵바 표시. (b) 모바일: api_error.dart 전 메시지('알 수 없는 오류…','인터넷 연결을 확인해주세요.' 등 36·47·57·73-93·145-188행), providers.dart 폴링 TimeoutException(874·880)·홈 폴백('오늘의 추천' 629, '오늘의 동화를 만들어보세요!' 631, '성장 중' 688), iap_service.dart(20·33), kakao_share_service.dart(38-46·93·104·121·130), env_config(36), main.dart MaterialApp title 'AI 동화책'(120), notification_scheduler.dart 채널명 '잠자리 알림'(116-117), BookTheme 한국어 label(create_screen.dart:318) 등이 하드코딩 — CLAUDE.md '사용자 노출 문자열 ko/en/ja .arb 필수' 규칙과 충돌.
- **트리거**: 영어/일본어 로캘 사용자가 크레딧/구독 화면 진입, 또는 네트워크 오류·스토어 불가·서버 5xx 등 어떤 실패든 만나는 순간(스낵바·에러 화면), 앱 스위처 타이틀·알림 채널 설정 화면.
- **영향**: 글로벌 스토어 심사·전환률에 직접 영향: 결제 화면에 읽을 수 없는 한국어 플랜 설명과 ₩ 가격(실청구 통화와 다름) 노출, 실패할 때마다 한국어 안내로 이탈·리뷰 하락. 오류 상황일수록 언어 접근성이 중요.
- **재현**: 기기 언어 en으로 /credits 진입 → 플랜명 '베이직', 한국어 features 칩, '₩6,900/month'. 크레딧 0으로 생성 시도 → 402 한국어 메시지. 기내모드 → 서재 새로고침 → '인터넷 연결을 확인해주세요.' 스낵바.
- **수정**: 플랜 name/features는 서버에서 키(id)만 내리고 클라이언트 .arb로 번역, 가격은 스토어 ProductDetails의 localizedPrice로 표시. 서버 에러는 error.code 기반으로 클라이언트에서 l10n 매핑(이미 code가 안정적으로 내려옴). ApiError는 코드만 담고 표시 계층에서 번역, 서비스 unavailableReason도 enum 반환, MaterialApp은 onGenerateTitle, 알림 채널명 l10n 전달.

### 49. job_monitor의 '재시도'가 실제 재실행을 디스패치하지 않는 no-op — 좀비 재큐로 ~1.5-2시간 가짜 대기 후에야 실패
`apps/api/src/services/job_monitor.py:160`  · src: orchestrator-jobs, silent-failures, docs-ops

- **주장**: _handle_stuck_job은 job.status='queued'로 DB만 갱신하고 retry_count를 증가시킬 뿐, Celery 태스크 재발행(generate_book_task.delay)이나 BackgroundTasks 재등록을 하지 않는다. Celery는 브로커 메시지를 소비하지 DB 행을 소비하지 않으므로 코드베이스 어디에도 'queued' 상태를 소비해 실행을 시작하는 컨슈머가 없다(grep 확인: status=='queued' 참조는 monitor 자신과 카운트 쿼리뿐, .delay 호출은 books.py:508 단 한 곳). Job 행에 BookSpec도 저장되지 않아 재디스패치 자체가 불가능한 구조다.
- **트리거**: 워커 hard time_limit(720s) SIGKILL(이때 Celery는 메시지를 ack하므로 재전달 없음), 워커 OOM/컨테이너 재시작·재배포, 브로커 메시지 유실(Redis 축출), use_celery=false·BackgroundTasks 모드에서 API 재시작 — 배포마다 발생 가능. 잡 running 정체 → 15분 후 queued 전환(1/3) → 아무도 실행 안 함 → 30분×3 반복 → 최종 실패+환불.
- **영향**: 사용자에게 '재시도 중... (n/3)'을 표시하지만 재시도는 한 번도 실행되지 않고, 최종 실패·환불 판정까지 약 1.5~2시간 소요 — 그동안 생성 화면에 매달린 사용자 이탈. 재시도 카운트·메시지가 전부 거짓. 워커 재시작이 잦은 출시 초기에 다발.
- **재현**: 잡 생성 후 워커 프로세스 kill -9 → job.updated_at 15분 경과 시 monitor가 status='queued', current_step='재시도 중... (1/3)'으로 변경 → 이후 어떤 프로세스도 해당 잡을 실행하지 않고(워커 로그에 task 수신 없음) 30분 뒤 다시 STUCK_QUEUED 처리, 3회 소진 후 failed.
- **수정**: _handle_stuck_job에서 settings.use_celery면 Job 행에 spec을 보존해 generate_book_task.delay(job_id, spec, user_key)를 재발행(태스크 시작부에 잡 상태 재확인 멱등 가드 + 조건부 UPDATE 클레임으로 다중 레플리카 이중 디스패치 방지). 재발행 불가 구조라면 재큐 분기를 제거하고 첫 스턱 감지 시 즉시 failed+refund_for_job으로 단순화.

### 50. 이미지 부분 실패 게이트 구멍 — 표지는 25% 실패 임계에서 제외되고, 예외 실패 페이지(빈 URL)는 generation_warnings에서 누락
`apps/api/src/services/orchestrator.py:674`  · src: orchestrator-jobs, silent-failures

- **주장**: (a) max_failures 임계 검사(673-679)는 image_prompts.pages만 집계하고 표지(page 0)는 포함하지 않는다 — 표지가 ImageError 소진으로 placeholder가 돼도(695-745) 잡은 성공. (b) 페이지가 asyncio.TimeoutError/네트워크 예외로 소진되면 generate_image_with_retry가 StoryBookError를 raise하고 gather 결과에서 image_urls[page]=''(661)로 저장되는데, build_generation_warnings(book_assets.py:62-90)는 placeholder.invalid 마커만 검사해(69,79-88) 빈 URL 페이지는 경고 0건이다(asset_status에만 missing 표기) — 동일한 실패가 placeholder면 경고되고 예외면 침묵하는 비대칭.
- **트리거**: 8페이지 책에서 표지 1장 + 페이지 2장이 이미지 API 오류로 소진(총 9장 중 3장=33% 실패) → 임계(>2) 미달로 잡 done. 이미지 API 행(hang)으로 일부 페이지가 wait_for 타임아웃 소진.
- **영향**: 서재 썸네일(표지)이 placeholder.invalid(해석 불가 도메인)인 책, 그림 없는 페이지가 책 수준 경고 배너 없이 '완성'으로 배달되고 크레딧 전액 소모 — degraded-asset 설계(asset_status/warnings)의 자기 계약을 스스로 어김.
- **재현**: 이미지 mock을 표지·2개 페이지에서 ImageError로 소진시키고 1개 페이지는 TimeoutError로 소진 → 잡 done, cover_image_url에 placeholder, 해당 페이지 image_url='' 이며 build_generation_warnings 결과에 빈 URL 페이지 항목이 없음을 확인.
- **수정**: failed_pages 집계에 표지 포함(또는 표지 placeholder 시 전체 실패), build_generation_warnings/is_placeholder 판정에 빈 문자열 URL도 'page_image_missing' 경고로 포함해 asset_status와 일관되게.

### 51. 규범 스펙 정합성 위반 묶음 — 진행률·단계 타임아웃·최종 에러코드 UNKNOWN 뭉갬·G단계 출력검사(이미지 전무·ja/zh/es 무력·SAFETY_OUTPUT 재시도 0회)·Replicate 60초 폴링 (보고 후 결정 필요)
`apps/api/src/services/orchestrator.py:776`  · src: orchestrator-jobs, silent-failures

- **주장**: CLAUDE.md 규범 표와 코드 불일치: (1) 진행률 — 스펙 40-55/55-95/95-100 vs 코드 PROGRESS_IMAGE_PROMPTS=50, IMAGES 50-85, 학습자산 92, 패키징 98(스펙에 없는 단계 삽입). (2) 입력 모더레이션 타임아웃 — 스펙 10초 vs settings.llm_timeout=30초(orchestrator.py:261). (3) 캐릭터 시트 — 스펙 20초 vs 30초(294). (4) run_step 최종 실패가 last_exc 코드를 버리고 UNKNOWN으로 뭉갬(142-145) — 스토리 타임아웃 소진이 LLM_TIMEOUT이 아니라 UNKNOWN으로 기록돼 에러코드 기반 안내·운영 지표 무력화. (5) 스펙 G단계 '출력 안전성 검사(이미지/텍스트)' — moderate_output(776-796)이 image_urls 인자를 받고도 이미지를 전혀 검사하지 않고, 텍스트도 한국어·영어 금칙 패턴만 검사해 스토리 언어 ko/en/ja/zh/es(core/i18n.py) 중 ja/zh/es 책은 출력 안전검사가 사실상 항상 True이며, SAFETY_OUTPUT은 스펙상 2회 재시도인데 즉시 SafetyError로 잡 종료(재시도 0회). (6) Replicate 폴링 60초 상한(image.py:392)이 스펙 이미지 타임아웃 90초보다 짧아 60-90초대 정상 완료를 IMAGE_TIMEOUT 처리.
- **트리거**: 모든 프로덕션 생성 잡(진행률·타임아웃), 타임아웃 소진 잡(UNKNOWN 기록), ja/zh/es 생성에서 LLM이 부적절 표현 출력, 이미지 프로바이더가 부적절 이미지 반환, replicate 선택 시 60초+ 예측.
- **영향**: 규범 문서와 구현의 계약 파괴: 클라이언트 진행률 UX 불일치, 에러코드 기반 재시도 안내·모니터링 왜곡, 글로벌 다국어 제품에서 5개 언어 중 3개의 출력 안전망 부재 + 이미지 안전망 전무(아동 앱 스토어 심사·안전 리스크). CLAUDE.md 규칙상 '코드 쪽으로 조용히 해소 금지 — 보고 후 결정' 대상.
- **재현**: 잡 1건 실행하며 progress 시퀀스 기록(50-85 구간 확인). 스토리 단계 mock timeout 3회 소진 → job.error_code=='UNKNOWN'(규범 기대 LLM_TIMEOUT). language=es로 mock 스토리에 'violencia' 삽입 → moderate_output True 통과 → 책 완성.
- **수정**: 진행률 상수·단계 타임아웃을 스펙 표에 맞추거나 스펙을 코드 실측으로 개정(창업자 결정). run_step 최종 실패 시 last_exc 코드 보존. 출력 모더레이션을 LLM 기반(call_moderation 재사용, 언어 무관)으로 교체하거나 ja/zh/es 패턴 추가, 이미지 안전검사(프로바이더 safety flag 또는 vision) 배선, SAFETY_OUTPUT 시 스펙대로 재생성 2회 후 실패(또는 스펙에서 명시 보류).

### 52. 사진/그림 캐릭터 분석 실패 시 고정 mock 캐릭터('양갈래 소녀')를 성공으로 저장
`apps/api/src/services/photo_character.py:112`  · src: silent-failures

- **주장**: vision LLM 응답 JSON 파싱 실패 시 _analyze_with_openai(110-112)·_analyze_with_anthropic(157-159)이 _mock_analysis()(고정된 '검은 양갈래·분홍 원피스 여자아이' 설명, 233-254)를 반환하고, create_character_from_text는 모든 예외를 mock으로 삼킨다(399-400). characters.py:554-583은 이 결과를 from_photo=True 캐릭터로 그대로 저장하고 200을 반환한다.
- **트리거**: vision 모델의 JSON 아닌 응답(잘림, 거부 응답 — anthropic 경로는 response_format 강제 없음), 프로바이더 일시 장애. 아동 사진 업로드 → POST /v1/characters/from-photo.
- **영향**: 부모가 아들 사진을 올려도 전혀 다른 '여자아이' 캐릭터가 성공으로 생성되고, 이후 이 캐릭터로 만드는 모든 책 삽화가 엉뚱한 인물로 나온다. 오류 표시가 전혀 없어 사용자는 기능 결함으로 인식(아동 사진 기능 신뢰 파괴). 장애 시간대엔 모든 사진 캐릭터가 동일 인물로 생성.
- **재현**: _analyze_with_openai가 invalid JSON을 받도록 응답 mock → from-photo 생성 호출 → 200 + master_description이 'black pigtails... pink dress' 고정값으로 저장됨을 확인.
- **수정**: mock 폴백을 실 프로바이더 모드에서 제거하고 파싱 실패 시 예외를 올려 5xx 반환(재시도 1회 허용). mock 반환은 llm_provider=='mock'일 때만.

### 53. '오늘의 동화' book_id가 서버에서 영원히 null — 카드 탭마다 새 책 생성으로 크레딧 반복 소모
`apps/api/src/services/streak.py:468`  · src: contract-consistency

- **주장**: 계약의 TodayStoryResponse.book_id와 홈 화면 게이트(home_screen.dart:31 'todayBookId != null이면 바로 읽기')는 오늘 생성한 책의 재진입을 전제하지만, DailyStory.book_id에 값을 쓰는 코드가 코드베이스 어디에도 없다(쓰기는 data_deletion.py:46의 book_id=None 뿐, POST /v1/streak/today/generate도 갱신하지 않음). 따라서 book_id는 항상 null이고 '있으면 바로 읽기' 분기는 데드코드다.
- **트리거**: 사용자가 홈의 '오늘의 동화' 카드를 탭해 개인화 책을 생성(크레딧 1 소모)한 뒤, 홈으로 돌아와 같은 카드를 다시 탭.
- **영향**: 탭마다 새 잡 생성 + 크레딧 1개씩 추가 차감(유료 사용자는 무제한 반복 차감, 무료 사용자는 월 한도 조기 소진). 방금 만든 오늘의 책을 카드에서 다시 열 방법이 없음.
- **재현**: 1) GET /v1/streak/today → book_id: null 확인. 2) POST /v1/streak/today/generate로 생성 완료. 3) GET /v1/streak/today 재호출 → 여전히 book_id: null. 4) 홈 카드 재탭 → 두 번째 잡·두 번째 크레딧 차감이 transactions에 기록됨.
- **수정**: 오늘의 책은 사용자별이므로 DailyStory(전역)에 book_id를 쓰면 타 사용자 403이 나므로 불가 — 사용자 단위 추적 필요: /today 응답을 user_key 스코프로 확장(오늘 날짜에 해당 사용자의 daily-generate 잡/북 조회해 book_id 반환)하거나 ReadingLog/Job에 daily_story_date를 남겨 조회. 최소 수정: generate_today_story가 만든 Book을 (user_key, 날짜)로 조회해 TodayStoryResponse.book_id에 채운다.

### 54. Celery 재전달(acks_late+reject_on_worker_lost) 재실행이 비멱등 — 복구 메커니즘이 unique 제약 충돌로 확정 실패를 생산
`apps/api/src/services/tasks.py:73`  · src: orchestrator-jobs

- **주장**: generate_book_task는 acks_late=True, reject_on_worker_lost=True로 워커 손실 시 재전달·재실행되도록 설계됐지만, start_book_generation은 재실행 멱등성이 없다: story_drafts.job_id(db.py:66)·image_prompts.job_id(db.py:78)·books.job_id(db.py:120)가 모두 unique라 1차 실행이 스토리 저장을 지난 뒤 죽으면 재실행은 save_story_draft(orchestrator.py:1023-1031)에서 IntegrityError → 광역 except(383-385) → UNKNOWN 실패. 즉 크래시 복구용 설정이 실제로는 '반드시 실패하는 2차 실행'을 만든다.
- **트리거**: 이미지 생성 중 워커 OOM/컨테이너 교체(배포) → Celery가 메시지 재전달 → 새 워커가 처음부터 재실행 → save_story_draft에서 job_id unique 충돌.
- **영향**: 복구돼야 할 잡이 UNKNOWN으로 실패(+크레딧 미환불 결함과 결합). 1차 실행이 이미 지불한 LLM·이미지 비용 낭비. 완료 직후 ack 유실 케이스에서는 done 잡을 running→failed로 오염(fence 부재 결함과 결합).
- **재현**: 잡 실행해 story_drafts 행 생성 시점에 워커 kill -9 → 재전달된 태스크가 save_story_draft IntegrityError로 실패하고 job.error_code='UNKNOWN'이 됨을 확인.
- **수정**: save_story_draft/save_image_prompts를 upsert(ON CONFLICT job_id DO UPDATE)로, package_book은 기존 books.job_id 행 존재 시 재사용/스킵으로 멱등화. 또는 태스크 시작 시 기존 산출물 행을 정리 후 재생성.

### 55. characters_screen 사진 업로드 경로에 부모 인증(age gate) 누락 — 진입점 간 보호 불일치
`apps/mobile/lib/screens/characters_screen.dart:257`  · src: mobile-flutter

- **주장**: 동일한 from-photo/from-drawing 업로드에 대해 character_source_sheet._usePhoto는 showAgeGateDialog를 강제(108-113행)하지만, characters_screen._pickImage(257-299행)는 age gate 없이 JIT 동의 다이얼로그(취소/동의 2버튼)만 거친다. 아동이 스스로 '동의'를 탭하고 얼굴 사진을 업로드할 수 있다.
- **트리거**: 아동이 캐릭터 화면에서 카메라/갤러리 버튼 탭(167·177·188행) — 부모 인증 세션이 없어도 진행됨.
- **영향**: 아동 사진 수집이 보호자 검증 없이 발생 — 이중 보호 설계(게이트→JIT 동의)가 한 진입점에서만 작동. COPPA식 보호자 게이트 우회 경로이자 스토어 심사 리스크.
- **재현**: 앱 재시작(게이트 세션 만료) → Characters → 카메라로 사진 촬영 → 게이트 다이얼로그 없이 동의 다이얼로그로 직행 → 업로드 성공.
- **수정**: _pickImage 시작부에 character_source_sheet와 동일한 isAgeGateVerifiedForSession 검사 + showAgeGateDialog 게이트 추가(공용 헬퍼로 추출 권장).

### 56. 인페인트 _waitForJob이 잡 실패·40초 타임아웃을 성공으로 처리
`apps/mobile/lib/screens/inpaint_screen.dart:141`  · src: mobile-flutter

- **주장**: _waitForJob은 isComplete뿐 아니라 isFailed에서도 그냥 return하고, 40회(40초) 초과 시에도 조용히 return한다. 호출부 _apply(121-124행)는 구분 없이 bookDetail invalidate 후 Navigator.pop(context, true)로 '성공(반영됨)'을 반환한다.
- **트리거**: 인페인트 잡이 이미지 프로바이더 오류로 실패하거나, 재시도 포함 40초를 초과(이미지 생성 타임아웃 90초 스펙상 정상 범위)하는 경우.
- **영향**: 사용자는 성공으로 안내받았는데 이미지는 그대로(또는 나중에 실패) — 에러가 삼켜져 재시도 판단 불가. '실패를 성공으로 삼킴' 클래스의 사용자 가시 버그.
- **재현**: 이미지 프로바이더가 실패를 반환하도록 한 상태에서 인페인트 적용 → 잡 failed → 화면은 true로 pop되고 스낵바·에러 없음, 페이지 이미지 무변화.
- **수정**: _waitForJob이 최종 JobStatus(또는 timeout 신호)를 반환하게 하여 failed→에러 스낵바, timeout→'적용 중, 잠시 후 새로고침' 안내로 분기. 폴링 예산도 이미지 타임아웃 스펙(90초×재시도)에 맞춰 확대.

### 57. deploy.sh 운영 결함 — deploy 순서가 stop→start→migrate(새 코드가 구 스키마로 트래픽 수신, 실패 후에도 계속 서빙) + cleanup의 docker volume prune이 데이터 전손 경로
`scripts/deploy.sh:243`  · src: docs-ops

- **주장**: (a) deploy 커맨드는 pull_images → stop_services(compose down, 전체 다운타임) → start_services(up -d, 즉시 트래픽 수신) → run_migrations → health_check 순서다. 새 코드가 신규 컬럼/테이블을 요구하면 start~migrate 사이 모든 요청이 500. health_check 실패 시 set -e로 스크립트만 종료되고 서비스는 restart:always로 계속 떠서 트래픽을 받는다(트래픽 차단·롤백 없음) — DEPLOYMENT.md 'Missing release config must surface as deployment failure' 규범과 상충. (b) cleanup 커맨드(181행)는 docker system prune -f && docker volume prune -f를 무조건 실행 — compose down 후에는 postgres-data·redis-data·minio-data가 어떤 컨테이너에도 참조되지 않고, Docker Engine 23 미만에서는 volume prune이 named volume도 삭제한다(리포는 Docker 버전을 어디에도 핀하지 않음).
- **트리거**: 스키마 변경이 포함된 릴리스 배포, 마이그레이션이 실패하는 배포(새 코드+구 스키마 상태 무기한 지속). 운영자가 ./scripts/deploy.sh stop 후 cleanup 실행(둘 다 문서화된 커맨드) + 호스트 Docker 23 미만.
- **영향**: 배포 창마다 사용자 가시 500 구간, 마이그레이션 실패 시 반영구 스키마 불일치 서빙. 최악의 경우 운영 DB(크레딧·구독·IAP 영수증·생성물 전부)와 오브젝트 스토리지 볼륨 영구 삭제(백업은 수동 backup 커맨드에만 의존).
- **재현**: 신규 NOT NULL 컬럼을 읽는 코드가 든 이미지로 deploy 실행 → up 직후 /v1/library가 마이그레이션 완료 전까지 500; alembic 실패 리비전 주입 시 스크립트는 에러 종료하지만 docker compose ps는 계속 Up. Docker 22 스테이징에서 up→down 후 docker volume prune -f → postgres-data 소멸.
- **수정**: 순서를 pull → (구 서비스 유지 상태에서) compose run --rm api alembic upgrade head → up -d로 변경(후방호환 마이그레이션 전제), health_check 실패 시 이전 이미지 태그 자동 재기동 롤백 추가. cleanup에서 volume prune 제거(또는 볼륨 label 필터로 앱 볼륨 제외 + 실행 중 스택 확인·백업 선행 강제).

### 58. 캐릭터 프리셋 6종이 한국어 전용으로 원문 서빙 — 비한국어 책 주인공 이름·외형 묘사가 한국어로 고정
`apps/api/src/core/character_presets.py:12`  · src: gap:Global multilang generation layer (the orphaned 'i18n lens'): prompt templates, i18n core, golden harness

- **주장**: CHARACTER_PRESETS의 name('햇살이' 등)·master_description·appearance/clothing 전 필드가 한국어 고정이며 GET /v1/characters/presets(characters.py:256-259)가 원문 그대로 반환, from-preset으로 캐릭터 저장 시 그대로 영속된다. 이 캐릭터로 en/ja 책을 만들면 load_characters_from_db(llm.py:437-461)가 한국어 name/appearance를 스토리·이미지 프롬프트에 주입한다.
- **트리거**: 비한국어 사용자가 프리셋 선택 화면 진입 또는 프리셋 캐릭터로 책 생성 — 사진 업로드의 대안으로 명시된 기본 경로.
- **영향**: en UI에 한국어 프리셋 이름 노출 + 영어 동화의 주인공 이름이 '햇살이'(또는 임의 로마자화)로 생성되는 사용자 가시적 어색함. 이미지 프롬프트에도 한국어 외형 묘사 혼입(캐릭터 일관성 열화 가중).
- **재현**: GET /v1/characters/presets 응답이 로케일 무관 한국어임을 확인 → from-preset 캐릭터로 language=en 책 생성 → generate_story.user 프롬프트의 characters에 한국어 name/appearance가 들어감(렌더 확인 결정적).
- **수정**: 프리셋에 언어별 name/description(최소 ko/en/ja) 추가 후 Accept-Language 또는 쿼리 language로 선택 서빙, 저장 시 책 생성 언어에 맞는 변형 사용.

### 59. 캐릭터 시트 master_description '한글로' 하드코딩 + 이미지 프롬프트 출력 언어 미지정 — 비한국어 책의 모든 이미지 프롬프트에 한국어 혼입
`apps/api/src/prompts/generate_character_sheet.system.jinja2:8`  · src: gap:Global multilang generation layer (the orphaned 'i18n lens'): prompt templates, i18n core, golden harness

- **주장**: 캐릭터 시트 시스템 프롬프트 8행이 master_description을 '한글로 1~2문단' 작성하도록 강제하며 call_character_sheet_generation(llm.py:512-530)은 언어를 전달하지 않는다. generate_image_prompts.system.jinja2:7은 모든 positive_prompt에 master_description 원문 포함을 요구하고, 이 템플릿 역시 프롬프트 출력 언어 지시가 없다. 결과: en/ja/zh/es 책의 DALL-E 3(기본 프로바이더) 프롬프트마다 한국어 문단이 강제 혼입되고, negative_prompt에는 'korean text' 배제 토큰이 동시에 들어가는 모순 신호.
- **트리거**: 비한국어 책의 이미지 생성 전 단계(D→E→F). 글로벌 롤아웃의 모든 신규 언어 생성이 해당.
- **영향**: 이미지 프로바이더의 비영어 프롬프트 해석 저하로 캐릭터 일관성(제품 핵심 차별화 #2)·장면 충실도 열화. 페이지별 image_prompt는 재생성·인페인트·골든 하니스 심사에도 재사용되므로 열화가 전파된다. 다국어 롤아웃 스펙 의도와 충돌(규범 충돌 보고 대상).
- **재현**: language=en으로 파이프라인 실행 시 렌더된 캐릭터 시트 시스템 프롬프트에 '한글로' 지시가 그대로 포함됨(코드 확인 결정적). 라이브에서는 en 책의 pages[*].image_prompt에 한국어 master_description 포함.
- **수정**: 캐릭터 시트·이미지 프롬프트 호출에 language 전달, master_description과 positive_prompt는 이미지 프로바이더 최적 언어(영어) 고정 작성으로 통일하고 사용자 노출용 번역은 분리.

### 60. 입력 모더레이션에 언어 미전달 — 비한국어 사용자에게 안전 차단 사유·수정 제안이 한국어로 노출
`apps/api/src/prompts/moderate_input.system.jinja2:1`  · src: gap:Global multilang generation layer (the orphaned 'i18n lens'): prompt templates, i18n core, golden harness

- **주장**: moderate_input 템플릿 2종에는 language 변수가 없고 call_moderation(llm.py:419-434)도 spec.language를 전달하지 않는다. 시스템 프롬프트 전체가 한국어라 reasons/suggestions는 입력 언어와 무관하게 한국어로 생성될 개연성이 높고, 오케스트레이터 268행은 'f"입력이 안전하지 않습니다: {reasons}"'로 한국어 접두어를 하드코딩해 job.error_message에 저장한다. 이 메시지는 books.py:661-663에서 그대로 반환되고 loading_screen.dart:192가 원문 표시한다. 비한국어 입력에 대한 판정 품질 자체도 미검증(ko 프레이밍 프롬프트).
- **트리거**: en/ja/zh/es 사용자가 안전 위반 토픽으로 책 생성 → SAFETY_INPUT 실패 → 로딩 화면에 한국어 에러.
- **영향**: 차단 사유·대체 표현 제안(설계상 사용자 수정 유도용)이 사용자 언어로 전달되지 않아 안전 UX가 비한국어권에서 무력화. 아동 안전 게이트의 다국어 검증 공백.
- **재현**: language=en, topic에 명백한 위반 내용으로 생성 요청 → GET /v1/books/{job} error.message가 '입력이 안전하지 않습니다: <한국어 사유>' 형태 → en UI에 그대로 렌더.
- **수정**: moderate_input 템플릿에 language_name 전달 + 'reasons/suggestions는 {{ language_name }}로 작성' 지시, 오케스트레이터 268행 접두어는 에러코드 기반 클라이언트 l10n으로 대체. 다국어 위반 샘플로 판정 회귀 테스트 추가.

### 61. 페이지 오디오가 ko/en 전용 — ja/zh/es 책은 한국어 보이스가 원문(일본어 등)을 읽는 오디오가 생성·영속됨
`apps/api/src/routers/books.py:1395`  · src: gap:Global multilang generation layer (the orphaned 'i18n lens'): prompt templates, i18n core, golden harness

- **주장**: GET /v1/books/{id}/pages/{n}/audio는 language 쿼리를 pattern='^(ko|en)$'로 제한하고 기본 ko다. ja 책에서 기본 호출 시 text_ko가 None이라 source_text가 page.text(일본어 원문)로 폴백(1455행)되고, tts.py:51-54는 language를 'ko-KR'/'en-US' 둘로만 매핑해 ko-KR Neural2 보이스로 일본어 텍스트를 합성한다. 결과물이 audio_url_ko/audio_url로 영속돼 이후 캐시 반환된다.
- **트리거**: ja/zh/es 책 사용자가 낭독 재생(모바일 기본 호출) — 3-5세 비독자 접근성의 유일한 소비 경로로 명시된 기능.
- **영향**: 출시 언어 3종에서 깨진(잘못된 보이스/발음) 오디오가 생성·과금(유료 게이트 연령대)·영구 캐시됨. 비독자 아동에게는 책 소비 자체가 불가능한 수준의 열화.
- **재현**: language=ja 책 생성 → GET .../pages/1/audio (기본 language=ko) → text_ko=None → page.text(일본어)가 ko-KR 보이스로 합성돼 audio_url_ko에 저장됨을 코드 경로로 확인.
- **수정**: 오디오 language를 책 언어까지 허용(SUPPORTED_LANGUAGES 기반 패턴)하고 tts.py 언어→보이스 매핑에 ja/zh/es 추가. 미지원 언어는 잘못된 보이스로 fail-open 하지 말고 명시 에러(NOT_SUPPORTED) 반환. TTS 언어 확장이 미결 제품 결정이라면 최소한 fail-open만이라도 차단 후 보고·결정 필요.

### 62. call_text_rewrite가 스키마 검증·펜스 제거 없는 raw json.loads + revised_text 누락 시 조용한 성공 처리
`apps/api/src/services/llm.py:577`  · src: gap:Global multilang generation layer (the orphaned 'i18n lens'): prompt templates, i18n core, golden harness

- **주장**: call_text_rewrite만 유일하게 parse_json_response를 우회하고 json.loads(response)를 직접 호출한다(577행) — 마크다운 펜스 제거·Pydantic 검증 없음. CLAUDE.md 규범 'LLM 출력은 무조건 JSON Schema 검증 후 진행' 위반. Anthropic 프로바이더는 JSON 모드 강제가 없어(response_format 미전달, 344-353행) ```json 펜스 출력이 흔한데 이 경로는 즉시 JSONDecodeError. 또한 orchestrator.py:1103의 rewrite_result.get("revised_text", page.text)는 키 누락 시 원문 유지인 채로 재생성 잡을 성공 처리한다(에러를 성공으로 삼킴 클래스).
- **트리거**: llm_provider=anthropic(또는 스키마 이탈 출력)에서 텍스트 재생성 호출. 프로바이더 전환은 config 한 줄.
- **영향**: 펜스 출력 → 재생성 실패(설계상 LLM_JSON_INVALID 2회 재시도 규칙도 미적용, 원시 예외 문자열이 error_message로 노출). 키 누락 → 사용자는 '재생성 완료'를 보지만 텍스트는 그대로 — 조용한 no-op 성공.
- **재현**: mock으로 {"result":...}만 반환하게 하거나 응답을 ```json 펜스로 감싸면: 전자는 페이지 불변+성공 보고, 후자는 JSONDecodeError. RewriteResult Pydantic 모델로 parse_json_response 태우면 둘 다 재현/차단 확인.
- **수정**: RewriteResult(page/revised_text/notes) DTO 추가 후 parse_json_response 사용, revised_text 부재 시 명시 실패(LLM_JSON_INVALID) + 설계 스펙대로 재시도.

### 63. 오케스트레이터 step_name 한국어 하드코딩이 모바일 l10n 키 매핑과 계약 불일치 — 전 로케일에서 생성 진행 문구가 한국어로 노출
`apps/api/src/services/orchestrator.py:247`  · src: gap:Global multilang generation layer (the orphaned 'i18n lens'): prompt templates, i18n core, golden harness

- **주장**: run_step에 전달되는 step_name이 '입력 확인 중...'(247), '안전성 검사 중...'(257), '이야기 쓰는 중...'(276) 등 한국어 표시 문자열이며 그대로 job.current_step에 저장돼 API로 반환된다. 반면 모바일 loading_screen.dart:222-233의 _getStepDescription은 'normalize'/'moderate_input' 등 영문 키를 기대하고 매칭 실패 시 `?? step`으로 원문을 그대로 표시한다 — l10n 매핑이 데드코드.
- **트리거**: 모든 책 생성. en/ja 로케일 사용자가 로딩 화면을 보는 순간(제품 핵심 플로우, 매 생성마다).
- **영향**: 글로벌 출시의 핵심 화면(생성 진행)에서 영어·일본어 사용자에게 한국어 진행 문구가 그대로 노출. 준비된 l10n 문자열(loadingStepNormalize 등)이 전혀 쓰이지 않음 — CLAUDE.md '하드코딩 금지' 규칙과 스펙-코드 계약 불일치.
- **재현**: 언어 무관 책 생성 → GET /v1/books/{job_id} 응답 current_step='이야기 쓰는 중...' → 모바일 _getStepDescription('이야기 쓰는 중...') 은 맵 미스 → 한국어 원문 표시. 코드 대조만으로 결정적.
- **수정**: 백엔드 current_step을 안정 키('generate_story' 등)로 저장하고 표시 문자열은 클라이언트 l10n에 위임(또는 키+한국어 병행 필드). routers/streak.py:213의 '오늘의 동화 대기 중', books.py 생성 경로의 초기 step도 동일 적용.

### 64. 네이티브 사용자 노출 문자열 전부 한국어 하드코딩 — 앱 표시명·iOS 권한 목적 문자열 en/ja 미지역화
`apps/mobile/ios/Runner/Info.plist:8`  · src: gap:Mobile native platform config (iOS Info.plist / AndroidManifest / store-review surface)

- **주장**: CFBundleDisplayName='AI 동화책'(Info.plist:8), android:label='AI 동화책'(AndroidManifest.xml:9), 카메라·사진·마이크 목적 문자열(Info.plist:31-38)이 모두 한국어 고정. ios/Runner에는 Base.lproj만 존재(InfoPlist.strings en/ja/ko 없음), Android에도 values-en/values-ja 문자열 리소스가 없다. 앱 UI는 ko/en/ja l10n을 갖춘 글로벌 제품인데 홈 화면 앱 이름과 iOS 권한 프롬프트만 전 세계에서 한국어로 뜬다.
- **트리거**: 영어/일본어 기기 사용자가 앱 설치 후 홈 화면 아이콘 라벨 확인, 또는 사진 기반 캐릭터 생성 시 iOS 권한 다이얼로그 노출.
- **영향**: 글로벌 출시 제품의 첫인상(앱 이름)·권한 동의 문구가 비한국어 사용자에게 이해 불가 — 전환율 손실 + Apple 심사에서 목적 문자열 명확성 지적 리스크. 프로젝트 규칙 '사용자 노출 문자열 ko/en/ja 동시(하드코딩 금지)' 위반.
- **재현**: 기기 언어 en/ja로 설정 → 앱 설치 → 홈 화면 라벨 'AI 동화책'(한국어) 확인; 캐릭터 사진 촬영 시도 → 한국어 권한 프롬프트.
- **수정**: Android: label을 @string/app_name으로 리소스화 + values-en/values-ja 추가. iOS: ko/en/ja lproj에 InfoPlist.strings(CFBundleDisplayName + NS*UsageDescription) 추가.

### 65. 골든 하니스 CI 게이트가 ko/en만 검증 — ja/zh/es는 게이트 미통과 언어인 채 출시, mock은 zh/es를 표현조차 못함
`docs/qa/golden-prompts.json:1`  · src: gap:Global multilang generation layer (the orphaned 'i18n lens'): prompt templates, i18n core, golden harness

- **주장**: CI 게이트(ci.yml:110-116)가 실행하는 골든 프롬프트는 ko 3건 + en 1건뿐 — ja/zh/es 엔트리가 없다. 게다가 mock LLM의 언어 감지 목록(llm.py:261, ('en','ja','ko'))에 zh/es가 없어 zh/es 골든을 추가해도 mock이 ko로 응답해 language_matches_spec(golden_harness.py:295-304)이 mock 한계로 실패한다 — 즉 신규 언어 2종은 구조 게이트를 통과할 수 있는 경로 자체가 배선되지 않았다.
- **트리거**: 매 CI 실행. 출시 판정이 이 게이트의 green에 의존한다(false-green).
- **영향**: 출시 헤드라인(5개 언어 생성)의 3개 언어가 파이프라인 게이트를 한 번도 통과하지 않은 채 GA — ja/zh/es 전용 회귀(언어 전파·학습자산·패키징)가 침묵 통과한다. 본 감사에서 발견된 ja/zh/es 계열 결함들이 게이트에 안 잡힌 것이 그 증거.
- **재현**: golden-prompts.json에 {language:"zh"} 엔트리 추가 후 mock 하니스 실행 → mock이 language:"ko"를 반환해 language_matches_spec 실패(테스트 인프라가 언어를 표현 못함이 즉시 드러남).
- **수정**: mock 언어 감지를 SUPPORTED_LANGUAGES 전체로 확장(i18n.SUPPORTED_LANGUAGES 참조로 단일 출처화)하고 ja/zh/es 골든 엔트리 각 1건 이상 추가.


## ⚪ LOW

### 66. deploy가 $GITHUB_SHA 대신 최신 origin/main을 체크아웃 — 이미지/리포 스큐
`.github/workflows/ci.yml:429`  · src: gap:CI release-gate workflow content

- **주장**: deploy 스텝의 원격 스크립트가 `git pull --ff-only origin main`(429행)으로 서버 리포를 그 시점의 최신 main으로 올리면서, 이미지는 `--image-tag "$GITHUB_SHA"`(430행)로 이 런의 커밋에 고정한다. 런 진행 중 main에 새 커밋이 오르면 compose 파일·nginx 설정·deploy.sh·smoke.sh(신 커밋)와 컨테이너 이미지(구 커밋)가 어긋난다. 불가역 액션(배포) 직전 stale-read 클래스. cancel-in-progress가 대부분의 창을 닫지만, 취소 신호가 SSH 스텝 실행 중 도착해 원격 스크립트만 살아남는 경로에서 정확히 이 스큐가 실현된다.
- **트리거**: 첫 런의 deploy SSH 스텝 실행 도중 두 번째 커밋이 main에 push되는 경우(연속 머지·hotfix).
- **영향**: 신 compose 정의(예: 새 env var, 새 서비스)와 구 이미지 조합으로 기동 실패 또는 미검증 조합이 프로덕션에 올라감. 어떤 CI 런도 이 조합을 테스트한 적이 없다.
- **재현**: 코드 검사로 확인: 429행은 ref를 고정하지 않고 430행만 SHA를 고정한다. 시뮬레이션: deploy 스크립트 실행 중 main에 커밋 추가 후 서버에서 `git log -1`과 실행 중 이미지 태그 비교.
- **수정**: 원격 스크립트를 `git fetch origin && git checkout --detach "$GITHUB_SHA"`로 변경해 리포와 이미지를 동일 커밋에 고정.

### 67. Live E2E가 스테일 APP_VERSION '0.3.2' 핀으로 구동 — 1.0.0 버전 통일 미반영
`.github/workflows/ci.yml:107`  · src: gap:CI release-gate workflow content

- **주장**: 커밋 94cb839가 api/mobile/contract 버전을 1.0.0으로 통일했으나(core/config.py:22 `app_version="1.0.0"`, apps/api/.env.example APP_VERSION="1.0.0") ci.yml 107행은 E2E 서버를 `APP_VERSION: "0.3.2"`로 구동하고, scripts/run_live_e2e.sh:26의 기본값도 `${APP_VERSION:-0.3.2}`다. e2e_journey.py는 현재 버전을 assert하지 않아 CI는 통과하지만, E2E가 GA 구성과 다른 버전 문자열(FastAPI 메타데이터·/health 응답)로 검증을 수행한다.
- **트리거**: 모든 main push/PR CI 실행 시 Live E2E 스텝.
- **영향**: 지금은 표기 드리프트(E2E의 /health가 0.3.2 보고)이나, 버전 기반 게이트(min_app_version 강제 업데이트, 계약 테스트의 info.version 검증 등)를 추가하는 순간 CI가 GA와 다른 버전으로 통과하는 잠복 정합성 구멍이 된다. 버전 통일 작업의 취지(단일 정본)에 대한 회귀.
- **재현**: ci.yml:107과 run_live_e2e.sh:26의 '0.3.2' 대 config.py:22·.env.example:12의 '1.0.0' 대조.
- **수정**: ci.yml 107행 env 삭제 + run_live_e2e.sh:26의 기본값 제거(설정 기본 1.0.0 사용) 또는 둘 다 1.0.0으로 갱신.

### 68. 'Check environment contracts' 게이트가 실제로는 .env.example 파일 존재만 확인
`.github/workflows/ci.yml:82`  · src: gap:CI release-gate workflow content

- **주장**: 82행(및 259행)의 `./scripts/check-env.sh --mode ci`가 호출하는 run_ci_checks(check-env.sh:135-163)는 apps/api/.env.example·infra/.env.example 파일이 존재하는지만 검사하고, env.schema.json은 존재 여부만 로그하며 어떤 검증에도 사용하지 않는다. config.py에 신규 필수 설정이 추가되고 .env.example/infra compose에 빠져도, 혹은 .env.example가 스키마와 어긋나도 CI는 통과한다. 스텝 이름 'Check environment contracts'가 실제 검증 강도를 크게 과장한다(계약 검증이 있다는 거짓 신호).
- **트리거**: 새 필수 설정(예: 신규 IAP 웹훅 시크릿)을 config.py에 추가하면서 infra/.env.example 갱신을 누락한 PR — CI 전 잡 green.
- **영향**: 배포 시점에야 결측 발견(deploy.sh는 infra/.env를 source하므로 값 결측 시 pydantic 기본값으로 fail-open 기동하거나 기동 실패). '환경 계약 검사 통과'라는 신호를 믿은 배포가 프로덕션에서 처음 깨진다.
- **재현**: check-env.sh run_ci_checks 본문 확인 — 파일 존재 검사 2건과 optional 로그뿐. config.py 필드와 .env.example 키의 대조 로직 부재.
- **수정**: CI 모드에서 env.schema.json 기준으로 .env.example 키/형식 검증 + config.py Settings 필드와의 대조를 추가하거나, 최소한 스텝 이름을 'Check env example files exist'로 실체에 맞게 변경.

### 69. 커버리지 게이트가 전역 임계(API 40% / Flutter 25%)뿐 — money 경로 per-glob 임계 부재
`.github/workflows/ci.yml:101`  · src: gap:CI release-gate workflow content

- **주장**: API는 `coverage report --fail-under=40`(101행), Flutter는 인라인 파이썬으로 전역 25%(164-182행)만 게이트한다. 리포에 .coveragerc·codecov.yml·pyproject coverage 설정이 없어 per-glob(경로별) 임계가 전혀 없다. services/credits·iap_verifier 등 money 경로 파일의 커버리지가 0%로 떨어져도 전역 40%만 넘으면 통과한다. 사용자 전역 규칙이 요구하는 '글로브별 임계' 게이트 표준과도 불일치.
- **트리거**: money 경로 테스트를 대거 삭제/스킵하는 PR도 전역 임계만 만족하면 green.
- **영향**: 출시 게이트가 결제·크레딧 코드의 테스트 소실을 감지하지 못함. 게이트 강도 문제(잠복).
- **재현**: 리포 루트·apps/api에서 coverage 설정 파일 부재 확인(`.coveragerc`, `codecov.yml`, pyproject `[tool.coverage]` 모두 없음) + ci.yml의 두 임계가 전역 단일값임을 확인.
- **수정**: apps/api에 `[tool.coverage.report] fail_under` + per-path 검사 스크립트(예: services/credits.py·iap_verifier.py 등 money 글로브 80%+) 추가, Flutter도 화면/서비스 글로브별 임계 스크립트로 확장.

### 70. 책 오디오 일괄 생성 실패가 어떤 상태 채널에도 표면화되지 않음
`apps/api/src/routers/books.py:1295`  · src: silent-failures

- **주장**: POST /v1/books/{id}/audio는 즉시 {'status':'processing'}을 반환하고 백그라운드 _generate_audio_for_book은 타임아웃·실패를 로그만 남긴다(1294-1295, 1376-1382). 잡 행이 없어 클라이언트가 폴링할 상태 엔드포인트가 없고, 전체 실패 시 사용자는 무한 '생성 중'만 본다.
- **트리거**: TTS 프로바이더 장애/S3 장애 중 오디오 생성 요청, 또는 5분 타임아웃 초과(저속 프로바이더 + 8페이지×2언어).
- **영향**: 사용자에게 실패 통지가 불가능한 fire-and-forget — 페이지별 온디맨드 합성으로 부분 복구는 되지만 일괄 생성 UX는 침묵 실패.
- **재현**: tts_service.synthesize_page를 raise로 패치 → 오디오 생성 호출 → 200 'processing', 이후 어떤 API로도 실패 확인 불가(audio_url 전부 null 유지).
- **수정**: regen 잡과 동일하게 Job 행(audio_ 접두)을 만들어 done/failed 전이 기록, 또는 응답에 폴링 가능한 상태 리소스 제공.

### 71. POD 주문 상태 동기화 결함 — GET 조회가 전이 가드 없이 provider 상태를 덮어써 취소가 sticky하지 않음 + strict 모드는 Printful 장애 시 조회 자체가 400
`apps/api/src/routers/pod.py:179`  · src: pod-orders

- **주장**: (a) get_pod_order는 sync 결과를 전이 검증 없이 직접 대입한다(routers/pod.py:179). 단일 전이 함수·금지 전이 목록(취소/환불 sticky 보장)이 없고, 로컬 상태 어휘('created')와 Printful 어휘(draft/inprocess/fulfilled/canceled 등)가 매핑 없이 혼재 저장되며, 읽기 엔드포인트가 상태를 쓰고 변경 없어도 무조건 commit(182)하는 side-effectful read다. (b) sync_order_status는 strict 모드에서 설정 결함(pod_provider.py:98) 또는 Printful 조회 실패(120)를 ValidationError(HTTP 400)로 전파하고 routers/pod.py:174는 이를 잡지 않아 GET /v1/pod/orders/{id}가 통째로 실패한다 — 게다가 모든 조회가 최대 20초 동기 외부호출을 수반(pod_provider.py:215).
- **트리거**: 운영자가 로컬 DB에서 주문을 canceled/refunded로 마킹(결제/취소가 별도 운영 절차인 현 구조의 유일한 로컬 상태 관리 경로)한 직후 사용자가 주문 상세를 열면 GET sync가 Printful의 'inprocess'로 되돌림. strict 운영 중 Printful 장애/키 만료 + 주문 상세 진입.
- **영향**: 취소·환불된 주문이 사용자 화면에서 진행 중으로 부활(고객 혼란·CS), 운영 로컬 상태 마킹 신뢰 불가, 상태 어휘 혼재로 모바일 표시 미정의. strict에서는 provider 장애 기간 동안 데이터가 로컬 DB에 있는데도 주문 조회 불가 + 응답 지연 최대 20초.
- **재현**: 주문 생성 → DB status='canceled' → Printful 스텁 'inprocess' 반환 → GET → status 'inprocess' 회귀. POD_MODE=strict + 스텁 500 → GET /v1/pod/orders/{id} → 400.
- **수정**: 허용 전이 테이블을 가진 단일 apply_provider_status() 도입: 종결 상태는 sticky, Printful→로컬 매핑 명시, 변경 없을 때 commit 생략. 조회 경로는 strict에서도 로컬 스냅샷을 반환하고 sync 실패는 sync_source='sync_failed' 메타로만 표시(읽기 로컬 우선, 쓰기만 fail-closed), 상태 동기화는 백그라운드 잡/웹훅으로 이동.

### 72. 스트릭 캘린더가 '지금 기준 상대 윈도우'로 조회 — 약 2개월 이전 달은 항상 빈 캘린더
`apps/api/src/routers/streak.py:323`  · src: time-streak

- **주장**: GET /v1/streak/calendar?year&month가 요청된 달의 절대 범위가 아니라 get_reading_history(days=days_diff+30) 즉 '지금 - (약 61일)'의 상대 윈도우로 로그를 가져온 뒤 문자열 prefix로 해당 월을 필터한다(318-329). 요청 월이 윈도우 밖이면 로그가 0건이라 전부 read=false가 된다. 부수적으로 get_reading_history의 since=utcnow()-timedelta(days)(services/streak.py:504)는 24시간 뺄셈이라 리포트의 로컬 하루 경계 방식(local_day_bounds_utc)과도 불일치.
- **트리거**: 캘린더 UI에서 2~3개월 이전 달로 스와이프하는 모든 사용자(year 2020~2100 허용이므로 API 스펙상 명시적으로 지원되는 조회).
- **영향**: 과거 달의 읽은 날이 전부 사라진 빈 캘린더 + total_read_days=0 표시 — 부모에게 '기록이 유실됐다'는 인상(신뢰 훼손, 지원 문의). 직전 달도 월 초 구간이 잘려 부분 누락.
- **재현**: 3개월 전 날짜의 ReadingLog가 있는 사용자로 GET /v1/streak/calendar?year=<3개월 전 연>&month=<월> 호출 → days 배열 전부 read:false, total_read_days:0. 같은 데이터가 GET /v1/growth의 total_reading_days에는 집계됨(모순 노출).
- **수정**: 캘린더는 요청 월의 절대 경계로 직접 조회: 해당 월의 로컬 자정 경계(local_day_bounds_utc 계열)로 [월초, 익월초) UTC 범위를 만들어 ReadingLog.read_date 범위 쿼리 후 to_local_date로 그룹화. get_reading_history의 since도 로컬 하루 경계 기반으로 정렬.

### 73. get_or_create_credits·get_or_create_streak 최초 생성이 check-then-write — 동시 첫 요청 PK 충돌로 신규 사용자에게 일회성 500
`apps/api/src/services/credits.py:54`  · src: money-credits, time-streak

- **주장**: user_credits 행 미존재 시 SELECT 후 INSERT하는 check-then-write(credits.py:54, PK=user_key)로, 신규 사용자의 첫 요청 2건이 동시에 오면 한쪽 INSERT가 IntegrityError로 실패하고 use_credit/잔액 조회 경로 밖으로 전파되어 500이 된다. ON CONFLICT 처리나 IntegrityError 재조회 폴백이 없다. 동일 패턴이 get_or_create_streak(services/streak.py:105-119, daily_streaks PK=user_key)에도 존재한다.
- **트리거**: 앱 첫 실행 시 클라이언트가 /credits/status와 /credits/balance(또는 books 생성)를 병렬 호출하는 일반적 패턴, 신규 사용자의 GET /v1/streak/info 동시 호출. 멀티 레플리카에서 확률 상승.
- **영향**: 신규 사용자 온보딩 첫 화면에서 간헐 500(재시도로 회복·자가 치유). 금전 손실은 없음(보너스 크레딧 이중 지급은 PK가 차단). 온보딩 첫인상 훼손 수준.
- **재현**: 미존재 user_key로 두 세션이 동시에 get_or_create_credits(또는 get_or_create_streak) 실행 → 한쪽 commit 성공, 다른 쪽 IntegrityError 전파 → 500.
- **수정**: 두 헬퍼 모두 IntegrityError를 잡아 rollback 후 재SELECT하여 기존 행을 반환(또는 PostgreSQL ON CONFLICT DO NOTHING 후 재조회).

### 74. 프로필 경유 읽기는 계정 단위 DailyStreak를 갱신하지 않음 — 같은 성장 리포트 안에서 books_read>0인데 streak=0 모순
`apps/api/src/services/growth.py:261`  · src: time-streak

- **주장**: get_growth_report(profile_id=None)는 books_read/completion을 profile 무관 전체 ReadingLog로 집계(224-244)하면서 current_streak/total_reading_days는 daily_streaks 테이블에서 읽는다(256-263). 그런데 record_reading의 profile 경로(services/streak.py:242-285)는 ReadingLog만 쓰고 daily_streaks를 전혀 갱신하지 않으며, 모바일 클라이언트는 활성 프로필이 있으면 모든 요청에 X-Profile-Id를 자동 첨부한다(apps/mobile/lib/services/api_client.dart:96-100). 즉 프로필 생성 이후 daily_streaks는 영구 동결.
- **트리거**: 자녀 프로필을 만든 뒤 프로필로 매일 읽는 일반 사용자가, 프로필 헤더 없이 GET /v1/growth 또는 GET /v1/streak/info를 조회(프로필 선택 전 화면·계정 요약 화면 등).
- **영향**: 동일 응답 안에서 books_read=30, current_streak=0, total_reading_days=0 같은 자기모순 리포트 — 부모 대시보드 신뢰 훼손. 프로필 없이 쓰다가 프로필을 만든 사용자는 계정 스트릭이 그 시점 값으로 박제되어 영원히 낡은 숫자가 노출됨.
- **재현**: 1) POST /v1/profiles로 프로필 생성. 2) X-Profile-Id 포함 POST /v1/streak/read를 3일 연속 호출. 3) X-Profile-Id 없이 GET /v1/growth → books_read=3, current_streak=0, total_reading_days=0. 4) X-Profile-Id 포함 GET /v1/streak/info → current_streak=3 (같은 데이터, 다른 답).
- **수정**: 계정 단위 스트릭도 ReadingLog 기반 재계산으로 통일(_get_profile_streak_info를 profile_id 필터 없는 버전으로 일반화해 get_growth_report·get_streak_info(no-profile)가 사용), 또는 profile 경로 record_reading에서도 daily_streaks를 동일하게 조건부 UPDATE.

### 75. IAP 검증·웹훅 하드닝 공백 — 운영에서 Apple 샌드박스 영수증 실지급 게이트 부재 + 웹훅 서명/타임스탬프/이벤트ID 리플레이 가드 부재
`apps/api/src/services/iap_verifier.py:236`  · src: iap-webhooks

- **주장**: (a) _post_apple_receipt는 status 21007(테스트 영수증을 프로덕션 엔드포인트로 전송) 시 샌드박스 URL로 재검증해 environment='Sandbox', verified=True를 반환하는데, verify_iap의 지급 경로(routers/iap.py:147 이후)는 verification.environment를 전혀 검사하지 않아 샌드박스(무결제) 영수증도 실제 크레딧·구독을 발급한다. (b) 웹훅 인증 _require_webhook_secret(iap.py:409)은 공유 시크릿 토큰(?token=) 일치만 검사하고 서명/HMAC, 타임스탬프 스테일니스 창, 외부 이벤트 id(notificationUUID 등) 기반 리플레이 dedup이 없다 — 토큰은 URL 쿼리에 실려 로그·리퍼러 노출 위험.
- **트리거**: 샌드박스 테스터 계정으로 생성한 무료 영수증을 운영 /v1/iap/verify에 제출(21007 폴백 통과). 토큰 유출/릴레이 경유 시 과거 refunded 이벤트 재전송·임의 transaction_id 상태 변조 시도.
- **영향**: 샌드박스 테스터 접근이 가능한 주체에게 무료 엔타이틀먼트 경로. 특정 유저를 겨냥한 refunded 재전송으로 구독 그리핑성 강등·오래된 이벤트로 상태 되돌리기 가능(하위 연산 다수가 멱등이라 피해는 제한적).
- **재현**: 샌드박스 영수증으로 verify → 크레딧 지급, IAPReceipt.payload.verification_environment='Sandbox' 확인. 유효 token으로 refunded 반복/지연 재전송 → 매번 수락, 이벤트 id 중복 거부 없음 확인.
- **수정**: 운영(testing=False)에서 environment=='Sandbox'는 실지급 차단(리뷰용 allowlist만 예외), 지급 전 environment 검사·별도 상태 기록. 실 스토어 서명(Apple JWS/Google Pub/Sub) 검증 + signedDate 스테일니스 창 + 이벤트 id dedup 추가, 토큰은 헤더로 이동.

### 76. pod_mode 무효값의 조용한 'local' 폴백 + .env.example에 POD/PRINTFUL 항목 전무 + printful_store_id int() 미보호
`apps/api/src/services/pod_provider.py:50`  · src: pod-orders

- **주장**: create_order/sync_order_status는 pod_mode가 {local,hybrid,strict} 밖이면 경고 없이 'local'로 폴백한다(pod_provider.py:50-51, 84-85). 그런데 apps/api/.env.example·infra/.env.example에는 POD_MODE·PRINTFUL_API_KEY·PRINTFUL_SYNC_VARIANT_ID·PRINTFUL_STORE_ID 항목이 아예 없어(grep 0건) 배포 템플릿상 유효값을 알 수 없고, 오타(예: POD_MODE=printful)가 무음 local이 된다. 추가로 pod_provider.py:157의 `int(settings.printful_store_id)`는 비숫자 문자열이면 ValueError가 미처리 전파되어 주문 API가 500이 된다.
- **트리거**: 출시 시 Printful 키 투입(런치 체크리스트 H6) 과정에서 운영자가 .env에 값을 수기로 추가 — 템플릿 부재 + 모드값 오타 시 조용한 local 강등. store_id에 비숫자 입력 시 전 주문 500.
- **영향**: 운영은 Printful 연동이 켜졌다고 믿는데 모든 주문이 provider로 전송되지 않고 로컬에만 쌓임(status='created' 영구) — 경고 로그·알림 없음. fail-open 설정 클래스.
- **재현**: POD_MODE=printful로 설정 → POST /v1/pod/orders → sync_source='local', 경고 로그 없음 확인. PRINTFUL_STORE_ID=mystore → POST 시 ValueError 500 확인.
- **수정**: 무효 pod_mode는 기동 시 검증 실패(fail-closed) 또는 최소 structlog warning. 두 .env.example에 POD_MODE/PRINTFUL_* 4종 추가. printful_store_id는 config에서 int 타입 선언 또는 파싱 실패를 ValidationError로 변환.

### 77. 프로필 경계 소결함 — 이미 지급된 마일스톤 보상이 응답에 reward로 재노출(미지급 축하) + growth 라우터 X-Profile-Id 소유권 검증 생략(무음 0점 리포트·dangling 기록)
`apps/api/src/services/streak.py:277`  · src: time-streak

- **주장**: (a) record_reading은 _grant_milestone_rewards의 반환값(실지급 여부)을 버리고 _check_milestones 결과를 그대로 응답 milestones에 담는다(277-285, 365-372). 보상 reference_id는 milestone_total_{days}로 프로필 구분이 없어(392), 두 번째 프로필이 같은 total 임계(10/50/100일)에 도달하면 add_milestone_credits_once가 유니크 인덱스(models/db.py:281-296)로 지급을 거부(False)하는데도 응답에는 reward:'free_pdf'가 그대로 실린다(크레딧 이중 지급 자체는 DB 유니크로 잘 차단됨을 확인). (b) streak 라우터는 _validate_profile_ownership으로 프로필 소유·존재를 검증해 422를 주는데(routers/streak.py:39-58), growth 라우터의 GET /v1/growth·/peers·POST /answers는 X-Profile-Id를 형식 검사만 하고 그대로 사용한다(growth.py:33, 43-45, 68) — 삭제/타인 profile_id면 전부 0인 리포트를 정상 응답하고, record_answer는 dangling profile_id로 QuizAnswer를 저장(FK 없음, db.py:604)하며, _resolve_age_band 기본 '5-7' 폴백(growth.py:320-321)으로 3-5세 랭킹 비노출 정책 우회 가능성. user_key 스코프는 유지되어 타 사용자 데이터 유출은 없음.
- **트리거**: 프로필 2개 계정에서 두 번째 프로필이 누적 10일차 읽기 기록; 프로필 삭제 후 클라이언트에 남은 stale X-Profile-Id로 성장 화면 진입(모바일은 활성 프로필 id를 모든 요청에 자동 첨부 — api_client.dart:96-100).
- **영향**: 클라이언트가 '무료 PDF 보상 획득' 축하를 표시하지만 크레딧 미지급 — 보상 신뢰 훼손·문의. '기록 전부 소실'로 보이는 무음 0점 리포트(에러 없어 원인 추적 어려움), 어느 프로필에도 귀속 못하는 퀴즈 응답 축적.
- **재현**: 프로필 A로 10일 누적 → 지급. 프로필 B 10일 도달 시 응답 milestones에 reward 포함되나 잔액 불변. 삭제된 프로필 id를 X-Profile-Id로 GET /v1/growth → 200 전부 0; POST /answers → dangling 저장.
- **수정**: _grant_milestone_rewards가 실지급 여부를 반환하게 바꿔 미지급 보상은 reward null(또는 granted:false) 처리 — 프로필별 지급 여부는 제품 결정. streak의 _validate_profile_ownership을 공용 의존성으로 승격해 growth 3개 엔드포인트에도 적용(무효 프로필 → 422).

### 78. 모바일 언어 표면 축소 — 설정 언어 선택이 실제 UI 로캘을 바꾸지 않음(ko/en만, ja 누락, MaterialApp locale 미배선) + 이야기 언어 선택지 3개(zh/es 미노출, 스펙 5개)
`apps/mobile/lib/screens/create_screen.dart:73`  · src: mobile-flutter

- **주장**: (a) 설정의 언어 드롭다운(settings_screen.dart:503)은 서버 설정 'language'(ko|en)만 저장하고, MaterialApp에는 locale/localeResolutionCallback 오버라이드가 없어(main.dart:119-128) UI 언어는 항상 시스템 로캘을 따른다 — 드롭다운 변경이 아무 가시 효과가 없고, UI가 지원하는 ja는 선택지에 없다. (b) 생성 화면 supportedStoryLangs = {'ko','en','ja'}이고 언어 칩도 3개(create_screen.dart:73-76, 393-397)라 zh/es 이야기 생성이 UI에서 불가능 — CLAUDE.md는 '스토리 생성 언어: ko/en/ja/zh/es(core/i18n.py)'를 제품 표면으로 명시하며, FOUNDER_DECISIONS_PENDING.md에 이 축소를 정당화하는 미결 결정이 없다.
- **트리거**: 사용자가 설정 → 언어를 English로 변경 후 저장(UI 그대로); 스페인어·중국어 사용자가 생성 화면 진입(로캘 비지원 시 영어로 강제 기본).
- **영향**: 동작하지 않는 설정 노출(사용자 혼란·리뷰 불만), 일본어 사용자는 언어 설정 자체가 불가, 서버 language 설정과 UI 언어의 의미가 갈라져 데이터 오염. 백엔드가 지원하는 시장 2개 언어가 제품에서 접근 불가 — 글로벌 롤아웃 스펙 미달(규범 충돌: 보고 후 결정 대상).
- **재현**: 한국어 시스템 기기에서 설정 언어를 English로 저장 → 앱 재시작 포함 UI 전부 한국어 유지. 생성 화면 언어 섹션 확인 → 한국어/English/日本語만 존재.
- **수정**: 선택 로캘을 로컬 저장 후 MaterialApp.locale에 반영(Riverpod provider)하고 선택지에 ja 추가 — 또는 UI 언어는 시스템 추종임을 명시하고 이 항목을 '이야기 기본 언어'로 명확화. 생성 칩에 Español·中文 추가 및 supportedStoryLangs 확장(서버 i18n.py는 이미 지원); 의도적 축소라면 CLAUDE.md 스펙 갱신을 창업자 결정으로 기록.

### 79. 계약 문서화 드리프트 소결함 묶음 — regenerate 'mode' vs 'regenerate_target' 미문서 alias, 인페인트 409 등 에러 시맨틱 미명세, 테마 enum '사회성' 모바일 누락
`apps/mobile/lib/services/api_client.dart:146`  · src: contract-consistency

- **주장**: (a) 계약 RegeneratePageRequest는 required 'mode'만 문서화하지만 모바일은 {'regenerate_target': ...}를 전송하고(api_client.dart:146), 백엔드 AliasChoices('mode','regenerate_target')(dto.py:359-361)라는 계약 밖 alias가 이를 수용한다 — 백엔드 테스트 다수(test_integration.py:319 등)도 alias 쪽만 사용해 드리프트를 축복(false-green). (b) 모바일은 inpaint 409를 '제공자 미지원 → 전체 재생성 폴백' 신호로 하드코딩하지만(api_client.dart:180-184), 계약에는 inpaint 포함 전 엔드포인트가 200/422만 문서화되어 있고 409(books.py:864-871)·400·402·403·404·429와 표준 에러 envelope({detail, error{code,message,details}, request_id})가 어디에도 명세되지 않는다. (c) 계약·백엔드 Theme enum은 '사회성'을 포함하지만(dto.py:45) 모바일 BookTheme enum(book_spec.dart:74)에는 없어 UI에서 선택 불가.
- **트리거**: 백엔드가 계약대로 mode만 받도록 리팩터(alias 제거)하거나 계약 기반 코드젠/서드파티 클라이언트가 구현하는 순간; inpaint에 다른 의미의 409 추가; 생성 화면 테마 선택.
- **영향**: alias 제거 시 구버전 앱의 페이지 재생성이 전부 422로 파손되는 시한폭탄('openapi.json = 정본' 규칙이 이 필드에서 거짓). 409 의미가 계약 밖 구두 약속이라 향후 오해석 시 조용한 전체 재생성 폴백(크레딧 낭비). '사회성' 테마 책을 앱에서 만들 수 없음(기능 노출 누락).
- **재현**: openapi.json RegeneratePageRequest에 'regenerate_target' 없음 ↔ 모바일이 그 키 전송. inpaint responses에 409 없음 ↔ books.py는 409 반환·모바일은 statusCode==409만 보고 폴백. book_spec.dart BookTheme에 '사회성' 부재 ↔ openapi.json Theme enum에 존재.
- **수정**: 모바일 전송 키를 'mode'로 변경(1줄), alias는 호환 기간만 유지 후 제거, 백엔드 테스트 최소 1개는 'mode'로 작성. FastAPI responses=로 409(INPAINT_UNSUPPORTED)와 공통 에러 스키마를 계약에 노출하고 모바일 폴백 조건을 error.code까지 확인하도록 좁힘. BookTheme에 social 추가(라벨은 .arb l10n).

### 80. 인프라 구성 저위험 묶음 — 컨테이너 healthcheck 상수 200·.dockerignore .env 누락·MinIO 포트 0.0.0.0 공개·nginx 10M 경계·dev/prod Postgres 메이저 드리프트
`infra/docker-compose.prod.yml:148`  · src: docs-ops

- **주장**: (a) 이미지 HEALTHCHECK(apps/api/Dockerfile:49)는 /health(무조건 200)만 때리고 prod compose api에 오버라이드가 없어 DB/Redis가 죽어도 healthy 판정 — 의존성 인지형 /health/ready(503)가 있는데 배선되지 않아 replicas:2 중 병든 인스턴스로 트래픽이 계속 간다. (b) apps/api/.dockerignore(1행)에 .env가 없어 로컬 빌드 시 실키가 담긴 apps/api/.env가 COPY . .로 이미지 레이어에 포함된다(config.py는 API_ROOT/.env를 명시적으로 읽음). (c) storage 프로파일 활성 시 minio가 9000/9001을 0.0.0.0으로 노출(docker-compose.prod.yml:202, dev는 127.0.0.1 바인딩) — 콘솔 로그인 계정이 곧 S3_ACCESS_KEY/S3_SECRET_KEY. (d) nginx client_max_body_size 10M(nginx.conf:76)이 앱의 사진 한도 10MB(characters.py:58)와 동일해 multipart 오버헤드 때문에 한도 근처 사진이 앱 검증 대신 nginx 413 HTML로 죽음. (e) 운영 postgres:15-alpine vs 개발/CI postgres:16-alpine(docker-compose.yml:3) — 모든 마이그레이션·실DB 검증이 16에서 수행되고 운영만 15에서 첫 실행.
- **트리거**: 한 api replica만 DB 커넥션 고갈 등으로 비정상; 개발 머신 docker build 후 이미지 push/공유; storage 프로파일 운영 배포(방화벽 미차단 호스트); 9.9~10MB HEIC/JPEG 업로드; 16 전용 SQL/동작 의존 릴리스의 운영 배포.
- **영향**: 요청 약 절반 5xx 상태가 자동 복구 없이 지속; LLM/이미지/스토리지 키 유출(docker history로 추출 가능) + 구성 오염; 인터넷에서 MinIO 콘솔/S3 API 직접 접근(성공 시 아이 사진 원본 포함 전체 버킷 노출); 사진 캐릭터 경계 사례가 JSON 아닌 413 페이지로 불친절 실패; dev·CI 통과 마이그레이션이 운영에서만 실패 가능.
- **재현**: prod 기동 후 한 api 컨테이너 DB 접근 차단 → docker ps healthy 유지·nginx 경유 간헐 500. apps/api에서 docker build 후 docker run --rm t cat /app/.env → 존재(값 출력 금지). 외부 IP에서 curl http://HOST:9001 → 콘솔 응답. 10,485,000바이트 이미지 multipart 업로드 → 413. compose 이미지 태그 비교(정적).
- **수정**: prod api에 healthcheck: curl -f /health/ready 추가. .dockerignore에 .env·.env.*(!.env.example) 추가. minio ports를 127.0.0.1 바인딩 또는 제거(내부 네트워크만). client_max_body_size 12M 상향. Postgres 이미지 메이저 통일(15 또는 승격 결정 후 16).

### 81. i18n.language_display_name의 미지원 코드 → 한국어 silent fallback (잠복) + 학습자산 언어명 맵에 zh/es 누락 (현행 도달)
`apps/api/src/core/i18n.py:25`  · src: gap:Global multilang generation layer (the orphaned 'i18n lens'): prompt templates, i18n core, golden harness

- **주장**: language_display_name은 미지원 코드를 거부하지 않고 '한국어'로 폴백한다. 현재는 Language enum 5종이 모두 맵에 있어 API 경로로는 미도달이나, i18n.py 독스트링이 명시한 확장 절차(enum 추가+맵 추가)가 반쪽만 수행되면 신규 언어 요청 책이 조용히 한국어로 생성된다(스토리 시스템 프롬프트가 이 표시명으로 출력 언어를 지시하므로). 별도로 llm.py:621-625의 call_learning_assets 언어명 맵은 ko/en/ja만 있어 zh/es 책은 지금도 '원문 언어: zh'처럼 코드가 프롬프트에 들어간다(경미하나 현행 도달).
- **트리거**: 잠복: 신규 언어 추가 시 맵 누락. 현행: zh/es 책의 학습자산 생성(모든 zh/es 책이 통과).
- **영향**: 잠복 건은 '언어 추가했는데 전부 한국어 책이 나오는' 조용한 대량 오생성. 현행 건은 학습자산 프롬프트 언어 지시가 코드 문자열이라 번역·언어 라벨 품질 저하 위험(낮음).
- **재현**: language_display_name('fr') == '한국어' (1줄 확인). call_learning_assets에 Language.zh 전달 시 source_lang_name=='zh' 확인.
- **수정**: 미지원 코드는 KeyError/ValueError로 시끄럽게 실패(호출부는 enum이라 정상 경로 무영향), 학습자산 언어명은 i18n.LANGUAGE_DISPLAY_NAMES로 단일 출처화(중복 맵 제거).

### 82. /streak/today/generate의 Theme(theme_name) 역매핑이 7개 테마 중 4개에서 조용히 실패 — theme=None으로 생성
`apps/api/src/routers/streak.py:188`  · src: gap:Global multilang generation layer (the orphaned 'i18n lens'): prompt templates, i18n core, golden harness

- **주장**: DAILY_THEMES의 한국어 name('용기','친절','성장','상상')이 dto.Theme enum 값에 존재하지 않아 Theme(theme_name)이 ValueError → except에서 book_theme=None으로 조용히 폴백한다(188-194행). 7개 일일 테마 중 우정·가족·자연 3개만 매핑된다. 한국어 표시명을 enum 값으로 역매핑하는 구조 자체가 취약(i18n 확장 시 전부 깨짐).
- **트리거**: 일일 테마 로테이션이 courage/kindness/growth/imagination인 날(7일 중 4일)의 오늘의 동화 생성.
- **영향**: 해당 일 생성 책이 교육 테마 프레이밍 없이 생성되고 Book.theme=None으로 저장 — 성장 리포트 preferred_theme 집계 누락. 조용한 품질 저하(silent fallback).
- **재현**: Theme('용기') 실행 시 ValueError 확인(1줄). day_of_year%7==1인 날 /today/generate 후 Book.theme가 None임을 확인.
- **수정**: DAILY_THEMES 각 항목에 Theme enum 멤버를 직접 연결(theme_enum 필드)하고 역매핑 제거. 매핑 불가면 조용한 None 대신 로그+명시 기본 테마.

### 83. release 빌드가 key.properties 부재 시 조용히 debug 서명으로 폴백
`apps/mobile/android/app/build.gradle.kts:59`  · src: gap:Mobile native platform config (iOS Info.plist / AndroidManifest / store-review surface)

- **주장**: buildTypes.release가 key.properties 파일이 없으면 debug signingConfig로 폴백해 빌드가 성공한다. 실패해야 할 릴리스 경로가 조용히 성공하는 fail-open — EnvConfig.validateProdUrl의 fail-closed 철학과 상반.
- **트리거**: CI 러너나 새 머신 등 key.properties가 없는 환경에서 flutter build appbundle --release 실행.
- **영향**: debug 서명된 '릴리스' 산출물 생성 — Play 업로드 시점에야 거부돼 출시 지연, 또는 사이드채널(내부 배포·QA 공유)로 debug 서명 빌드 유통 위험.
- **재현**: key.properties 없는 클린 체크아웃에서 flutter build apk --release → 빌드 성공, apksigner verify --print-certs로 androiddebugkey 서명 확인.
- **수정**: release 빌드에서 key.properties 부재 시 GradleException을 던져 즉시 실패시키기.

### 84. Info.plist placeholder URL(example.com) 잔존 + 바이너리 내 도메인 3종 혼재
`apps/mobile/ios/Runner/Info.plist:39`  · src: gap:Mobile native platform config (iOS Info.plist / AndroidManifest / store-review surface)

- **주장**: 비표준 키 PrivacyPolicyURL/TermsOfServiceURL이 https://example.com/... placeholder로 남아 있고(코드에서 읽는 곳 없음 — grep 확인), 실제 사용되는 도메인은 settings_screen.dart:22-23의 aistorybook.com과 kakao_share_service.dart:25 기본값 aistorybook.app으로 서로 다르다. 어떤 도메인이 정본인지 코드만으로 판별 불가.
- **트리거**: 스토어 심사 시 개인정보처리방침 URL 검증, 또는 사용자가 설정에서 방침 URL 복사 → 실도메인이 aistorybook.com이 아니면 404.
- **영향**: 개인정보처리방침 링크 불일치는 아동 대상 앱 심사에서 반려 사유 가능, 잘못된 도메인이면 사용자가 방침에 도달 불가(법적 고지 실패).
- **재현**: grep 결과: Info.plist:39-42 example.com, settings_screen.dart:22 aistorybook.com, kakao_share_service.dart:25 aistorybook.app — 3개 상이한 도메인이 한 바이너리에 공존.
- **수정**: 정본 도메인 1개 확정 후 전 지점 통일, Info.plist의 미사용 placeholder 키 2개 삭제, 릴리스 게이트(store-preflight)에 도메인 일관성 검사 추가.

### 85. 설정 화면 앱 버전이 릴리스에서 'v0.1.0+1'로 표시 — 1.0.0 통일 누락 지점
`apps/mobile/lib/screens/settings_screen.dart:21`  · src: gap:Mobile native platform config (iOS Info.plist / AndroidManifest / store-review surface)

- **주장**: APP_VERSION dart-define의 defaultValue가 '0.1.0+1'로 stale인데, 정본 릴리스 빌드 명령(scripts/final-external-preflight.sh:81-83, docs/FINAL_USER_INPUT_REQUIRED.md:32-35) 어디에도 --dart-define=APP_VERSION 이 없다. pubspec은 1.0.0+1로 통일됐지만(커밋 94cb839) 이 표시 경로는 누락됐다.
- **트리거**: 문서화된 빌드 명령으로 만든 스토어 릴리스 빌드에서 설정 화면 하단 버전 항목 조회(settings_screen.dart:591 'v$_appVersion').
- **영향**: 1.0.0 출시 빌드가 설정에 v0.1.0+1을 표시 — 사용자 혼란 + CS/버그 리포트의 버전 식별 오염. CLAUDE.md 규범('버전 1.0.0 통일')과 충돌하는 추가 표기 지점.
- **재현**: flutter build apk --release --dart-define=PROD_API_URL=... --dart-define=KAKAO_NATIVE_APP_KEY=... (문서 그대로) → 설정 화면 → 'v0.1.0+1' 표시.
- **수정**: package_info_plus로 pubspec 버전을 런타임 조회해 정본을 단일화(권장), 최소한 defaultValue를 '1.0.0+1'로 갱신하고 릴리스 게이트에 버전 표기 검사 추가.

### 86. 카카오 execution params 딥링크 수신 미배선 — 스킴 등록·핸들러 전무
`apps/mobile/lib/services/kakao_share_service.dart:98`  · src: gap:Mobile native platform config (iOS Info.plist / AndroidManifest / store-review surface)

- **주장**: 공유 템플릿에 androidExecutionParams/iosExecutionParams({book_id})를 실어 보내지만, 수신 측 배선이 전무하다: AndroidManifest에 kakao{APP_KEY}://kakaolink 스킴 intent-filter 없음, Info.plist에 CFBundleURLTypes 없음, main.dart buildAppRoute에 외부 링크 진입 처리 없음.
- **트리거**: 앱이 설치된 수신자가 카카오톡 공유 메시지의 '동화책 보기' 버튼 탭.
- **영향**: 의도된 앱 딥오픈(설치자는 앱에서 바로 책 열기)이 절대 동작하지 않고 항상 웹 폴백(공개 share 페이지)으로만 이동 — 웹 폴백은 동작하므로 완전 차단은 아님.
- **재현**: Android 기기 2대(발신/수신, 수신자 앱 설치) → 카카오 공유 → 수신자 버튼 탭 → 앱이 아닌 브라우저로 열림.
- **수정**: 양 플랫폼에 kakao{NATIVE_APP_KEY} 스킴 등록 + 진입 URL의 book_id 파싱→뷰어 라우팅 구현, 또는 딥오픈을 출시 범위에서 제외한다면 execution params 전달 코드 제거로 의도 명확화.


---

## 기각된 finding (오탐 — 쫓지 말 것)

- **IAP: purchaseStream 리스너가 CreditsScreen 수명에 묶여 있어 화면 밖 결제 이벤트 유실** — 세 렌즈 중 trigger·impact 반증. finding은 in_app_purchase 공식 가이드 문구("앱 시작 즉시 구독")에서 유실을 추론했지만, 실제 핀 버전 플러그인은 정확히 이 문제를 막도록 설계됨 — iOS는 onListen 게이트(SK2: Transaction.updates 지연 시작, SK1: 네이티브 트랜잭션 캐시+재전달)로 이벤트가 유실이 아닌 '다음 크레딧 화면 오픈까지 지연'이고, Android는 앱 킬 구매가 애초에 스트림으로 방출되지 않아(startup queryPurchases 필요) 제안된 수정으로도 해결되지 않음. 크레딧 미지급 사용자는 자연히 크레딧 화면을 열게 되어 iOS는 자동 회복, Android는 복원 버튼으로 회복. 잔존 리스크(Android off-screen 이벤트 드랍+3일 acknowledgement 창, 시작 시 restore 부재, 검증 실패 시 finally completePurchase)는 실재하나 이는 별개 finding으로 재정식화해야 할 medium급 견고성 결함이며, 제출된 finding의 서술(critical·영구 유실·리스너 위치가 원인)로는 확정 불가.
- **운영 Redis가 allkeys-lru 상태로 Celery 브로커/결과백엔드를 겸함 — 메모리 압박 시 결제된 잡의 큐 메시지 조용히 소실** — 코드 렌즈는 생존(설정은 클레임 그대로이고 Celery+Redis에 allkeys-lru는 안티패턴)하나, 트리거 렌즈가 반증됨: 시스템의 자체 상한(max_pending_jobs=100, 소형 태스크 결과+24h 만료, rate-limit 61s TTL, API 처리량 한계)이 256MB 도달을 현실 트래픽 대비 2-3자릿수 차이로 차단하며, Redis에 대형 데이터를 쓰는 경로가 코드베이스에 존재하지 않음. 임팩트도 job_monitor의 멱등 환불(job_monitor.py:174-198)로 영구 크레딧 손실이 아닌 지연 환불로 완화됨. 세 렌즈 중 둘이 무너지므로 REFUTED. 단 두 가지는 별도 가치가 있음: (1) 하드닝 권고 — 브로커를 겸하는 Redis는 noeviction으로 바꾸는 것이 Celery 운영 표준이며 비용이 0에 가까움(장기 드리프트·미래 캐시 추가 대비), (2) 독립 결함 — job_monitor의 STUCK_QUEUED 재큐가 Celery 재디스패치 없는 DB-only no-op인 것은 이 finding과 무관하게 실재하는 버그로 별도 등재 권고(브로커 메시지 유실 원인이 무엇이든 복구가 무효). severity는 설정 하드닝 권고 수준인 low로 조정.
- **계정 삭제와 진행 중 생성 잡의 경쟁 → 삭제 후 아동 PII(책/페이지/이미지) 잔존** — 3렌즈 중 code·impact 반증으로 기각. finding이 주장한 "삭제 후 Book/Page 행·books/{id}/ 이미지 잔존" 경로는 books.job_id NOT NULL FK(모델·마이그레이션 모두 존재)가 삭제 커밋 이후 워커의 모든 DB write를 FK 위반으로 차단하므로 성립하지 않고, S3 경로 주장(books/{new_book_id}/)도 실제 저장 위치(images/{provider}/{uuid})와 다르다. 경쟁·revoke 부재 자체는 사실이나 그 결과는 (a) 워커의 시끄러운 실패 + 무용한 LLM/이미지 비용 소모, (b) images/ 고아 파일뿐이며, (b)는 경쟁 없이도 존재하는 별도의 시스템적 erasure 갭이다. 별도 보고: 계정 삭제가 생성 일러스트(images/{provider}/{uuid}, 아동 사진 파생 가능)를 전혀 삭제하지 못하는 갭은 독립 finding으로 상정 권고(medium 감).
- **레이트리밋 공백 — 공개 공유 라우터(HTML+이미지 프록시) 무스로틀로 무인증 S3 egress 증폭 + 리미터가 Redis 오류에 fail-open으로 장애 시 전면 해제** — finding의 핵심 주장 두 축이 모두 운영 구성에서 반증된다. "공개 공유 경로에 신원·IP 어떤 기준의 스로틀도 없다"는 nginx.conf:112-114의 /share/ 전용 IP 스로틀(의도적 설계, 주석 명기)로 거짓이며, api 컨테이너 포트 미공개로 우회도 불가. "Redis 장애 시 비용 폭주 무제어"는 (1) 동일 Redis 호스트가 Celery 브로커라 장애 창에 생성 잡 enqueue 자체가 실패하고, (2) 크레딧 게이트가 사용자별 비용을 상한하며, (3) nginx /v1/ IP 스로틀이 유지되므로 거짓. 패널이 앱 레이어만 보고 infra 레이어 가드를 놓친 전형적 사례. 다만 잔여 하드닝 여지는 실재: rate_limit.py:129-136의 일반 Exception fail-open 제거, 이미지 프록시 no-store→짧은 private max-age 전환, nginx 없는 배포 변형 대비 앱 레벨 IP 폴백은 심층방어로 권장(출시 차단 아님, low).
- **PATCH /v1/library/{book_id} 응답이 series_id/series_index/character_id를 누락 — 제목 수정 시 UI에서 시리즈 그룹 해체** — 3렌즈 중 code만 생존. PATCH 응답이 GET과 달리 series/character 메타데이터를 누락하는 비대칭(library.py:177-184 vs 136-138)은 실재하지만, finding이 주장한 트리거(시리즈 책 rename)는 UI에 해당 affordance가 전혀 없어(rename은 standalone 그리드 library_screen.dart:413 전용, 시리즈 셸프 BookCard는 onTap만) 프로덕션에서 도달 불가하고, 도달 가능한 standalone rename에서는 지워지는 필드의 소비처가 없어 사용자 피해가 0이다. openapi 계약상으로도 해당 필드는 Optional이라 계약 위반도 아니다. 결론: 현시점 버그가 아니라 향후 시리즈 rename 기능 추가 시 터질 잠복 비대칭 — GET과 동일 빌더로 통일하는 저비용 위생 수정(fix 제안 자체는 유효)으로 low 백로그 처리 권장. medium 확정은 기각.
- **미사용 마이크·음성인식 목적 문자열 — 실제 녹음/음성인식 코드 전무** — 코드 관찰(문자열 존재·녹음 코드 부재)은 사실이나, 3렌즈 중 trigger·impact가 반증됨. 애플의 목적 문자열 자동 검사는 '누락' 방향(ITMS-90683)만 존재하고 '여분' 문자열을 적발하지 않으며, API 미호출로 권한 프롬프트가 절대 표시되지 않아 사용자·심사관 노출 경로가 없고, App Privacy 라벨 불일치도 성립하지 않음. 결정적으로 제안된 수정이 유해함: NSMicrophoneUsageDescription은 image_picker(실사용 의존성)의 iOS 요구사항이라 삭제 시 실제 업로드 반려 위험이 생김. 잔여 진실은 NSSpeechRecognitionUsageDescription(Info.plist:37-38)이 순수 미사용이며 문구가 미구현 기능을 서술한다는 것 — 출시 리스크가 아닌 코스메틱 정리 항목으로, 정리 시에도 speech 키만 제거하고 mic 키는 유지하되 문구를 image_picker 카메라 용도에 맞게 조정하는 것이 안전.
- **validateProdUrl이 https를 강제하지 않음 — 평문 API 트래픽 허용 경로** — code·trigger 렌즈는 생존하나 impact 렌즈가 반증됨 — finding의 유일한 실해악 주장(평문 크리덴셜 전송)은 'dart:io에는 플랫폼 cleartext 정책이 적용되지 않는다'는 잘못된 전제에 기반한다. 실제로는 Flutter 엔진이 Android cleartext 정책과 iOS ATS를 dart:io에 강제하므로(본 프로젝트 매니페스트·Info.plist 모두 기본 차단 상태), 잘못된 http 빌드는 도청 가능한 앱이 아니라 첫 요청에서 즉시 실패하는 앱이 된다. 남는 것은 실패 시점을 런타임 첫 요청에서 빌드 검증 시점으로 앞당기는 방어적 스킴 체크(1줄) 개선 여지뿐이며, 이는 보안 취약점이 아닌 fail-fast 인체공학 개선이므로 REFUTED.