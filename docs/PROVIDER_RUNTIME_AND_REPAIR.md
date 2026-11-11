# Provider observations and bounded illustration repairs

Updated 2026-09-07. These controls establish behavior under simulated provider responses; they do not establish current paid API balance, live illustration acceptance or launch approval.

## Availability and usage

`/health/live` only reports process liveness. `/health/ready` checks infrastructure/configuration and adds `services.provider_runtime`:

- `unverified`: one or more configured provider/credential/model/kind combinations have no recent response observation. Key presence alone does not verify usable credit or permissions. `provider_access_observed` is false and production readiness returns HTTP 503. Deterministic `TESTING=true` checks remain exempt from this first-observation requirement.
- A malformed 2xx text or image result changes that combination to `unverified` rather than refreshing an earlier `healthy` result. Redis records an invalid marker separately from the last definitive outcome. A credential or quota rejection remains `unavailable` until an eligible recovery. Validated recovery clears the marker atomically.
- `healthy`: recent successful responses were observed for all required combinations. This is an observation, not a future credit guarantee or a claim that a whole book passed quality review.
- `unavailable`: a recent permanent quota/billing or credentials rejection was observed. Readiness returns HTTP 503. New generation requests are rejected before credit reservation; existing reading remains available.

Observations are shared between the API and workers through Redis, keyed by a credential/configuration hash. They expire after `PROVIDER_OBSERVATION_TTL_SECONDS` (default 86,400 seconds). Expiry or credential rotation returns to **unverified**, never healthy. Changing billing does not magically clear an observation; an explicit successful probe clears the affected combination. Health GET requests never invoke paid models.

The API reads all required observation values and invalid markers in one Redis transaction. A wrong-type reply leaves the affected observation unverified, while another provider's known credentials or quota failure can still determine the overall status. A failed transaction leaves the observations unverified.

For text and image adapters, a 2xx response alone does not create a healthy observation: text must be syntactically valid JSON output, and an image must contain bounded, structurally verifiable PNG/JPEG/WebP bytes. This does not establish application-schema validity, visual/story quality, or a whole-book success. The atomic Redis update orders definitive outcomes by request start, and a success older than a recorded invalid marker cannot clear it. Keep API and worker clocks synchronized and roll them out together. An observation written by an earlier release uses its observation time as the ordering baseline until replaced.

If the atomic update fails, the worker attempts to preserve a failure using the legacy write path. That fallback can conservatively report a failure out of order. If it cannot write to Redis at all while other workers can still read old data, cross-process invalidation is not guaranteed.

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

The job summary reports wall time in `duration_seconds` and elapsed time by stage in `stage_seconds`. Repeated runs of a stage include retry delays and accumulate under the same name. Learning asset work may overlap illustration verification, so use the job duration for the total.

OpenAI JSON requests within a book share up to two connections. Each request retains its own credentials and timeout. The client discards cookies and closes the pool when generation ends or is cancelled. [HTTPX async client pooling](https://www.python-httpx.org/async/)

`PROVIDER_USAGE_PRICES_JSON` is an optional per-model mapping. Each model can have `input_usd_per_million` and `output_usd_per_million`, or an approximate `image_request_usd`. Empty/missing rates produce a null estimate, not a zero-cost claim. Image flat rates are approximate and cannot replace a provider invoice or multimodal token billing reconciliation. Update rates explicitly when changing providers/models/quality; test rates are not production pricing.

### Scheduled pilot observation refresh

The refresh timer reads the pinned API container's observations every 30 minutes. If narration alone needs verification, both OpenAI observations have at least 19 hours left, and the ledger permits a follow-up claim after 18 hours, the scheduled runner probes narration alone. Otherwise, an available claim refreshes text, image and narration together. The extra hour covers the timer interval and scheduling delays. Explicit `--refresh-now` still verifies all enabled providers covered by the pilot runner.

The timer starts five minutes after boot and checks every 30 minutes. The refresh service candidate waits for Docker and backup recovery, then checks that Docker is active and the loaded backup recovery service exited successfully. A failed check records failure on the refresh service before running any provider probe. The next scheduled attempt can still run after recovery. Provider calls require an eligible claim in the existing persistent ledger. [systemd timer semantics](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)

When Gemini cannot acquire workload credentials, the adapter invalidates an earlier successful narration observation as `credentials_unavailable` before reserving a synthesis request. A Gemini credential rejection can be rechecked under the existing ledger because workload credentials refresh. Rejected OpenAI text or image keys still require operator intervention. A successful, validated narration response clears the invalid marker.

The existing private SQLite ledger records the claim before the first provider request. It limits claims to one per 18 hours and 41 in 31 days. Install the refresh runner and budget module together and preserve the ledger across upgrades and rollbacks. `PROBE_REQUIRED_BUDGET_DEFERRED` means a required observation is still missing or unhealthy and the next claim is unavailable. `PROBE_FAILED` requires checking the pinned container and the private provider observations, especially credentials rejection. Confirm recovery with `/health/ready` after successful verification. The scheduled runner and readiness GET are separate paths.

When switching narration providers, update the installed refresh runner and budget module before pointing the timer at the new API image. A Gemini-only runner rejects an API configured for `openai_realtime` before claiming a probe, so the remaining provider observations can all expire even while the containers stay up. Run the installed command without `--execute` against the pinned API and require `OBSERVATIONS_DUE` or `OBSERVATIONS_FRESH` before relying on the timer. This check makes no provider requests.

The observation subprocess has a 60-second bound: importing production modules on the small pilot VM exceeded the former 20-second limit even with healthy provider observations. This does not extend observation freshness or change paid request budgets. The service allows 600 seconds for Docker identity (20), two observation checks (120), text/image probe (300), narration probe (105), and 55 seconds of startup/cleanup. An observation check that exceeds its bound still fails; it never becomes a healthy result by timeout.

Keep the Redis data volume through an API or Redis container replacement. In the local restart rehearsal, a new API and Redis container using the same append-only volume retained fresh observations and credential rejection. An observation that expired while the containers were stopped still required re-verification. Check the volume binding and the pinned refresh status after the production reboot. [Local restart evidence](acceptance/2026-11-08-provider-readiness-cold-boot/result.json)

## Repairs

Clear action contradictions require a new scene composition. These repairs use the approved character reference and a cover that passed review; they do not use the rejected page as a pose/composition anchor. Text-removal-only repairs can still preserve the otherwise valid page composition. No untrusted reviewer prose becomes executable repair instructions.

Twelve body pages plus a cover share a hard limit of 16 image requests: 13 initial assets and up to three repair/transient-retry requests. Shorter books retain the existing two-request repair allowance. Each repair attempt consumes the allowance, even when it repairs the same page a second time. If two pages fail initially and only one still fails on recheck, the remaining third request may repair that page. A third attempt is unavailable if transient retries already spent the shared allowance.

Every repair round reserves time for a mandatory whole-book recheck and commit. The operation's original deadline never resets. Unsafe/uncertain findings, scope violations, insufficient remaining time/budget, or unresolved clear defects still block publication and preserve the existing refund/purge behavior. Additional rounds are not permission to publish a known defective page or weaken the human-level quality standard.
