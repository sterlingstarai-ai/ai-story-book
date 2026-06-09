# AI Story Book

AI Story Book is a production-oriented storybook platform with a Flutter mobile app and a FastAPI backend. The current repository includes P0-P4 product scope plus a P5 hardening sweep focused on deterministic gates, image-based deployment, explicit feature availability, and stronger operational visibility.

## Current state

- Mobile app: implemented for iOS and Android in `apps/mobile`
- Backend API: implemented in `apps/api`
- Deployment model: GHCR image tag -> production compose pull -> up
- Quality gate: repository-root `./scripts/phase-gate.sh`
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

## Production deployment

Production deploy is image-based. The repository is not the build artifact; tagged container images are.

```bash
./scripts/deploy.sh --env-file infra/.env --image-tag <git-sha> deploy
```

Key properties:
- `infra/docker-compose.prod.yml` uses `image:` for `api` and `worker`
- `scripts/deploy.sh` supports `--env-file`, `--compose-file`, `--image-tag`
- health validation runs against `http://localhost/health/live` and `/health/ready`

More detail: `docs/DEPLOYMENT.md`

## Configuration rules

- API settings load from `apps/api/.env`, not the repository root `.env`
- unrelated root env keys should not break API test execution
- production env validation uses `./scripts/check-env.sh --mode production --env-file infra/.env`
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
