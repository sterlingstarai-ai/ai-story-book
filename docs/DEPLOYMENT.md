# Deployment Guide

> 현재 출시 상태와 비공개 미디어 전환 절차: [LAUNCH_STATUS.md](LAUNCH_STATUS.md). 로컬 API는 `apps/api/.env`, 운영 Compose는 `infra/.env`를 사용합니다.

시험 운영 서버의 복구 코드는 이미지와 별도로 매니페스트에 고정한다. systemd의 실제 실행 명령과 사전 검증 명령이 같은 복구 아티팩트를 가리키는지 확인한다. 숫자 접두어의 drop-in이 기존 알파벳 파일보다 나중에 적용된다고 가정하지 않는다. [고정 복구 코드 확인](OPERATIONS_TEST_RUNBOOK.md#pilot-recovery-source-binding-2026-11-11).


This document defines the production deployment contract after the P5 hardening sweep.

모바일 정책 전문은 앱에 포함되며, 공개본은 `scripts/render_legal_documents.py`로 같은 JSON 원본에서 생성한다. `final-external-preflight.sh`는 원본의 검토 상태와 시행일을 확인하고, 승인 표시가 있더라도 본문에 외부 처리·보존을 추후 확정한다는 준비 문구가 남으면 차단한다. `PRIVACY_POLICY_URL`·`TERMS_OF_SERVICE_URL`이 없는 모바일 release는 컴파일 단계에서 차단되고 공개 HTTPS 주소의 형식도 검사한다. [문서 생성과 공개 절차](../apps/public-site/README.md)를 함께 따른다.

출시 후보의 API와 worker는 `ILLUSTRATION_QUALITY_ENABLED=true` 및 검토를 지원하는 OpenAI 모델·키를 함께 설정해야 한다. 설정이 빠지거나 지원하지 않는 모델이면 사전 검사/readiness와 실제 생성 경로가 완성을 차단한다. 동작·횟수·검증 범위는 [삽화 검사와 부분 재생성](ILLUSTRATION_QUALITY_GATE.md)을 따른다.

외부 PostgreSQL·비공개 S3와 상주 API/워커/Redis 구성은 [외부 호스팅 배포 준비](EXTERNAL_HOSTING_DEPLOYMENT.md)를 따릅니다. 기존 자체 호스팅 Compose를 대체하지 않으며, 실제 연결·배포를 실행했다는 뜻은 아닙니다.

Render 대상은 [불변 이미지 기반 실행 패키지](RENDER_DEPLOYMENT_PACKAGE.md)에 별도로 정의합니다. Blueprint 준비는 실서비스 활성화를 뜻하지 않습니다.

## Local release preparation without account activation

`codex/**` branch pushes and manual CI runs validate API/mobile tests and build/scan both container images. Registry login, image publication and deployment remain restricted to `main` push and the existing deployment switch; a branch test run creates no hosted services.

For mobile release compilation, copy `infra/mobile-release.example.json` to a private local configuration and replace its three public URL placeholders. Run `scripts/build_mobile_release.py --config /path/mobile-release.json --platform android` to validate the URL configuration and see the bundled policy status. This default check runs offline. To compile, add `--execute --support-site-config /path/public-site-config.json`. The compiler runs after the approved, dated bundled documents match the generated policy HTML and the public `/privacy/` and `/terms/` URLs match the same support site. All seven published files must match their expected bytes over HTTPS. Use `--platform android` for the signed AAB or `--platform ios` for the unsigned iOS release. Success records the output SHA-256. Production E2E, operational support handling and store approval require separate verification.

The iOS release builder also checks every native binary in the resulting `.app` with Apple's installed `lipo` and `vtool`. Only device arm64/arm64e with IOS platform metadata (including genuine legacy iPhoneOS metadata) passes. A successful compile or arm64 architecture alone does not prove a device artifact. Build store archives in a clean isolated source directory without simulator build/Pods/native-asset caches, preserving the original checkout. Inspect the archive app with `python3 scripts/validate_ios_native_platforms.py --app /path/Runner.xcarchive/Products/Applications/Runner.app`, then inspect the signed export with `--ipa /path/app.ipa` before upload. The checker is read-only, does not sign/upload, and returns nonzero on an unproven or simulator platform. Signing, export and store processing remain separate checks.

When the `share_plus` native framework is present, this gate also requires its own `PrivacyInfo.xcprivacy` in the framework root or the explicitly named SDK resource bundle. It rejects substitution by an app-root or unrelated SDK file, malformed plist fields and oversized manifests. `required_sdk_privacy_manifests` identifies the files checked. This is a structural gate, not a complete Apple category/reason or policy validator. Verify the selected SDK's official source and the exported IPA; the former 7.2.2 package has no iOS privacy manifest and is not an acceptable substitute for the pinned 10.1.4 package.

The optional `phase-gate.sh --with-ios-build` and acceptance bundle now compile **debug/no-codesign** iOS as a local compatibility check. They are not substitutes for the explicit release configuration above. Existing SDK/JDK installations are discovered within script processes, without global configuration changes.

## Source of truth

Guardian mail credentials are connected separately with `scripts/connect_guardian_smtp.py --execute --account your-sender@example.com` in a private terminal. The script validates TLS authentication but does not send mail or activate production. For Gmail, use a Google app password, with Unicode grouping whitespace accepted; a regular account password is not accepted. The JSON failure result exposes fixed reasons, safe guidance and a validated numeric SMTP code only. Existing private settings are never overwritten. See [mail activation and declaration obligations](appstore/guardian-email-release.md).

Production is deployed from version-tagged container images.

With `FREE_PLAN_FIRST_BOOK_TRIAL` enabled, `deploy.sh deploy` and `deploy.sh start`
run the free beta preflight against the loaded Compose environment. Missing
configuration or bundled policies awaiting approval block the command before
image pulls, database migrations, or service changes. This check needs Python
3.11 or newer. Verify the published policy pages, effective provider data
controls, and physical devices as separate release steps.

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

## Trusted proxy and public share limits

Production Compose gives nginx a fixed internal address (`NGINX_PROXY_IP`, default
`172.30.0.2`) and passes that same address to the API's `FORWARDED_ALLOW_IPS`.
Only nginx's forwarded client address is trusted; public share requests use that
address for a shared Redis read limit. Caller-supplied user keys do not change it.
The API has no published host port. Keep nginx's appended `X-Forwarded-For` header.

`APP_NETWORK_SUBNET` defaults to `172.30.0.0/24`. If it conflicts with a host network,
set both variables to an unused subnet and an address inside it before recreating
the Compose network. Other deployment topologies must set `FORWARDED_ALLOW_IPS`
to their actual trusted proxy addresses; do not use `*` on an exposed API.

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

LLM, image and OpenAI narration providers may read keys from `LLM_API_KEY_FILE`,
`IMAGE_API_KEY_FILE` and `OPENAI_TTS_API_KEY_FILE` inside the container instead
of their corresponding environment values. A pair cannot be set simultaneously. The configured path must
be absolute and have no symlink in any component; the file must be regular,
owned by the process's effective numeric UID and inaccessible to group/others.
The same private file can supply multiple adapters if the key has the approved
project scope for each one. An absent, unreadable or unsafe configured file
blocks startup. Settings serialization excludes the key values. Provider
acceptance requires a separate live check.

The optional `infra/docker-compose.provider-key-files.yml` override mounts an
existing directory from `PROVIDER_KEY_HOST_DIR` read-only into both API and
worker at `/run/asb-provider-keys`. Set each `*_API_KEY_FILE` to an absolute
path under that mount and leave each corresponding raw environment key empty.
With `deploy.sh`, pass the base file first and repeat `--compose-file` for the
key mount override. Rollback uses the same file order with the previous env.
The host file's numeric UID must match the actual effective UID of **both**
container processes (check the pinned images and runtime user namespaces), and
its mode must be 0400 or 0600. Limit access to the host directory and transfer
the credential securely; this override does not create or deliver it. Verify
the mount and permissions within isolated candidate containers before any
rollout. Host/container paths in configuration preflight do not prove a file
exists or can be read. Docker administrators and privileged host users may read
mounted files and process memory; this is not a secret-manager boundary.

The optional `GENERATION_BUDGET_STORE=postgres` persists the global request count in
PostgreSQL and fails closed if its activation or database is unavailable. Existing
deployments remain on Redis by default. This remains a request count, not a spending
cap; provider billing limits are still required. A successful database backup restore
can rewind counts: fence generation until the next Korea-local day, or restore the
latest independently verified admission history before resuming. The application
cannot detect a valid but stale restored row or a mixed-store rollout. Keep durable
mode inactive until these operational controls are in place. Do not downgrade the
migration after activation or revert to Redis while the durable mode is active. The
PostgreSQL server clock defines the day for all API and worker instances.

**Fenced one-way cutover:** take a verified backup; deploy the new image and migration
while generation is disabled. Stop and fence every old API instance, worker, cron job
and other writer, including autoscaling/restart paths, and verify they cannot make
provider calls or restart. An old binary cannot honor the new counter. On the intended
PostgreSQL database, from `apps/api`, run:

```bash
python -m scripts.activate_generation_budget --all-old-writers-stopped-and-fenced
```

The flag records an operator assertion; the
script cannot prove fencing. It blocks all admissions for the rest of the current
Korea-local day instead of guessing the old Redis count, and refuses reactivation.
Set `GENERATION_BUDGET_STORE=postgres` and the same positive daily limit on every new
API and worker, then start only those new instances. Verify the detailed budget status
and instance configuration before reopening generation. Keep all old writers fenced;
never use a rolling mixed-store deployment. If fencing, migration, database identity,
or verification cannot be established, do not activate or reopen generation.

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
3. capture the running API and worker image IDs for rollback
4. `docker compose pull`
5. Alembic migration — applied while the **old** stack is still serving, so the new
   schema is in place before new code runs (no compose-down, no full downtime)
6. rolling `docker compose up -d` (only changed containers recreate)
7. check HTTPS liveness and readiness, then require each Celery worker to answer
   a targeted ping through the broker. On failure, restore the captured API and
   worker images by local ID and repeat the checks. The deploy exits non-zero
   even when rollback restores service.

When the release changes API or worker settings, keep a private copy of the
currently running Compose environment and pass it as `--rollback-env-file PATH`.
If the release adds or removes a Compose override, repeat
`--rollback-compose-file PATH` for the previous base file and every previous
override in their original order. Otherwise the previous environment uses
the same Compose files as the release. Both configurations must refer to
the same running Compose project.
Compose must report the same configuration hashes and image IDs as the running
API and worker before the deploy can proceed. This mode starts only those two
services. On failure it revalidates the previous environment and restores the
captured local image IDs without pulling. It verifies the image and configuration
hash of every restored replica before checking API and worker health, then exits
non-zero. Keep the captured images available locally. Before a retry, prepare
the rollback env to match the running stack's current image references, including
any IDs pinned by the last rollback. Use the pilot's pinned operation and
restore procedures for deployments outside this Compose workflow.

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
  returns `503` when degraded, unavailable, or provider access is unverified.
  Each API process shares a read-only S3 bucket check for up to 15 seconds;
  startup or upload checks cannot replace it. Readiness never creates a bucket.
  Self-managed deployments with `S3_AUTO_CREATE_BUCKET=true` initialize the
  bucket at startup. External deployments use an existing private bucket.
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

## 2026-09-12 제한 베타 운영 제어

운영 템플릿은 새 AI 생성을 초대 계정으로 제한합니다. `GENERATION_ACCESS_MODE`와 `GENERATION_ALLOWED_USER_HASHES`, 읽기 전용 운영 점검 `scripts/check_operations.py`, 중단·최종 승인 절차는 [출시 후보 기록](LAUNCH_CANDIDATE_2026-09-12.md)을 따릅니다.
