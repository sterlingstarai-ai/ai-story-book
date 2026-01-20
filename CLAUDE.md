# AI Story Book 프로젝트 컨텍스트

> Claude Code가 이 프로젝트를 빠르게 이해하기 위한 메모리 파일

## 프로젝트 개요

**AI Story Book**은 AI로 맞춤형 동화책을 생성하는 모바일 앱입니다.

- **타입**: Flutter 모바일 앱 + FastAPI 백엔드
- **언어**: 한국어 (Korean) 우선
- **버전**: 0.2.0
- **상태**: v0.2 개발 완료 (Day 25 테스트 예정)

## 핵심 차별화 (2개)

1. **한국어 연령 최적화**: 3-5/5-7/7-9세 문체/어휘/교육 테마
2. **캐릭터 일관성 + 시리즈**: 캐릭터 시트 저장 → 같은 캐릭터로 매일 1권

## 기술 스택

```
Frontend: Flutter (iOS/Android)
Backend: FastAPI (Python 3.11+)
Queue: Celery + Redis
Database: PostgreSQL
Storage: S3 호환 (Minio 로컬, R2/S3 운영)
AI: LLM (텍스트) + Image API (이미지)
```

## 모노레포 구조

```
ai-story-book/
├── apps/
│   ├── mobile/          # Flutter 앱
│   └── api/             # FastAPI 백엔드
│       └── src/
│           ├── models/      # Pydantic 모델 (dto.py)
│           ├── core/        # 에러, 설정 (errors.py)
│           ├── services/    # 오케스트레이터
│           ├── prompts/     # 프롬프트 템플릿 (.jinja2)
│           └── routers/     # API 라우터
├── packages/
│   └── shared/
│       └── schema/      # JSON Schema
├── infra/               # docker-compose
└── docs/
    ├── api/             # API 문서, 샘플 응답
    └── qa/              # QA 시나리오
```

## API 엔드포인트 (v1)

### 책 관련
| Method | Path | 설명 |
|--------|------|------|
| POST | `/v1/books` | 책 생성 요청 (job_id 반환, 크레딧 1 소모) |
| GET | `/v1/books/{job_id}` | 생성 상태/결과 조회 |
| POST | `/v1/books/{job_id}/pages/{page_number}/regenerate` | 페이지 재생성 |
| POST | `/v1/books/series` | 시리즈 다음 권 생성 |
| GET | `/v1/books/{book_id}/pdf` | PDF 내보내기 (v0.2) |
| POST | `/v1/books/{book_id}/audio` | 전체 오디오 생성 (v0.2) |
| GET | `/v1/books/{book_id}/pages/{page_number}/audio` | 페이지 오디오 (v0.2) |

### 캐릭터 관련
| Method | Path | 설명 |
|--------|------|------|
| POST | `/v1/characters` | 캐릭터 저장 |
| GET | `/v1/characters` | 캐릭터 목록 (user_key 기반) |
| GET | `/v1/characters/{character_id}` | 캐릭터 상세 |
| POST | `/v1/characters/from-photo` | 사진에서 캐릭터 생성 (v0.2) |

### 서재
| Method | Path | 설명 |
|--------|------|------|
| GET | `/v1/library` | 내 책 목록 (user_key 기반) |

### 크레딧 (v0.2)
| Method | Path | 설명 |
|--------|------|------|
| GET | `/v1/credits/status` | 크레딧 및 구독 상태 |
| GET | `/v1/credits/balance` | 크레딧 잔액 |
| GET | `/v1/credits/transactions` | 거래 내역 |
| POST | `/v1/credits/subscribe` | 구독 시작 |
| POST | `/v1/credits/cancel-subscription` | 구독 취소 |
| POST | `/v1/credits/add` | 크레딧 추가 |

### 스트릭 (v0.2)
| Method | Path | 설명 |
|--------|------|------|
| GET | `/v1/streak/info` | 스트릭 정보 |
| GET | `/v1/streak/today` | 오늘의 동화 |
| POST | `/v1/streak/read` | 읽기 기록 |
| GET | `/v1/streak/history` | 읽기 히스토리 |
| GET | `/v1/streak/calendar` | 스트릭 캘린더 |

**공통 헤더**: `X-User-Key: {uuid}` (필수)
**멱등성**: `X-Idempotency-Key: {uuid}` (POST /v1/books)

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

## 데이터베이스 스키마 (PostgreSQL)

```sql
-- 잡 상태
CREATE TABLE jobs (
  id VARCHAR(60) PRIMARY KEY,
  status VARCHAR(20) NOT NULL,  -- queued/running/failed/done
  progress INT DEFAULT 0,
  current_step VARCHAR(120),
  error_code VARCHAR(60),
  error_message VARCHAR(300),
  moderation_input JSONB,       -- ModerationResult
  moderation_output JSONB,      -- ModerationResult
  user_key VARCHAR(80) NOT NULL,
  idempotency_key VARCHAR(80),
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- 중간 산출물
CREATE TABLE story_drafts (
  id SERIAL PRIMARY KEY,
  job_id VARCHAR(60) REFERENCES jobs(id),
  draft JSONB NOT NULL,         -- StoryDraft
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE image_prompts (
  id SERIAL PRIMARY KEY,
  job_id VARCHAR(60) REFERENCES jobs(id),
  prompts JSONB NOT NULL,       -- ImagePrompts
  created_at TIMESTAMP DEFAULT NOW()
);

-- 최종 결과
CREATE TABLE books (
  id VARCHAR(60) PRIMARY KEY,
  job_id VARCHAR(60) REFERENCES jobs(id),
  title VARCHAR(80) NOT NULL,
  language VARCHAR(10) NOT NULL,
  target_age VARCHAR(10) NOT NULL,
  style VARCHAR(30) NOT NULL,
  theme VARCHAR(20),
  character_id VARCHAR(60),
  cover_image_url VARCHAR(500),
  pdf_url VARCHAR(500),
  audio_url VARCHAR(500),
  user_key VARCHAR(80) NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE pages (
  id SERIAL PRIMARY KEY,
  book_id VARCHAR(60) REFERENCES books(id),
  page_number INT NOT NULL,     -- 1-indexed
  text TEXT NOT NULL,
  image_url VARCHAR(500),
  image_prompt TEXT,
  audio_url VARCHAR(500),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE characters (
  id VARCHAR(60) PRIMARY KEY,
  name VARCHAR(40) NOT NULL,
  master_description TEXT NOT NULL,
  appearance JSONB NOT NULL,
  clothing JSONB NOT NULL,
  personality_traits JSONB NOT NULL,
  visual_style_notes VARCHAR(200),
  user_key VARCHAR(80) NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Rate Limiting
CREATE TABLE rate_limits (
  user_key VARCHAR(80) PRIMARY KEY,
  request_count INT DEFAULT 0,
  window_start TIMESTAMP DEFAULT NOW()
);
```

## 에러 코드 (ErrorCode)

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

## 이미지 API (초기)

- **권장**: Replicate (Flux/SDXL) 또는 FAL.ai
- **환경변수**: `IMAGE_API_PROVIDER`, `IMAGE_API_KEY`
- **비용 추정**: $0.02-0.05/장 → 1권당 $0.20-0.50

## Rate Limiting

- Redis 기반 Sliding Window
- 기본: 10 requests / minute / user_key
- 구현: `apps/api/src/core/rate_limit.py`

## 주요 명령어

```bash
# 개발
cd apps/api && uvicorn src.main:app --reload
cd apps/mobile && flutter run

# Docker
docker-compose -f infra/docker-compose.yml up -d

# DB
alembic upgrade head
alembic revision --autogenerate -m "message"

# 테스트
pytest apps/api/tests/
flutter test
```

## MVP v0.1 범위

### 포함
- [x] 책 생성 (topic, age, style, theme, character)
- [x] 표지 + 8페이지 (텍스트 + 이미지)
- [x] 페이지 단위 재생성 (text/image/both)
- [x] 캐릭터 시트 자동 생성 + 저장
- [x] 내 서재 (최근 N권)
- [x] 진행률 표시

### 제외 (v0.2+)
- [ ] PDF 내보내기
- [ ] TTS (오디오)
- [ ] 사진 기반 캐릭터
- [ ] 크레딧/구독
- [ ] 오늘의 동화 (스트릭)

## QA P0 체크리스트 (출시 차단)

1. [ ] 기본 생성 성공 (8페이지)
2. [ ] 진행률 표시 정상
3. [ ] 입력 안전성 차단 (아동)
4. [ ] 개인정보 차단
5. [ ] forbidden_elements 강제
6. [ ] 페이지 이미지 재생성
7. [ ] 페이지 텍스트 리라이트
8. [ ] 캐릭터 저장 (시리즈 씨앗)
9. [ ] 캐릭터 일관성 확인
10. [ ] 이미지 생성 실패 처리
11. [ ] LLM JSON 파싱 실패 처리
12. [ ] 중복 요청 방지
13. [ ] 앱 재실행 후 서재 유지
14. [ ] 느린 네트워크 처리
15. [ ] 이미지 텍스트/워터마크 방지
16. [ ] Cover 이미지 생성 테스트

## 개발 일정

| 기간 | 작업 |
|------|------|
| Day 1-2 | 모노레포 + docker-compose + FastAPI skeleton + DB |
| Day 3-4 | job queue + orchestrator(텍스트) + Flutter Create/Loading |
| Day 5-7 | 이미지 생성 + 스토리지 + Viewer |
| Week 2 | 재생성/편집 + 캐릭터 저장 + Library + QA |

## 현재 단계

- [x] 프로젝트 설계 완료
- [x] Pydantic 모델 정의
- [x] JSON Schema 정의
- [x] 프롬프트 패키지 작성
- [x] QA 시나리오 30개 작성
- [x] 누락 사항 12개 반영
- [x] Day 1: 모노레포 구조 + Docker Compose + FastAPI
- [x] Day 2: Pydantic 모델 + DB 스키마 + API 라우터
- [x] Day 3: Celery + 오케스트레이터 + 프롬프트 템플릿
- [x] Day 4: LLM 서비스 (스토리, 모더레이션)
- [x] Day 5: 캐릭터 시트 + 이미지 프롬프트
- [x] Day 6: 이미지 API + S3 스토리지
- [x] Day 7: API 테스트 + README
- [x] Week 2: Flutter 앱 개발 완료
  - [x] 프로젝트 구조 + pubspec.yaml
  - [x] API 클라이언트 + 모델
  - [x] 상태 관리 (Riverpod)
  - [x] Home 화면
  - [x] Create 화면 (책 생성 폼)
  - [x] Loading 화면 (진행률 표시)
  - [x] Viewer 화면 (책 뷰어)
  - [x] Library 화면 (내 서재)
  - [x] Characters 화면 (캐릭터 관리)
  - [x] 라우팅 및 네비게이션
- [x] 통합 테스트 완료
  - [x] API 통합 테스트 (test_integration.py)
  - [x] E2E 플로우 테스트 (test_e2e.py)
  - [x] QA P0 체크리스트 테스트 (test_qa_p0.py)
  - [x] Flutter 위젯 테스트 (widget_test.dart)
  - [x] Flutter 모델 테스트 (model_test.dart)
- [x] 배포 구성 완료
  - [x] API Dockerfile (멀티스테이지 빌드)
  - [x] Worker Dockerfile
  - [x] docker-compose.prod.yml
  - [x] Nginx 설정 (Reverse Proxy, Rate Limiting)
  - [x] GitHub Actions CI/CD
  - [x] 배포 스크립트 (deploy.sh)
  - [x] 환경 변수 문서화 (.env.example)
  - [x] 배포 가이드 (DEPLOYMENT.md)
- [x] **MVP v0.1 개발 완료!**

### v0.2 기능 개발 완료
- [x] Day 15-16: PDF 내보내기
  - [x] ReportLab 기반 PDF 생성 서비스 (services/pdf.py)
  - [x] GET /v1/books/{book_id}/pdf 엔드포인트
  - [x] Flutter PDF 다운로드 및 공유 기능
- [x] Day 17-18: TTS 오디오
  - [x] TTS 서비스 (services/tts.py) - Google TTS, ElevenLabs 지원
  - [x] POST /v1/books/{book_id}/audio 엔드포인트
  - [x] GET /v1/books/{book_id}/pages/{page_number}/audio 엔드포인트
  - [x] Flutter 오디오 플레이어 (just_audio)
- [x] Day 19-20: 크레딧/구독 시스템
  - [x] 크레딧 서비스 (services/credits.py)
  - [x] DB 모델: UserCredits, Subscription, CreditTransaction
  - [x] /v1/credits/* API (status, balance, subscribe, transactions)
  - [x] Flutter 크레딧 화면 (credits_screen.dart)
  - [x] 책 생성 시 크레딧 차감
- [x] Day 21-22: 사진 기반 캐릭터
  - [x] 사진 분석 서비스 (services/photo_character.py)
  - [x] POST /v1/characters/from-photo 엔드포인트
  - [x] Flutter 카메라/갤러리 연동 (image_picker)
- [x] Day 23-24: 오늘의 동화 (스트릭)
  - [x] 스트릭 서비스 (services/streak.py)
  - [x] DB 모델: DailyStreak, DailyStory, ReadingLog
  - [x] /v1/streak/* API (info, today, read, history, calendar)
  - [x] 마일스톤 및 뱃지 시스템
- [x] **v0.2 개발 완료!**

## 누락 사항 반영 완료 (12개)

1. ✅ Cover 이미지 → ImagePrompts에 cover 필드 추가
2. ✅ idempotency_key → 헤더 X-Idempotency-Key로 처리
3. ✅ 페이지 인덱스 → 1-indexed로 통일
4. ✅ 캐릭터 목록 API → GET /v1/characters 추가
5. ✅ 시리즈 API → POST /v1/books/series 추가
6. ✅ user_key 필수화 → 헤더 X-User-Key로 필수
7. ✅ DB 스키마 → story_drafts, image_prompts, rate_limits 추가
8. ✅ Audio/PDF → v0.2로 명시
9. ✅ 이미지 API → Replicate/FAL 명시
10. ✅ Rate Limit → Redis sliding window 명시
11. ✅ ModerationResult 저장 → jobs 테이블에 컬럼 추가
12. ✅ 프롬프트 파일 → .jinja2 형식 권장

## 주의사항

- 이미지 병렬 생성 시 rate limit 고려 (동시 최대 3개 권장)
- 캐릭터 시트 master_description은 모든 이미지 프롬프트에 필수 포함
- LLM 출력은 무조건 JSON Schema 검증 후 진행
- 페이지 재생성은 해당 페이지만 (전체 재생성 금지)

## 비용 추정

| 항목 | 단가 | 1권당 |
|------|------|-------|
| LLM (스토리+캐릭터+프롬프트) | ~$0.05 | $0.05 |
| 이미지 (cover+8p) | $0.03×9 | $0.27 |
| **합계** | | **~$0.32** |
| 재생성 포함 (×1.5) | | **~$0.48** |

---

## 🔴 최근 세션 (2026-01-21)

### 코드 리뷰 30개 이슈 수정 완료

외부 코드 리뷰 2건을 받아 분석 후, 총 30개 이슈를 모두 수정함.

**커밋**: `537a5e2` - `fix: 코드 리뷰 30개 이슈 수정`
**GitHub**: Push 완료 → CI/CD 파이프라인 자동 실행 중

### 수정된 이슈 목록

#### P0 Critical (7개) ✅
| 이슈 | 파일 | 수정 내용 |
|-----|------|----------|
| P0-1 | `routers/books.py` | `use_credit()` 호출 추가 (크레딧 차감 누락) |
| P0-2 | `routers/books.py` | `/v1/books/{book_id}/detail` 엔드포인트 추가 |
| P0-3 | `services/orchestrator.py` | `character_id=spec.character_id` 저장 |
| P0-4 | `services/orchestrator.py` | `generate_series_book()` 구현 (TODO였음) |
| P0-5 | `services/orchestrator.py` | `regenerate_page()` 구현 (TODO였음) |
| P0-6 | `docker-compose.prod.yml` | init-db.sql 참조 제거 |
| P0-7 | `core/database.py` | sync/async URL 분리 함수 추가 |

#### P1 Runtime Risk (8개) ✅
| 이슈 | 파일 | 수정 내용 |
|-----|------|----------|
| P1-1 | `routers/characters.py` | from-photo 스키마 정규화 |
| P1-2 | `core/rate_limit.py` (신규) | Redis 기반 Rate Limiter |
| P1-3 | `services/storage.py` | bucket 체크 캐싱 (`_bucket_verified`) |
| P1-4 | `mobile/lib/core/env_config.dart` (신규) | 환경별 baseUrl 분리 |
| P1-5 | `mobile/lib/services/api_client.dart` | `response.data!` 안전 처리 |
| P1-6 | `main.py`, `core/config.py` | CORS 설정 환경변수화 |
| P1-7 | `services/orchestrator.py` | 출력 모더레이션 구현 |
| P1-8 | `services/tasks.py` (신규) | Celery task 래퍼 |

#### P2 Code Quality (9개) ✅
| 이슈 | 파일 | 수정 내용 |
|-----|------|----------|
| P2-1 | `core/dependencies.py` (신규) | `get_user_key` 공통 모듈 |
| P2-2 | `routers/books.py` | print문 → logger 교체 |
| P2-4 | `.env.example` | 보안 경고 추가 |
| P2-5 | `mobile/assets/images/.gitkeep` | 폴더 유지 파일 |
| P2-7 | `tests/conftest.py` | credits mock 추가 |

#### P3 Improvements (6개) ✅
| 이슈 | 파일 | 수정 내용 |
|-----|------|----------|
| P3-1 | `core/exceptions.py` (신규) | 표준화된 에러 응답 |
| P3-2 | `models/db.py` | Page에 UniqueConstraint 추가 |
| P3-3 | `core/config.py` | `image_max_retries` 설정 추가 |
| P3-4 | `services/tts.py`, `core/config.py` | TTS provider 설정화 |
| P3-6 | `mobile/lib/core/api_error.dart` (신규) | 모바일 에러 핸들링 |

### 신규 생성된 파일 (8개)
```
apps/api/src/core/rate_limit.py      # Redis Rate Limiter
apps/api/src/core/dependencies.py    # 공통 의존성
apps/api/src/core/exceptions.py      # 표준 에러 응답
apps/api/src/services/tasks.py       # Celery task 래퍼
apps/mobile/lib/core/env_config.dart # 환경 설정
apps/mobile/lib/core/api_error.dart  # API 에러 핸들링
apps/mobile/assets/images/.gitkeep   # assets 폴더 유지
apps/mobile/pubspec.lock             # 의존성 잠금
```

### 다음 단계
1. **CI/CD 확인**: GitHub Actions 빌드/테스트 결과 확인
2. **서버 설정** (미완료 시):
   - GitHub Secrets 설정: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_KEY`
   - 서버에 `.env` 파일 생성
3. **프로덕션 배포**: CI/CD 통과 시 자동 배포

### GitHub Actions URL
```
https://github.com/sterlingstarai-ai/ai-story-book/actions
```
