# API TESTS

Scope: pytest guidance for `apps/api/tests`. Inherit repository and API rules; this file only describes test-specific behavior.

## HARNESS

- Run from `apps/api` so `src.*` imports and relative SQLite paths resolve consistently.
- `pytest.ini` sets `asyncio_default_fixture_loop_scope = function`.
- Async tests use `pytest.mark.asyncio`; there are no slow/integration/E2E marker partitions.
- `conftest.py` sets test environment variables before importing `src.main.app`.
- `DATABASE_URL` is forcibly replaced with `sqlite+aiosqlite:///./test.db`.
- LLM and image providers are forced to `mock`; S3 credentials are inert test values.
- `db_session` creates and drops the complete schema for every test.
- SQLite foreign keys are explicitly enabled to catch ownership and cascade defects.
- Do not run this suite concurrently: fixtures share `test.db`, and `pytest-xdist` is not installed.

## FIXTURES

- `client`: HTTPX `ASGITransport` against the in-process FastAPI app; no socket or Uvicorn.
- `client` overrides `get_db` with the function-scoped SQLite session.
- `client` temporarily replaces credit allowance/consumption methods; tests of real credit behavior should use `db_session` directly.
- Always restore dependency overrides, monkeypatches, and service method replacements.
- `user_key` and `headers` provide the standard UUID-shaped identity boundary.
- `valid_book_spec` and `valid_character` are canonical request payloads; copy before mutation.
- Story, character-sheet, image-prompt, and moderation fixtures are deterministic provider outputs.
- `factories.make_book_rows()` builds the required `Job -> Book` chain for activity rows under enforced FKs.
- Prefer factories over incomplete ORM rows that only pass when FK checks are disabled.

## TEST BOUNDARIES

- Files named `test_integration.py` and `test_e2e.py` still use the in-process ASGI client.
- These tests validate routing, DTOs, middleware, persistence, and mocked collaborator behavior.
- Background generation may stop at `queued`/`running` when `TESTING=true`.
- `test_golden_prompts.py` drives the mock generation pipeline and asserts structural quality, not semantic quality.
- `../../scripts/run_live_e2e.sh` starts real Uvicorn and reaches generation completion.
- Live E2E still uses SQLite, mock LLM/image/TTS, `USE_CELERY=false`, and no real object store.
- No pytest path proves Celery worker execution, Postgres-specific SQL, Redis behavior, or live providers.
- CI migrates Postgres separately, but `conftest.py` still redirects the pytest suite to SQLite.
- Add dialect-sensitive regressions to a dedicated Postgres integration harness; do not label SQLite evidence as Postgres coverage.

## PLACEMENT

- Endpoint and error-envelope behavior: focused router/contract test.
- Service algorithms, retries, and provider parsing: focused service test with the narrowest fake.
- Commit/rollback and unique-key behavior: transaction-focused test with failure injection.
- Ownership, consent, payment, and share-token changes require negative-path regression coverage.
- DTO or route changes require `test_openapi_contract.py`.
- Prompt/pipeline changes require structural golden tests; live semantic review remains separate.

## COMMANDS

```bash
# Full local API suite
./venv/bin/python -m pytest tests -q

# Focused file or test
./venv/bin/python -m pytest tests/test_orchestrator.py -q
./venv/bin/python -m pytest tests/test_orchestrator.py::TestRunStep -q

# Collection without fixture execution
./venv/bin/python -m pytest tests --collect-only -q -p no:cacheprovider

# CI-equivalent line coverage
./venv/bin/python -m pytest tests -v --cov=src --cov-report=xml
./venv/bin/python -m coverage report --fail-under=40

# Cross-client contract
./venv/bin/python -m pytest tests/test_openapi_contract.py -q
```

## COVERAGE CAVEATS

- Coverage measures `src` line execution only; branch coverage is not configured.
- Standalone live E2E runs after the CI coverage command and does not contribute to `coverage.xml`.
- Generated reports committed or left in the workspace may predate current source; regenerate before citing percentages.
- A green coverage floor is not evidence for Postgres, Celery, live AI, store receipt, or network-service correctness.
