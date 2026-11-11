# Operations and Test Runbook

This runbook is the operator-facing checklist for validating code, runtime behavior, and deployment readiness.

## Pilot recovery source binding (2026-11-11)

The installed pilot recovery artifact is `/opt/ai-story-book/ops-releases/4f75ac4b2def64ee7f2e2ce0b1abb90489d39a8b3cf426d1e9fd7bc1b4f2b7eb` (210 verified files). Its manifest is pinned by the same hexadecimal digest. The previous 209-file artifact is retained. A future local candidate can contain additional operator tools; do not equate a new checkout with the installed artifact.

Systemd reads drop-ins alphabetically. A numeric `99-` file still precedes unnumbered `provider-interlock.conf`; a valid pinned `ExecStartPre` does not prove that `ExecStart` runs the same source. The pilot uses `zzz-verified-release.conf`, preserving narration/provider conditions and unit ordering. Always inspect effective commands after daemon reload:

```bash
python3 scripts/verify_pilot_recovery_units.py \
  --artifact /opt/ai-story-book/ops-releases/4f75ac4b2def64ee7f2e2ce0b1abb90489d39a8b3cf426d1e9fd7bc1b4f2b7eb \
  --manifest-sha256 4f75ac4b2def64ee7f2e2ce0b1abb90489d39a8b3cf426d1e9fd7bc1b4f2b7eb
```

This command only reads systemd properties. A pass is not a reboot or restore rehearsal. Keep the shared backup lock and every rollback marker until original container identities, worker response, strict TLS and readiness all pass. Configuration rollback journals contain credentials: never print them or copy them into acceptance artifacts. Public Cloud Run readiness must also be checked from outside the VM; a same-VM hairpin request is not the internal proxy check.

Restore the API upstream and reload the verified TLS proxy before waiting for worker control replies. A slow worker must retain the recovery marker without unnecessarily delaying the HTTP route. Before reload, require Docker DNS inside nginx to resolve only to the current canonical API container. Finite proxy failure codes omit response bodies, URLs and transport stderr.

The November 11 pilot reboot preserved an interrupted-service marker and stopped admission. The first recovery invocation failed; the provider-refresh timer's boot-time prerequisite reran recovery and it succeeded. The final image pins, strict TLS, worker reply, cleared marker and existing narration cache were verified. This is evidence of eventual boot recovery, not first-attempt reliability, backup restoration or uninterrupted service. Keep the initial failure in the record and improve cold-start recovery time separately. See [recorded reboot](acceptance/2026-11-11-backend-final-r7/reboot-audit.json).

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

Use `./scripts/run_runtime_e2e.sh --suite first-book-trial` to verify the single
signup credit, twelve signed page images for a book for ages 7–9, idempotent retry, and exhausted
credit handling with checkout disabled. An invited synthetic account generates
the book. Another synthetic account keeps its credit when generation is denied.
The runtime check delays the worker until a fresh HTTP client rediscovers the
queued job. It checks that another profile and account cannot list the job, then
verifies that the same job completes and the book appears in the library.
AI providers remain deterministic mocks.

For a localhost-only interactive review after those checks, add
`--suite media --serve --api-port 18280`. The runner keeps its isolated source,
database, worker and private media alive until interrupted, and permits only
the local browser origin `http://127.0.0.1:18281` by default. The README documents
the corresponding debug web build and `scripts/serve_web_preview.py`. Use its
`/preview` route to retire a previous Flutter service worker without clearing
browser storage. Its no-store responses and build-specific JS URLs prevent an
older cached application bundle from invalidating the review. This mode uses synthetic mocks, keeps public
readiness blocked, never loads saved provider credentials, and cleans up only its
own resources on shutdown; it is not a hosting deployment.

For the current Android joint-review APK, use port 18080 for the local
first-book preview and a fresh report directory:

```bash
asb_review_dir=$(mktemp -d)
./scripts/run_runtime_e2e.sh --suite first-book-trial --serve \
  --api-port 18080 --report-dir "$asb_review_dir"
```

After `Synthetic preview API ready` appears, reverse port 18080 and the media
port from `preview_media_url` in the report through the Android test device.
Use `adb -s <test-device> reverse tcp:<port> tcp:<port>` once for each port.
Both ports remain bound to the Mac's loopback interface. The iOS QA package
uses the Mac's local-network address. For that build, use a separate first-book
preview run with the Mac interface and iPhone address on the same private network:

```bash
./scripts/run_runtime_e2e.sh --suite first-book-trial --serve --api-port 57332 \
  --report-dir "$asb_review_dir" \
  --iphone-bind-ip "$asb_mac_ipv4" --iphone-peer-ip "$asb_iphone_ipv4"
```

Use a fresh report directory and substitute the actual private IPv4 addresses.
The Mac and the selected iPhone are the only allowed clients on the two
review listeners. The report's `preview_iphone_api_url` must match the Mac
hostname used by the QA build. `preview_media_url` uses the same `.local`
hostname with the storage port, so MinIO can verify the original signed `Host`.
The listeners close when the preview stops. For a Mac-only check, specify the
same Mac address for both options.

In the QA app, complete consent and copy **베타 참여 ID** in Settings. On the
Mac, add that ID as a single line to the private `review-invitations.txt` in the
same report directory. On macOS and Linux the running preview reads that file
on the next admission check and preserves consent and books already recorded.
Return to the app's creation screen or reopen the app to refresh availability.
The file accepts only lowercase, 64-character invitation IDs. If an ID is
already available at startup, repeat `--invite-id` for each account instead.
The preview uses mock AI, and stopping it removes the disposable account data
and the invitation file.

For a whole-book playback review, append the following option to either device
preview command. This uses the locally stored fictional acceptance archive:

```bash
--review-archive docs/acceptance/2026-11-07-live-length-fixed-first-book
```

In the app, create a Korean 7–9 book with 12 pages, watercolor, no added
character, and the exact topic **하루와 세 알의 기다림**. This request replays
the archived text and illustrations. Select **기본 목소리** and **구연동화**
in the reader to play the previously recorded Kore audio. The preview verifies
the text and audio hashes before replay. Other voices and styles have no
recordings in this archive. The preview makes no new synthesis request.

For the OpenAI Realtime QA packages, append these options instead:

```bash
--review-archive docs/acceptance/2026-11-08-auto-action-focus-live \
--review-realtime-audio docs/acceptance/2026-11-08-realtime-live-full-book
```

Use the same book settings with the exact topic **하루와 반짝이는 작은 숲**.
Select **기본 목소리** and **구연동화** for the twelve archived Coral recordings.
The runner checks the archived title, each narration input and WAV hash, and
the WAV format before starting. The app's Settings can also play all six
bundled OpenAI samples. These samples do not add recordings for the other
styles or voices to the archived book. The provider adapter reads from the
staged archive and requires a fixture-only credential.

It requires Docker Compose, the API Python dependencies, and locally available
`postgres:15-alpine`, `redis:7-alpine`, and `storybook-minio-test:2025-09-07`.
Build the disposable storage image once with
`docker build -f infra/Dockerfile.minio-test -t storybook-minio-test:2025-09-07 infra`.
The Dockerfile downloads the official release binary and verifies its architecture-specific
SHA-256; it is for isolated tests, not production. The runner itself never pulls
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
Image models include `gemini-3-pro-image`, `gemini-3.1-flash-image`, and `gpt-image-2`
with a matching configured provider. The selected provider endpoint and model are
enforced before HTTP. The 4-, 8-, and 12-page runs allow at most 16 LLM requests and
7, 11, and 16 image requests, respectively. Failed attempts, initial generation retries,
and up to two page repairs (three for 12 pages) share the image allowance. To check
the default book size, use `--page-count 12 --age 3-5` with fully fictional input and
no `--reader-profile-file`. Optional `--retain-fictional-review-evidence` captures
private illustration inputs for 4- and 12-page fictional runs, including when review
blocks the book. OpenAI output, including
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

It migrates the current schema, publishes the synthetic dump and media through a GCS
stand-in, and restores the quarantined import into a second empty stack. It rejects
missing or replaced completion markers and corrupted payloads, compares table and media
checksums, and verifies restored constraints and private access. Both temporary stacks
and all dump/media files are removed. The result measures recovery of the small fixture.
Production RTO and RPO require a separate measurement. See
[BACKUP_RESTORE.md](BACKUP_RESTORE.md) for production ordering and deletion replay.

The optional `PRIVACY_JOURNAL_WITNESS_BUCKET` requires a distinct private GCS
bucket and a completed, fenced backfill. Configure the same witness for API,
worker, and the backup runner (`ASB_JOURNAL_WITNESS_BUCKET`); mismatches fail
closed. This option is not enabled on the pilot. Matching replicas do not prove
complete history or permit a restored service to be opened. Current evidence and
remaining production recovery gates are in [BACKUP_DELETION_GUARD_2026-11-02.md](BACKUP_DELETION_GUARD_2026-11-02.md).

The alternative explicit S3 witness uses all five `PRIVACY_JOURNAL_WITNESS_S3_*`
settings with a separate access key and secret, a private existing bucket and an
HTTPS endpoint. It cannot be combined with the GCS witness. The same settings
must reach both writers; mount the existing private journal key separately.
The candidate scheduled backup reads these settings from its private env file,
requires an exact match with both writers, and compares both stores with the DB
before and after the guarded backup. Missing or mismatched settings block the
backup. This is local candidate code, not an installed pilot configuration.
Keep the option off until initial backfill, provider permissions, key recovery
and independent latest-history evidence are validated. Neon app credentials
can delete objects; configuring S3 does not establish append-only access or
permit restoring/publishing a service.

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

When the free first book is enabled, `deploy` and `start` also run the free beta
preflight before any image pulls, migrations, or service changes. Resolve its
configuration and bundled policy findings before retrying. The published pages,
provider data controls, and device verification still require their own evidence.

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

무료 제한 베타 후보에는 `--free-beta`를 추가한다. 초대 전용 생성, 신규 구매 비활성화, OpenAI Realtime 낭독 설정과 모바일 빌더와 동일한 공개 HTTPS 주소 형식을 확인한다. 계정별 일일 책 생성 한도와 계정별·전역 대기열 한도는 각각 최소 1이어야 한다. 새 캐릭터와 기본 12쪽 동화 및 12쪽의 새 낭독을 하루에 시험하려면 공유 생성 한도가 최소 14회여야 한다. 운영 한도 변경은 별도 절차를 따른다. 출시 전에 해당 OpenAI 프로젝트의 ZDR 적용 범위, 가상 동화의 실제 한국어 합성과 실기기 전권 재생을 확인한다. [OpenAI 데이터 제어](https://developers.openai.com/api/docs/guides/your-data)

The external preflight loads only explicitly selected dotenv files without executing
shell content; mobile values such as `PROD_API_URL` can be exported or provided with
another `--env-file`. It reports `BLOCKED` for missing/placeholder/invalid settings and
`CONFIGURED_NOT_VERIFIED` otherwise. `launch_ready` remains false because presence
checks cannot prove live AI, legal approval, actual purchases or production operations.
No secret values are included in text or JSON output.

The preflight also checks both `apps/mobile/assets/legal/*.ko.json` sources for
complete text, approved status and an effective date that has arrived in Korea.
Run `python3 scripts/render_legal_documents.py`
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

검증용 MinIO 이미지는 공식 Quay의 `RELEASE.2025-09-07T16-13-09Z`와 다중 아키텍처 digest `sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e`로 고정한다. 원격 Docker Hub pull이 거부되어 출처를 변경했으며, 9월 12일 로컬 실행에서 검증한 이미지와 digest가 동일함을 확인했다. 실제 운영의 외부 저장소 선택이나 활성화를 변경하지 않는다.

## 원격 백업 개인정보 기록 기준점 검증

`publish_backup_gcs.verify_remote_backup`은 백업 표식에 개인정보 기록 기준점의 건수와 해시가 일부만 있거나 형식이 잘못된 경우 거부한다. 호출자가 별도로 진위를 확인한 기준점을 `expected_journal_checkpoint`로 전달하면 표식의 누락이나 값 불일치도 거부한다. 이 인자를 생략한 검사는 기준점이 없는 마이그레이션 전 백업과의 호환을 유지하므로, 삭제 이력이 필요한 복원 판단에 단독으로 사용하면 안 된다. 기준점 대조는 백업 이후 발생한 최신 개인정보 변경의 완전성이나 두 저장소의 독립성을 증명하지 않으며, 반환 결과도 복원을 승인하지 않는다. 변경은 로컬 코드에만 있고 운영 배포 전이다.
