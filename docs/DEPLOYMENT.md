# Deployment Guide

This document defines the production deployment contract after the P5 hardening sweep.

## Source of truth

Production is deployed from version-tagged container images.

Canonical path:
1. GitHub Actions builds `ghcr.io/<repo>/api:<sha>` and `ghcr.io/<repo>/worker:<sha>`
2. Production server pulls those images
3. Production compose brings services up
4. Readiness is verified via `/health/ready`

Local `docker build` is not the production source of truth.

## Required tools

- Docker Engine
- `docker compose` plugin or `docker-compose`
- Git
- curl

## Environment files

- Local API runtime: `apps/api/.env`
- Production compose runtime: `infra/.env`

Validate before deploy:

```bash
./scripts/check-env.sh --mode production --env-file infra/.env
./scripts/phase-gate.sh
./scripts/flutter-ui-preflight.sh
```

`phase-gate.sh` now includes a dedicated mobile UI preflight step for overlay layering, modal scroll safety, and release checklist surfacing.

## Production compose

File: `infra/docker-compose.prod.yml`

Important properties:
- `api` and `worker` use `image:`
- image defaults can be overridden with `API_IMAGE` and `WORKER_IMAGE`
- `IMAGE_TAG` is propagated through `scripts/deploy.sh --image-tag`

## TLS termination (H9 — required before any real traffic)

**Until this section is done, the edge serves plain HTTP and `X-User-Key` — the only
credential in the system — travels in clear text along with children's photos.** One
passive observer on the path is a full account takeover. This is a launch blocker.

`infra/nginx/nginx.conf` now terminates TLS: port 80 serves only the ACME challenge and
301-redirects everything else; port 443 serves the app with HSTS
(`max-age=63072000; includeSubDomains`). nginx will **refuse to start** without
certificates at `/etc/nginx/ssl/{fullchain.pem,privkey.pem}` — that is intentional
fail-closed behaviour, not a bug: it makes a plaintext production deploy impossible.

Owner steps (once per domain):

```bash
cd infra

# 1. Point the DNS A/AAAA record at this host FIRST (ACME HTTP-01 validates over :80).

# 2. Bring up nginx with a temporary self-signed pair so :80 can serve the challenge.
mkdir -p nginx/ssl
openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
  -keyout nginx/ssl/privkey.pem -out nginx/ssl/fullchain.pem \
  -subj "/CN=$DOMAIN"
docker compose -f docker-compose.prod.yml up -d nginx

# 3. Issue the real certificate (webroot challenge served by the :80 listener).
docker compose -f docker-compose.prod.yml run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  -d "$DOMAIN" --email "$OPS_EMAIL" --agree-tos --no-eff-email

# 4. Point nginx at the issued files and reload.
ln -sf /etc/letsencrypt/live/$DOMAIN/fullchain.pem nginx/ssl/fullchain.pem
ln -sf /etc/letsencrypt/live/$DOMAIN/privkey.pem   nginx/ssl/privkey.pem
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

Renewal is automatic: the `certbot` service retries `certbot renew` every 12h. Reload
nginx after renewal (cron on the host, or `docker compose exec nginx nginx -s reload`).

Verification (all three must hold):

```bash
curl -sSI  http://$DOMAIN/health  | head -1          # expect 301
curl -sSI https://$DOMAIN/health  | grep -i strict-  # expect Strict-Transport-Security
curl -sS  https://$DOMAIN/health/ready | jq .status  # expect healthy
```

## Cost guardrail (H4 — required before any real traffic)

`DAILY_GENERATION_BUDGET` is the **only** control that caps the LLM/image bill.
`X-User-Key` is a client-generated UUID, so every per-user control (rate limit, daily
20 books, free-plan monthly limit) is bypassed by rotating the key. The variable is now
wired into `.env.example` and `docker-compose.prod.yml`, but **it defaults to 0 = OFF**.

Pick the value from spend tolerance, not from traffic: one book costs roughly `$0.32`
(`~$0.48` with regeneration headroom). `budget = tolerable_daily_spend / cost_per_book`.

`/health/ready` reports `services.cost_budget: "disabled"` and the API logs an
`error`-level line on every readiness probe while it is unset. That is a warning, not a
block — deploying with it off is an explicit choice, and it is the wrong one for GA.

## Deploy script

Usage:

```bash
./scripts/deploy.sh [--env-file PATH] [--compose-file PATH] [--image-tag TAG] <command>
```

Common commands:

```bash
./scripts/deploy.sh --env-file infra/.env --image-tag <sha> deploy
./scripts/deploy.sh --env-file infra/.env status
./scripts/deploy.sh --env-file infra/.env logs
./scripts/deploy.sh --env-file infra/.env health
./scripts/deploy.sh --env-file infra/.env backup
```

`deploy` performs (M26 order — **migrate before up**):
1. env validation and compose detection
2. image selection from the provided tag
3. capture currently-running image tags (rollback target)
4. `docker compose pull`
5. Alembic migration — applied while the **old** stack is still serving, so the new
   schema is in place before new code runs (no compose-down, no full downtime)
6. rolling `docker compose up -d` (only changed containers recreate)
7. liveness/readiness checks; **on failure, auto-rollback** to the captured previous
   images and re-check. The deploy still exits non-zero (CI red) so the failure is visible.

**Migration discipline (required by the migrate-before-up order): expand-then-contract.**
Because old code briefly runs against the new schema, every Alembic revision MUST be
backward-compatible: add columns as nullable / with defaults, add tables/indexes additively.
Destructive changes (drop/rename column, tighten NOT NULL, remove table) are split into a
later release, after all running code no longer references the old shape. A revision that
breaks the old code will 500 the old stack during the migrate→up window.

`cleanup` prunes containers/images/networks only — it never prunes volumes, so the
`postgres-data`/`redis-data`/`minio-data` named volumes are safe.

## CI/CD expectations

Workflow: `.github/workflows/ci.yml`

Quality jobs:
- API lint/tests/coverage
- Flutter analyze/tests/coverage
- repository-root phase gate
- focused Flutter UI preflight inside the phase gate
- security scan

Protected build behavior:
- coverage thresholds are enforced
- analyzer warnings fail the job
- phase gate runs from the repository root
- deploy uses the exact commit SHA tag built by CI

Release gate hardening (2026-07-22, W6):
- **CVE policy**: CRITICAL findings are **release-blocking** (child-facing service). The
  repo `safety`/Trivy scans and the API+worker image scans exit non-zero on CRITICAL, so a
  vulnerable dependency or image fails CI. HIGH is surfaced (image SARIF → Security tab) but
  not blocking, to avoid transitive-HIGH noise. Narrow false positives with an explicit
  `safety check --ignore <ID>` rather than re-masking the whole step.
- **Images are scanned before publish**: build → scan (blocking) → push. A CRITICAL image is
  never pushed to `ghcr` `:latest`/`:sha`.
- **Deploy is serialized, never cancelled**: `build`/`deploy` jobs carry
  `cancel-in-progress: false`. Two rapid merges to `main` **queue** the second deploy behind
  the first instead of cancelling an in-flight deploy mid-sequence. Operational expectation
  (latest commit wins) holds, but deploys run one at a time.
- **Repo == image parity**: the deploy SSH script checks out the exact built commit
  (`git checkout --detach "$GITHUB_SHA"`), so compose/nginx/deploy.sh/smoke.sh on the server
  match the container image. After a deploy the server repo is a detached HEAD at
  `$GITHUB_SHA`; the next deploy re-fetches and checks out the new SHA.

## Post-deploy verification

Minimum checks:

```bash
./scripts/deploy.sh --env-file infra/.env health
./scripts/smoke.sh http://localhost
```

Health semantics:
- `/health/live`: process alive
- `/health/ready`: dependency readiness, returns `503` when degraded/unhealthy
- `/health`: compatibility endpoint for simple monitoring

## Rollback

Rollback is image-tag based.

```bash
./scripts/deploy.sh --env-file infra/.env --image-tag <previous-sha> deploy
```

If the image tag is known-good, rollback does not require a new build.

## Production safety rules

- Do not serve production traffic over plain HTTP (H9). TLS termination is configured
  in `infra/nginx/nginx.conf`; certificates are an owner step (see "TLS termination").
- Do not deploy with `DAILY_GENERATION_BUDGET=0` (H4). It is the only global cost cap.
- Do not rely on test ad units in release builds
- Do not allow silent share/IAP/POD fallback in production
- Do not allow silent TTS/STT mock fallback in production (H1). Audio ships
  **disabled by default** (`AUDIO_FEATURE_ENABLED=false`, G9). To enable audio,
  set `AUDIO_FEATURE_ENABLED=true` **and** a live `TTS_PROVIDER` (google|elevenlabs,
  with its key) and `STT_PROVIDER` (openai|google); otherwise `/health/ready`
  returns 503 with `tts_provider_not_live` / `stt_provider_not_live`.
- Missing release config must surface as either:
  - explicit feature disablement in the UI, or
  - deployment / verification failure

## Troubleshooting

### Readiness fails after deploy

Check:
- `docker compose ps`
- `docker compose logs api`
- `docker compose logs worker`
- DB credentials in `infra/.env`
- migrations via `./scripts/deploy.sh --env-file infra/.env migrate`

### Wrong image version is running

Check:
- `API_IMAGE` / `WORKER_IMAGE` overrides in `infra/.env`
- `--image-tag` value passed by CI
- pulled image digests on the host

### Smoke fails but containers are running

Check:
- nginx route to `/health/live` and `/health/ready`
- API dependency readiness (DB/Redis)
- external provider configuration unexpectedly required in strict mode
