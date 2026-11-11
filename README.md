# AI Story Book

AI Story Book is a production-oriented storybook platform with a Flutter mobile app and a FastAPI backend. The current repository includes P0-P4 product scope plus a P5 hardening sweep focused on deterministic gates, image-based deployment, explicit feature availability, and stronger operational visibility.

Current launch decisions, remaining owner actions, and verification boundaries: [Launch status](docs/LAUNCH_STATUS.md).

The pilot uses Flare for initial illustrations and Sunburst only for flagged-page repair. Latest full-backend rollout and store-submission status remain separate from that model setting. Verify effective pinned systemd recovery commands with the [operations runbook](docs/OPERATIONS_TEST_RUNBOOK.md#pilot-recovery-source-binding-2026-11-11).

## Release status — 2026-11-12

Google Play Alpha `1.0.0(5)` is active for selected testers in South Korea. Apple `1.0.0(6)` is waiting for review after the required sharing SDK privacy manifest was fixed and verified in the signed IPA. Neither status means general public release is complete. The owner is handling Google's 12-tester/14-day production-access requirement. Guardian email remains disabled; final release-device checks are separate. See the [current follow-up and evidence](docs/appstore/release-followup-2026-11-12.md).

## Historical release checkpoint — 2026-09-06

**Public release quality remains on hold.** The fixed 15-book baseline completed all technical paths, but character consistency and text–image agreement each passed only 53.3%. A prepublication [illustration review and bounded page repair gate](docs/ILLUSTRATION_QUALITY_GATE.md) has been implemented and verified on stored error cases. It does not overwrite the failed baseline or establish zero-error generation. See [launch status](docs/LAUNCH_STATUS.md).

- Current root gate and Python 3.11 verification: **1,400 API tests passed, 14 skipped, 75.62% coverage**; all 14 PostgreSQL/Celery cases passed separately against disposable dependencies. [Release evidence](docs/RELEASE_PREPARATION.md).
- Flutter with the new inspection/repair progress: **367 passed, 50.5135% coverage**, analyze passed, two applicable app-flow tests passed. Android debug and iOS unsigned builds completed. Physical-device validation remains separate.
- Local text configuration uses **OpenAI `gpt-5.6-sol`**, selected from four models over the same six tasks (24 text stories). Gemini remains the image provider. [Model decision](docs/AI_MODEL_DECISION_2026-09-06.md).
- OpenAI **US$10** funding and an approved Google **₩10,000 additional top-up** are complete; automatic reload is off. These are funding records, not current balances or spending caps.
- **24 complete books before the new gate:** nine earlier books plus the fixed 15-book baseline. One additional four-page runtime sample completed with review enabled; subsequent visual review still required correction, so it is not a quality GO. Recent tests use an authorized parent-provided first name with fictional appearance/story; real child photos were not used. The personal reading PDF was manually corrected and is not evidence of automated quality acceptance.
- Production hosting, public DNS/HTTPS, private S3, external encrypted backups, Apple agreement/provisioning, legal business details, store submission and physical-device validation remain external prerequisites. New purchases, audio and print ordering remain disabled.

## Current state

- Mobile app: implemented for iOS and Android in `apps/mobile`
- Backend API: implemented in `apps/api`
- Deployment model: GHCR image tag -> production compose pull -> up
- Quality gate: repository-root `./scripts/phase-gate.sh`
- Public-only mobile release build preparation: `scripts/build_mobile_release.py` ([deployment guide](docs/DEPLOYMENT.md)); validation by default, no store upload.
- iOS release output is checked for device-only native platforms. Use a clean isolated source directory for store archives and check the exported IPA with `scripts/validate_ios_native_platforms.py --ipa /path/app.ipa` before upload; simulator arm64 binaries are rejected.
- The same iOS check requires a valid SDK-owned privacy manifest whenever `share_plus.framework` is included. An app-root manifest or another SDK's manifest cannot satisfy that check; full Apple policy validation remains separate.
- The existing Gmail SMTP helper, `scripts/connect_guardian_smtp.py`, uses a 16-letter app password in a private terminal. This is the helper's authentication method, not a product requirement to use app passwords; OAuth or another mail provider would need its own connection. Mail remains disabled. Errors distinguish authentication, TLS, network and local saving failures without exposing secrets. [Current mail status](docs/appstore/guardian-email-release.md).
- Health contract:
  - `/health/live`
  - `/health/ready`
  - `/health` (compatibility endpoint)
- Degraded generation contract:
  - `generation_warnings`
  - page-level `asset_status`

## Repository layout

```text
ai-story-book/
├── apps/
│   ├── api/              # FastAPI + Celery backend
│   └── mobile/           # Flutter mobile app
├── docs/                 # product, deploy, QA, store, legal docs
├── infra/                # docker compose and nginx assets
├── scripts/              # quality gate, smoke, deploy, env checks
└── packages/             # shared assets and API contract artifacts
```

## Local development

### Backend

```bash
cd apps/api
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn src.main:app --reload
```

### Mobile

```bash
cd apps/mobile
flutter pub get
flutter run
```

Useful runtime overrides:

```bash
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
flutter run --dart-define=API_BASE_URL=http://localhost:8000
```

## Quality gates

Canonical gate from repository root:

```bash
./scripts/check-env.sh --mode ci
./scripts/phase-gate.sh
```

Extended gate including Android build and API smoke:

```bash
./scripts/phase-gate.sh --with-mobile-build --with-api-smoke
```

Real PostgreSQL/Celery/private-S3 rehearsal with disposable Docker dependencies:

```bash
./scripts/run_runtime_e2e.sh
```

This uses deterministic AI providers and local images only. It proves runtime
integration and media access control, including a synthetic portrait's preview,
parental approval, twelve-page book generation and consent-withdrawal erasure.
The queued-book check opens a fresh HTTP client before the worker starts and
verifies that the same profile can rediscover the job and see the completed book.
PostgreSQL also checks that photo publication and withdrawal serialize for one
account without blocking another account. Live AI/store acceptance remains separate.

To exercise the limited beta's first-book credit and twelve-page reading flow
with the same isolated dependencies, use `./scripts/run_runtime_e2e.sh --suite first-book-trial`.

To inspect the current app locally without loading saved provider credentials,
keep that verified synthetic backend running and build a debug browser preview:

```bash
./scripts/run_runtime_e2e.sh --suite media --serve --api-port 18280
# In a second terminal, from apps/mobile:
flutter build web --debug --no-wasm-dry-run --dart-define=API_BASE_URL=http://127.0.0.1:18280
python3 ../../scripts/serve_web_preview.py
```

Open `http://127.0.0.1:18281/preview`. The local server serves fresh build URLs,
disables offline worker registration and preserves browser data. This is a
synthetic review preview, not a public
release or native feature certification. Use fictional inputs only. Readiness
continues to reject mock providers with HTTP 503 even when local dependencies
are healthy. Ctrl-C on the runtime command removes only its temporary services.

For a synthetic PostgreSQL/private-media backup and restore check, run
`./scripts/run_backup_restore_rehearsal.sh`. It compares restored database and media
checksums in a second isolated stack. The operational procedure is in
[docs/BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md).

For the installed pilot, the [recovery-source runbook](docs/OPERATIONS_TEST_RUNBOOK.md#pilot-recovery-source-binding-2026-11-11) checks five effective systemd commands against one immutable release. Use `PYTHONDONTWRITEBYTECODE=1` and Python `-B` for its diagnostic commands and children; strict verification still rejects unexpected bytecode files. Backup health also checks recovery dependency failures and completion after an actual timer trigger, rather than treating an older successful snapshot as proof that today's job ran.

What it verifies:
- API tests from `apps/api`
- Flutter analyze
- Flutter tests
- optional Android debug build
- optional API smoke against a running server
- shared OpenAPI contract stays in sync with the API app

## Smoke and health checks

```bash
./scripts/smoke.sh http://127.0.0.1:8000
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
```

`/health/ready` is the deployment readiness source of truth. Non-healthy readiness returns `503`.

Policy and terms are bundled for offline reading before consent and from Settings.
Their canonical sources are `apps/mobile/assets/legal/*.ko.json`; run
`python3 scripts/render_legal_documents.py` to render matching review HTML.
Mobile release compilation requires both public policy URL defines, and the
external release preflight rejects draft bundled documents or missing effective
dates. An available policy screen does not establish legal approval or deployment.
See [public policy publishing](apps/public-site/README.md).

## Production deployment

Production deploy is image-based. The repository is not the build artifact; tagged container images are.

```bash
./scripts/deploy.sh --env-file infra/.env --image-tag <git-sha> deploy
```

Key properties:
- `infra/docker-compose.prod.yml` uses `image:` for `api` and `worker`
- `scripts/deploy.sh` supports `--env-file`, `--compose-file`, `--image-tag`
- Repeat `--compose-file` to add the optional private provider-key mount after the base file.
- With `FREE_PLAN_FIRST_BOOK_TRIAL` enabled, `deploy` and `start` check the free beta configuration and bundled policy status before modifying services.
- health validation requires exact HTTP 200 over the configured `PROD_API_URL` HTTPS origin, with certificate validation

More detail: `docs/DEPLOYMENT.md`

## Configuration rules

- API settings load from `apps/api/.env`, not the repository root `.env`
- unrelated root env keys should not break API test execution
- production env validation uses `./scripts/check-env.sh --mode production --env-file infra/.env`
- external PostgreSQL/private S3 uses `--mode external --env-file infra/.env.external`; see [external hosting preparation](docs/EXTERNAL_HOSTING_DEPLOYMENT.md)
- Render uses an offline [Blueprint preparation package](docs/RENDER_DEPLOYMENT_PACKAGE.md) with immutable images; no automatic paid activation
- release-time missing external config must disable the feature explicitly or block deploy; no silent production fallback

## QA assets

- Golden prompt set: `docs/qa/golden-prompts.json`
- Acceptance artifact policy: `docs/acceptance/README.md`
- Store submission assets: `docs/appstore/README.md`
- Operations runbook: `docs/OPERATIONS_TEST_RUNBOOK.md`
- Shared API contract: `packages/shared/schema/openapi.json`
- Refresh command: `python3 scripts/export_openapi_contract.py`

## External integrations requiring real keys

Code paths are implemented, but end-to-end real verification still requires live credentials for:
- Apple / Google IAP
- Printful POD
- Kakao share
- AdMob rewarded ads

Until then, local, mock, or hybrid paths are used for non-production verification.

`./scripts/check-env.sh --mode ci`는 생성·수정 및 조회 요청 한도의 기본값을
API·배포 설정·CI 사이에서 대조합니다. 실제 생성 검증에는 운영 기본 한도를 적용합니다.

## 2026-09-12 제한 베타 운영 제어

운영 템플릿은 새 AI 생성을 초대 계정으로 제한합니다. `GENERATION_ACCESS_MODE`와 `GENERATION_ALLOWED_USER_HASHES`, 읽기 전용 운영 점검 `scripts/check_operations.py`, 중단·최종 승인 절차는 [출시 후보 기록](docs/LAUNCH_CANDIDATE_2026-09-12.md)을 따릅니다.
