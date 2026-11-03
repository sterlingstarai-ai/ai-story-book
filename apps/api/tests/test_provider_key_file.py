"""Private provider-key file inputs; no real credentials or provider calls."""
import os
from pathlib import Path

import pytest
import yaml

from src.core.config import Settings, read_provider_key_file

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def private_dir(tmp_path):
    # macOS may expose the pytest directory through /var's symlink.
    return Path(os.path.realpath(tmp_path))


@pytest.fixture(autouse=True)
def isolate_provider_settings(monkeypatch):
    for name in ('LLM_API_KEY', 'LLM_API_KEY_FILE', 'IMAGE_API_KEY', 'IMAGE_API_KEY_FILE'):
        monkeypatch.delenv(name, raising=False)


def make_key(directory, name='key', value=b'synthetic-secret-key\n'):
    path = directory / name
    path.write_bytes(value)
    path.chmod(0o600)
    return path


def test_private_file_can_supply_same_key_to_both_adapters(private_dir):
    path = make_key(private_dir)
    config = Settings(_env_file=None, llm_api_key_file=str(path), image_api_key_file=str(path))
    assert config.llm_api_key == config.image_api_key == 'synthetic-secret-key'
    assert 'synthetic-secret-key' not in repr(config)
    assert 'synthetic-secret-key' not in str(config.model_dump())
    assert 'synthetic-secret-key' not in config.model_dump_json()


def test_same_key_file_is_read_once_for_consistent_provider_settings(private_dir, monkeypatch):
    path = make_key(private_dir)
    reads = []
    def tracked(value):
        reads.append(value)
        return 'synthetic-secret-key'
    monkeypatch.setattr('src.core.config.read_provider_key_file', tracked)
    config = Settings(_env_file=None, llm_api_key_file=str(path), image_api_key_file=str(path))
    assert config.llm_api_key == config.image_api_key == 'synthetic-secret-key'
    assert reads == [str(path)]


def test_empty_raw_environment_values_do_not_conflict_with_file(private_dir, monkeypatch):
    path = make_key(private_dir)
    monkeypatch.setenv('LLM_API_KEY', '')
    monkeypatch.setenv('IMAGE_API_KEY', '')
    config = Settings(_env_file=None, llm_api_key_file=str(path), image_api_key_file=str(path))
    assert config.llm_api_key == config.image_api_key == 'synthetic-secret-key'


def test_environment_key_stays_supported():
    config = Settings(_env_file=None, llm_api_key='synthetic-llm', image_api_key='synthetic-image')
    assert config.llm_api_key == 'synthetic-llm'
    assert config.image_api_key == 'synthetic-image'


@pytest.mark.parametrize('role', ['llm', 'image'])
def test_raw_key_and_file_are_rejected_without_disclosing_key_or_path(private_dir, role):
    path = make_key(private_dir)
    with pytest.raises(RuntimeError) as error:
        Settings(_env_file=None, **{role + '_api_key': 'sensitive-direct-key', role + '_api_key_file': str(path)})
    assert 'sensitive-direct-key' not in str(error.value)
    assert str(path) not in str(error.value)


@pytest.mark.parametrize('value', [b'', b' ', b'a\nb', b'a\x00b', b'\xff', b'x' * 4097])
def test_invalid_file_contents_are_rejected_without_disclosure(private_dir, value):
    path = make_key(private_dir, value=value)
    with pytest.raises(RuntimeError, match='unavailable or unsafe') as error:
        read_provider_key_file(str(path))
    assert str(path) not in str(error.value)


def test_missing_world_readable_and_wrong_owner_are_rejected(private_dir, monkeypatch):
    path = make_key(private_dir)
    with pytest.raises(RuntimeError):
        read_provider_key_file(str(private_dir / 'missing'))
    path.chmod(0o640)
    with pytest.raises(RuntimeError):
        read_provider_key_file(str(path))
    path.chmod(0o600)
    monkeypatch.setattr('src.core.config.os.geteuid', lambda: -1)
    with pytest.raises(RuntimeError):
        read_provider_key_file(str(path))


def test_symbolic_links_and_relative_paths_are_rejected(private_dir):
    path = make_key(private_dir)
    (private_dir / 'link').symlink_to(path)
    (private_dir / 'dir-link').symlink_to(private_dir, target_is_directory=True)
    for candidate in (private_dir / 'link', private_dir / 'dir-link' / 'key', Path('relative')):
        with pytest.raises(RuntimeError):
            read_provider_key_file(str(candidate))


def test_fifo_is_rejected_without_waiting(private_dir):
    path = private_dir / 'fifo'
    os.mkfifo(path, 0o600)
    with pytest.raises(RuntimeError):
        read_provider_key_file(str(path))


def test_compose_file_inputs_reach_both_services_without_mount_by_default():
    external = yaml.safe_load((ROOT / 'infra/docker-compose.external.yml').read_text())['services']
    production = yaml.safe_load((ROOT / 'infra/docker-compose.prod.yml').read_text())['services']
    for services in (external, production):
        for name in ('api', 'worker'):
            env = services[name]['environment']
            for key in ('LLM_API_KEY_FILE', 'IMAGE_API_KEY_FILE'):
                assert key in env if isinstance(env, dict) else any(item.startswith(key + '=') for item in env)
    override = yaml.safe_load((ROOT / 'infra/docker-compose.provider-key-files.yml').read_text())['services']
    for name in ('api', 'worker'):
        mount = override[name]['volumes'][0]
        assert mount['target'] == '/run/asb-provider-keys' and mount['read_only'] is True
