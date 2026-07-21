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

`deploy` performs:
1. env validation and compose detection
2. image selection from the provided tag
3. `docker compose pull`
4. service restart
5. Alembic migration
6. liveness/readiness checks

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
