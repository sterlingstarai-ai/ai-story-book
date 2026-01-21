# Repository Snapshot

**Date**: 2026-01-21
**Commit**: e3fdf3d (main)
**Branch**: chore/overnight-architecture-hardening-20260121

---

## Directory Structure

```
ai-story-book/
├── apps/
│   ├── api/                      # FastAPI Backend
│   │   ├── src/
│   │   │   ├── core/             # Config, DB, Errors, Rate Limit
│   │   │   │   ├── config.py     # Settings (env-based)
│   │   │   │   ├── database.py   # SQLAlchemy async engine
│   │   │   │   ├── errors.py     # ErrorCode, exceptions
│   │   │   │   ├── rate_limit.py # Redis sliding window
│   │   │   │   ├── dependencies.py # FastAPI dependencies
│   │   │   │   └── exceptions.py # API error handlers
│   │   │   ├── models/
│   │   │   │   ├── db.py         # SQLAlchemy models
│   │   │   │   └── dto.py        # Pydantic schemas
│   │   │   ├── routers/          # API endpoints
│   │   │   │   ├── books.py      # /v1/books/*
│   │   │   │   ├── characters.py # /v1/characters/*
│   │   │   │   ├── library.py    # /v1/library/*
│   │   │   │   ├── credits.py    # /v1/credits/*
│   │   │   │   └── streak.py     # /v1/streak/*
│   │   │   ├── services/         # Business logic
│   │   │   │   ├── orchestrator.py # Main pipeline (A-H steps)
│   │   │   │   ├── llm.py        # LLM calls (story, moderation)
│   │   │   │   ├── image.py      # Image generation
│   │   │   │   ├── storage.py    # S3/Minio upload
│   │   │   │   ├── pdf.py        # PDF export
│   │   │   │   ├── tts.py        # Text-to-speech
│   │   │   │   ├── credits.py    # Credit system
│   │   │   │   ├── streak.py     # Daily streak
│   │   │   │   └── tasks.py      # Celery tasks
│   │   │   ├── prompts/          # Jinja2 templates
│   │   │   ├── main.py           # FastAPI app
│   │   │   └── worker.py         # Celery worker
│   │   ├── tests/                # Pytest tests
│   │   ├── alembic/              # DB migrations
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   └── mobile/                   # Flutter App
│       ├── lib/
│       │   ├── core/             # Config, errors
│       │   ├── models/           # Data models
│       │   ├── providers/        # Riverpod providers
│       │   ├── screens/          # UI screens
│       │   ├── services/         # API client
│       │   ├── widgets/          # Common widgets
│       │   └── main.dart
│       ├── test/
│       └── pubspec.yaml
│
├── infra/
│   ├── docker-compose.yml        # Development
│   └── docker-compose.prod.yml   # Production
│
├── scripts/
│   ├── check-env.sh              # Environment validation
│   └── smoke.sh                  # Smoke tests
│
├── .github/workflows/
│   └── ci.yml                    # CI/CD pipeline
│
└── docs/                         # Documentation
```

---

## Service Flow Summary

### Book Generation Pipeline (Orchestrator)

```
┌─────────────────────────────────────────────────────────────────┐
│                     POST /v1/books                               │
│                          │                                       │
│         ┌────────────────▼────────────────┐                     │
│         │   1. Create Job (queued)        │                     │
│         │   2. Check idempotency          │                     │
│         │   3. Deduct credit              │                     │
│         │   4. Start background task      │                     │
│         └────────────────┬────────────────┘                     │
│                          │                                       │
│         ┌────────────────▼────────────────┐                     │
│         │   ORCHESTRATOR PIPELINE         │                     │
│         │                                  │                     │
│         │   A. Input Normalization (5%)   │                     │
│         │         │                        │                     │
│         │   B. Input Moderation (10%)     │ ◄─── LLM Call       │
│         │         │ (safety check)         │                     │
│         │         │                        │                     │
│         │   C. Story Generation (30%)     │ ◄─── LLM Call       │
│         │         │                        │                     │
│         │   D. Character Sheet (40%)      │ ◄─── LLM Call       │
│         │         │                        │                     │
│         │   E. Image Prompts (55%)        │ ◄─── LLM Call       │
│         │         │                        │                     │
│         │   F. Image Generation (55-95%)  │ ◄─── Image API      │
│         │         │ (cover + 8 pages)      │     (parallel x3)   │
│         │         │                        │                     │
│         │   G. Output Moderation (95%)    │                     │
│         │         │                        │                     │
│         │   H. Package & Save (100%)      │ ◄─── DB + S3        │
│         └────────────────┬────────────────┘                     │
│                          │                                       │
│         ┌────────────────▼────────────────┐                     │
│         │   Job Status: done/failed       │                     │
│         │   GET /v1/books/{job_id}        │                     │
│         └─────────────────────────────────┘                     │
└─────────────────────────────────────────────────────────────────┘
```

### Request Flow

```
Client ──▶ Nginx ──▶ FastAPI ──▶ Redis (rate limit)
                        │
                        ├──▶ PostgreSQL (jobs, books, pages)
                        │
                        ├──▶ Celery Worker (optional)
                        │         │
                        │         ├──▶ OpenAI API (LLM)
                        │         ├──▶ Replicate/FAL (Images)
                        │         └──▶ S3/Minio (Storage)
                        │
                        └──▶ Background Task (asyncio)
```

---

## External Dependencies

### 1. LLM Provider

| Setting | Default | Description |
|---------|---------|-------------|
| `LLM_PROVIDER` | `openai` | Provider (openai, anthropic) |
| `LLM_API_KEY` | - | API key |
| `LLM_MODEL` | `gpt-4o-mini` | Model name |
| `LLM_TIMEOUT` | `30s` | Per-call timeout |

**Usage Points**:
- Input moderation (1 call)
- Story generation (1 call)
- Character sheet (1 call)
- Image prompts (1 call)
- Text rewrite (optional, per regeneration)

**Cost Estimate**: ~$0.05/book

---

### 2. Image Provider

| Setting | Default | Description |
|---------|---------|-------------|
| `IMAGE_PROVIDER` | `replicate` | Provider (replicate, fal) |
| `IMAGE_API_KEY` | - | API key |
| `IMAGE_TIMEOUT` | `90s` | Per-image timeout |
| `IMAGE_MAX_CONCURRENT` | `3` | Parallel limit |
| `IMAGE_MAX_RETRIES` | `3` | Retry count |

**Usage Points**:
- Cover image (1)
- Page images (8 default)
- Regeneration (per request)

**Cost Estimate**: ~$0.27/book (9 images × $0.03)

---

### 3. Storage (S3/Minio)

| Setting | Default | Description |
|---------|---------|-------------|
| `S3_ENDPOINT` | `localhost:9000` | S3 endpoint |
| `S3_ACCESS_KEY` | - | Access key |
| `S3_SECRET_KEY` | - | Secret key |
| `S3_BUCKET` | `storybook` | Bucket name |

**Usage Points**:
- Image uploads (cover + pages)
- PDF exports
- Audio files (TTS)

---

### 4. Queue (Redis + Celery)

| Setting | Default | Description |
|---------|---------|-------------|
| `REDIS_URL` | `localhost:6379/0` | Rate limiting |
| `CELERY_BROKER_URL` | `localhost:6379/1` | Task queue |
| `USE_CELERY` | `false` | Use Celery vs asyncio |

**Queue Settings**:
- `task_time_limit`: 600s (10 min SLA)
- `task_soft_time_limit`: 540s
- `worker_prefetch_multiplier`: 1
- `task_acks_late`: true

---

### 5. Database (PostgreSQL)

| Setting | Default | Description |
|---------|---------|-------------|
| `DATABASE_URL` | - | Connection string |

**Tables**:
- `jobs` - Job tracking
- `books` - Completed books
- `pages` - Book pages
- `characters` - User characters
- `story_drafts` - Intermediate drafts
- `image_prompts` - Generated prompts
- `user_credits` - Credit balances
- `subscriptions` - User subscriptions
- `credit_transactions` - Transaction log
- `daily_streaks` - Reading streaks
- `daily_stories` - Daily featured stories
- `reading_logs` - Reading history
- `rate_limits` - Rate limit state

---

## Key Metrics (Current)

| Metric | Value |
|--------|-------|
| Python files | 35 |
| Dart files | 20 |
| Test files | 10 |
| API endpoints | ~25 |
| DB tables | 13 |
| External APIs | 3 (LLM, Image, TTS) |

---

## Known Limitations

1. **No circuit breaker** for external APIs
2. **No stuck job detection** (jobs can hang indefinitely)
3. **No cost cap** beyond rate limiting
4. **No image NSFW filtering**
5. **Weak authentication** (X-User-Key only)
6. **No distributed tracing**
7. **No health metrics** beyond /health endpoint

---

*Generated: 2026-01-21*
