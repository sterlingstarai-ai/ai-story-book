"""Fail-closed offline backup probe behavior with synthetic archives."""
import hashlib
import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def probe(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    module = importlib.import_module('narration_restore_probe')
    image_id = 'sha256:' + 'a' * 64
    container_id = 'b' * 64
    data = b'synthetic postgres archive'
    (tmp_path / 'database.dump').write_bytes(data)
    (tmp_path / 'objects').mkdir()
    manifest = {'format_version': 1, 'database_scope': 'public', 'restore_verified': False,
                'alembic_revision': '5de7a40b6c12',
                'requires_latest_deletion_and_identity_revocations': True,
                'database': {'file': 'database.dump', 'size': len(data),
                             'sha256': hashlib.sha256(data).hexdigest()}, 'objects': []}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    state = {'revision': b'5de7a40b6c12\n', 'calls': [], 'mutate': False}

    def fake_run(args, *, input_bytes=None, timeout=60):
        state['calls'].append(args)
        if args[:3] == ['docker', 'context', 'inspect']:
            return b'"unix:///synthetic/docker.sock"'
        if args[:3] == ['docker', 'image', 'inspect']:
            return json.dumps([{'Id': image_id}]).encode()
        if args[:2] == ['docker', 'run']:
            return (container_id + '\n').encode()
        if 'pg_restore' in args[-11:] or any(arg.endswith('/pg_restore') for arg in args):
            assert input_bytes == data
            if state['mutate']:
                (tmp_path / 'database.dump').write_bytes(b'changed')
            return b''
        if args and args[-1] == 'SELECT version_num FROM public.alembic_version ORDER BY version_num':
            return state['revision']
        return b''

    monkeypatch.delenv('DOCKER_HOST', raising=False)
    monkeypatch.setattr(module, '_run', fake_run)
    monkeypatch.setattr(module, '_sandbox', lambda *_: None)
    return module, image_id, tmp_path, manifest, state


def test_probe_keeps_restored_database_and_migration_unapproved(probe):
    module, image_id, folder, manifest, state = probe
    result = module.probe_database_archive(folder, image_id=image_id, expected_revision='5de7a40b6c12')
    assert result == {'status': 'OFFLINE_DATABASE_RESTORED', 'revision': '5de7a40b6c12',
                      'archive_sha256': manifest['database']['sha256'], 'media_restore_verified': False,
                      'restore_authorized': False, 'migration_authorized': False}
    assert state['calls'][-1] == ['docker', 'rm', '-f', 'b' * 64]


def test_wrong_manifest_revision_is_rejected_before_container_creation(probe):
    module, image_id, folder, manifest, state = probe
    manifest['alembic_revision'] = 'aaaaaaaaaaaa'
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(module.RestoreProbeError, match='revision'):
        module.probe_database_archive(folder, image_id=image_id, expected_revision='5de7a40b6c12')
    assert not any(call[:2] == ['docker', 'run'] for call in state['calls'])


def test_wrong_restored_revision_is_rejected_and_container_removed(probe):
    module, image_id, folder, _, state = probe
    state['revision'] = b'aaaaaaaaaaaa\n'
    with pytest.raises(module.RestoreProbeError, match='revision'):
        module.probe_database_archive(folder, image_id=image_id, expected_revision='5de7a40b6c12')
    assert state['calls'][-1] == ['docker', 'rm', '-f', 'b' * 64]


def test_archive_change_during_probe_is_rejected_and_container_removed(probe):
    module, image_id, folder, _, state = probe
    state['mutate'] = True
    with pytest.raises(module.RestoreProbeError):
        module.probe_database_archive(folder, image_id=image_id, expected_revision='5de7a40b6c12')
    assert state['calls'][-1] == ['docker', 'rm', '-f', 'b' * 64]


def test_nonlocal_docker_endpoint_is_rejected_before_container_creation(probe, monkeypatch):
    module, image_id, folder, _, state = probe
    monkeypatch.setenv('DOCKER_HOST', 'tcp://remote.example:2375')
    with pytest.raises(module.RestoreProbeError, match='local Docker'):
        module.probe_database_archive(folder, image_id=image_id, expected_revision='5de7a40b6c12')
    assert not any(call[:2] == ['docker', 'run'] for call in state['calls'])
