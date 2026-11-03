# Provider observations and bounded illustration repairs

Updated 2026-09-07. These controls establish behavior under simulated provider responses; they do not establish current paid API balance, live illustration acceptance or launch approval.

## Availability and usage

`/health/live` only reports process liveness. `/health/ready` checks infrastructure/configuration and adds `services.provider_runtime`:

- `unverified`: one or more configured provider/credential/model/kind combinations have no recent response observation. Key presence alone does not verify usable credit or permissions. `provider_access_observed` is false and production readiness returns HTTP 503. Deterministic `TESTING=true` checks remain exempt from this first-observation requirement.
- A malformed 2xx text or image result also changes that combination to `unverified` rather than refreshing an earlier `healthy` result. A shared invalid marker protects this result if its follow-up Lua update fails; validated recovery clears the marker atomically. A concurrent credential/quota rejection remains `unavailable` instead of being weakened by malformed output.
- `healthy`: recent successful responses were observed for all required combinations. This is an observation, not a future credit guarantee or a claim that a whole book passed quality review.
- `unavailable`: a recent permanent quota/billing or credentials rejection was observed. Readiness returns HTTP 503. New generation requests are rejected before credit reservation; existing reading remains available.

Observations are shared between the API and workers through Redis, keyed by a credential/configuration hash. They expire after `PROVIDER_OBSERVATION_TTL_SECONDS` (default 86,400 seconds). Expiry or credential rotation returns to **unverified**, never healthy. Changing billing does not magically clear an observation; an explicit successful probe clears the affected combination. Health GET requests never invoke paid models.

For text and image adapters, a 2xx response alone does not create a healthy observation: text must be syntactically valid JSON output, and an image must contain bounded, structurally verifiable PNG/JPEG/WebP bytes. This does not establish application-schema validity, visual/story quality, or a whole-book success. If a worker cannot publish even the invalid marker to Redis while other workers can still read old Redis values, cross-process invalidation is not guaranteed. Existing ordering races between concurrent valid successes and permanent failures are not solved by the invalid marker.

OpenAI `insufficient_quota`, `credit_balance_exhausted`, organization/project enforced spend limits and usage limits fail without automatic retries. Temporary request/token 429 limits retain the transient retry policy. This distinction follows [OpenAI's official 429 guidance](https://help.openai.com/en/articles/5955604-troubleshooting-api-rate-limits-and-429-errors) and [usage/spend-limit guidance](https://help.openai.com/en/articles/6614457-why-am-i-getting-an-error-message-stating-that-i-ve-reached-my-usage-limi).

Run from `apps/api`:

```bash
./venv/bin/python scripts/provider_preflight.py --check-only
# Explicit operator opt-in: generic text and one generic illustration incur API usage.
./venv/bin/python scripts/provider_preflight.py --allow-billable-requests
```

The live probe sends no child photograph or story, does not add credit or change billing, and removes its generated test asset. It stops before image generation if a required text request fails. A successful text-only probe does not verify the image endpoint. The probe must run against the API/worker's exact provider configuration and Redis instance.

Before promoting a candidate deployment, run the explicit billable probe in that candidate image/environment with its configured Redis and storage, then require `/health/ready` HTTP 200. The probe runs directly and does not depend on an already-healthy HTTP server. It is an operator action, never part of recurring health polling. After a top-up or credential/model change, repeat this explicit probe if readiness is unavailable or unverified. The unverified state still allows a deliberately invoked private generation to establish observations; a known quota or authentication failure blocks new generation until a successful provider response or observation expiry. Expiry alone leaves production readiness at 503.

Adapters emit numeric `AI provider request usage` events, including model, request kind, HTTP status, token counts when provided, and an optional reference cost. Book generation emits a `Generation provider usage` aggregate even if a later pipeline step fails. Timeouts/cancellation remain incomplete attempts, not zero-cost requests. Prompts, provider response bodies, image URLs, user keys and API keys are excluded.

`PROVIDER_USAGE_PRICES_JSON` is an optional per-model mapping. Each model can have `input_usd_per_million` and `output_usd_per_million`, or an approximate `image_request_usd`. Empty/missing rates produce a null estimate, not a zero-cost claim. Image flat rates are approximate and cannot replace a provider invoice or multimodal token billing reconciliation. Update rates explicitly when changing providers/models/quality; test rates are not production pricing.

## Repairs

Clear action contradictions require a new scene composition. These repairs use the approved character reference and a cover that passed review; they do not use the rejected page as a pose/composition anchor. Text-removal-only repairs can still preserve the otherwise valid page composition. No untrusted reviewer prose becomes executable repair instructions.

Twelve body pages plus a cover share a hard limit of 16 image requests: 13 initial assets and up to three repair/transient-retry requests. Shorter books retain the existing two-request repair allowance. Each repair attempt consumes the allowance, even when it repairs the same page a second time. If two pages fail initially and only one still fails on recheck, the remaining third request may repair that page. A third attempt is unavailable if transient retries already spent the shared allowance.

Every repair round reserves time for a mandatory whole-book recheck and commit. The operation's original deadline never resets. Unsafe/uncertain findings, scope violations, insufficient remaining time/budget, or unresolved clear defects still block publication and preserve the existing refund/purge behavior. Additional rounds are not permission to publish a known defective page or weaken the human-level quality standard.
