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

## 4. Runtime health checks

Against a live API host:

```bash
./scripts/smoke.sh http://127.0.0.1:8000
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
```

Interpretation:
- `200 /health/live`: process is up
- `200 /health/ready`: dependencies are healthy enough for traffic
- `503 /health/ready`: service is up but not ready

## 5. Local docker runtime

```bash
cp -n infra/.env.example infra/.env
./scripts/check-env.sh --mode production --env-file infra/.env

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
./scripts/smoke.sh http://localhost
```

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

Until those keys are present, use mock or hybrid validation paths and do not mark the integration as production-verified.

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
