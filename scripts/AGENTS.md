# SCRIPT AND OPERATIONS GUIDANCE

## SCOPE

- Applies to repository-level QA, contract generation, E2E, load, acceptance, and deployment tools.
- Invoke repository-wide scripts from the repository root unless the script documents another working directory.
- Shell entry points must derive `ROOT_DIR` from `BASH_SOURCE`; never depend on the caller's current directory.
- Keep non-interactive scripts fail-fast with `set -euo pipefail`; preserve cleanup traps for spawned processes and temporary databases.

## GATE MATRIX

- Canonical fast gate:
  - `./scripts/check-env.sh --mode ci`
  - `./scripts/phase-gate.sh`
- Optional phase-gate flags are additive:
  - `--with-mobile-build`: Android debug APK.
  - `--with-ios-build`: iOS no-codesign build; macOS/Xcode required.
  - `--with-api-smoke`: requires an already-running API; override with `API_SMOKE_BASE_URL`.
- `flutter-ui-preflight.sh` combines a focused widget test, source inventory, and the manual checklist. Inventory counts are diagnostic, not behavioral proof.
- `run_integration.sh` needs a Flutter device/simulator; default device is `macos`.
- `run_live_e2e.sh` runs Uvicorn with SQLite and mock providers. It proves the FastAPI background-generation path, not Postgres, Celery, S3, or live providers.
- `final-external-preflight.sh` checks ambient release credentials only. It does not load an env file or perform live store/provider calls.

## ENVIRONMENT OWNERSHIP

- Local API runtime values: `apps/api/.env`.
- Production Compose values: `infra/.env`.
- CI test values: explicit job `env` blocks in `.github/workflows/ci.yml`.
- Mobile release values: explicit `--dart-define` arguments; never assume backend env propagation.
- `check-env.sh --mode local` validates API names; `--mode production` validates Compose names; `--mode ci` validates repository contract files.
- Env files loaded by shell scripts must remain valid shell assignment syntax as well as Compose dotenv syntax.
- Never print, commit, copy into artifacts, or pass secrets on process command lines.
- When adding a runtime variable, update its owner, validator, example, schema, Compose forwarding, and CI fixture together.

## OPERATOR-SENSITIVE COMMANDS

- Require explicit operator intent before `deploy.sh deploy|start|stop|restart|migrate|cleanup|backup`.
- `deploy.sh cleanup` prunes Docker resources across the host, not only this Compose project.
- Preserve SHA-tagged API and worker selection. An env-file image override must not silently defeat `--image-tag`.
- Do not validate deployment changes by touching a real host. Prefer syntax/config inspection and documented dry checks.
- `smoke.sh` is stateful: it attempts book creation. Confirm the target URL before running it outside disposable environments.
- `load_test.py` defaults to real API calls and 100 jobs. Use `--mock` or `--simulate` unless real cost and state mutation are explicitly approved.
- `load_test.py --test-stuck --db-url ...` inserts rows directly and may wait up to 15 minutes.
- `long_running_test.py` is synthetic simulation; never present its results as service capacity evidence.
- `quality_check.py` is imported by the API golden harness. Preserve `run_quality_check`, report fields, and threshold semantics.

## GENERATED OUTPUTS

- `export_openapi_contract.py` is the sole writer for committed `packages/shared/schema/openapi.json`.
- `build-acceptance-artifacts.sh` writes ignored timestamped bundles under `docs/acceptance/`; partial bundles may remain after failure.
- Load tools write ignored output under `results/` by default.
- `run_live_e2e.sh` owns `apps/api/live_e2e.db` and its temporary server log; cleanup must run on every exit path.
- Database backups contain production data. Do not generate, inspect, stage, or relocate them without explicit authorization.

## SYNC OBLIGATIONS

- Script behavior changes must stay aligned with `.github/workflows/ci.yml`, `README.md`, `docs/DEPLOYMENT.md`, and `docs/OPERATIONS_TEST_RUNBOOK.md`.
- Environment changes must stay aligned with `env.schema.json`, both `.env.example` files, and both Compose files.
- Gate changes must preserve CI's Python 3.11 and Flutter 3.38.7 assumptions.
- Keep smoke endpoints aligned with nginx routing and `/health/ready` readiness semantics.
- Do not turn mock, structural, inventory, or simulated checks into claims of live integration or content quality.

## VERIFICATION

- Shell-only edit: `bash -n scripts/<changed-script>.sh`, then run its safe `--help` or focused non-mutating mode.
- Quality checker edit: `python3 scripts/quality_check.py --mock --ci --threshold 0.85`.
- OpenAPI exporter edit: regenerate, then `cd apps/api && python -m pytest tests/test_openapi_contract.py -q`.
- Cross-stack gate edit: run the canonical fast gate; add only the optional build/smoke flags affected by the change.
- Never use production deploy, cleanup, backup, real smoke, or real load as routine verification.
