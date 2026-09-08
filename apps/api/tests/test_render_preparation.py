"""Render package remains offline, immutable-image based and gated on TLS/secrets."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from src.ops import render_entrypoint as launcher

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('render_preparation_test', ROOT / 'scripts/prepare_render_blueprint.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


@pytest.fixture
def release():
    sha = '0123456789abcdef0123456789abcdef01234567'
    return {'commit_sha': sha, 'api_image': f'ghcr.io/sterlingstarai-ai/ai-story-book/api:{sha}',
            'worker_image': f'ghcr.io/sterlingstarai-ai/ai-story-book/worker:{sha}', 'ci_status': 'success',
            'ci_run_url': 'https://github.com/sterlingstarai-ai/ai-story-book/actions/runs/12345'}


@pytest.mark.parametrize('key,value', [
    ('commit_sha', 'latest'), ('commit_sha', 'a' * 40), ('ci_status', 'pending'),
    ('api_image', 'ghcr.io/sterlingstarai-ai/ai-story-book/api:latest'),
    ('worker_image', 'ghcr.io/other-project/worker:' + 'b' * 40),
    ('ci_run_url', 'https://other.invalid/sensitive-value'),
])
def test_incomplete_or_mismatched_release_cannot_create_blueprint(release, key, value):
    with pytest.raises(ValueError):
        prepare.prepare({**release, key: value}, registry_credential='storybook-ghcr-read')


def test_blueprint_contains_only_three_paid_services_and_no_embedded_secrets(release):
    text = prepare.prepare(release, registry_credential='storybook-ghcr-read')
    doc = yaml.safe_load(text)
    assert doc['previews']['generation'] == 'off'
    api, worker, redis = doc['services']
    assert [service['plan'] for service in doc['services']] == ['0.5c-512mb', '1c-2g', '256mb']
    assert 'databases' not in doc and 'envVarGroups' not in doc
    for service in [api, worker]:
        assert service['runtime'] == 'image'
        assert service['autoDeployTrigger'] == 'off'
        assert service['numInstances'] == 1 and 'scaling' not in service
        assert service['image']['url'].endswith(release['commit_sha'])
        assert service['maxShutdownDelaySeconds'] == 300
        assert service['image']['creds']['fromRegistryCreds']['name'] == 'storybook-ghcr-read'
    env = {item['key']: item for item in api['envVars']}
    for key in ['DATABASE_URL', 'S3_ACCESS_KEY', 'S3_SECRET_KEY', 'LLM_API_KEY', 'IMAGE_API_KEY', 'ADMIN_API_KEY']:
        assert env[key] == {'key': key, 'sync': False}
    assert env['DATABASE_SSL_ROOT_CERT']['value'] == '/etc/secrets/supabase-ca.crt'
    assert env['DATABASE_SSL_MODE']['value'] == 'verify-full'
    assert env['S3_AUTO_CREATE_BUCKET']['value'] == 'false'
    assert env['S3_ADDRESSING_STYLE']['value'] == 'path'
    assert env['REDIS_URL']['fromService'] == {'name': redis['name'], 'type': 'keyvalue', 'property': 'connectionString'}
    for key in ['PHOTO_PROCESSING_ENABLED', 'PURCHASES_ENABLED', 'AUDIO_FEATURE_ENABLED', 'POD_ORDERING_ENABLED']:
        assert env[key]['value'] == 'false'
    assert all(v['fromService']['name'] == api['name'] for v in worker['envVars'])
    assert redis['ipAllowList'] == []
    assert redis['persistenceMode'] == 'journal-snapshot' and redis['maxmemoryPolicy'] == 'noeviction'
    assert api['healthCheckPath'] == '/health/ready'
    assert api['preDeployCommand'] == 'python -m src.ops.render_entrypoint migrate'
    assert 'secretFiles:' not in text  # Not a supported Blueprint field; dashboard secret file required.


def test_generator_does_not_overwrite_or_echo_untrusted_manifest(release, tmp_path, capsys):
    evidence = tmp_path / 'release.json'
    evidence.write_text(json.dumps(release))
    output = tmp_path / 'render.yaml'
    args = ['--release-manifest', str(evidence), '--registry-credential-name', 'storybook-ghcr-read', '--output', str(output)]
    assert prepare.main(args) == 0
    original = output.read_bytes()
    assert prepare.main(args) == 1
    assert output.read_bytes() == original
    release['api_image'] = 'sensitive-value'
    evidence.write_text(json.dumps(release))
    assert prepare.main(args) == 1
    assert 'sensitive-value' not in capsys.readouterr().out


@pytest.mark.parametrize('base', ['redis://internal:6379', 'redis://user:p%40ss%25word@internal:6379/0',
                                  'rediss://user:p%40ss@internal:6379/'])
def test_render_redis_urls_preserve_credentials_and_database_separation(base):
    result = launcher.redis_databases(base)
    for index, key in enumerate(['REDIS_URL', 'CELERY_BROKER_URL', 'CELERY_RESULT_BACKEND']):
        assert result[key] == base.rstrip('/0') + f'/{index}'


@pytest.mark.parametrize('base', ['http://internal', 'redis://', 'redis://internal:bad',
                                  'redis://internal/2', 'redis://internal?password=secret-value'])
def test_invalid_render_redis_fails_without_echoing_the_url(base):
    with pytest.raises(ValueError) as error:
        launcher.redis_databases(base)
    assert base not in str(error.value)


@pytest.fixture
def runtime(monkeypatch):
    config = SimpleNamespace(database_url='postgresql://user:secret@db.host/postgres',
        database_ssl_mode='verify-full', database_ssl_root_cert='/etc/secrets/supabase-ca.crt',
        s3_addressing_style='path', s3_auto_create_bucket=False, debug=False, testing=False, use_celery=True,
        redis_url='redis://user:secret@internal:6379')
    monkeypatch.setattr(launcher, 'Path', lambda _: SimpleNamespace(is_file=lambda: True))
    tls = Mock(return_value=('postgresql+asyncpg://db', {}))
    monkeypatch.setattr('src.core.database_options.database_options', tls)
    return config, tls


def test_launcher_validates_tls_then_execs_original_process_without_secrets_in_argv(runtime, monkeypatch, capsys):
    config, tls = runtime
    monkeypatch.setattr('src.core.config.settings', config)
    execute = Mock()
    monkeypatch.setattr(launcher.os, 'execvpe', execute)
    assert launcher.main(['worker']) == 0
    command, args, env = execute.call_args.args
    assert command == 'celery' and args[:3] == ['celery', '-A', 'src.worker']
    assert 'secret' not in ' '.join(args)
    assert env['CELERY_BROKER_URL'].endswith('/1') and env['CELERY_RESULT_BACKEND'].endswith('/2')
    tls.assert_called_once_with(config.database_url, asynchronous=True, ssl_mode='verify-full',
                               ssl_root_cert='/etc/secrets/supabase-ca.crt')
    assert 'secret' not in capsys.readouterr().out


@pytest.mark.parametrize('field,value', [('database_ssl_mode', 'require'), ('s3_auto_create_bucket', True),
                                       ('s3_addressing_style', 'virtual'), ('use_celery', False), ('testing', True)])
def test_launcher_rejects_unsafe_runtime_before_exec(runtime, monkeypatch, field, value):
    config, _ = runtime
    setattr(config, field, value)
    monkeypatch.setattr('src.core.config.settings', config)
    execute = Mock()
    monkeypatch.setattr(launcher.os, 'execvpe', execute)
    assert launcher.main(['api']) == 1
    execute.assert_not_called()


def test_missing_ca_secret_file_prevents_start(runtime, monkeypatch):
    config, _ = runtime
    monkeypatch.setattr(launcher, 'Path', lambda _: SimpleNamespace(is_file=lambda: False))
    with pytest.raises(ValueError, match='Secret File is missing'):
        launcher.launch_environment(config, {})


def test_new_paid_feature_settings_reach_api_and_worker_in_all_topologies(release):
    required = {'APPLE_APP_ID', 'APPLE_BUNDLE_ID', 'APPLE_NOTIFICATION_ENVIRONMENT', 'APPLE_ROOT_CA_PATHS',
                'GOOGLE_RTDN_AUDIENCE', 'GOOGLE_RTDN_SERVICE_ACCOUNT_EMAIL', 'STT_MODEL'}
    for name in ['docker-compose.yml', 'docker-compose.prod.yml', 'docker-compose.external.yml']:
        services = yaml.safe_load((ROOT / 'infra' / name).read_text())['services']
        for role in ['api', 'worker']:
            env = services[role]['environment']
            keys = set(env) if isinstance(env, dict) else {item.split('=', 1)[0] for item in env}
            assert required <= keys, (name, role, required - keys)
    api, worker, _ = yaml.safe_load(prepare.prepare(release, registry_credential='storybook-ghcr-read'))['services']
    for service in [api, worker]:
        assert required <= {item['key'] for item in service['envVars']}


def test_disabled_optional_integrations_do_not_break_render_settings_startup(release):
    from src.core.config import Settings

    api = yaml.safe_load(prepare.prepare(release, registry_credential='storybook-ghcr-read'))['services'][0]
    values = {item['key'].lower(): item['value'] for item in api['envVars'] if 'value' in item}
    values.update(database_url='sqlite+aiosqlite:///:memory:', redis_url='redis://localhost:6379/0')
    config = Settings(_env_file=None, **values)
    assert config.printful_sync_variant_id == 0
    assert config.apple_app_id == 0
    assert config.purchases_enabled is False
    assert config.pod_ordering_enabled is False
