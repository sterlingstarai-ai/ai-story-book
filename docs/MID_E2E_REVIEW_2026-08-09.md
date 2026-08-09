# 중간 점검 E2E 리뷰 — 2026-08-09

> 목적: 신규 기능 구현이 아니라, **지금까지 구현된 기능 전체를 실제 사용자 여정으로 통과시키며 결함을 찾는 것**.
> 프로바이더는 전부 mock(실키·비용·외부 계정 불필요). 결함은 즉석 수정하지 않고 여기에 기록한다.
>
> **판정: ❌ 최종 E2E 진행 불가 — 치명 1건(C1) + 높음 2건(H1·H2) 선결 필요.**

---

## 0. 데모 계정 / 실행 환경

| 항목 | 값 |
|------|-----|
| **데모 계정 `X-User-Key`** | **`5bc95a69-3d96-4fff-9f02-b9205e2bc747`** ← 이후 라운드 재사용 |
| 데모 계정 상태 | 크레딧 58, 구독 premium(픽스처), 책 5권, 캐릭터 1개, 프로필 1개 |
| 부정경로용 타 유저 키 | `2ed9b2b6-...`(state.json) — IDOR 9종 검증에 사용 |
| 계정삭제 검증용 일회용 키 | `55c59aba-b286-467a-885c-3b47777e4060` |
| 앱 온보딩이 생성한 키(참고) | `1435b7a2-…`, `26f104b1-…` (통합 테스트 실행마다 신규 생성) |
| API | `http://127.0.0.1:8000` — uvicorn, venv Python 3.12.12, `TESTING=false` |
| DB | **실 PostgreSQL 15** (docker `storybook-postgres`, host `:5433`) |
| Redis / Storage | docker `storybook-redis` / `storybook-minio`(버킷 `storybook` 자동 생성) |
| 프로바이더 | `LLM=mock` `IMAGE=mock` `TTS=mock` `STT=mock` |
| 오디오 기능 | `AUDIO_FEATURE_ENABLED=false` (G9 정본 — GA 비활성 출시) |
| 모바일 | iOS 시뮬레이터 **iPhone 17** (iOS 26.2), Flutter, `--dart-define=API_BASE_URL=http://127.0.0.1:8000` |

**환경 구성 이탈 2건(정직 고지)**
1. `compose.override.e2e.yml` — 리포의 dev compose가 그대로는 안 뜬다(M1·L1·L5). redis 기동 인자·PG 호스트 포트·볼륨만 우회. 리포 파일은 **변경하지 않음**.
2. **구독 픽스처 DB 직접 주입** — `subscriptions` 에 premium/active 1행 삽입. 사유: `TESTING=false`에서 유료 구독 확립 경로가 **설계상 도달 불가**(M4). 이 이탈로 커버한 건 *구독 게이트 하위 표면*(시리즈 2권차 이상·PDF)이며, **구독 생성 경로 자체는 검증하지 않았다**(최종 라운드 IAP 샌드박스로 이연).

---

## 1. 체크 매트릭스

### Phase 0 — 베이스라인

| 항목 | 결과 | 근거 |
|------|------|------|
| `check-env.sh --mode ci` | ✅ PASS | 3개 env 계약 파일 확인 |
| `phase-gate.sh` | ✅ PASS | `✅ Phase gate checks passed` (모바일/iOS 빌드는 옵션 플래그 미사용 skip) |
| 백엔드 `pytest tests -q` | ✅ **675 passed** (73s) | 기준치 일치 |
| 모바일 `flutter test` | ✅ **252 passed** | 기준치 일치 |

### Phase 1 — 풀스택 기동

| 항목 | 결과 | 비고 |
|------|------|------|
| PG·Redis·Minio 기동 | ⚠️ PASS(우회) | M1·L1·L5 |
| `alembic upgrade head` (빈 실PG) | ✅ PASS | 23개 리비전 완주, 단일 head `a7b8c9d0e1f2` |
| 모델 ↔ 실DB drift | ✅ **diff 0** | autogenerate `upgrade(): pass`, 프로브 삭제·워킹트리 clean |
| API / Celery 워커 기동 | ✅ PASS | 워커 broker 연결 + 3개 태스크 등록 |
| `/health/ready` 의존성 | ✅ DB·Redis·job_monitor·storage 전부 `healthy` | 전체는 `degraded`/503 — 사유 `provider_keys`(IAP 실검증 키 부재). mock 구성의 **정상 fail-closed** |
| 계약 신선도 | ✅ PASS | live 77 ops ↔ `openapi.json` 77 ops, 차집합 0, version 양쪽 `1.0.0` |

### Phase 2 — API 여정

| # | 항목 | 결과 | 비고 |
|---|------|------|------|
| 1 | 회귀 앵커 `run_live_e2e.sh` | ✅ **30/30** | 단, SQLite 기반 — C1을 구조적으로 못 잡음 |
| 2 | 크레딧 베이스라인·거래내역 | ✅ PASS | 신규 3크레딧 보너스 |
| 3 | 크레딧 충전(admin) + 멱등 | ✅ PASS | 무키/오키 403, 같은 `transaction_id` 재전송 시 이중지급 없음 |
| 4 | 동의 부여/조회 | ✅ PASS | |
| 5 | 캐릭터 CRUD(생성·목록·단건·프리셋) | ✅ PASS | |
| 6 | **책 생성 — Celery 경로** | ❌ **FAIL (C1)** | 전량 실패 |
| 7 | 책 생성 — 인프로세스 경로 | ✅ PASS | 4.1초 done, 진행률 궤적 10→85→100 |
| 8 | 생성 멱등키 재전송 | ✅ PASS | 동일 `job_id` |
| 9 | 시리즈 2·3권차 + 일관성 메타 | ✅ PASS | 동일 `series_id`, index 1·2, 동일 `character_id` |
| 10 | 서재 시리즈 셸프 그룹핑 | ✅ PASS | |
| 11 | **from-photo / from-drawing** | ❌ **FAIL (H2)** | 500 + 고아 캐릭터 |
| 12 | 페이지 재생성(image/text) | ✅ PASS | |
| 13 | 인페인트 | ✅ PASS(계약 확인) | mock은 **409 `INPAINT_UNSUPPORTED`** — 지시서의 "전체 재생성 폴백" 기대와 다름(L6) |
| 14 | **연령 리텔링(retell)** | ❌ **FAIL (M3)** | mock에서 구조적으로 불가 |
| 15 | **PDF 내보내기** | ❌ **FAIL (H1)** | 한국어 전량 깨짐 |
| 16 | 오디오 409 `AUDIO_NOT_SUPPORTED` | ✅ PASS | 책·페이지·발음(오디오) 3경로 |
| 17 | 분기 스토리 init→graph→choose | ✅ PASS | 잘못된 선택 400 거부 포함 |
| 18 | 발음 연습(정확/부정확 변별) | ✅ PASS | 100점 / 20점 + 피드백 |
| 19 | 음성 프로필 생성·수정·**삭제 파기** | ✅ PASS | minio `voice-samples/` 실제 비워짐 확인 |
| 20 | 스트릭 info/today/themes/history/calendar | ✅ PASS | report는 `period=weekly` (테스트 파라미터 오류였음) |
| 21 | **스트릭 2일 연속 / 끊김** | ✅ PASS | 2일 → `current_streak=2`, 끊김 → 1 리셋 + `longest=2` 보존 |
| 22 | 오늘의 동화 생성 | ✅ PASS | |
| 23 | 퀴즈 응답 4종 + 성장 리포트 + 또래비교 | ✅ PASS | 정확도·레벨 산출 정상 |
| 24 | 설정 조회/변경(타임존·언어·다크모드) | ✅ PASS | 잘못된 tz 422 거부 |
| 25 | 자녀 프로필 CRUD | ✅ PASS | |
| 26 | 라이브러리 제목 변경 | ✅ PASS | |
| 27 | 공유 생성→공개 조회→철회→**404** | ✅ PASS | 비인증 공개 조회 200, 철회 후 404 |
| 28 | POD 지역별 가격(KR/US/JP)→주문(멱등) | ✅ PASS | 미지원 국가는 L2 참조 |
| 29 | **동의 철회 → 파생 데이터 파기** | ✅ PASS | 사진·그림 캐릭터 2개 + 스토리지 원본 파기, 이후 from-photo 403 |
| 30 | **IDOR 9종** | ✅ PASS | 책·캐릭터·job·프로필·공유·제목변경·삭제·POD·읽기기록 전부 403/404 |
| 31 | 잘못된 입력 부정경로 7종 | ✅ PASS | 키 형식 400, 헤더 누락 422, 없는 리소스 404, 잘못된 enum 422 |
| 32 | **레이트리밋 429** | ✅ PASS | `Retry-After: 60` + `X-RateLimit-*`. 단 코드 명명은 M2 |
| 33 | 계정 삭제(`DELETE /v1/users/me`) | ✅ PASS | 서재 1→0, 재초기화 |
| 34 | **크레딧 정합** | ✅ PASS | `sum(credit_transactions.amount) = 58 = user_credits.credits` **완전 일치** |
| 35 | 스턱 잡 SLA → failed + 자동 환불 | ✅ PASS | 10분 후 `SLA_BREACH` + refund 트랜잭션 |
| 36 | `golden_prompts_harness.py` (구조 모드) | ✅ **7/7 통과** | ko/en/ja/zh/es 언어·연령 전파 검증 |

### Phase 3 — 모바일 여정 (iPhone 17 시뮬레이터 · 라이브 로컬 API)

| 항목 | 결과 | 비고 |
|------|------|------|
| 신규설치 여정 **ko** — 시작게이트→동의→온보딩→홈 | ✅ PASS | 실제 `POST /v1/consent` 왕복 |
| 신규설치 여정 **en** | ✅ PASS | 키 노출·미해석 플레이스홀더 0 |
| 신규설치 여정 **ja** | ✅ PASS | 키 노출·미해석 플레이스홀더 0 |
| 재방문 여정 — 홈→서재→읽기성장 | ✅ PASS | 라이브 데이터 렌더 |
| **핵심 여정 — 홈→만들기→생성→로딩(진행률)→뷰어** | ✅ PASS | 실제 책 생성 후 뷰어 자동 전환 |
| l10n 키 완전성(ko/en/ja) | ✅ PASS | **848키 3로케일 완전 일치, 누락 0** |
| 오디오 버튼 게이팅 | ✅ 계약 확인 | `/v1/config/capabilities` → `audio_supported:false`, `inpaint_supported:false` |
| **하드코딩 문자열(l10n 우회)** | ❌ **FAIL (M6)** | 성격 칩 10개 등 |
| **UI_PREFLIGHT 수동 체크** | ⛔ **막힘** | 오버레이·바텀시트 스크롤·글자 130%·작은 화면 — 시뮬레이터 탭 입력 불가(§3) |
| 데이터 삭제 후 재시작 초기 상태(앱) | ⛔ 막힘 | API 레벨은 #33에서 PASS |

### 이번 라운드 SKIP (최종 라운드 이연 — 지시대로 시도하지 않음)

| 항목 | 사유 |
|------|------|
| 실키 생성 품질(LLM·이미지·TTS 실호출) | 최종 라운드 |
| IAP 샌드박스 구매·구독 생성 경로 | 최종 라운드 (M4로 mock 라운드에서 도달 불가) |
| 실기기 스모크 | 최종 라운드 |
| 실서버 배포 / 버킷 ACL | 최종 라운드 |
| PDF 이미지 삽입 | mock 이미지가 외부 `picsum.photos` URL(302)이라 검증 불가 — 제품 결함 아님 |
| 시리즈 *내용* 연속성 | mock이 topic 무관 동일 스토리 반환 — 메타 일관성만 검증 가능 |

---

## 2. 결함 목록

### 🔴 C1 (치명 / 출시 차단) — Celery 워커에서 책·시리즈 생성이 **전량** 실패 (프로덕션 기본 구성)

**증상** — 프로덕션 구성(`USE_CELERY=true` + PostgreSQL)에서 `POST /v1/books`·`/v1/books/series`가 200 + 크레딧 차감까지 하지만, 워커가 태스크 수신 **0.3초 뒤** 예외로 죽어 책이 **한 권도 생성되지 않는다**. 잡은 `queued`(progress 0)에 정지.

**영향 범위** — `generate_book_task`(즉시), `generate_series_task`(즉시), `regenerate_page_task`(같은 워커에서 앞선 태스크가 한 번이라도 돌면 이후 전부). 즉 **책 생성 파이프라인 전체**. 앱에서는 로딩이 10분 멈춘 뒤 실패로 뒤집힌다.

**근본 원인** — `src/services/tasks.py:32` `run_async()`는 호출마다 새 이벤트 루프를 만들고 **닫는다**:
```python
def run_async(coro):
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    try: return loop.run_until_complete(coro)
    finally: loop.close()
```
그런데 `src/core/database.py:44`는 풀 설정 없이 엔진을 만든다:
```python
async_engine = create_async_engine(async_database_url, echo=settings.debug)
```
→ asyncpg 기본 풀은 **`AsyncAdaptedQueuePool`**(커넥션 캐싱). `generate_book_task`는 `run_async()`를 **최소 2회** 호출한다:

| 순서 | 코드 | 결과 |
|------|------|------|
| 1 | `tasks.py:160` `run_async(_get_job_status_async(job_id))` | 루프 **L1**에서 커넥션 체크아웃 → 풀 반납 → **L1 닫힘** |
| 2 | `tasks.py:174` `run_async(start_book_generation(...))` | **L2**가 L1에 묶인 커넥션을 재사용 → 💥 |

```
RuntimeError: Task <...start_book_generation...> got Future <Future pending>
              attached to a different loop
→ sqlalchemy.exc.InterfaceError: (asyncpg.InterfaceError)
  cannot perform operation: another operation is in progress
```

**2차 피해 — 실패 기록조차 못 한다.** 예외 핸들러(`tasks.py:198`)가 다시 `run_async(_mark_job_failed_async(...))`를 호출 → **같은 이유로 또 실패** → 잡이 `failed`로 전이되지 않고 `queued`에 잔류. 워커 로그:
```
[11:52:52] [error] Book generation failed   error=(asyncpg.InterfaceError) cannot perform operation...
[11:52:52] [error] Failed to update job status  error=(asyncpg.InterfaceError) cannot perform operation...
```

**결정적 재현 (10줄, 오케스트레이터 무관)** — 같은 `run_async`로 `SELECT 1`을 두 번:

| DB | 풀 클래스 | 1st | 2nd |
|----|-----------|-----|-----|
| PostgreSQL(asyncpg) | `AsyncAdaptedQueuePool` | ✅ | ❌ **RuntimeError: attached to a different loop** |
| SQLite(aiosqlite) | `NullPool` | ✅ | ✅ |

**왜 모든 게이트가 놓쳤나 (false-green 메커니즘)** — 백엔드 675 테스트와 `run_live_e2e.sh` 30/30이 **전부 SQLite**에서 돈다. SQLite 비동기 방언의 기본 풀이 `NullPool`이라 커넥션이 루프를 건너 재사용되지 않는다 → 이 버그 클래스를 **구조적으로 잡을 수 없다**. 코드가 맞아서 통과한 게 아니라 **SQLite가 커넥션을 캐싱하지 않아서** 통과했다(전역 규칙의 *"mock 순수성 의존 정합성"*).

**프로덕션이 실제로 이 구성인가 — 예**
- `infra/docker-compose.prod.yml:41` → `USE_CELERY=${USE_CELERY:-true}` (기본 **true**)
- `src/core/config.py:123` → `use_celery: bool = False  # ... (True for production)`
- 개발 compose는 기본 `false` → **dev/prod 드리프트가 결함을 가려왔다.**

**경계 확인(안 깨진 것)** — `USE_CELERY=false` 인프로세스 경로 + 실PG는 **정상**(4.1초 done). 오케스트레이터·프로바이더·스토리지·DB는 멀쩡하고 깨진 건 **Celery 디스패치 경로 하나**. 돈 안전망도 작동: 10분 SLA 후 failed 전이 + 자동 환불(영구 손실 아님, 다만 사용자는 **10분 대기 후 실패**).

**재현 절차**
1. 인프라 기동(M1·L1 우회) → `alembic upgrade head`
2. `USE_CELERY=true` + `DATABASE_URL=postgresql+asyncpg://...` + mock 프로바이더로 uvicorn + `celery -A src.worker worker`
3. `POST /v1/books` → 200 + `job_id`
4. `GET /v1/books/{job_id}` 폴링 → **`queued`/progress 0 영구 정지**, 워커 로그에 `InterfaceError`

**수정 방향(제안)** — (a) 워커에서는 엔진을 `NullPool`로 만들거나 태스크당 엔진 생성 후 `dispose()`, 또는 (b) 태스크당 `run_async()`를 **1회로 통합**(상태조회+본작업+실패마킹을 한 코루틴 안에서). **회귀 방지 필수**: 실PG + Celery 통합 테스트가 없으면 재발 확정.

---

### 🟠 H1 (높음 / 출시 차단급) — PDF 내보내기의 한국어 본문이 **전부 검은 사각형(■)** 으로 렌더된다

**증상** — 유료(베이직 이상) 기능인 PDF를 내려받으면, 표지·본문의 한국어가 **한 글자도 읽히지 않는다**. 라틴 문자·숫자만 살아남는다.

**증적 1 — PDF 내부 (`book1.pdf`, 6883 bytes)**
```
BaseFont: ['Helvetica', 'ZapfDingbats']     ← CJK 폰트 없음
표지: /F2 48 Tf (nnn) Tj ( ) Tj (nnn) Tj ( ) Tj (nn) Tj ( ) Tj (nn) Tj
      → "용감한 토끼의 숲속 모험"(한글 10자)이 전부 ZapfDingbats 'n'(= ■)으로 치환
본문: (- 1 -) / ( 2: ) / (AI Story Book) 같은 라틴·숫자만 정상
```
**증적 2 — 렌더 결과**: 표지 제목이 **빈 사각형 10개**로만 보임(`scratchpad/shots/book1.pdf.png`).

**근본 원인** — `src/services/pdf.py:48-66`는 폰트 경로 3종을 시도하고 전부 실패하면 `Helvetica`로 폴백한다. 그런데 **세 경로가 모두 충족되지 않는다**:

| 경로 | 상태 |
|------|------|
| `/usr/share/fonts/truetype/nanum/NanumGothic.ttf` (Linux) | ❌ 프로덕션 `Dockerfile`은 `python:3.11-slim`에 `libpq5`·`curl`만 설치 — **폰트 패키지 없음** |
| `/System/Library/Fonts/AppleSDGothicNeo.ttc` (macOS) | ❌ 등록 실패 — `postscript outlines are not supported` (실제 API 로그에 발생) |
| `/app/assets/fonts/NanumGothic.ttf` (Docker) | ❌ 리포에 해당 파일 **없음**(모바일의 Pretendard만 존재) |

→ 프로덕션에서도 동일하게 `Helvetica` 폴백. **ko/ja/zh 3개 언어(지원 5개 중)에서 PDF가 무의미하다.** en/es는 정상.

**재현** — 구독 상태에서 `GET /v1/books/{book_id}/pdf` → 내려받은 PDF 열기(또는 `BaseFont` 확인).

**수정 방향** — CJK 폰트(NanumGothic 등)를 리포에 번들하고 Dockerfile에 복사하거나 `fonts-nanum` 패키지 설치. 폰트 등록 실패 시 **조용한 Helvetica 폴백 대신 명시적 실패/경고**(현재는 `logger.debug`로 묻힌다).

---

### 🟠 H2 (높음) — 사진·그림 기반 캐릭터 생성이 500으로 실패하고, **되살릴 수 없는 고아 캐릭터**를 남긴다

**증상**
- `POST /v1/characters/from-photo` → **500 `INTERNAL_ERROR`** ("캐릭터 생성에 실패했습니다")
- `POST /v1/characters/from-drawing` → **500 `INTERNAL_ERROR`**
- 그런데 **캐릭터는 실제로 생성되어 목록에 나타난다**(`GET /v1/characters` 200에 '사진토토'·'그림토토' 존재).
- 같은 멱등키로 재시도 → **또 500**(멱등 재생 경로도 같은 지점을 지남).
- `GET /v1/characters/{id}` 단건 조회 → **영구 500**. 즉 그 캐릭터는 **만들어졌지만 영원히 열 수 없다**.

**근본 원인** — `src/routers/characters.py:78` `_normalize_character_payload`:
```python
"bottom": clothing.get("bottom", "알 수 없음"),
```
`dict.get(k, default)`의 기본값은 **키가 없을 때만** 적용된다. 프로바이더가 `"bottom": ""`(키는 있고 값이 빈 문자열)를 주면 `""`가 그대로 통과 → DB 저장 → `characters.py:130`의
```python
"clothing": CharacterClothing(**normalized_clothing).model_dump()
```
에서 `min_length=1` 위반 → **처리되지 않은 pydantic `ValidationError`** → 500.

실측 저장값: `{"top":"분홍색 원피스","bottom":"","shoes":"알 수 없음","accessories":"꽃 머리핀"}`

**"mock이라 터진 것 아닌가" — 아니다.** 같은 패턴이 `top`·`shoes`·`skin`·`body` 전부에 있다. **아이 상반신만 나온 사진**(어린이 프로필 사진의 절대다수)이면 실제 비전 모델도 `bottom: ""`를 반환하는 것이 자연스럽다. 즉 **실키 환경에서 더 자주 터질 트리거**다.

**부수 문제** — 로컬 DB 커밋이 먼저 성공하고 응답 직렬화에서 죽으므로, 사용자에겐 "실패"인데 리소스는 남는다(전역 규칙의 *orphan* 클래스). 되돌리기·재시도 경로가 모두 막힌다.

**재현** — 동의(photos) 부여 후 `POST /v1/characters/from-photo`(임의 PNG) → 500 → `GET /v1/characters`에 존재 → `GET /v1/characters/{id}` 500.

---

### 🟡 M1 (중간 / 개발 온보딩 즉시 차단) — dev compose의 redis가 기본값으로 기동 불가

`infra/docker-compose.yml:24`
```yaml
command: redis-server --requirepass ${REDIS_PASSWORD:-}
```
`REDIS_PASSWORD`가 없으면 `redis-server --requirepass`(인자 없음)가 되어 컨테이너 즉사:
```
*** FATAL CONFIG FILE ERROR (Redis 7.4.8) ***
Reading the configuration file, at line 2
>>> 'requirepass'  wrong number of arguments
```
- `REDIS_PASSWORD`는 **리포 전체에서 이 한 줄에만 존재**한다 — `infra/.env.example`·`apps/api/.env.example`·`env.schema.json`(55개 프로퍼티)·문서 어디에도 없다. 문서만 보고 따라 한 신규 개발자는 **반드시** 막힌다.
- `check-env.sh --mode ci`는 파일 존재만 검사해 이 누락을 못 잡는다.
- 프로덕션 compose는 `--requirepass`를 안 쓰므로 **개발 스택 전용**.

### 🟡 M2 (중간) — 429 봉투 코드만 소문자 → 모바일 매칭 실패 → **en/ja 사용자에게 한국어 노출**

서버 429 본문:
```json
{"error":{"code":"rate_limit_exceeded", ...}}   ← 소문자
```
다른 모든 코드는 UPPER_SNAKE(`VALIDATION_ERROR`·`NOT_FOUND`·`FORBIDDEN`·`PAYMENT_REQUIRED`·`AUDIO_NOT_SUPPORTED`·`INPAINT_UNSUPPORTED`…). 출처: `src/core/rate_limit.py:113`.

모바일 `lib/core/api_error.dart:38`은 **서버 봉투 코드를 우선**한다:
```dart
code: envelopeCode ?? _codeFromStatus(statusCode)
```
→ `code == 'rate_limit_exceeded'` → `case 'RATE_LIMIT_EXCEEDED'`에 **매칭 실패** → `userMessage`/`localizedMessage` 모두 `default: return message` → 서버가 준 **한국어** "요청 한도 초과. 60초 후 다시 시도해주세요."가 en/ja 사용자에게 그대로 노출된다. `localizedMessage`가 막으려던 M15 회귀가 이 경로로 재발.

**false-green**: `apps/mobile/test/api_error_test.dart:223`은 `ApiError(code: 'RATE_LIMIT_EXCEEDED', ...)`를 **손으로 만들어** 검증한다 — 실제 서버 429 봉투를 파싱하지 않으므로 영원히 통과한다.

### 🟡 M3 (중간 / 테스트 사각지대) — 연령 리텔링(retell)이 mock에서 **구조적으로 불가능**

`POST /v1/books/{id}/retell` → 항상 **500 `LLM_JSON_INVALID`**:
```
2 validation errors for RetoldStory: title Field required, pages Field required
input_value={'result': 'mock response'}
```
mock LLM(`src/services/llm.py:136-323`)은 프롬프트 유형을 5개 분기로 감지하고 나머지는 `{"result":"mock response"}`로 폴백한다. 프롬프트 템플릿 8종 중 **`rewrite_story_for_age.system.jinja2` 하나만 미커버**:

| 템플릿 | mock 분기 |
|--------|-----------|
| generate_story / rewrite_page_text | 스토리 ✅ |
| generate_character_sheet | 캐릭터시트 ✅ |
| generate_image_prompts | 이미지 ✅ |
| generate_learning_assets | 학습 ✅ |
| moderate_input / moderate_output | 안전성 ✅ |
| **rewrite_story_for_age** | ❌ **미커버** |

→ 핵심 차별화 #1 "연령 리텔링"은 **단위 테스트 밖에서 한 번도 통과된 적이 없다**. 제품 결함이라기보다 **mock 커버리지 공백**이지만, 그래서 실제 결함이 있어도 지금은 알 방법이 없다.

### 🟡 M4 (중간 / 테스트 사각지대) — 구독 게이트 표면이 mock 라운드에서 **도달 불가**

`POST /v1/credits/subscribe` → **403** ("유료 구독은 앱스토어 결제(검증된 영수증)를 통해서만"). `IAP_VERIFICATION_MODE=local`로 우회 시도해도 `src/services/iap_verifier.py:448`이 `if not settings.testing: raise ValidationError(...)`로 **fail-closed**(2026-07-13 보안수정의 의도된 동작, 올바름).

결과: `TESTING=false`인 어떤 mock 구성에서도 유료 구독을 만들 수 없어 아래가 전부 미검증으로 남는다 — 시리즈 2권차 이상, PDF 내보내기, 프리미엄 스타일(watercolor/cartoon 외). 이번 라운드는 **DB 픽스처 주입**으로 우회했다(§0).

**제안** — 최종 라운드 전에 (a) admin 전용 구독 부여 테스트 훅, 또는 (b) `REVIEW_SANDBOX_ALLOWLIST` + 샌드박스 영수증 경로 중 하나를 정해두지 않으면, 유료 표면은 항상 사각지대로 남는다.

### 🟡 M5 (중간 / 잠복) — 서버 에러 **메시지 문자열을 한국어로 부분매칭**해 UI를 분기한다

```dart
// lib/screens/create_screen.dart:164
final title = message.contains('스타일') || message.contains('월 ')  ...
// lib/screens/viewer_screen.dart:904-905
message.contains('오디오') || message.contains('플랜')
```
402(`PAYMENT_REQUIRED`)의 구체 사유를 코드가 아니라 **한국어 메시지 본문**으로 판별한다. 지금 동작하는 이유는 서버 402 메시지가 한국어 고정이기 때문이며, `api_error.dart` 주석 스스로 "서버측 402 로컬라이즈는 M15 서버 잔여"라고 인정한다. **서버가 402를 로컬라이즈하는 순간 이 분기는 조용히 깨진다**(테스트도 안 잡는다). 안정 키는 `error.code` + `details`로 내려야 한다.

### 🟡 M6 (중간) — l10n을 우회하는 하드코딩 문자열 (en/ja 사용자에게 한국어 노출)

`.arb` 자체는 **완전**하다(848키 × ko/en/ja, 누락 0). 문제는 l10n을 **거치지 않는** 경로:

| 위치 | 노출 | 비고 |
|------|------|------|
| `characters_screen.dart:956-966` | **성격 특성 칩 10개**('호기심 많은'·'활발한'…)가 선택 UI에 한국어로 렌더 | 주석은 "AI 페이로드라 현지화 안 함"이라 하지만 **동시에 표시 라벨**이다(표시/전송 분리 필요) |
| `notification_scheduler.dart:116-117` | Android 알림 채널명 '잠자리 알림' + 설명 | OS 설정 화면에 영구 노출 |
| `kakao_share_service.dart:92,101` | 공유 카드 title '동화책 보기' / description | 공유 수신자에게 노출 |
| `providers.dart:637,639,698` | 서버 값 누락 시 폴백 '오늘의 추천'·'오늘의 동화를 만들어보세요!'·'성장 중' | 홈·성장 화면 |
| `api_error.dart` `userMessage` | 한국어 고정 메시지 15종 | `api_client.dart:94`가 이 값을 예외 메시지로 사용 |

*(검사 결과 오탐 제외: `book_spec.dart`의 enum `label`은 UI에서 `localizedLabel(l)`로 대체돼 미노출, `_CharacterRole`의 한국어는 `ageHint` 페이로드로 라벨은 l10n 사용.)*

### 🟢 L1 (낮음 / DX) — dev compose가 호스트 5432를 하드코딩
`infra/docker-compose.yml:10` `- "127.0.0.1:5432:5432"` — env 파라미터화 부재. 로컬 네이티브 postgres가 있으면 `bind: address already in use`로 스택이 안 뜬다.

### 🟢 L2 (낮음 / 제품 결정 필요) — POD가 **미지원·존재하지 않는 국가**도 USD 기본가로 주문받는다
`src/routers/pod.py:57-67` — 가격표는 `KR/US/JP` 3개뿐이고 나머지는 `_POD_PRICING_DEFAULT = (20, 8, "USD")`. 검증은 2자리 정규식뿐이라 **`ZZ`·`XX` 같은 존재하지 않는 코드도 200으로 견적**이 나오고 주문까지 생성된다. 실제 배송 불가 지역 주문을 받을 수 있다 → **규범적 결정 사항**(지원 국가 화이트리스트 여부)이라 코드 쪽으로 조용히 정하지 않고 보고한다.

### 🟢 L3 (낮음 / 계약 의미 모호) — 동의 철회 후 `revoked: false`
철회 직후 `GET /v1/consent` → `{"granted": false, ..., "revoked": false, "consent_version": "v2"}`. 활성 동의 행이 없으면 기본 응답(`consent.py:52-53`)으로 떨어지기 때문. `granted=false`가 실제 게이트를 정확히 막고 있어(from-photo 403 확인) **기능 영향은 없고**, 모바일도 이 필드를 쓰지 않는다. 다만 `revoked`를 신뢰하는 클라이언트는 오판한다.

### 🟢 L4 (정보) — `CLAUDE.md`의 테이블 수 서술 드리프트
"27개 테이블" ↔ 실측 28개(+`alembic_version`). 2026-07-08 실측 이후 `iap_webhook_events` 등 추가분. 코드가 정본이므로 문서 갱신 대상.

### 🟢 L5 (낮음 / 로컬 상태) — `infra_postgres_data` 볼륨이 PG16으로 초기화돼 15-alpine과 비호환
`FATAL: database files are incompatible with server ... initialized by PostgreSQL version 16`. 리포 결함 아님. 이번 라운드는 "빈 DB 마이그레이션 완주" 검증이 목적이라 신규 볼륨 사용.

### 🟢 L6 (정보) — 인페인트 계약이 문서 서술과 다름
`CLAUDE.md`는 "그 외 프로바이더는 **전체 재생성 폴백**"이라고 하나, 실제는 **409 `INPAINT_UNSUPPORTED`** 거부다(`/v1/config/capabilities`도 `inpaint_supported:false`로 정직하게 알린다 — 앱은 이 값으로 UI를 가린다). 구현 현황 서술은 코드가 정본이므로 **문서 갱신 대상**.

---

## 3. 막힌 지점

| # | 막힌 지점 | 우회 |
|---|-----------|------|
| 1 | dev compose redis가 기본값으로 즉사 (M1) | 우회(override) — 단 **리포 상태로는 스택이 안 뜬다**는 사실 자체가 발견 |
| 2 | 호스트 5432 점유로 PG 바인드 실패 (L1) | 우회(5433) |
| 3 | 기존 PG 볼륨 버전 비호환 (L5) | 우회(신규 볼륨) |
| 4 | **Celery 경로 책 생성 전량 실패 (C1)** | ❌ 우회 불가 → `USE_CELERY=false`로 **경로를 바꿔** 나머지 표면 검증 |
| 5 | **유료 구독 확립 경로 도달 불가 (M4)** | DB 픽스처 주입(구독 생성 경로 자체는 미검증) |
| 6 | **retell이 mock에서 항상 실패 (M3)** | ❌ 우회 불가 — 실키 라운드로 이연 |
| 7 | **시뮬레이터 탭 입력 불가** — `idb` 미설치, AppleScript는 접근성 권한 대기로 타임아웃(`-1712`) | 통합 테스트(위젯 파인더 + 라이브 API)로 대체. **UI_PREFLIGHT 수동 체크(오버레이 겹침·바텀시트 스크롤·글자 130%·320x480 작은 화면)는 여전히 사람 손이 필요** |
| 8 | 2주 전 배포 테스트 잔존 컨테이너(`infra-api-1/2`·`infra-worker-1/2`·`infra-nginx-1`)가 같은 compose 프로젝트명(`infra`)으로 생존 | 별도 네트워크(`infra_app-network`)라 격리됨. 다만 `docker compose up`이 이들의 postgres/redis/minio를 dev 설정으로 **재생성**했다 — 오너 확인 필요 |
| 9 | PDF 이미지 삽입 검증 불가 | mock 이미지가 외부 `picsum.photos` URL(302 반환) — 제품 결함 아님, 실키 라운드로 이연 |

---

## 4. 중간 판정

**❌ 최종 E2E 진행 불가.**

`USE_CELERY=true`가 프로덕션 기본값이고 그 경로에서 **핵심 기능(책 생성)이 100% 실패**한다(C1). 이 상태로 실키·실기기·실서버 라운드를 돌면 어떤 실패든 C1이 원인인지 분리할 수 없다. 추가로 유료 기능 두 축이 깨져 있다 — PDF는 한국어가 읽히지 않고(H1), 사진 기반 캐릭터는 500 + 고아를 남긴다(H2).

**반대로, 견고함이 확인된 부분** (이번 라운드에서 실제로 깨보려 했으나 버티었다):
- **돈**: 크레딧 정합 `sum(tx) = balance` 완전 일치, 멱등 충전 이중지급 없음, 실패 잡 자동 환불, 무료 플랜 한도가 `failed` 제외 카운트
- **권한**: IDOR 9종 전부 차단, 관리자 엔드포인트 403, 레이트리밋 429 정상
- **파기 의무**: 음성 샘플 삭제 시 스토리지 실제 파기, 동의 철회 시 사진·그림 파생 캐릭터 + 원본 파기 + 이후 기능 재차단, 계정 삭제
- **마이그레이션**: 빈 실PG 23리비전 완주, 모델 drift 0, 단일 head
- **계약**: live ↔ `openapi.json` 77 ops 완전 일치
- **모바일**: 848키 3로케일 완전 일치, 라이브 API로 5개 여정(ko/en/ja 신규설치 + 재방문 + 생성→로딩→뷰어) 전부 통과, 키 노출 0

### 선결 수정 목록

| 우선 | 항목 | 사유 |
|------|------|------|
| 1 | **C1** — Celery 태스크의 이벤트 루프 / 커넥션 풀 정합성 | 출시 차단 |
| 2 | **C1 회귀 테스트** — 실PG + Celery 통합 테스트 신설 | SQLite 게이트는 이 클래스를 **구조적으로** 못 잡음 → 없으면 재발 확정 |
| 3 | **H1** — CJK 폰트 번들/설치 + 폰트 등록 실패 시 조용한 폴백 금지 | 유료 기능이 주력 언어에서 무의미 |
| 4 | **H2** — `""` 값 정규화(`get(k) or default`) + 응답 직렬화 실패가 고아를 남기지 않도록 | 실키에서 더 자주 터질 트리거 |
| 5 | **M1** — dev compose redis 수정 + `REDIS_PASSWORD` 문서화(또는 제거) | 신규 개발자 즉시 차단 |
| 6 | **M2** — 429 코드를 `RATE_LIMIT_EXCEEDED`로 통일 + 실제 봉투를 파싱하는 모바일 테스트 | 현재 테스트는 false-green |
| 7 | **M3 / M4** — mock retell 분기 추가, 구독 테스트 훅 결정 | 없으면 최종 라운드에도 같은 사각지대 |
| 8 | **M5** — 402 분기를 메시지 문자열이 아닌 `error.code`/`details` 기반으로 | 서버 로컬라이즈 시 조용히 깨짐 |
| 9 | M6 · L2 · L3 · L4 · L6 | 출시 전 정리 / 제품 결정 |

### 재개 지점
C1·H1·H2 수정 후, 데모 계정 `5bc95a69-3d96-4fff-9f02-b9205e2bc747`(크레딧 58·책 5권)을 그대로 재사용해 **Phase 2 #6(Celery 경로 책 생성)부터** 재개한다. 그 밖의 PASS 항목은 재실행 불필요하되, C1 수정이 `tasks.py`/`database.py`를 건드리므로 **#6~#10·#22(생성 계열)는 Celery 경로로 전량 재검증**해야 한다.

### 오너 액션(사람만 가능)
1. `UI_PREFLIGHT` 수동 체크 — 오버레이 겹침·바텀시트 스크롤·글자 130%·320x480 작은 화면 (막힌 지점 #7)
2. 2주 전 잔존 컨테이너(`infra-*`) 정리 여부 판단 (막힌 지점 #8)
3. 시뮬레이터 자동화가 필요하면 `idb` 설치 또는 터미널 접근성 권한 부여

---

*작성: 2026-08-09. 산출물: 본 문서. 하네스·로그·증적은 세션 스크래치패드(`e2elib.py`, `step1~6_*.py`, `repro_celery_loop.py`, `e2e_live_journey_test.dart.bak`, `worker.log`, `book1.pdf`, `shots/`)에 보존.*
