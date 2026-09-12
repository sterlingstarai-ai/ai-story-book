# Operations and Test Runbook

This runbook is the operator-facing checklist for validating code, runtime behavior, and deployment readiness.

## 1. Fast path: repository root quality gate

Run from the repository root:

```bash
./scripts/check-env.sh --mode ci
./scripts/phase-gate.sh
```

Extended gate:

```bash
./scripts/phase-gate.sh --with-mobile-build --with-api-smoke
```

Expected result:
- API tests pass
- Flutter analyze passes with no warnings
- Flutter tests pass
- optional Android build succeeds
- optional smoke returns `Failed: 0`

## 2. API-only validation

```bash
cd apps/api
./venv/bin/python -m pytest tests -q
```

Key regression coverage includes:
- IAP verify and webhook flows
- profiles/settings/rewards/POD/voice/pronunciation endpoints
- readiness contract
- degraded asset metadata (`generation_warnings`, `asset_status`)
- config scoping to `apps/api/.env`

## 3. Mobile-only validation

```bash
cd apps/mobile
flutter pub get
flutter analyze
flutter test
```

Key regression coverage includes:
- consent/onboarding/startup flows
- settings/profiles/voice profile widgets
- pronunciation/POD/branch story interactions
- API request correlation and degraded asset parsing

The integration/build wrappers source `scripts/mobile-toolchain.sh` to find existing Android SDK and Android Studio JDK installations when they are absent from PATH. They do not install tools or edit shell configuration. Android native storage/device tests remain separate from headless tests. The optional iOS quality build is debug/no-codesign; use `scripts/build_mobile_release.py` with explicit public URLs for release compilation.

## 4. Runtime health checks

Against a live API host:

```bash
./scripts/smoke.sh http://127.0.0.1:8000
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
```

Interpretation:
- `200 /health/live`: process is up
- `200 /health/ready`: dependencies/configuration are healthy and all required real
  providers have recent successful response observations (outside `TESTING=true`)
- `503 /health/ready`: service is up but not ready, including unverified provider
  access or an observed quota/credential failure

Before promoting a candidate, run the explicitly billable
`python scripts/provider_preflight.py --allow-billable-requests` from its API image
(`/app`) with exactly the candidate API/worker configuration, Redis and storage.
It sends generic content and requires no ready HTTP server. A check-only run or
health GET cannot prove usable API credit and never makes paid calls. After a
manual top-up, repeat the explicit preflight to clear the observed quota failure;
do not clear observations by hand. See
[provider operations](PROVIDER_RUNTIME_AND_REPAIR.md) for expiry and cost details.

## 5. Local docker runtime

For an isolated integration rehearsal, use the disposable runtime gate:

```bash
./scripts/run_runtime_e2e.sh
```

It requires Docker Compose, the API Python dependencies, and locally available
`postgres:15-alpine`, `redis:7-alpine`, and `minio/minio:latest` images. It never pulls
images, reads project `.env` files, calls paid AI providers, or uses existing volumes.
Dependencies bind to random localhost ports and are removed after the run. A temporary
source copy excludes credentials and runtime databases.

The default suite must execute at least 21 PostgreSQL regression cases with zero skips:
10 erasure/Celery cases, 4 account recovery concurrency cases, and 7 photo-lifecycle
concurrency cases. The latter observe actual PostgreSQL lock waits for the same
owner, including legacy users with no identity row, and verify publication versus
consent-withdrawal ordering. They also verify that individual book deletion waits
for an edit to publish and then erases its newest image. The runtime suite verifies
the HTTP reading journey through a real Celery worker and
private-S3 signed download, anonymous denial, signature tampering/expiry and share
revocation. A separate HTTP journey uploads a locally generated color tile, polls
the Celery portrait preview, checks that unapproved portraits cannot create books,
approves its version, and verifies a twelve-page book and its durable portrait
snapshot. It checks metadata removal and real S3 erasure of the temporary source
after approval, then removes the character and withdraws consent to verify that
the derived book, snapshot and images are still found and erased. The photo path
explicitly sets `PHOTO_ANALYSIS_PROVIDER=mock` and `PHOTO_PROCESSING_ENABLED=false`;
no real person, photograph, paid model or live portrait-quality review is used.
`--suite media` runs migrations and the HTTP/media/portrait journeys only; CI uses
that mode after its separate PostgreSQL/Celery regression gates. A mock release is
expected to return **503 readiness**, while real dependency statuses must be healthy.
This is runtime integration evidence, not live AI content quality or store acceptance.

Use `--report-dir /tmp/storybook-runtime-report` to choose the report directory;
`result.json` records pass/fail, separate PostgreSQL recovery/photo-lifecycle counts,
portrait journey checks, executed coverage and cleanup status. Logs contain only
synthetic test activity. Cleanup failure is a gate failure and includes the unique
Compose project name for recovery.

### Paid synthetic book comparison

After explicit approval for paid generation, `run_live_book_acceptance.py` creates
one fictional character and one book against disposable PostgreSQL, Celery and private
S3. It reads only the named configuration files and never edits the active API `.env`.
For a separate OpenAI credential file containing `OPENAI_API_KEY`:

```bash
apps/api/venv/bin/python scripts/run_live_book_acceptance.py --live \
  --env-file apps/api/.env --llm-env-file /path/to/private-openai.env \
  --llm-model gpt-5.6-sol --page-count 4 --age 5-7 \
  --output-dir docs/acceptance/YYYY-MM-DD-gpt-book
```

Every new paid full-book run enables illustration review and therefore requires
`gpt-6-astra` or `gpt-5.6-sol`; text-only comparisons can still evaluate Anthropic.
Image models remain `gemini-3-pro-image` and `gemini-3.1-flash-image`. The selected
provider endpoint and model are enforced before HTTP. Four-page runs allow at most
16 LLM and 7 image requests; eight-page runs allow 16 LLM and 11 image requests.
Failed attempts, initial generation retries, and at most two page repairs share
these limits. Only page counts 4 and 8 are accepted. OpenAI output, including
reasoning, is limited to 16,000 tokens per request; visual reviews use the narrower
6,144-token ceiling. OpenAI requires `store:false` and rejects non-default service
tiers. Existing Gemini request bodies are unchanged. See [the publication gate](ILLUSTRATION_QUALITY_GATE.md).

`run_live_quality_matrix.py` accepts the same `--llm-env-file`, `--llm-model` and
`--image-model` flags and schedules 15 four-page books, two at a time. It also accepts
`--reader-profile-file` for an explicitly authorized private name/gender profile;
omit its exact age so all three QA age bands remain covered. Profile privacy checks
run before paid work, and all outputs stay Git-ignored with private permissions.
It stops starting
books after a failure or the $2 text/$11.50 image estimate threshold. An explicit
`--text-spend-threshold-usd` may set a positive finite text threshold up to $10 after
checking the selected provider's remaining credit and allowing for in-flight work.
The default remains $2; the chosen thresholds are recorded in `matrix.json`. Estimates
use each result's recorded model/provider and standard prices checked on 2026-09-06.
New v2 journals record dimensions for every returned image, including images
subsequently rejected or replaced. These estimates do not substitute final saved
files when response metadata is missing. Legacy journals retain their original
final-file fallback. Image estimates assume 1,120 image tokens for each verified
896×1200 image; missing usage, unknown models, or other dimensions stop estimation. These are completed-usage
estimates, not invoices or provider-enforced dollar caps; in-flight work can exceed a
threshold. A completed sample still needs a separate content-quality review.

For an independent PostgreSQL/private-media backup and restore rehearsal:

```bash
./scripts/run_backup_restore_rehearsal.sh --report-dir /tmp/storybook-restore-report
```

It migrates the current schema, restores synthetic data into a second empty stack,
compares every table and media checksum, and verifies restored constraints and private
access. Both temporary stacks and all dump/media files are removed. The result is a
small-fixture recovery check, not production RTO/RPO evidence. See
[BACKUP_RESTORE.md](BACKUP_RESTORE.md) for production ordering and deletion replay.

For the persistent developer stack instead:

```bash
cp -n infra/.env.example infra/.env

if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
else
  DC="docker-compose"
fi

$DC --env-file infra/.env -f infra/docker-compose.yml up -d postgres redis minio api worker
$DC --env-file infra/.env -f infra/docker-compose.yml exec -T api alembic upgrade head
./scripts/smoke.sh http://127.0.0.1:8000
```

For low-risk local validation, use mock providers where available.

## 6. Production deployment verification

```bash
./scripts/check-env.sh --mode production --env-file infra/.env
./scripts/deploy.sh --env-file infra/.env --image-tag <sha> deploy
./scripts/deploy.sh --env-file infra/.env smoke
```

Set `PROD_API_URL=https://<real-api-host>` in `infra/.env`. Deployment health and smoke
use this HTTPS origin with certificate validation; a redirect is not a pass.

Minimum acceptance after deploy:
- `docker compose ps` healthy
- `/health/live` returns `200`
- `/health/ready` returns `200`
- smoke passes

## 7. External integration status

Code-complete but live-key dependent:
- Apple/Google IAP sandbox and real store validation
- Printful POD sync
- Kakao share live key validation
- AdMob rewarded ads with production units

Use mock validation only in disposable environments. Production receipt verification
stays strict. New purchases ship disabled for the initial free limited beta;
`PURCHASES_ENABLED=true` requires both store configurations. Disabled audio/POD and
optional Kakao do not require their keys.

```bash
./scripts/final-external-preflight.sh --env-file infra/.env --json
```

The external preflight loads only explicitly selected dotenv files without executing
shell content; mobile values such as `PROD_API_URL` can be exported or provided with
another `--env-file`. It reports `BLOCKED` for missing/placeholder/invalid settings and
`CONFIGURED_NOT_VERIFIED` otherwise. `launch_ready` remains false because presence
checks cannot prove live AI, legal approval, actual purchases or production operations.
No secret values are included in text or JSON output.

The preflight also checks both `apps/mobile/assets/legal/*.ko.json` sources for
approved status and a valid effective date. Run `python3 scripts/render_legal_documents.py`
after an approved source revision, then refresh the private publication hashes.
The public builder rejects a document still marked `review`, even with an approval
flag. Mobile release compilation rejects absent public policy URL defines; native
policy reading itself uses bundled assets and works before consent and offline.

For provider availability, use the explicit operator probe documented in
[provider observations and repairs](PROVIDER_RUNTIME_AND_REPAIR.md). Health requests
do not spend API credit. `unverified` observations cannot prove usable AI balance;
known billing failures return readiness 503. After funding, verify recovery with a
successful probe against the same credentials and Redis used by API and workers.

## 8. Failure patterns

### Phase gate passes in `apps/api` but fails from repo root

This should no longer happen. Root execution is the supported path. If it does, inspect:
- `apps/api/src/core/config.py`
- unexpected environment exports in the shell
- `apps/api/.env` contents

### Smoke fails on readiness only

Likely causes:
- DB unreachable
- Redis unreachable
- migrations missing
- strict external provider configuration unexpectedly required

### Mobile release feature missing

Check explicit availability rules:
- AdMob unit configured for platform
- Kakao native key configured
- IAP available on device/store
- POD provider mode not blocked by missing config

### Preserve fictional live-review evidence

For an explicitly approved live photo acceptance run using an entirely fictional
fixture, add `--retain-fictional-review-evidence` to
`scripts/run_live_photo_acceptance.py run`. This option rejects `real_child`
input before startup. It saves generated cover/page bytes and the matching
story/prompt context before QA under `fictional-review-evidence/review-01/`;
the mandatory recheck, when reached, uses `review-02/`. Files are owned, mode
0600, and Git-ignored. Source photos, credentials and raw provider responses
are excluded. Normal disposable service cleanup still runs after failure.

`scripts/replay_fictional_review.py --live --capture-dir <review-directory>
--output-dir <new-private-output> --env-file <explicit-provider-config>
--policy-file <new-approved-review-budget>` reuses those exact images and context
for at most one guarded QA call. It generates no new images and does not publish
a book. Assign its budget separately; starting a new journal is not permission
to reuse a prior spending allowance. A validated response can contain defects;
read its issue codes before treating it as a quality pass. The original evidence
is unchanged. These commands do not establish real-child likeness or release
approval.

## 외부 PostgreSQL·비공개 S3 사전 점검

[외부 호스팅 배포 준비](EXTERNAL_HOSTING_DEPLOYMENT.md)의 `check-env.sh --mode external`과 Compose `config --quiet`는 설정만 검증합니다. 실제 호스트에서 DB TLS·Celery·private media·삭제 흐름을 별도로 검증해야 합니다. `backup_external.py`는 기본 dry-run이며 운영자 승인·쓰기 중지·암호화 저장소 확인 후에만 읽기를 실행합니다. 백업 생성은 [격리 복원과 최신 삭제/인증 폐기 기록 재적용](BACKUP_RESTORE.md)을 대신하지 않습니다.

Render 선택 시 [실행 패키지](RENDER_DEPLOYMENT_PACKAGE.md)의 CA Secret File·Auto Sync·작업 소진 후 worker 교체 조건을 확인합니다. 공식 스키마와 합성 이미지 검증은 실제 registry·계정·배포 검증을 대신하지 않습니다.


요청 제한 회귀 확인: 생성·수정 10회/분과 조회 120회/분은 별도 집계입니다.
실제 생성 검증에서는 한도를 임의로 높이지 말고 2초 상태 조회가 완성까지 유지되는지
확인합니다. 월간 무료 크레딧은 한국 시간 매월 1일에 다음 접속 시 최대 2개로 보충하며,
이전 잔액이나 구매분을 줄이지 않습니다. 사진 동의 철회로 콘텐츠를 지워도 과금 기록의
생성 식별자로 당월 사용량을 유지합니다. 전체 삭제 후 이전 인증키는 `ACCOUNT_DELETED`로
거부되어 삭제 응답을 놓친 앱도 완료를 확인할 수 있습니다.

## 2026-09-12 제한 베타 운영 제어

운영 템플릿은 새 AI 생성을 초대 계정으로 제한합니다. `GENERATION_ACCESS_MODE`와 `GENERATION_ALLOWED_USER_HASHES`, 읽기 전용 운영 점검 `scripts/check_operations.py`, 중단·최종 승인 절차는 [출시 후보 기록](LAUNCH_CANDIDATE_2026-09-12.md)을 따릅니다.
