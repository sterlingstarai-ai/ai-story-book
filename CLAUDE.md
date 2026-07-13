# AI Story Book 프로젝트 컨텍스트

> Claude Code가 이 프로젝트를 빠르게 이해하기 위한 메모리 파일.
> **구현 현황 서술은 코드가 정본** — 이 문서와 코드가 충돌하면 코드를 믿고 이 문서를 갱신한다.
> 마지막 코드 실측: **2026-07-08**

## 프로젝트 개요

**AI Story Book**은 AI로 맞춤형 동화책을 생성하는 모바일 앱입니다.

- **타입**: Flutter 모바일 앱 + FastAPI 백엔드 (모노레포)
- **글로벌·다국어 제품** (2026-06-22 한국어 우선 → 글로벌 전환)
  - 스토리 생성 언어: ko / en / ja / zh / es (`apps/api/src/core/i18n.py`, 기본 ko)
  - 모바일 UI l10n: ko / en / ja (`apps/mobile/lib/l10n/*.arb`)
- **상태**: 글로벌 다국어 롤아웃 머지(PR #45, 2026-07-06) + 출시 차단 감사 수정 머지(PR #56) → 출시 준비 단계
- ⚠️ **버전 표기 불일치(출시 전 정리 필요)**: `core/config.py` app_version=`0.2.0`, `pubspec.yaml`=`0.1.0+1`, 과거 문서 표기 0.3.x — 셋 다 실제 기능 스코프보다 뒤처짐

## 핵심 차별화

1. **연령 최적화**: 3-5/5-7/7-9/adult 문체·어휘·교육 테마 + 연령 리텔링(`POST /v1/books/{id}/retell`)
2. **캐릭터 일관성 + 시리즈**: 캐릭터 시트 저장 → 같은 캐릭터로 계속 생성
3. **v0.3 확장**: 인페인트 부분 재생성 · 지역별 POD 인쇄 주문 · 스트릭 보상 · 분기 스토리 · 발음 연습 · 사진 기반 캐릭터

## 기술 스택

```
Frontend: Flutter (Riverpod, gen-l10n)
Backend:  FastAPI (Python 3.11+)
Queue:    Celery + Redis
DB:       PostgreSQL (SQLAlchemy + Alembic)
Storage:  S3 호환 (Minio 로컬, R2/S3 운영)
AI:       LLM (스토리·모더레이션) + 이미지 API + TTS/STT
```

## 모노레포 구조

```
ai-story-book/
├── apps/
│   ├── mobile/          # Flutter 앱 (lib/screens·services·providers·models·l10n)
│   └── api/             # FastAPI 백엔드
│       └── src/
│           ├── core/        # config, i18n, rate_limit, consent, dependencies, errors
│           ├── models/      # SQLAlchemy(db.py) + Pydantic(dto.py)
│           ├── routers/     # /v1 API 라우터 (아래 표)
│           ├── services/    # orchestrator, credits, iap_verifier, pod_provider, ...
│           └── prompts/     # 프롬프트 템플릿 (.jinja2)
├── packages/shared/schema/  # openapi.json = API 계약 정본
├── infra/               # docker-compose(.prod), nginx
└── docs/                # 스펙·QA·운영 문서
```

## API 표면

**계약 정본: `packages/shared/schema/openapi.json`** — 엔드포인트 상세는 여기서 확인한다(이 문서에 복제하지 않음).

| Prefix | 도메인 |
|--------|--------|
| `/v1/books` | 생성·상태 조회·페이지 재생성·인페인트·시리즈·retell(연령 리텔링)·PDF·오디오 |
| `/v1/characters` | 캐릭터 CRUD + 사진 기반 생성 |
| `/v1/library` | 내 서재 |
| `/v1/credits` | 크레딧·구독 |
| `/v1/iap` | 인앱결제 영수증 검증·복원 |
| `/v1/pod` | 실물 인쇄(POD) 주문·지역별 가격 |
| `/v1/streak` | 스트릭·오늘의 동화·마일스톤 보상 |
| `/v1/growth` | 독서 성장 리포트 |
| `/v1/profiles` | 자녀 프로필 |
| `/v1/users` | 계정 (데이터 삭제 포함) |
| `/v1/settings` | 사용자 설정 |
| `/v1/consent` | 동의 관리 (사진 등) |
| `/v1/branch` | 분기 스토리 |
| `/v1/voice-profiles` | 음성 프로필 |
| `/v1/pronunciation` | 발음 연습 |
| `/v1/config` | 원격 설정 |
| (shares) | 공유 링크 — 인증 라우터 + 공개(public) 라우터 분리 |

**공통 헤더**: `X-User-Key: {uuid}` (필수) / **멱등성**: `X-Idempotency-Key: {uuid}` (POST /v1/books 등 생성 계열)

## DB 스키마

**정본: `apps/api/src/models/db.py` + `apps/api/alembic/versions/`** — 27개 테이블, SQL을 이 문서에 복제하지 않음.

- **생성 파이프라인**: jobs, story_drafts, image_prompts, books, pages, series
- **캐릭터**: characters
- **돈**: user_credits, subscriptions, credit_transactions, iap_receipts, pod_orders, ad_reward_logs
- **참여**: daily_streaks, daily_stories, reading_logs, quiz_answers, pronunciation_logs
- **계정/보호자**: user_consents, user_settings, child_profiles, screen_time_limits
- **기타**: book_shares, rate_limits, voice_profiles, branch_story_nodes, branch_story_edges

---

# 설계 스펙 (규범 — 코드가 이를 어기면 코드가 버그일 수 있음, 충돌 시 보고 후 결정)

## 오케스트레이터 파이프라인

```
A. 입력 정규화 (BookSpec 확정)
B. 입력 안전성 검사 (ModerationResult)
C. 스토리 생성 (LLM → StoryDraft)
D. 캐릭터 시트 생성 (LLM → CharacterSheet)
E. 이미지 프롬프트 생성 (LLM → ImagePrompts) [cover 포함]
F. 이미지 생성 (cover + pages 병렬, rate limit 고려)
G. 출력 안전성 검사 (이미지/텍스트)
H. 패키징 (BookResult 생성, 업로드, 저장)
```

## 에러 코드 (`core/errors.py`)

| 코드 | 설명 | 재시도 |
|------|------|--------|
| SAFETY_INPUT | 입력 안전성 위반 | ❌ 금지 |
| SAFETY_OUTPUT | 출력 안전성 위반 | ⚠️ 2회 |
| LLM_TIMEOUT | LLM 타임아웃 | ✅ 2회 |
| LLM_JSON_INVALID | LLM JSON 파싱 실패 | ✅ 2회 |
| IMAGE_TIMEOUT | 이미지 생성 타임아웃 | ✅ 3회 |
| IMAGE_RATE_LIMIT | 이미지 API 레이트 리밋 | ✅ 백오프 후 3회 |
| IMAGE_FAILED | 이미지 생성 실패 | ✅ 3회 |
| STORAGE_UPLOAD_FAILED | 스토리지 업로드 실패 | ✅ 2회 |
| DB_WRITE_FAILED | DB 쓰기 실패 | ❌ 즉시 실패 |
| QUEUE_FAILED | 큐 등록 실패 | ❌ 즉시 실패 |
| UNKNOWN | 알 수 없는 에러 | ❌ 즉시 실패 |

## 타임아웃/재시도 기본값

| 단계 | 타임아웃 | 재시도 | 백오프 |
|------|----------|--------|--------|
| 입력 모더레이션 | 10초 | 0회 | - |
| 스토리 생성 | 30초 | 2회 | 2s, 5s |
| 캐릭터 시트 | 20초 | 1회 | 2s |
| 이미지 프롬프트 | 30초 | 1회 | 2s |
| 이미지 생성 (페이지당) | 90초 | 3회 | 2s, 5s, 12s |
| 전체 잡 SLA | 10분 | - | - |

## 진행률 계산

| 범위 | 단계 |
|------|------|
| 0-10% | 입력 정규화/모더레이션 |
| 10-30% | 스토리 생성 |
| 30-40% | 캐릭터 시트 |
| 40-55% | 이미지 프롬프트 |
| 55-95% | 이미지 생성 (페이지별 n/total 반영) |
| 95-100% | 업로드/패키징 |

## 연령별 규칙

| 연령 | 페이지당 문장 | 최대 단어 | 특징 |
|------|--------------|----------|------|
| 3-5 | 1-2문장 | 25단어 | 반복 표현, 의성어, 쉬운 단어 |
| 5-7 | 2-3문장 | 40단어 | 감정 표현, 간단 대화 |
| 7-9 | 2-4문장 | 60단어 | 접속사, 원인-결과 |
| adult | 3-6문장 | 제한 없음 | 서사 밀도 높음 |

## 스타일 토큰

| Style | Prompt Token |
|-------|--------------|
| watercolor | soft watercolor painting, gentle brush strokes, pastel colors, warm light |
| cartoon | vibrant cartoon, bold outlines, bright colors, playful |
| 3d | 3D rendered, Pixar-like, cute proportions, soft lighting |
| pixel | pixel art, 16-bit retro, limited palette |
| oil_painting | oil painting illustration, rich texture, warm tones |
| claymation | claymation, stop-motion look, textured clay figures |

---

# 구현 실측 (2026-07-08)

## 이미지 API

- `image_provider` 설정: `openai`(기본) | `gemini` | `replicate` | `fal` | `mock` (`core/config.py`)
- **인페인트(마스킹 부분 재생성)는 replicate/fal에서만 실동작** (`services/image.py: supports_inpaint`) — 그 외 프로바이더는 전체 재생성 폴백
- 비용 추정(설계 시점 기준): 이미지 $0.02-0.05/장 → 1권(cover+8p) 약 $0.27, LLM 포함 ~$0.32, 재생성 여유 ×1.5 ≈ $0.48

## Rate Limiting

- Redis 기반 Sliding Window, 기본 10 requests / minute / user_key
- 구현: `apps/api/src/core/rate_limit.py`

## 검증 루프 (정본)

```bash
# 백엔드 테스트/린트 (venv 필수 — 시스템 pytest 아님)
cd apps/api && venv/bin/python -m pytest tests/
cd apps/api && venv/bin/ruff check src/

# Flutter 테스트 (CI 핀 버전 3.38.7과 동일 바이너리)
cd apps/mobile && /opt/homebrew/bin/flutter test

# l10n 재생성 (신규 문자열 추가 후 필수)
cd apps/mobile && /opt/homebrew/bin/flutter gen-l10n

# 개발 실행
cd apps/api && uvicorn src.main:app --reload
cd apps/mobile && flutter run
docker-compose -f infra/docker-compose.yml up -d

# DB 마이그레이션
alembic upgrade head
alembic revision --autogenerate -m "message"
```

## 개발 규칙

- **모든 신규 사용자 노출 문자열은 ko/en/ja 3개 `.arb`에 동시 추가 + `flutter gen-l10n`** (하드코딩 금지)
- 캐릭터 시트 master_description은 모든 이미지 프롬프트에 필수 포함
- LLM 출력은 무조건 JSON Schema 검증 후 진행
- 페이지 재생성은 해당 페이지만 (전체 재생성 금지)
- 이미지 병렬 생성 시 rate limit 고려 (동시 최대 3개 권장)
- API 변경 시 `packages/shared/schema/openapi.json` 계약을 함께 갱신

## 정본 포인터

| 무엇 | 어디 |
|------|------|
| API 계약 | `packages/shared/schema/openapi.json` |
| DB 스키마 | `apps/api/src/models/db.py` + `apps/api/alembic/versions/` |
| 글로벌 전환 스펙 | `docs/DEV_SPEC_GLOBAL_2026-07-02.md` |
| QA·운영 | `docs/qa/`, `docs/OPERATIONS_TEST_RUNBOOK.md`, `docs/UI_PREFLIGHT_CHECKLIST.md`, `docs/DEPLOYMENT.md` |
| 미결 제품 결정 | `docs/FOUNDER_DECISIONS_PENDING.md` |
| 세션 이력·진행 상황 | Claude 오토메모리 (`~/.claude/projects/.../memory/`) — **이 문서에 세션 로그를 쌓지 않는다** |
