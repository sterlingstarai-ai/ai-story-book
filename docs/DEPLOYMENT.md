# Deployment Guide

> 현재 출시 상태와 비공개 미디어 전환 절차: [LAUNCH_STATUS.md](LAUNCH_STATUS.md). 로컬 API는 `apps/api/.env`, 운영 Compose는 `infra/.env`를 사용합니다.


This document defines the production deployment contract after the P5 hardening sweep.

모바일 정책 전문은 앱에 포함되며, 공개본은 `scripts/render_legal_documents.py`로 같은 JSON 원본에서 생성한다. `final-external-preflight.sh`는 원본의 검토 상태·시행일까지 확인한다. 검토본을 승인본으로 표시하거나 빌드 URL만 넣어서 우회하지 않는다. `PRIVACY_POLICY_URL`·`TERMS_OF_SERVICE_URL`이 없는 모바일 release는 컴파일 단계에서 차단되고 공개 HTTPS 주소의 형식도 검사한다. [문서 생성과 공개 절차](../apps/public-site/README.md)를 함께 따른다.

출시 후보의 API와 worker는 `ILLUSTRATION_QUALITY_ENABLED=true` 및 검토를 지원하는 OpenAI 모델·키를 함께 설정해야 한다. 설정이 빠지거나 지원하지 않는 모델이면 사전 검사/readiness와 실제 생성 경로가 완성을 차단한다. 동작·횟수·검증 범위는 [삽화 검사와 부분 재생성](ILLUSTRATION_QUALITY_GATE.md)을 따른다.

외부 PostgreSQL·비공개 S3와 상주 API/워커/Redis 구성은 [외부 호스팅 배포 준비](EXTERNAL_HOSTING_DEPLOYMENT.md)를 따릅니다. 기존 자체 호스팅 Compose를 대체하지 않으며, 실제 연결·배포를 실행했다는 뜻은 아닙니다.

Render 대상은 [불변 이미지 기반 실행 패키지](RENDER_DEPLOYMENT_PACKAGE.md)에 별도로 정의합니다. Blueprint 준비는 실서비스 활성화를 뜻하지 않습니다.

## Source of truth

Production is deployed from version-tagged container images.

Canonical path:
1. GitHub Actions builds `ghcr.io/<repo>/api:<sha>` and `ghcr.io/<repo>/worker:<sha>`
2. Production server pulls those images
3. Production compose brings services up
4. Readiness is verified via `/health/ready`

Local `docker build` is not the production source of truth.

Before deployment, the disposable runtime rehearsal in
[OPERATIONS_TEST_RUNBOOK.md](OPERATIONS_TEST_RUNBOOK.md#5-local-docker-runtime)
checks PostgreSQL photo-publication/withdrawal concurrency and the synthetic
portrait approval-to-erasure journey through Celery and private S3. Its explicit
mock photo-provider settings are test configuration, not production launch approval.

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
docker compose -f docker-compose.prod.yml run --rm --entrypoint certbot certbot certonly \
  --webroot -w /var/www/certbot \
  -d "$DOMAIN" --email "$OPS_EMAIL" --agree-tos --no-eff-email

# 4. Point nginx at the issued files and reload.
ln -sf live/$DOMAIN/fullchain.pem nginx/ssl/fullchain.pem
ln -sf live/$DOMAIN/privkey.pem   nginx/ssl/privkey.pem
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

The `certbot` service retries `certbot renew` every 12h. The one-off issuance command
overrides that service entrypoint so `certonly` actually runs. The relative symlinks
resolve inside the shared certificate tree mounted in both containers. nginx must be
reloaded after renewal; schedule `docker compose -f docker-compose.prod.yml exec -T
nginx nginx -s reload` on the host and monitor its result. Container renewal alone does
not reload the certificate used by nginx.

Verification (all three must hold):

```bash
curl -sSI  http://$DOMAIN/health  | head -1          # expect 301
curl -sSI https://$DOMAIN/health  | grep -i strict-  # expect Strict-Transport-Security
curl -sS  https://$DOMAIN/health/ready | jq .status  # expect healthy
```

## Cost guardrail (H4 — required before any real traffic)

`DAILY_GENERATION_BUDGET` limits total daily generation attempts across all users.
`X-User-Key` is a client-generated UUID, so every per-user control (rate limit, daily
20 books, free-plan monthly limit) is bypassed by rotating the key. The variable is now
wired into `.env.example` and `docker-compose.prod.yml` with a conservative default of
**20 attempts per Korea-local day** for the initial limited beta. This is a request
count, not a currency spending cap: model prices, page counts and retries affect cost.
Configure provider-side billing limits separately and raise this count only after
measuring actual generation cost. Do not disable the limit in production.

Redis holds both generation counters and Celery messages. Production uses
`maxmemory-policy noeviction` so memory pressure cannot silently delete either; rejected
writes must be treated as unavailable capacity rather than permission to generate.

## Deploy script

Before promoting the selected candidate image, establish its provider observations
with the [explicit provider preflight](PROVIDER_RUNTIME_AND_REPAIR.md). Run
`python scripts/provider_preflight.py --allow-billable-requests` from `/app` in that
candidate image using the API/worker's exact configuration, Redis and storage. This
operator-approved command incurs generic text/image API usage and needs no running
HTTP server. A candidate with new credentials/models, expired observations, or no
previous observations returns **503** from `/health/ready` until all required
providers have recent successful responses. `--check-only` reads observations and
does not establish them. Neither the deploy health loop nor health GETs call paid
models automatically. After a billing top-up, the same explicit preflight can
replace a cached quota rejection with verified successful responses.

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
1. load the explicitly selected env file and detect Compose (run the validation commands above separately)
2. image selection from the provided tag; `--image-tag` overrides stale API/worker image variables
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

For paired database/media backup and an executable disposable restore rehearsal,
see [BACKUP_RESTORE.md](BACKUP_RESTORE.md). `deploy.sh backup` creates only a private,
verified PostgreSQL custom-format archive; it does not back up media.

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
./scripts/deploy.sh --env-file infra/.env smoke
```

Health checks require `PROD_API_URL` to be the public HTTPS origin, with a valid
certificate and no trailing slash. They accept exactly HTTP 200, do not follow
redirects, and never bypass certificate validation. A 301 redirect to HTTPS is not
readiness. The `smoke` command uses the same origin and creates synthetic test state.

Health semantics:
- `/health/live`: process alive
- `/health/ready`: infrastructure/configuration and recent provider-response readiness;
  returns `503` when degraded, unavailable, or provider access is unverified
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
- Do not deploy with `DAILY_GENERATION_BUDGET=0` (H4). Keep the global attempt limit and provider billing limits enabled.
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


생성 상태 조회는 `RATE_LIMIT_READ_REQUESTS=120`, 생성·수정 요청은
`RATE_LIMIT_REQUESTS=10`의 독립된 60초 한도를 사용합니다. 거부된 재시도는 창을
연장하지 않으며 응답의 `Retry-After` 이후 다시 시도합니다. `RATE_LIMIT`은 지원하지
않는 이름입니다. `scripts/check-env.sh --mode ci`는 이 기본값이 API, 환경 예시,
Compose, Render, CI와 일치하는지 검사합니다.
