# API PACKAGE

FastAPI + Celery backend. Run package commands from `apps/api` so imports, Alembic,
and prompt paths resolve consistently; settings deliberately load `apps/api/.env`.

## MAP

```text
src/main.py             # composition root, middleware, health, router registration
src/worker.py           # Celery application and worker policy
src/core/               # settings, DB sessions, dependencies, consent, errors, limits
src/models/db.py        # all SQLAlchemy persistence models
src/models/dto.py       # Pydantic request/result and OpenAPI types
src/routers/            # feature-grouped HTTP boundary
src/services/           # workflows, background tasks, provider/storage adapters
src/prompts/            # Jinja2 LLM prompt templates
src/qa/                 # golden-generation validation
alembic/                # migration environment and revisions
tests/                  # async API, service, security, contract, and QA tests
scripts/                # live HTTP journey and golden-prompt CLIs
```

## HIGH-BLAST-RADIUS FILES

- `src/main.py`: middleware order, exception envelopes, lifespan cleanup, readiness,
  CORS, rate-limit attachment, and every router prefix.
- `src/routers/books.py`: ownership, profile scope, consent, credits, idempotency,
  guardrails, job creation, and background/Celery dispatch.
- `src/services/orchestrator.py`: canonical persisted generation pipeline; progress,
  retries, moderation, learning assets, degraded-image behavior, and packaging.
- `src/models/{dto,db}.py`: shared API and persistence contracts; changes fan out to
  routers, services, tests, migrations, Flutter parsing, and committed OpenAPI.
- `src/core/{config,database,exceptions}.py`: import-time runtime configuration,
  session construction, and stable error responses.

## BOUNDARY RULES

- Set environment variables before importing `src.main` or DB modules. `settings`
  and engines are created at import time; `DATABASE_URL` is mandatory.
- Keep HTTP parsing/authorization in routers and provider calls/workflows in services.
  Existing large routers are pragmatic seams, not templates for further growth.
- Use `AsyncSession` on request paths. Preserve explicit commit/rollback, credit refund,
  ownership, profile scope, and consent behavior across failure paths.
- New protected `/v1` routers must be imported and registered in `src/main.py` with
  `Depends(check_rate_limit)`. Public share-token routes are the deliberate exception.
- Use `APIError` subclasses for HTTP policy failures and `StoryBookError` subclasses
  for generation/provider failures. Preserve machine-readable codes and request IDs.
- Use `structlog`; redact full user keys, share tokens, provider secrets, and child data.
- Provider implementations must retain deterministic `mock` paths. Do not make the
  ordinary suite require live LLM, image, speech, store, POD, Redis, or S3 credentials.

## SCHEMA AND CONTRACT CHANGES

- Persistence change: update `src/models/db.py`, add an Alembic revision, and ensure
  a new model is imported in `alembic/env.py` so metadata sees it.
- Route/DTO change: regenerate `packages/shared/schema/openapi.json` from repository
  root; never patch the snapshot directly.
- Treat `tests/test_openapi_contract.py` as a cross-package gate: it compares FastAPI,
  the committed snapshot, and calls/required fields used by the Flutter client.
- Prompt or generation-shape changes require golden structural checks; live content
  quality remains a separate credentialed/manual evaluation.

## FOCUSED COMMANDS

```bash
cd apps/api
python -m pytest tests/test_openapi_contract.py -q
python -m pytest tests/test_orchestrator.py tests/test_services.py -q
python -m pytest tests/test_security.py tests/test_payment_security.py -q
python -m pytest tests -q
alembic upgrade head
alembic revision --autogenerate -m "description"
uvicorn src.main:app --reload
celery -A src.worker worker --loglevel=info
python scripts/golden_prompts_harness.py
```

Pytest uses SQLite with foreign keys enabled, mock providers, and an in-process ASGI
client. `TESTING=true` skips generation dispatch; use the repository live-E2E script
when validating the real Uvicorn/background pipeline.
