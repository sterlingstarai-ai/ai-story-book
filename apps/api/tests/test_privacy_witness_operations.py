import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return (importlib.import_module('recover_witness_key'),
            importlib.import_module('publish_privacy_witness_health'))


def test_recovered_key_is_private_and_never_overwrites(modules, tmp_path):
    recovery, _ = modules
    path = tmp_path / 'recovered.key'
    recovery.write_new_private_key(path, b'k' * 32)
    assert path.read_bytes() == b'k' * 32
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        recovery.write_new_private_key(path, b'x' * 32)
    assert path.read_bytes() == b'k' * 32
    link = tmp_path / 'link.key'
    link.symlink_to(path)
    with pytest.raises(FileExistsError):
        recovery.write_new_private_key(link, b'x' * 32)
    assert path.read_bytes() == b'k' * 32


def test_signal_fails_closed_for_missing_or_malformed_status(modules):
    _, signal = modules
    def measure(value, exit_code=0):
        return signal.measurement(SimpleNamespace(returncode=exit_code, stdout=json.dumps(value)))
    assert measure({'status': 'SNAPSHOT_MATCHES', 'restore_authorized': False}) == 1
    assert measure({'status': 'SNAPSHOT_MATCHES', 'restore_authorized': 0}) == 0
    assert measure({'status': 'ALERT', 'restore_authorized': False}) == 0
    assert measure({'status': 'SNAPSHOT_MATCHES', 'restore_authorized': False}, 1) == 0
    assert measure({'status': 'SNAPSHOT_MATCHES', 'restore_authorized': False, 'extra': 'x'}) == 0
    with pytest.raises(ValueError):
        signal.watch_command({})


def test_offline_envelope_recovers_without_google_access(modules, tmp_path, capsys):
    from src.services.privacy_checkpoint_keys import issue_checkpoint_key
    from src.services.privacy_journal_outbox import DisposableMemoryJournalStore

    recovery, _ = modules
    store = DisposableMemoryJournalStore()
    key, ref = issue_checkpoint_key(store, namespace='a' * 32, recovery_key=b'r' * 32)
    encrypted = next(iter(store.data.values()))
    secret_file, ref_file, envelope_file, output = (tmp_path / x for x in ('secret', 'reference', 'envelope', 'recovered'))
    secret_file.write_bytes(b'r' * 32)
    ref_file.write_text(json.dumps(ref))
    envelope_file.write_bytes(encrypted)
    for item in (secret_file, ref_file, envelope_file):
        item.chmod(0o600)
    assert recovery.main(['--recovery-key-file', str(secret_file), '--envelope-reference-file', str(ref_file),
                          '--envelope-file', str(envelope_file), '--output', str(output)]) == 0
    assert output.read_bytes() == key and output.stat().st_mode & 0o777 == 0o600
    assert capsys.readouterr().out.strip() == '{"status": "KEY_RECOVERED", "restore_authorized": false}'


def test_enrollment_exports_offline_recovery_material(modules, monkeypatch, tmp_path, capsys):
    from src.services import privacy_checkpoint_gcs
    from src.services.privacy_journal_outbox import DisposableMemoryJournalStore

    recovery, _ = modules
    enroll = importlib.import_module('enroll_witness_key')
    store = DisposableMemoryJournalStore()
    store.close = lambda: None
    monkeypatch.setattr(privacy_checkpoint_gcs, 'GCSCheckpointStore', lambda bucket: store)
    secret_file, key_file, ref_file, envelope_file, recovered = (tmp_path / x for x in
        ('secret', 'key', 'reference', 'envelope', 'recovered'))
    secret_file.write_bytes(b'r' * 32)
    secret_file.chmod(0o600)
    assert enroll.main(['--recovery-key-file', str(secret_file), '--namespace', 'a' * 32,
        '--envelope-bucket', 'synthetic-bucket', '--key-output', str(key_file), '--reference-output', str(ref_file),
        '--envelope-output', str(envelope_file)]) == 0
    assert recovery.main(['--recovery-key-file', str(secret_file), '--envelope-reference-file', str(ref_file),
        '--envelope-file', str(envelope_file), '--output', str(recovered)]) == 0
    assert key_file.read_bytes() == recovered.read_bytes()
    assert all(item.stat().st_mode & 0o777 == 0o600 for item in (key_file, ref_file, envelope_file, recovered))
    assert 'KEY_ENROLLED_INACTIVE' in capsys.readouterr().out


def test_second_host_observer_blocks_restore_when_source_receipt_is_absent_or_old(modules, tmp_path, capsys):
    import time
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from src.services.privacy_witness_receipt import sign_receipt

    observer = importlib.import_module('mac_privacy_witness_observer')
    key = Ed25519PrivateKey.generate()
    head = {'sequence': 1, 'sha256': 'a' * 64}
    now = int(time.time())
    args = {'namespace': 'a' * 32, 'head': head,
            'observation': {'status': 'SNAPSHOT_MATCHES', 'restore_authorized': False}}
    receipt_file, pub_file, ref_file = (tmp_path / x for x in ('receipt', 'public', 'reference'))
    pub_file.write_bytes(key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    ref_file.write_text(json.dumps({'version': 1, 'namespace': 'a' * 32, 'head': head}))
    pub_file.chmod(0o600)
    ref_file.chmod(0o600)
    cli = ['--execute', '--receipt-file', str(receipt_file), '--public-key-file', str(pub_file),
           '--trusted-reference-file', str(ref_file), '--max-age', '10']
    assert observer.main(cli) == 1
    assert json.loads(capsys.readouterr().out)['restore_authorized'] is False
    receipt_file.write_text(json.dumps(sign_receipt(key, observed_at=now - 11, **args)))
    receipt_file.chmod(0o600)
    assert observer.main(cli) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'ALERT'
    receipt_file.write_text(json.dumps(sign_receipt(key, observed_at=now, **args)))
    assert observer.main(cli) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {'status': 'SIGNED_OBSERVATION_VALID', 'source_reachability': 'UNVERIFIED',
                      'restore_authorized': False}
