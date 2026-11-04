"""Public-only build inputs cannot leak backend keys or bypass release URL checks."""

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('mobile_release_preparation', ROOT / 'scripts/build_mobile_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def valid():
    return {'PROD_API_URL': 'https://storybook-api.onrender.com',
            'PRIVACY_POLICY_URL': 'https://storybook-policy.vercel.app/privacy',
            'TERMS_OF_SERVICE_URL': 'https://storybook-policy.vercel.app/terms'}


@pytest.mark.parametrize('name', ['LLM_API_KEY', 'ADMIN_API_KEY', 'DATABASE_URL', 'S3_SECRET_KEY'])
def test_backend_fields_are_rejected_before_build(name):
    with pytest.raises(ValueError, match='public mobile build fields'):
        release.release_configuration({**valid(), name: 'secret-not-for-mobile'})


@pytest.mark.parametrize('value', ['http://story.app', 'https://localhost', 'https://127.0.0.1',
                                  'https://demo.invalid', 'https://example.com', 'https://replace-me.onrender.com',
                                  'https://user:password@story.app', 'https://story.app/api', 'https://story.app/?token=hidden'])
def test_invalid_api_origins_fail_before_build(value):
    with pytest.raises(ValueError):
        release.release_configuration({**valid(), 'PROD_API_URL': value})


def test_missing_legal_url_and_blank_kakao_key_fail_before_build():
    values = valid()
    values.pop('PRIVACY_POLICY_URL')
    with pytest.raises(ValueError):
        release.release_configuration(values)
    with pytest.raises(ValueError):
        release.release_configuration({**valid(), 'KAKAO_NATIVE_APP_KEY': ''})


@pytest.mark.parametrize('name,value', [
    ('PROD_API_URL', 'https://8.8.8.8'),
    ('PROD_API_URL', 'https://api.example.org'),
    ('PROD_API_URL', 'https://api.story.app?'),
    ('PRIVACY_POLICY_URL', ' https://story.app/privacy'),
    ('PRIVACY_POLICY_URL', 'https://story.app/privacy?draft=1'),
    ('TERMS_OF_SERVICE_URL', 'https://story.app/terms#'),
])
def test_release_builder_rejects_urls_the_app_cannot_use(name, value):
    with pytest.raises(ValueError):
        release.release_configuration({**valid(), name: value})


def test_release_commands_keep_no_coded_api_credentials_and_no_publication():
    values = release.release_configuration(valid())
    android = release.build_command('android', values)
    ios = release.build_command('ios', values)
    assert android[:4] == ['flutter', 'build', 'appbundle', '--release']
    assert ios[:5] == ['flutter', 'build', 'ios', '--release', '--no-codesign']
    for command in (android, ios):
        assert len([item for item in command if item.startswith('--dart-define=')]) == 3
        assert not any('upload' in item or 'publish' in item for item in command)
