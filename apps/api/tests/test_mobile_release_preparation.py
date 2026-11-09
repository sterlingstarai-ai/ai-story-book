"""Public-only build inputs cannot leak backend keys or bypass release URL checks."""

import hashlib
import importlib.util
import json
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
            'PRIVACY_POLICY_URL': 'https://storybook-policy.vercel.app/privacy/',
            'TERMS_OF_SERVICE_URL': 'https://storybook-policy.vercel.app/terms/'}


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


@pytest.mark.parametrize('platform', ['ios', 'android'])
@pytest.mark.parametrize('document_status', ['draft', 'approved_future', 'approved_with_draft_label'])
def test_execute_blocks_unready_bundled_documents(tmp_path, monkeypatch, capsys, platform, document_status):
    monkeypatch.setattr(release, 'ROOT', tmp_path)
    legal = tmp_path / 'apps/mobile/assets/legal'
    legal.mkdir(parents=True)
    for slug in ('privacy', 'terms'):
        effective_date = '2999-01-01' if document_status == 'approved_future' else '2000-01-01'
        version_label = f'시행일 {effective_date}'
        if document_status == 'approved_with_draft_label':
            version_label += ' 검토본'
        (legal / f'{slug}.ko.json').write_text(json.dumps({
            'publication_status': 'draft' if document_status == 'draft' else 'approved',
            'effective_date': effective_date,
            'operator': 'Test operator', 'contact_email': 'qa@example.com',
            'title': 'Test document', 'introduction': 'Synthetic text', 'version_label': version_label,
            'sections': [{'heading': 'Heading', 'paragraphs': ['Test policy']}],
        }))
    config = tmp_path / 'public-build.json'
    config.write_text(json.dumps(valid()))
    monkeypatch.setattr(release.subprocess, 'run', lambda *args, **kwargs: pytest.fail('Compiler invoked'))
    monkeypatch.setattr(release, 'verify_published', lambda *args, **kwargs: pytest.fail('Public site contacted'))

    assert release.main(['--config', str(config), '--platform', platform, '--execute',
                         '--support-site-config', str(tmp_path / 'site.json')]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'BLOCKED'
    assert 'Bundled privacy and terms' in result['message']


@pytest.mark.parametrize('platform,relative_output,hash_field', [
    ('ios', 'ios/iphoneos/Runner.app/Runner', 'ios_executable_sha256'),
    ('android', 'app/outputs/bundle/release/app-release.aab', 'artifact_sha256'),
])
@pytest.mark.parametrize('has_artifact', [True, False])
def test_execute_requires_approved_documents_and_expected_artifact(
    tmp_path, monkeypatch, capsys, platform, relative_output, hash_field, has_artifact,
):
    monkeypatch.setattr(release, 'ROOT', tmp_path)
    monkeypatch.setattr(release.shutil, 'which', lambda name: f'/tools/{name}')
    legal = tmp_path / 'apps/mobile/assets/legal'
    legal.mkdir(parents=True)
    for slug in ('privacy', 'terms'):
        (legal / f'{slug}.ko.json').write_text(json.dumps({
            'publication_status': 'approved', 'effective_date': '2000-01-01',
            'operator': 'Test operator', 'contact_email': 'qa@example.com',
            'title': 'Test document', 'introduction': 'Synthetic text', 'version_label': '시행일 2000-01-01',
            'sections': [{'heading': 'Heading', 'paragraphs': ['Test policy']}],
        }))
    config = tmp_path / 'public-build.json'
    config.write_text(json.dumps(valid()))
    if platform == 'android':
        signing = tmp_path / 'apps/mobile/android/key.properties'
        signing.parent.mkdir()
        signing.touch()
    commands = []
    support = tmp_path / 'support-site.json'

    def verify(config_path, *, bundled_policies):
        assert not commands and config_path == support
        assert bundled_policies.keys() == {'privacy', 'terms'}
        assert bundled_policies['privacy'][0] == valid()['PRIVACY_POLICY_URL']
        assert bundled_policies['terms'][0] == valid()['TERMS_OF_SERVICE_URL']
        assert all(b'<p>Test policy</p>' in expected for _, expected in bundled_policies.values())
        return 7

    monkeypatch.setattr(release, 'verify_published', verify)

    def run(command, **kwargs):
        commands.append(command)
        if has_artifact:
            artifact = tmp_path / 'apps/mobile/build' / relative_output
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b'fixture build output')
        return release.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(release.subprocess, 'run', run)
    args = ['--config', str(config), '--platform', platform, '--execute']
    assert release.main(args) == 1
    assert '--support-site-config' in json.loads(capsys.readouterr().out)['message']
    assert not commands
    result = release.main(args + ['--support-site-config', str(support)])
    assert commands[0][5:] == release.build_command(platform, release.release_configuration(valid()))
    evidence = json.loads(capsys.readouterr().out)
    if has_artifact:
        assert result == 0
        assert evidence['status'] == 'LOCAL_BUILD_NOT_SUBMITTED'
        assert evidence[hash_field] == hashlib.sha256(b'fixture build output').hexdigest()
        assert evidence['published_support_files_verified'] == 7
    else:
        assert result == 1
        assert evidence['status'] == 'BLOCKED'
        assert 'expected mobile release artifact' in evidence['message']
