# Architecture Notes

**Date**: 2026-01-21
**Purpose**: 운영자/개발자가 시스템을 이해하고 유지보수할 수 있도록

---

## 1. Provider Abstraction

### 1.1 Current Provider Structure

```
src/services/
├── llm.py          # LLMProvider (OpenAI, Anthropic)
├── image.py        # ImageProvider (Replicate, FAL)
├── tts.py          # TTSProvider (Google, ElevenLabs, Mock)
└── storage.py      # StorageProvider (S3, Minio)
```

### 1.2 Provider Interface Pattern

All providers follow a common pattern:

```python
class BaseProvider:
    """Base interface for all external API providers"""

    async def health_check(self) -> bool:
        """Check if provider is available"""
        raise NotImplementedError

    async def call_with_retry(self, fn, max_retries=3, backoff=[2, 5, 12]):
        """Execute with exponential backoff retry"""
        for attempt in range(max_retries):
            try:
                return await fn()
            except TransientError as e:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(backoff[min(attempt, len(backoff)-1)])
```

### 1.3 Adding New Providers

To add a new provider (e.g., new image API):

1. Create provider class in `src/services/`
2. Implement required interface methods
3. Add to `settings` in `config.py`
4. Update selection logic based on `PROVIDER` env var

```python
# Example: Adding new image provider
class NewImageProvider:
    async def generate_image(self, prompt: str, **kwargs) -> bytes:
        # Implementation
        pass

# In config.py
image_provider: str = "replicate"  # replicate, fal, new_provider

# In image.py
def get_provider():
    if settings.image_provider == "new_provider":
        return NewImageProvider()
    # ...
```

---

## 2. Configuration Hierarchy

### 2.1 Build-time vs Runtime Config

| Config Type | When Applied | Examples |
|-------------|--------------|----------|
| Build-time | Docker build | Python version, dependencies |
| Deploy-time | Container start | DATABASE_URL, API keys |
| Runtime | Request-time | Rate limits (can be changed via Redis) |

### 2.2 Configuration Sources

```
Priority (highest to lowest):
1. Environment variables
2. .env file
3. Default values in config.py
```

### 2.3 Required vs Optional Settings

| Setting | Required | Default | Description |
|---------|----------|---------|-------------|
| `DATABASE_URL` | Yes | - | PostgreSQL connection |
| `REDIS_URL` | Yes | localhost:6379 | Redis for rate limiting |
| `LLM_API_KEY` | Production | - | OpenAI/Anthropic key |
| `IMAGE_API_KEY` | Production | - | Replicate/FAL key |
| `S3_ACCESS_KEY` | Production | minioadmin | S3 credentials |
| `DEBUG` | No | true | Debug mode |
| `CORS_ORIGINS` | No | * | Allowed origins |

---

## 3. Logging Architecture

### 3.1 Structured Logging

All logs use `structlog` with JSON format:

```python
import structlog
logger = structlog.get_logger()

# Good: Structured with context
logger.info("Book generation started",
    job_id=job_id,
    user_key=user_key[:8] + "...",  # Masked
    topic=spec.topic
)

# Bad: Unstructured
logger.info(f"Started job {job_id} for user {user_key}")
```

### 3.2 Log Levels

| Level | Usage |
|-------|-------|
| DEBUG | Detailed debugging (disabled in production) |
| INFO | Normal operations, milestones |
| WARNING | Recoverable issues, retries |
| ERROR | Failures requiring attention |

### 3.3 Job-Centric Logging

All logs related to a job should include `job_id`:

```python
logger.info("Step completed",
    job_id=job_id,
    step="story_generation",
    duration_ms=1234,
    attempt=1
)
```

### 3.4 Sensitive Data Handling

```python
# ALWAYS mask sensitive data
user_key_masked = user_key[:8] + "..." if user_key else None
logger.info("Request", user_key=user_key_masked)

# NEVER log full API keys, tokens, or passwords
```

---

## 4. Error Code System

### 4.1 Error Categories

| Category | Code Range | Example |
|----------|------------|---------|
| Safety | SAFETY_* | SAFETY_INPUT, SAFETY_OUTPUT |
| LLM | LLM_* | LLM_TIMEOUT, LLM_JSON_INVALID |
| Image | IMAGE_* | IMAGE_TIMEOUT, IMAGE_FAILED |
| Storage | STORAGE_* | STORAGE_UPLOAD_FAILED |
| Database | DB_* | DB_WRITE_FAILED |
| System | SYS_* | SYS_RATE_LIMIT, SYS_OVERLOADED |

### 4.2 User-Facing vs Operator Errors

| Error Code | User Message | Operator Action |
|------------|--------------|-----------------|
| SAFETY_INPUT | "부적절한 내용이 포함되어 있습니다" | Log and monitor |
| LLM_TIMEOUT | "잠시 후 다시 시도해주세요" | Check API status |
| IMAGE_FAILED | "이미지 생성에 실패했습니다" | Check image API |
| DB_WRITE_FAILED | "서버 오류가 발생했습니다" | Immediate alert |

### 4.3 Error Response Format

```json
{
    "error": {
        "code": "LLM_TIMEOUT",
        "message": "스토리 생성에 시간이 초과되었습니다",
        "details": "잠시 후 다시 시도해주세요",
        "retry_after": 60
    }
}
```

---

## 5. Request Flow

### 5.1 Book Creation Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  1. Client Request                                               │
│     POST /v1/books                                               │
│     Headers: X-User-Key, X-Idempotency-Key                      │
│                                                                  │
│  2. Middleware Chain                                             │
│     SecurityHeaders → CORS → RateLimit → Auth                   │
│                                                                  │
│  3. Route Handler (books.py)                                     │
│     - check_guardrails()  ← Daily limit, system load            │
│     - has_credits()       ← Credit check                         │
│     - idempotency check   ← Duplicate prevention                 │
│     - create Job          ← DB insert                            │
│     - use_credit()        ← Credit deduction                     │
│     - start background    ← Celery or asyncio                    │
│                                                                  │
│  4. Background Task (orchestrator.py)                            │
│     A. normalize_input()                                         │
│     B. moderate_input()   → LLM call                            │
│     C. generate_story()   → LLM call                            │
│     D. character_sheet()  → LLM call                            │
│     E. image_prompts()    → LLM call                            │
│     F. generate_images()  → Image API (parallel)                │
│     G. moderate_output()                                         │
│     H. package_book()     → DB + S3                             │
│                                                                  │
│  5. Job Complete                                                 │
│     status: done                                                 │
│     Client polls GET /v1/books/{job_id}                         │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Timeout Budget

```
Total SLA: 600 seconds (10 minutes)

Step                    Timeout   Retries   Max Total
─────────────────────────────────────────────────────
Input moderation        10s       0         10s
Story generation        30s       2         90s
Character sheet         20s       1         40s
Image prompts           30s       1         60s
Image generation (×9)   90s       3         810s (parallel: ~270s)
Output moderation       10s       0         10s
Packaging               30s       1         60s
─────────────────────────────────────────────────────
                                 Budget:    ~540s
```

---

## 6. Database Patterns

### 6.1 Async Session Management

```python
# Correct: Using dependency injection
@router.get("/books/{book_id}")
async def get_book(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Book).where(Book.id == book_id))
    return result.scalar_one_or_none()

# Correct: Manual session (background tasks)
async with AsyncSessionLocal() as session:
    # Do work
    await session.commit()
```

### 6.2 Transaction Boundaries

```python
# Good: Atomic operation
async with AsyncSessionLocal() as session:
    job = Job(...)
    session.add(job)
    # All-or-nothing commit
    await session.commit()

# Bad: Multiple separate commits
job = Job(...)
await db.add(job)
await db.commit()  # Job created
credit = await deduct_credit()
await db.commit()  # What if this fails?
```

### 6.3 Query Patterns

```python
# Eager loading for related data
result = await db.execute(
    select(Book)
    .options(selectinload(Book.pages))
    .where(Book.id == book_id)
)

# Pagination
result = await db.execute(
    select(Book)
    .where(Book.user_key == user_key)
    .order_by(Book.created_at.desc())
    .offset(skip)
    .limit(limit)
)
```

---

## 7. Deployment Architecture

### 7.1 Container Structure

```
┌─────────────────────────────────────────────────────────────────┐
│                         Nginx (Reverse Proxy)                    │
│                         Rate limiting, SSL                       │
└────────────────────────────────┬────────────────────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│   API Server    │   │   API Server    │   │   API Server    │
│   (FastAPI)     │   │   (FastAPI)     │   │   (FastAPI)     │
└────────┬────────┘   └────────┬────────┘   └────────┬────────┘
         │                     │                     │
         └─────────────────────┼─────────────────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         │                     │                     │
         ▼                     ▼                     ▼
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│   PostgreSQL    │   │     Redis       │   │      S3         │
│   (Primary)     │   │   (Cache/Queue) │   │   (Storage)     │
└─────────────────┘   └─────────────────┘   └─────────────────┘
```

### 7.2 Scaling Guidelines

| Component | Scale Trigger | Scale Action |
|-----------|---------------|--------------|
| API Server | CPU > 70% | Add replica |
| Worker | Queue depth > 50 | Add replica |
| PostgreSQL | Connections > 80% | Upgrade instance |
| Redis | Memory > 80% | Upgrade instance |

---

## 8. Monitoring Points

### 8.1 Health Endpoints

| Endpoint | Purpose | Interval |
|----------|---------|----------|
| `/health` | Basic liveness | 10s |
| `/health/detailed` | Full status | 60s |

### 8.2 Key Metrics

| Metric | Type | Alert Threshold |
|--------|------|-----------------|
| `http_requests_total` | Counter | - |
| `http_request_duration` | Histogram | p99 > 5s |
| `jobs_total` | Counter | - |
| `jobs_failed_total` | Counter | rate > 5% |
| `jobs_stuck_total` | Gauge | > 0 |
| `external_api_errors` | Counter | rate > 10% |
| `db_connections_active` | Gauge | > 80% of pool |

### 8.3 Log Aggregation

Recommended stack:
- Logs: CloudWatch / ELK / Loki
- Metrics: Prometheus + Grafana
- Tracing: Jaeger / X-Ray (future)

---

*Generated: 2026-01-21*
