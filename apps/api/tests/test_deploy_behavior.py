"""Exercise deploy decisions with synthetic env and inert Docker/curl executables."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def deployment(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(ROOT / "scripts/deploy.sh", scripts / "deploy.sh")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text('''#!/bin/bash
case "$*" in
  *"compose version"*) exit 0 ;;
  *"config --services"*) printf '%s\\n' "${FAKE_SERVICES:-postgres}"; exit 0 ;;
  *"pg_dump"*) printf 'synthetic-archive'; exit "${DUMP_EXIT:-0}" ;;
  *"pg_restore --list"*) cat >/dev/null; exit "${RESTORE_EXIT:-0}" ;;
esac
printf '%s|%s\\n' "${API_IMAGE:-}" "${WORKER_IMAGE:-}" >>"$FAKE_DOCKER_LOG"
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
