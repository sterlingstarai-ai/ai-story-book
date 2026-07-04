# SERVICE LAYER

Applies to `apps/api/src/services/**`. Parent instructions remain authoritative.

## RESPONSIBILITY MAP

- `orchestrator.py`: canonical book pipeline, persisted job progress, packaging.
- `llm.py`: prompts, provider dispatch, typed LLM output parsing.
- `image.py`: image providers, reference-image handling, durable storage.
- `storage.py`: S3-compatible persistence and URL/download safeguards.
- `tts.py` / `stt.py`: speech provider boundaries.
- `tasks.py`: JSON-safe Celery bridge into async services.
- `credits.py` / `iap_verifier.py`: money-like integrity; preserve atomicity.
- `job_monitor.py` / `periodic_credits.py`: process-lifecycle background services.

## ORCHESTRATOR CONTRACT

- Preserve pipeline order: normalize, input moderation, story, character sheet, image prompts, images, output moderation, learning assets, package.
- Route observable stages through `run_step`; persist localized step text, monotonic progress, timeout, retries, and structured completion logs.
- Use named progress constants. Keep `Job.status` within `queued | running | failed | done` and progress within `0..100`.
- Persist drafts and image prompts before downstream generation that may fail.
- Keep `orchestrator.py` coordinating. Extract new provider, policy, formatting,
  or persistence behavior instead of expanding this already-large module.
- Queue payloads are JSON-safe `model_dump()` values; reconstruct Pydantic DTOs before entering service logic.

## ADAPTER BOUNDARIES

- Provider selection comes from `settings`; keep dispatch inside its adapter.
- Orchestrator calls thin adapter functions, not provider HTTP APIs directly.
- Convert provider failures to canonical `StoryBookError` / `ErrorCode` types.
- Set explicit HTTP/provider timeouts. Never introduce unbounded network waits.
- Preserve patch seams such as orchestrator-level `generate_image`; tests mock adapters at the service boundary, not internal HTTP-client implementation.
- Store generated media durably before returning URLs; temporary provider URLs are not book assets.

## RETRIES AND DEGRADATION

- Retry only timeouts, rate limits, and declared transient/provider failures.
- Use configured retry counts and `get_backoff`; do not add tight retry loops.
- Non-transient safety, validation, ownership, and database errors fail fast.
- Optional learning assets may degrade to `None`; do not fail a completed story.
- Per-page image/audio work may partially degrade, but must log failed pages and
  preserve `generation_warnings` / page `asset_status`.
- Keep the image failure threshold and placeholder detection explicit. Do not
  silently convert total provider failure into a successful book.
- Catch-all handling belongs at job/task boundaries, where it must log and
  persist failure; inner helpers should propagate typed failures.

## DATABASE AND CONCURRENCY

- Background work opens a fresh `AsyncSessionLocal`; never retain a request
  session or ORM object across a background/Celery boundary.
- Keep transactions short. Do not hold sessions open during long provider calls
  unless the operation requires it.
- Commit status/artifact transitions deliberately; rollback write failures
  before translating them.
- Image fan-out remains bounded by `settings.image_max_concurrent`.
- Celery tasks keep JSON serialization, late acknowledgement, worker-loss
  rejection, and hard/soft time limits.

## SAFETY AND PRIVACY

- Input and output moderation are mandatory pipeline gates.
- Character/photo lookup is always scoped by `user_key`; deterministic ID order
  selects the primary face reference.
- Apply storage SSRF guards before fetching reference or external image URLs.
- Never log API keys, raw provider bodies, prompts containing child data,
  reference-image bytes/URLs, full user keys, or voice samples.
- Optional face-reference lookup may fail closed to no reference; it must never fall back to another user's character or image.

## VERIFICATION

- Orchestrator/retry changes: run `python -m pytest tests/test_orchestrator.py tests/test_chaos.py -q` from `apps/api`.
- Learning quality changes: run `python -m pytest tests/test_learning_quality.py -q`.
- Image/reference changes: add focused image persistence/Gemini tests.
- Task/Celery changes need unit coverage for DTO reconstruction and persisted
  failure state; ordinary pytest does not exercise a live broker.
- Finish with `ruff check src/services tests/` and the focused pytest set.
