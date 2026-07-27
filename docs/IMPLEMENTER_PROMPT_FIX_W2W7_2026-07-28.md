# 구현 개발자용 프롬프트 — W2–W7 감사 반송 fix

> CTO 감사 결과 W2–W7은 **클린 PASS 아님**. 아래 확정 결함을 수정한다. 전체 보고서: `docs/AUDIT_W2-W7_2026-07-28.md`.
> 아래 블록을 구현 개발자 세션에 붙여넣으세요.

---

당신은 AI Story Book 모노레포의 **구현 전담 개발자**입니다. W2–W7 구현이 CTO 적대 감사를 받았고 **확정 결함 20건(치명1·높음2·보통10·낮음7)**이 나왔습니다. 게이트(백엔드 619 pass·모바일 242 pass)는 전부 green이지만 **false-green 테스트가 치명 결함을 은폐**했습니다 — green을 신뢰하지 말고 각 fix의 테스트가 수정 전 실제로 red인지 반드시 확인하세요.

## 먼저 읽기
1. `docs/AUDIT_W2-W7_2026-07-28.md` — 감사 보고서(§1 확정 20건 각 fix 포함, §3 기각 9건=쫓지 말 것).
2. `docs/DEV_SPEC_2026-07-20.md` — 원 명세(§2 결정, 티켓별 ⚠정정).
3. `docs/FIXLOG_2026-07-20.md` — 기존 진행 원장(계속 갱신).

## 절대 규칙 (감사에서 실제로 깨진 것들 — 이번엔 반드시)
- **false-green 금지**: 모든 회귀 테스트는 **수정 전 코드에서 red임을 눈으로 확인**한 뒤 fix. 특히 검증 대상 함수를 통째로 monkeypatch하지 말 것 — 그게 C1/MA1 치명을 통과시킨 원인이다. mock은 최하위 I/O 경계(HTTP POST 등)에만, 검증 로직 자체는 실경로로 통과시킬 것.
- **보고 정직성**: FIXLOG에 "완료"로 적기 전에, 그 주장이 실경로 테스트로 뒷받침되는지 재확인. (지난번 'MA1 완료·false-green 없음'이 코드와 불일치했다.)
- TDD·최소 변경·§2 결정 준수·`.env`/secrets 금지·커밋은 오너(staged까지). 계약 변경 시 openapi 동기, DB 변경 시 `alembic heads` 단일 + 실PG 리허설.
- 게이트: `venv/bin/python -m pytest tests/` · `ruff check src/ tests/` · `flutter test` · `flutter analyze` · `alembic upgrade head && alembic heads`.

## 🔴 반드시 먼저 — 치명 1건 (출시 차단)

### F1. C1/MA1 — Apple 만료 영수증으로 무한 구독·크레딧 리필
- **결함**: `apps/api/src/services/iap_verifier.py`의 `_verify_apple` 반환부(≈135-149)가 `IAPVerificationResult`에 `expires_date_ms`를 실지 않아 항상 None. 라우터 가드 `_subscription_expired`(`iap.py:71-77`)가 `if not expires_ms: return False`로 **항상 통과** → 만료된 Apple 자동갱신 영수증을 verify/restore하면 active 구독 재생성 + `periodic_credits`가 30일마다 무기한 리필. Google은 정상(`expiryTimeMillis` 실검사)이라 Apple만 열려 있음.
- **fix**:
  1. `_verify_apple`에서 매칭된 트랜잭션의 `expires_date_ms`(Apple `latest_receipt_info[].expires_date_ms`)를 `_parse_int`로 추출해 `IAPVerificationResult(expires_date_ms=...)`에 실어 반환(구독 상품일 때). Google도 `expiryTimeMillis`를 같은 필드에 실어 일관화.
  2. **테스트 교체(핵심)**: 기존 `test_expired_receipt_restore_creates_no_active_sub`는 `verify_purchase`를 통째 monkeypatch해 false-green이다. `iap_verifier._post_apple_receipt`(HTTP 경계)만 mock해 `{status:0, latest_receipt_info:[{product_id, transaction_id, expires_date_ms:<과거>}]}`를 반환시키고 **실제 `_verify_apple` 추출 경로를 통과**시켜 → verify/restore가 active 구독을 만들지 않음을 assert. 수정 전 이 테스트가 red인지 확인.
- **DoD**: 만료 Apple 영수증 verify/restore가 active 구독 미생성·크레딧 미지급, 유효 영수증은 정상 통과, Google 대칭 확인, 실경로 테스트 red→green.

## 🟠 높음 2건 (출시 전)

### F2. H1/G9 — 오디오 비활성 GA 구성에서 매 탭 500
- **결함**: `audio_feature_enabled`(config.py:72, 기본 False)가 `main.py:479` readiness 게이트에만 쓰임. GA 구성(플래그 off + `tts_provider` mock)에서 오디오/발음 엔드포인트가 provider raise → 500. G9 결정은 "명시적 비활성 + NOT_SUPPORTED 명시"인데 현재는 "라이브 버튼 + 500".
- **fix**: `/v1/config/capabilities`에 `audio_supported`(= `audio_feature_enabled` && provider live) 추가 → 모바일 뷰어 낭독/발음 UI를 인페인트와 동일 패턴(`capabilitiesProvider`)으로 게이팅. 또는 오디오 엔드포인트가 플래그 off일 때 4xx `NOT_SUPPORTED` 명시 응답. (GA를 오디오 활성=라이브 TTS/STT로 갈지 여부는 §2 G9 재확인 — 비활성이 결정.)
- **DoD**: 오디오 비활성 구성에서 낭독/발음 버튼이 노출되지 않거나 명시적 NOT_SUPPORTED, 500 없음. 모바일 게이팅 위젯 테스트.

### F3. N1 — 단건 책 삭제·동의 철회가 파이프라인 이미지를 파기하지 않음
- **결함**: 계정 삭제 경로만 이미지 파기를 커버. `consent.revoke`(consent.py:176)·단건 책 삭제(`library.delete_book`)는 DB 행만 지우고 `images/{provider}/…` 파이프라인 이미지를 남김 + 행 삭제로 역산 키까지 소실 → 아동 likeness 일러스트 영구 잔존(규제 위반).
- **fix**: `consent.revoke`와 `library.delete_book`에서 **행 삭제 전** `collect_book_image_keys(db, book_ids)`로 스토리지 키를 수집 → 삭제 후 `delete_keys`로 파기(실패는 H8처럼 partial 표면화). 계정 삭제와 동일 헬퍼 재사용.
- **DoD**: 단건 삭제·동의 철회 후 해당 책의 cover/page 이미지가 스토리지에서 파기됨(mock 스토리지 delete 호출 assert), 파기 실패가 관측됨.

## 🟡 별도 결정 필요 — 타임존(G10) 프로덕션 비작동
- **상태**: 서버 배관은 완비됐으나 **모바일이 timezone을 한 번도 전송하지 않아** 전 사용자 `Asia/Seoul` 고정. 추가로 `get_reading_report`/`get_reading_history`(streak.py:720)가 tz 미스레딩(F-medium). G10(사용자별 타임존) 효과가 0.
- **fix (창업자 결정 후)**: (A) 앱 기동/온보딩 시 `FlutterTimezone.getLocalTimezone()`을 `PATCH /v1/settings`로 1회 전송(+변경 시 재전송, 5~10줄) + report/history에 `load_user_tz` 스레딩, 또는 (B) G10을 KST 고정으로 재결정하고 서버 배관 원복. **어느 쪽인지 CTO/창업자에게 먼저 확인**하고 진행.

## 🟡🟠 보통 10 · ⚪ 낮음 7
`docs/AUDIT_W2-W7_2026-07-28.md` §1의 4~20번 항목을 각 fix대로 처리. 특히 **false-green 테스트 3건(M23 재전달 멱등·H7 erasure flaky·H6 POD 멱등)은 실경로 red-provable 테스트로 교체**가 핵심 — 통과하는 것처럼 보이지만 결함을 못 잡는다. 나머지(웹훅 orphan H4·FK dangling H5·모바일 재생성 422 M12·서버 멱등 미착륙 H17/H18·iOS l10n 미등록 M33 등)도 §1대로.

## 진행
1. **F1(치명) → F2·F3(높음) → 타임존 결정 대기분 → 보통/낮음** 순.
2. 각 fix를 수정 전 red 확인 → green → 게이트 회귀 0 → per-fix(또는 클러스터) 커밋(푸시 안 함) → FIXLOG 갱신.
3. **기각 9건(§3)은 손대지 말 것** — 오탐이다.
4. 전부 끝나면 CTO 재감사용 요약(수정 티켓·각 실경로 red 확인 여부·게이트·실PG 리허설 결과) 제출. CTO가 동일 방식(게이트 재실행+실경로 red 확인)으로 재감사한다.

**F1부터 시작하되, 착수 전 F1 계획(expires_date_ms 추출 위치 + 실경로 테스트 설계)을 3–5줄로 먼저 제시**하고 진행하세요.
