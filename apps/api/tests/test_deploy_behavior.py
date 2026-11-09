"""Exercise deploy decisions with synthetic env and inert Docker/curl executables."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
PREVIOUS_API_ID = "sha256:" + "a" * 64
PREVIOUS_WORKER_ID = "sha256:" + "b" * 64
FIXTURE_CONFIG_HASH = "c" * 64


@pytest.fixture
def deployment(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for script in ("deploy.sh", "final-external-preflight.sh", "final_external_preflight.py"):
        shutil.copy2(ROOT / "scripts" / script, scripts / script)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text('''#!/bin/bash
printf '%s\n' "$*" >>"$FAKE_COMPOSE_ARGS_LOG"
case "$*" in
  *"compose version"*) exit 0 ;;
  *"ps -q api"*) if [ "${FAKE_RUNNING_STACK:-0}" = 1 ]; then echo fixture-api; fi; exit 0 ;;
  *"ps -q worker"*) if [ "${FAKE_RUNNING_STACK:-0}" = 1 ]; then echo fixture-worker; fi; exit 0 ;;
  *"ps --all --quiet api"*) echo fixture-api; exit 0 ;;
  *"ps --all --quiet worker"*) printf '%s\n' fixture-worker fixture-worker-2; exit 0 ;;
  *"config --hash api"*) echo "api $FAKE_CONFIG_HASH"; exit 0 ;;
  *"config --hash worker"*) echo "worker $FAKE_CONFIG_HASH"; exit 0 ;;
  *"exec fixture-worker-2 "*) exit "${FAKE_SECOND_WORKER_PING_EXIT:-0}" ;;
  *"exec fixture-worker "*) exit 0 ;;
  *"inspect --format"*"fixture-api")
    binding="true $FAKE_PREVIOUS_API_ID"
    if [[ "$*" == *com.docker.compose.config-hash* ]]; then binding="$binding $FAKE_CONFIG_HASH"; fi
    echo "$binding"
    exit 0 ;;
  *"inspect --format"*"fixture-worker"*)
    binding="true $FAKE_PREVIOUS_WORKER_ID"
    if [[ "$*" == *fixture-worker-2 && "${FAKE_ROLLBACK_WRONG_ID:-0}" == 1 ]]; then
      binding="true $FAKE_PREVIOUS_API_ID"
    fi
    if [[ "$*" == *com.docker.compose.config-hash* ]]; then binding="$binding $FAKE_CONFIG_HASH"; fi
    echo "$binding"
    exit 0 ;;
  *"config --services"*) printf '%s\\n' "${FAKE_SERVICES:-postgres}"; exit 0 ;;
  *"pg_dump"*) printf 'synthetic-archive'; exit "${DUMP_EXIT:-0}" ;;
  *"pg_restore --list"*) cat >/dev/null; exit "${RESTORE_EXIT:-0}" ;;
esac
printf '%s|%s\\n' "${API_IMAGE:-}" "${WORKER_IMAGE:-}" >>"$FAKE_DOCKER_LOG"
if [[ "$*" == *' up -d' && "${API_IMAGE:-}" != "$FAKE_PREVIOUS_API_ID" ]]; then
  exit "${FAKE_START_EXIT:-0}"
fi
''')
    curl = bindir / "curl"
    curl.write_text('''#!/bin/bash
printf '%s\\n' "$*" >>"$FAKE_CURL_LOG"
printf '%s' "${HTTP_CODE:-200}"
exit "${CURL_EXIT:-0}"
''')
    docker.chmod(0o755)
    curl.chmod(0o755)
    env_file = tmp_path / "configuration.env"
    env_file.write_text("PROD_API_URL=https://api.storybook.invalid\nDB_USER=fixture\nDB_NAME=fixture\n"
                        "IMAGE_REPOSITORY=fixture/storybook\nAPI_IMAGE=old/api:stale\nWORKER_IMAGE=old/worker:stale\n")
    env = {"PATH": str(bindir) + os.pathsep + os.environ["PATH"],
           "FAKE_DOCKER_LOG": str(tmp_path / "docker.log"), "FAKE_CURL_LOG": str(tmp_path / "curl.log"),
           "FAKE_COMPOSE_ARGS_LOG": str(tmp_path / "compose-args.log"),
           "FAKE_PREVIOUS_API_ID": PREVIOUS_API_ID, "FAKE_PREVIOUS_WORKER_ID": PREVIOUS_WORKER_ID,
           "FAKE_CONFIG_HASH": FIXTURE_CONFIG_HASH,
           "HEALTH_WAIT_RETRIES": "1", "HEALTH_WAIT_INTERVAL": "0"}

    def invoke(command, *options, **variables):
        return subprocess.run(["bash", str(scripts / "deploy.sh"), "--env-file", str(env_file),
                               *options, command], env={**env, **variables}, cwd="/tmp",
                              capture_output=True, text=True, timeout=10)
    return invoke, tmp_path, env_file


def test_explicit_image_tag_overrides_stale_image_environment(deployment):
    invoke, directory, _ = deployment
    result = invoke("status", "--image-tag", "abc123")
    assert result.returncode == 0, result.stderr
    assert (directory / "docker.log").read_text().strip() == (
        "ghcr.io/fixture/storybook/api:abc123|ghcr.io/fixture/storybook/worker:abc123")


def test_repeated_compose_files_are_forwarded_in_order(deployment):
    invoke, directory, _ = deployment
    result = invoke('status', '--compose-file', 'base.yml', '--compose-file', 'private-keys.yml')
    assert result.returncode == 0, result.stderr
    assert '-f base.yml -f private-keys.yml ps' in (directory / 'compose-args.log').read_text()


def test_deploy_rolls_back_after_service_start_failure(deployment):
    invoke, directory, _ = deployment
    result = invoke("deploy", FAKE_RUNNING_STACK="1", FAKE_START_EXIT="1")
    assert result.returncode != 0
    assert "Rollback restored health" in result.stdout
    assert "Services started" not in result.stdout
    assert f"{PREVIOUS_API_ID}|{PREVIOUS_WORKER_ID}" in (directory / "docker.log").read_text()
    assert "up -d --no-deps --pull never api worker" in (directory / "compose-args.log").read_text()


def test_rollback_fails_if_any_restored_replica_uses_the_wrong_image(deployment):
    invoke, directory, _ = deployment
    result = invoke("deploy", FAKE_RUNNING_STACK="1", FAKE_START_EXIT="1", FAKE_ROLLBACK_WRONG_ID="1")
    assert result.returncode != 0
    assert "Rollback could not restore the expected images and health" in result.stdout
    assert "Rollback restored health" not in result.stdout
    assert not (directory / "curl.log").exists()


def test_runtime_rollback_requires_separate_previous_environment(deployment):
    invoke, _, env_file = deployment
    result = invoke("deploy", "--rollback-env-file", str(env_file), FAKE_RUNNING_STACK="1")
    assert result.returncode != 0
    assert "separate previous env file" in result.stdout
    assert "Pulling configured images" not in result.stdout


def test_previous_compose_files_require_a_previous_env(deployment):
    invoke, directory, _ = deployment
    result = invoke("deploy", "--rollback-compose-file", "previous.yml")
    assert result.returncode != 0
    assert "--rollback-compose-file requires --rollback-env-file" in result.stdout
    assert not (directory / "compose-args.log").exists()


@pytest.mark.parametrize(("command", "enabled"), [("deploy", "true"), ("start", "YES"), ("deploy", "t")])
def test_free_beta_preflight_blocks_before_docker_mutations(deployment, command, enabled):
    invoke, directory, env_file = deployment
    with env_file.open("a") as config:
        config.write(f"FREE_PLAN_FIRST_BOOK_TRIAL={enabled}\nLLM_API_KEY=synthetic-secret-value\n")
    result = invoke(command)
    assert result.returncode != 0
    assert "Checking free beta release configuration" in result.stdout
    assert "BUNDLED_POLICY_DOCUMENTS" in result.stdout
    assert "synthetic-secret-value" not in result.stdout + result.stderr
    assert not (directory / "docker.log").exists()
    assert not (directory / "curl.log").exists()


def test_health_uses_https_and_requires_exact_200(deployment):
    invoke, directory, _ = deployment
    assert invoke("health").returncode == 0
    calls = (directory / "curl.log").read_text()
    assert "https://api.storybook.invalid/health/ready" in calls
    assert "--proto =https" in calls
    assert "--location" not in calls and "--insecure" not in calls
    assert invoke("health", HTTP_CODE="301").returncode != 0
    assert invoke("health", HTTP_CODE="503").returncode != 0
    assert invoke("health", HTTP_CODE="200", CURL_EXIT="60").returncode != 0


def test_health_fails_when_any_worker_does_not_answer_its_targeted_ping(deployment):
    invoke, directory, _ = deployment
    result = invoke("health", FAKE_SECOND_WORKER_PING_EXIT="1")
    assert result.returncode != 0
    assert "Readiness check passed" in result.stdout
    assert "Celery workers did not respond through the broker" in result.stdout
    calls = (directory / "compose-args.log").read_text()
    assert 'exec fixture-worker-2 sh -c' in calls
    assert '--destination="celery@$(hostname)" ping' in calls


@pytest.mark.parametrize("url", ["http://api.storybook.invalid", "https://user:pass@api.storybook.invalid",
                                 "https://api.storybook.invalid/path", "https://"])
def test_invalid_health_target_rejected_without_network(deployment, url):
    invoke, directory, env_file = deployment
    env_file.write_text(f"PROD_API_URL={url}\n")
    assert invoke("health").returncode != 0
    assert not (directory / "curl.log").exists()


def test_backup_publishes_only_complete_private_archive(deployment):
    invoke, directory, _ = deployment
    assert invoke("backup").returncode == 0
    archives = list((directory / "backups").iterdir())
    assert len(archives) == 1 and archives[0].suffix == ".dump"
    assert archives[0].stat().st_mode & 0o777 == 0o600
    assert (directory / "backups").stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("failure", [{"DUMP_EXIT": "1"}, {"RESTORE_EXIT": "1"}])
def test_failed_backup_discards_partial_output(deployment, failure):
    invoke, directory, _ = deployment
    assert invoke("backup", **failure).returncode != 0
    assert list((directory / "backups").iterdir()) == []


def test_external_backup_does_not_try_an_internal_postgres_container(deployment):
    invoke, directory, _ = deployment
    result = invoke("backup", FAKE_SERVICES="api\nworker\nredis")
    assert result.returncode != 0
    assert "backup_external.py" in result.stdout
    assert not (directory / "backups").exists()
