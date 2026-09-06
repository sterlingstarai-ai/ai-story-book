"""An external hosting package does not create databases, weaken gates, or leak keys."""

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('external_config_preflight', ROOT / 'scripts/final_external_preflight.py')
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


@pytest.fixture
def infrastructure():
    return {'DATABASE_URL': 'postgresql+asyncpg://postgres.project:synthetic-secret@aws-0.pooler.supabase.com:5432/postgres',
            'DATABASE_SSL_MODE': 'verify-full', 'DATABASE_SSL_ROOT_CERT': '/run/storybook-certs/provider.crt',
            'S3_ENDPOINT': 'https://project.storage.supabase.co/storage/v1/s3', 'S3_REGION': 'ap-northeast-2',
            'S3_ADDRESSING_STYLE': 'path', 'S3_AUTO_CREATE_BUCKET': 'false',
            'API_IMAGE': 'ghcr.io/repo/api:' + 'a' * 40, 'WORKER_IMAGE': 'ghcr.io/repo/worker@sha256:' + 'b' * 64}


def test_external_infrastructure_is_configuration_only(infrastructure):
    assert preflight.external_infrastructure_errors(infrastructure) == []


@pytest.mark.parametrize('name,value', [
    ('DATABASE_SSL_MODE', 'require'), ('DATABASE_SSL_ROOT_CERT', ''),
    ('DATABASE_URL', 'postgresql://user:sensitive-value@aws-0.pooler.supabase.com:6543/postgres'),
    ('DATABASE_URL', 'postgresql://user:sensitive-value@db.host:5432/postgres?sslmode=disable'),
    ('DATABASE_MIGRATION_URL', 'postgresql://user:sensitive-value@db.host:5432/postgres?sslrootcert=/other'),
    ('DATABASE_URL', 'sqlite:///./test.db'), ('S3_REGION', ''), ('S3_ADDRESSING_STYLE', 'virtual'),
    ('S3_AUTO_CREATE_BUCKET', 'true'), ('S3_ENDPOINT', 'http://storage.invalid'),
    ('API_IMAGE', 'ghcr.io/repo/api:latest'), ('WORKER_IMAGE', 'ghcr.io/repo/worker:stable'),
])
def test_external_settings_fail_closed_without_secret_output(infrastructure, name, value):
    errors = preflight.external_infrastructure_errors({**infrastructure, name: value})
    assert any(item.startswith(name) for item in errors)
    assert 'sensitive-value' not in json.dumps(errors)


def test_compose_external_runs_only_resident_services_with_private_redis_and_shared_tls():
    services = yaml.safe_load((ROOT / 'infra/docker-compose.external.yml').read_text())['services']
    assert set(services) == {'api', 'worker', 'redis'}
    api, worker, redis = (services[name] for name in ['api', 'worker', 'redis'])
    assert api['environment'] == worker['environment']
    env = api['environment']
    assert env['S3_ADDRESSING_STYLE'] == 'path'
    assert env['S3_AUTO_CREATE_BUCKET'] == 'false'
    assert env['USE_CELERY'] == 'true'
    assert env['DEBUG'] == env['TESTING'] == 'false'
    assert env['PHOTO_PROCESSING_ENABLED'] == '${PHOTO_PROCESSING_ENABLED:-false}'
    assert 'verify-full' in env['DATABASE_SSL_MODE']
    assert 'DATABASE_URL:?' in env['DATABASE_URL']
    assert 'postgres' not in api['depends_on']
    assert api['volumes'] == worker['volumes'] == ['./certs:/run/storybook-certs:ro']
    assert api['ports'][0].startswith('127.0.0.1:')
    assert 'ports' not in redis
    assert '--appendonly yes' in redis['command'] and '--maxmemory-policy noeviction' in redis['command']
    assert redis['volumes'] == ['redis-data:/data']
    assert api['healthcheck']['test'][-1].endswith('/health/ready')


def test_new_settings_forwarded_in_existing_compose_and_schema_examples():
    names = {'DATABASE_SSL_MODE', 'DATABASE_SSL_ROOT_CERT', 'DATABASE_MIGRATION_URL',
             'S3_REGION', 'S3_ADDRESSING_STYLE', 'S3_AUTO_CREATE_BUCKET'}
    schema = json.loads((ROOT / 'env.schema.json').read_text())['properties']
    assert names <= schema.keys()
    for name in ['apps/api/.env.example', 'infra/.env.example', 'infra/.env.external.example']:
        text = (ROOT / name).read_text()
        assert all(f'{key}=' in text for key in names)
    for name in ['infra/docker-compose.yml', 'infra/docker-compose.prod.yml']:
        services = yaml.safe_load((ROOT / name).read_text())['services']
        for service in ['api', 'worker']:
            keys = {item.split('=', 1)[0] for item in services[service]['environment']}
            assert names <= keys


def test_external_check_requires_an_explicit_file():
    result = subprocess.run(['bash', str(ROOT / 'scripts/check-env.sh'), '--mode', 'external'],
                            capture_output=True, text=True, env={'PATH': '/usr/bin:/bin'})
    assert result.returncode == 1
    assert 'requires --env-file' in result.stdout
