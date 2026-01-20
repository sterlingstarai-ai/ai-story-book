# AI Story Book

AI로 맞춤형 동화책을 생성하는 모바일 앱

## 핵심 기능

- **한국어 연령 최적화**: 3-5/5-7/7-9세 문체/어휘 자동 조정
- **캐릭터 일관성**: 캐릭터 시트 기반 일관된 이미지 생성
- **시리즈 지원**: 같은 캐릭터로 매일 새로운 이야기
- **페이지 편집**: 텍스트/이미지 개별 재생성

## 기술 스택

- **Frontend**: Flutter (iOS/Android)
- **Backend**: FastAPI + Celery + Redis
- **Database**: PostgreSQL
- **Storage**: S3/Minio
- **AI**: OpenAI/Anthropic (텍스트) + Replicate/FAL (이미지)

## 프로젝트 구조

```
ai-story-book/
├── apps/
│   ├── api/           # FastAPI 백엔드
│   └── mobile/        # Flutter 앱 (예정)
├── packages/
│   └── shared/        # 공유 스키마
├── infra/             # Docker Compose
└── docs/              # 문서
```

## 시작하기

### 1. 환경 설정

```bash
cd apps/api
cp .env.example .env
# .env 파일에서 API 키 설정
```

### 2. Docker 실행

```bash
cd infra
docker-compose up -d postgres redis minio
```

### 3. 데이터베이스 마이그레이션

```bash
cd apps/api
pip install -r requirements.txt
alembic upgrade head
```

### 4. API 서버 실행

```bash
uvicorn src.main:app --reload
```

### 5. API 문서 확인

http://localhost:8000/docs

## API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| POST | `/v1/books` | 책 생성 |
| GET | `/v1/books/{job_id}` | 상태 조회 |
| POST | `/v1/books/{job_id}/pages/{n}/regenerate` | 페이지 재생성 |
| POST | `/v1/characters` | 캐릭터 저장 |
| GET | `/v1/characters` | 캐릭터 목록 |
| GET | `/v1/library` | 내 서재 |

## 환경 변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 연결 | `postgresql://...` |
| `REDIS_URL` | Redis 연결 | `redis://localhost:6379/0` |
| `LLM_PROVIDER` | LLM 제공자 | `openai` |
| `LLM_API_KEY` | LLM API 키 | - |
| `IMAGE_PROVIDER` | 이미지 제공자 | `replicate` |
| `IMAGE_API_KEY` | 이미지 API 키 | - |

## 테스트

```bash
cd apps/api
pytest tests/ -v
```

## 개발 현황

- [x] API 스키마 설계
- [x] FastAPI 백엔드 구현
- [x] 오케스트레이터 파이프라인
- [x] LLM 서비스 연동
- [x] 이미지 생성 서비스
- [x] S3 스토리지 서비스
- [ ] Flutter 앱 개발
- [ ] 통합 테스트
- [ ] 배포

## 라이선스

MIT
