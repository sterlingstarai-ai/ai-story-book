"""Safety checks for the local-only pinned narration image builder."""
import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def builder(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    module = importlib.import_module('build_narration_candidate')
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    return module


def make_manifest(builder, tmp_path):
    source = b'# invented source\n'
    for name in builder.ALLOWED_FILES:
        path = tmp_path / 'apps/api' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source)
    config = b'class Settings:\n' + builder.ANCHOR + b'    other_setting = 1\n'
    manifest = {'files': {name: builder.sha(source) for name in builder.ALLOWED_FILES},
                'base_config_sha256': builder.sha(config)}
    return manifest, config


def test_snapshot_patches_only_google_field_and_freezes_paths(builder, tmp_path, monkeypatch):
    manifest, config = make_manifest(builder, tmp_path)
    monkeypatch.setattr(builder, 'read_from_image', lambda *_args: config)
    result = builder.snapshot(manifest, 'sha256:fixture')
    assert set(result) == builder.ALLOWED_FILES | {builder.CONFIG_PATH}
    assert result[builder.CONFIG_PATH] == config.replace(builder.ANCHOR, builder.ANCHOR + builder.ADDITION)


def test_snapshot_rejects_altered_source_and_manifest_expansion(builder, tmp_path, monkeypatch):
    manifest, config = make_manifest(builder, tmp_path)
    monkeypatch.setattr(builder, 'read_from_image', lambda *_args: config)
    (tmp_path / 'apps/api/src/services/tts.py').write_bytes(b'changed after review')
    with pytest.raises(RuntimeError, match='Reviewed source changed'):
        builder.snapshot(manifest, 'sha256:fixture')
    manifest['files']['.env'] = builder.sha(b'fixture')
    with pytest.raises(RuntimeError, match='reviewed source allowlist'):
        builder.snapshot(manifest, 'sha256:fixture')


def test_snapshot_rejects_configuration_mismatch(builder, tmp_path, monkeypatch):
    manifest, config = make_manifest(builder, tmp_path)
    monkeypatch.setattr(builder, 'read_from_image', lambda *_args: config + b'# drift\n')
    with pytest.raises(RuntimeError, match='configuration differs'):
        builder.snapshot(manifest, 'sha256:fixture')


def test_privacy_bundle_requires_every_dependency_and_uses_reviewed_config(builder, tmp_path, monkeypatch):
    manifest, config = make_manifest(builder, tmp_path)
    monkeypatch.setattr(builder, 'read_from_image', lambda *_args: config)
    for name in builder.PRIVACY_FILES - builder.ALLOWED_FILES:
        path = tmp_path / 'apps/api' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'# reviewed privacy fixture\n')
        manifest['files'][name] = builder.sha(path.read_bytes())
    result = builder.snapshot(manifest, 'sha256:fixture')
    assert result[builder.CONFIG_PATH] == b'# reviewed privacy fixture\n'
    del manifest['files']['src/services/privacy_journal_mirror.py']
    with pytest.raises(RuntimeError, match='reviewed source allowlist'):
        builder.snapshot(manifest, 'sha256:fixture')


def test_monitor_bundle_refuses_host_artifact_drift(builder, tmp_path, monkeypatch):
    manifest, config = make_manifest(builder, tmp_path)
    monkeypatch.setattr(builder, 'read_from_image', lambda *_args: config)
    for name in builder.MONITOR_FILES - builder.ALLOWED_FILES:
        path = tmp_path / 'apps/api' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'# reviewed source\n')
        manifest['files'][name] = builder.sha(path.read_bytes())
    manifest['host_artifacts'] = {}
    for name in builder.MONITOR_HOST_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'# reviewed host artifact\n')
        manifest['host_artifacts'][name] = builder.sha(path.read_bytes())
    assert builder.snapshot(manifest, 'sha256:fixture')
    (tmp_path / 'scripts/check_privacy_purge_queue.py').write_bytes(b'changed')
    with pytest.raises(RuntimeError, match='host artifact changed'):
        builder.snapshot(manifest, 'sha256:fixture')


def test_untagged_base_is_not_retagged_or_removed(builder, monkeypatch):
    image = 'sha256:' + 'a' * 64
    data = {'Id': image, 'Os': 'linux', 'Architecture': 'amd64', 'RepoTags': [],
            'Config': {'User': 'appuser', 'Env': []}}
    calls = []

    def fake_docker(*args, **_kwargs):
        calls.append(args)
        return json.dumps([data]).encode()

    monkeypatch.setattr(builder, 'docker', fake_docker)
    with pytest.raises(RuntimeError, match='pre-existing stable tag'):
        builder.inspect_base(image)
    assert calls == [('image', 'inspect', image)]


def test_final_candidate_freezes_only_reviewed_prompt_templates(builder, tmp_path, monkeypatch):
    manifest, config = make_manifest(builder, tmp_path)
    monkeypatch.setattr(builder, 'read_from_image', lambda *_args: config)
    for name in builder.FINAL_FILES - builder.ALLOWED_FILES:
        path = tmp_path / 'apps/api' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'reviewed content\n')
        manifest['files'][name] = builder.sha(path.read_bytes())
    manifest['host_artifacts'] = {}
    for name in builder.FINAL_HOST_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'reviewed host artifact\n')
        manifest['host_artifacts'][name] = builder.sha(path.read_bytes())
    result = builder.snapshot(manifest, 'sha256:fixture')
    assert builder.FINAL_PROMPTS <= result.keys()
    assert {'src/services/image_quality.py', 'src/services/image_correction.py'} <= result.keys()
    assert 'alembic/versions/4c2d8f71b906_privacy_retry_fairness.py' in result
    assert 'src/services/privacy_journal_gcs.py' in result
    assert 'scripts/run_scheduled_backup.py' in manifest['host_artifacts']
    backup_digest = manifest['host_artifacts'].pop('scripts/run_scheduled_backup.py')
    with pytest.raises(RuntimeError, match='host artifact manifest is incomplete'):
        builder.snapshot(manifest, 'sha256:fixture')
    manifest['host_artifacts']['scripts/run_scheduled_backup.py'] = backup_digest
    rogue = 'src/prompts/unreviewed.system.jinja2'
    manifest['files'][rogue] = builder.sha(b'unreviewed')
    with pytest.raises(RuntimeError, match='reviewed source allowlist'):
        builder.snapshot(manifest, 'sha256:fixture')


def test_current_candidate_requires_both_new_sources_and_contract_pin(builder, tmp_path, monkeypatch):
    manifest, config = make_manifest(builder, tmp_path)
    monkeypatch.setattr(builder, 'read_from_image', lambda *_args: config)
    for name in builder.CURRENT_FILES - builder.ALLOWED_FILES:
        path = tmp_path / 'apps/api' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'reviewed current source\n')
        manifest['files'][name] = builder.sha(path.read_bytes())
    manifest['host_artifacts'] = {}
    for name in builder.FINAL_HOST_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'reviewed host artifact\n')
        manifest['host_artifacts'][name] = builder.sha(path.read_bytes())
    assert builder.snapshot(manifest, 'sha256:fixture')
    for name in ('src/core/cost_budget.py', 'src/routers/branch.py'):
        digest = manifest['files'].pop(name)
        with pytest.raises(RuntimeError, match='reviewed source allowlist'):
            builder.snapshot(manifest, 'sha256:fixture')
        manifest['files'][name] = digest
    (tmp_path / 'packages/shared/schema/openapi.json').write_bytes(b'drift')
    with pytest.raises(RuntimeError, match='host artifact changed'):
        builder.snapshot(manifest, 'sha256:fixture')


def test_postgres_budget_candidate_freezes_model_migration_and_config(builder, tmp_path, monkeypatch):
    manifest, config = make_manifest(builder, tmp_path)
    monkeypatch.setattr(builder, 'read_from_image', lambda *_args: config)
    for name in builder.BUDGET_FILES - builder.ALLOWED_FILES:
        path = tmp_path / 'apps/api' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'reviewed source\n')
        manifest['files'][name] = builder.sha(path.read_bytes())
    manifest['host_artifacts'] = {}
    for name in builder.BUDGET_HOST_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'reviewed host artifact\n')
        manifest['host_artifacts'][name] = builder.sha(path.read_bytes())
    assert builder.snapshot(manifest, 'sha256:fixture')
    for name in ('src/models/generation_budget.py',
                 'alembic/versions/e7b93d2a601f_generation_budget.py',
                 'scripts/activate_generation_budget.py'):
        digest = manifest['files'].pop(name)
        with pytest.raises(RuntimeError, match='reviewed source allowlist'):
            builder.snapshot(manifest, 'sha256:fixture')
        manifest['files'][name] = digest
    (tmp_path / 'env.schema.json').write_bytes(b'drift')
    with pytest.raises(RuntimeError, match='host artifact changed'):
        builder.snapshot(manifest, 'sha256:fixture')
