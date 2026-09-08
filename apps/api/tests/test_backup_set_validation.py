"""Offline corruption/path checks for the private DB + media backup format."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('backup_set_validation', ROOT / 'scripts/verify_backup_set.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


@pytest.fixture
def backup_set(tmp_path):
    folder = tmp_path / 'private-set'
    folder.mkdir()
    (folder / 'objects').mkdir()
    key = 'synthetic/book.png'
    filename = 'objects/' + hashlib.sha256(key.encode()).hexdigest()
    (folder / 'database.dump').write_bytes(b'synthetic-db')
    (folder / filename).write_bytes(b'synthetic-media')
    def descriptor(file):
        value = (folder / file).read_bytes()
        return {'file': file, 'sha256': hashlib.sha256(value).hexdigest(), 'size': len(value)}
    manifest = {'format_version': 1, 'database_scope': 'public',
                'requires_latest_deletion_and_identity_revocations': True,
                'database': descriptor('database.dump'), 'objects': [{'key': key, **descriptor(filename)}]}
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    return folder, manifest


def test_verified_files_do_not_claim_restore_or_revocation_replay(backup_set):
    folder, _ = backup_set
    result = backup.verify(folder)
    assert result['status'] == 'CHECKSUMS_VERIFIED_NOT_RESTORED'
    assert result['restore_verified'] is False
    assert result['requires_latest_deletion_and_identity_revocations'] is True
    assert result['object_count'] == 1
    assert 'synthetic/book.png' not in json.dumps(result)


@pytest.mark.parametrize('corruption', ['database', 'media', 'missing', 'extra', 'duplicate', 'traversal', 'symlink'])
def test_corrupt_or_escaping_backup_is_rejected(backup_set, corruption):
    folder, manifest = backup_set
    media = folder / manifest['objects'][0]['file']
    if corruption == 'database':
        (folder / 'database.dump').write_bytes(b'partial')
    elif corruption == 'media':
        media.write_bytes(b'corrupt')
    elif corruption == 'missing':
        media.unlink()
    elif corruption == 'extra':
        (folder / 'objects' / 'unlisted').write_bytes(b'extra')
    elif corruption == 'duplicate':
        manifest['objects'].append(manifest['objects'][0])
    elif corruption == 'traversal':
        manifest['objects'][0]['file'] = '../outside'
    else:
        media.unlink()
        media.symlink_to(folder / 'database.dump')
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(backup.BackupValidationError):
        backup.verify(folder)


def test_cli_suppresses_private_names_on_failure(backup_set, capsys):
    folder, _ = backup_set
    (folder / 'database.dump').write_bytes(b'private text must not be printed')
    assert backup.main(['--backup-set', str(folder)]) == 1
    output = capsys.readouterr().out
    assert str(folder) not in output
    assert 'synthetic/book.png' not in output
    assert 'private text must not be printed' not in output
