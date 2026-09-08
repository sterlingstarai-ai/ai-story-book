# AI Story Book

AI Story Book is a production-oriented storybook platform with a Flutter mobile app and a FastAPI backend. The current repository includes P0-P4 product scope plus a P5 hardening sweep focused on deterministic gates, image-based deployment, explicit feature availability, and stronger operational visibility.

Current launch decisions, remaining owner actions, and verification boundaries: [Launch status](docs/LAUNCH_STATUS.md).

## Release status — 2026-09-06

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
PostgreSQL also checks that photo publication and withdrawal serialize for one
account without blocking another account. Live AI/store acceptance remains separate.

For a synthetic PostgreSQL/private-media backup and restore check, run
`./scripts/run_backup_restore_rehearsal.sh`. It compares restored database and media
checksums in a second isolated stack. The operational procedure is in
[docs/BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md).

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
