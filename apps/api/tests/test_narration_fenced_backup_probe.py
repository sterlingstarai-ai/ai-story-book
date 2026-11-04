"""Test fence ordering and fail-closed evidence without real user data."""
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def context(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    module = importlib.import_module('narration_fenced_backup_probe')
    state = {'active': False, 'journal': 'a' * 64, 'remote': b'manifest', 'probe': True}
    events = []
    folder = tmp_path / 'external-example'
    folder.mkdir()
    (folder / 'manifest.json').write_bytes(b'manifest')

    class Fence:
        def __init__(self, _environment):
            pass

        def __enter__(self):
            state['active'] = True
            return self

        def verify(self):
            assert state['active']
            events.append('verify')

        def __exit__(self, *_):
            state['active'] = False

    class Store:
        def read_small(self, *_):
            return state['remote']

    def checkpoint():
        return {'status': 'CURRENT_OUTBOX_MATCHES_JOURNAL', 'restore_authorized': False,
                'event_count': 1, 'journal_sha256': state['journal']}

    def backup(**kwargs):
        assert state['active'] and isinstance(kwargs['fence'], Fence)
        events.append('backup')
        return {'run_id': 'a' * 32, 'backup_set': folder.name}

    def probe(*_args, **_kwargs):
        assert state['active']
        events.append('restore')
        if not state['probe']:
            raise ValueError('restore failed')
        return {'status': 'OFFLINE_DATABASE_RESTORED', 'revision': module.SOURCE_REVISION,
                'restore_authorized': False, 'migration_authorized': False}

    def remote(*_args, **_kwargs):
        assert state['active']
        events.append('remote')
        return {'status': 'REMOTE_CHECKSUMS_VERIFIED_NOT_RESTORED', 'restore_authorized': False}

    monkeypatch.setattr(module, 'NarrationTransactionFence', Fence)
    monkeypatch.setattr(module, 'database_environment', lambda *_: {})
    monkeypatch.setattr(module, 'assert_quiescent', lambda *_: None)
    monkeypatch.setattr(module, 'capture_quiesced_backup', backup)
    monkeypatch.setattr(module, 'probe_database_archive', probe)
    monkeypatch.setattr(module, 'verify_remote_backup', remote)
    kwargs = dict(values={}, ca_file=tmp_path / 'ca', output_dir=tmp_path,
                  store=Store(), verify_journal=checkpoint, image_id='trusted')
    return module, state, events, kwargs


def test_fence_covers_backup_restore_and_remote_recheck(context):
    module, state, events, kwargs = context
    result = module.capture_and_probe(**kwargs)
    assert events == ['backup', 'restore', 'verify', 'remote', 'verify']
    assert not state['active']
    assert result['restore_authorized'] is False
    assert result['migration_authorized'] is False
    assert result['media_restore_verified'] is False


def test_remote_manifest_mismatch_rejects_before_restore(context):
    module, state, events, kwargs = context
    state['remote'] = b'different'
    with pytest.raises(module.FencedBackupProbeError, match='manifests differ'):
        module.capture_and_probe(**kwargs)
    assert events == ['backup']
    assert not state['active']


@pytest.mark.parametrize('alter', [None, 'nonce', 'manifest_sha256', 'journal_sha256', 'issued_at'])
def test_offhost_restore_is_bound_to_exact_fenced_backup(context, monkeypatch, alter):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    module, state, events, kwargs = context
    attestation = importlib.import_module('narration_detach_attestation')
    signer = Ed25519PrivateKey.generate()
    monkeypatch.setattr(module, 'verify_empty_media_detach', lambda *_a, **_k: None)
    monkeypatch.setattr(attestation, 'ingest_verified_backup', lambda **_: {
        'status': 'BACKUP_IMPORTED_QUARANTINED', 'restore_authorized': False, 'privacy_replay_verified': False})
    monkeypatch.setattr(attestation, 'restore_in_owned_sandbox', lambda **_: {
        'status': 'DATABASE_AND_MEDIA_RESTORED_QUARANTINED', 'restore_authorized': False,
        'service_publish_authorized': False})
    monkeypatch.setattr(attestation, '_verify_signed_checkpoint', lambda *_: None)

    def attest(challenge):
        assert state['active']
        if alter is not None:
            challenge[alter] = challenge[alter] - 1 if alter == 'issued_at' else 'c' * 64
        return attestation.restore_and_attest(challenge, store=None, sandbox={}, signed_witness={},
                                             signing_key=signer)

    kwargs.update(image_id=None, media_detach_target={}, offhost_restore=(signer.public_key(), attest))
    if alter:
        with pytest.raises(attestation.DetachAttestationError, match='attestation is invalid'):
            module.capture_and_probe(**kwargs)
        assert events == ['backup']
    else:
        result = module.capture_and_probe(**kwargs)
        assert result['status'] == 'FENCED_BACKUP_OFFHOST_RESTORE_VERIFIED'
        assert result['media_restore_verified'] is True
        assert result['restore_authorized'] is False
    assert not state['active']


@pytest.mark.parametrize('reply', [b'A' * 86 + b'==\n', b'A' * 89 + b'\n', b''])
def test_offhost_restore_pipe_is_bounded(context, reply):
    import io
    import json
    import os

    module, _, _, kwargs = context
    attestation = importlib.import_module('narration_detach_attestation')
    challenge = attestation.issue_restore_challenge(run_id='a' * 32, manifest_sha256='b' * 64,
        revision=module.SOURCE_REVISION, journal_checkpoint=kwargs['verify_journal']())
    read_fd, write_fd = os.pipe()
    os.write(write_fd, reply)
    os.close(write_fd)
    output = io.BytesIO()
    try:
        if len(reply) == 89:
            assert attestation.request_restore_attestation(challenge, input_fd=read_fd, output=output) == reply[:-1].decode()
        else:
            with pytest.raises(attestation.DetachAttestationError):
                attestation.request_restore_attestation(challenge, input_fd=read_fd, output=output)
        assert json.loads(output.getvalue()) == challenge
    finally:
        os.close(read_fd)


def test_detach_mailbox_accepts_a_verified_reply_after_reconnect(context, tmp_path, monkeypatch):
    from base64 import b64encode
    import json
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    module, _, _, kwargs = context
    attestation = importlib.import_module('narration_detach_attestation')
    challenge = attestation.issue_restore_challenge(run_id='a' * 32, manifest_sha256='b' * 64,
        revision=module.SOURCE_REVISION, journal_checkpoint=kwargs['verify_journal']())
    mailbox = tmp_path / 'mailbox'
    mailbox.mkdir(mode=0o700)
    signer = Ed25519PrivateKey.generate()

    def reconnect(_seconds):
        published = json.loads(attestation.read_mailbox_record(mailbox, 'challenge'))
        assert published == challenge
        signature = b64encode(signer.sign(attestation._message(published))) + b'\n'
        attestation.write_mailbox_record(mailbox, 'signature', signature)
        with pytest.raises(FileExistsError):
            attestation.write_mailbox_record(mailbox, 'signature', b'changed')

    monkeypatch.setattr(attestation.time, 'sleep', reconnect)
    signature = attestation.request_mailbox_attestation(challenge, mailbox)
    attestation.verify_restore_attestation(challenge, signature, public_key=signer.public_key())


def test_detach_mailbox_rejects_symlink(context, tmp_path):
    attestation = importlib.import_module('narration_detach_attestation')
    mailbox = tmp_path / 'mailbox'
    mailbox.mkdir(mode=0o700)
    target = tmp_path / 'outside'
    target.write_bytes(b'not in the mailbox')
    (mailbox / 'signature').symlink_to(target)
    with pytest.raises(OSError):
        attestation.read_mailbox_record(mailbox, 'signature')


def test_context_retains_fence_until_caller_leaves(context):
    module, state, _, kwargs = context
    with module.fenced_backup_probe(**kwargs) as (fence, evidence):
        assert state['active']
        fence.verify()
        assert evidence['migration_authorized'] is False
    assert not state['active']


def test_failed_restore_releases_fence_and_never_rechecks_remote(context):
    module, state, events, kwargs = context
    state['probe'] = False
    with pytest.raises(ValueError, match='restore failed'):
        module.capture_and_probe(**kwargs)
    assert events == ['backup', 'restore']
    assert not state['active']


def test_changed_journal_rejects_after_restore(context, monkeypatch):
    module, state, events, kwargs = context
    original = module.probe_database_archive

    def changed(*args, **probe_kwargs):
        result = original(*args, **probe_kwargs)
        state['journal'] = 'b' * 64
        return result

    monkeypatch.setattr(module, 'probe_database_archive', changed)
    with pytest.raises(module.FencedBackupProbeError, match='journal changed'):
        module.capture_and_probe(**kwargs)
    assert 'remote' not in events
    assert not state['active']


def test_cutover_rechecks_media_before_yield_and_closes_clients(context, monkeypatch):
    module, state, events, kwargs = context
    media = importlib.import_module('media_cutover_preflight')
    reader = {'S3_BUCKET': 'source', 'role': 'reader', 'S3_ENDPOINT': 'source-endpoint',
              'S3_REGION': 'fixture', 'S3_ACCESS_KEY': 'reader-access', 'S3_SECRET_KEY': 'reader-secret'}
    writer = {'S3_BUCKET': 'source', 'role': 'retired', 'S3_ENDPOINT': 'source-endpoint',
              'S3_REGION': 'fixture', 'S3_ACCESS_KEY': 'retired-access', 'S3_SECRET_KEY': 'retired-secret'}
    target = {'S3_BUCKET': 'target', 'role': 'target', 'S3_ENDPOINT': 'target-endpoint',
              'S3_REGION': 'fixture', 'S3_ACCESS_KEY': 'target-access', 'S3_SECRET_KEY': 'target-secret'}

    class Client:
        def __init__(self, values):
            self.role = values['role']

        def close(self):
            assert state['active']
            events.append('close:' + self.role)

    def permissions(source, retired, bucket):
        assert state['active']
        assert (source.role, retired.role, bucket) == ('reader', 'retired', 'source')
        events.append('permissions')

    def empty(fence, source, source_bucket, destination, target_bucket):
        assert state['active']
        assert (source.role, source_bucket, destination.role, target_bucket) == (
            'reader', 'source', 'target', 'target')
        events.append('empty')
        if events.count('empty') == 2:
            raise module.FencedBackupProbeError('Media appeared during backup')

    monkeypatch.setattr(media, 'storage_client', Client)
    monkeypatch.setattr(media, 'verify_source_storage_permissions', permissions)
    monkeypatch.setattr(media, 'verify_empty_cutover', empty)
    with pytest.raises(module.FencedBackupProbeError, match='Media appeared'):
        module.capture_and_probe(**{**kwargs, 'values': reader, 'media_cutover': (writer, target)})
    assert events == ['permissions', 'empty', 'close:target', 'close:retired', 'close:reader',
                      'backup', 'restore', 'verify', 'remote', 'verify',
                      'permissions', 'empty', 'close:target', 'close:retired', 'close:reader']
    assert not state['active']


@pytest.mark.parametrize('upload_timeout', [False, True])
def test_target_writer_checks_and_cleans_canary_with_one_read(context, monkeypatch, upload_timeout):
    from io import BytesIO
    from unittest.mock import Mock
    from botocore.exceptions import ClientError

    media = importlib.import_module('media_cutover_preflight')
    target = Mock()
    not_found = ClientError({'ResponseMetadata': {'HTTPStatusCode': 404}}, 'HeadObject')
    target.head_object.side_effect = [not_found, not_found]
    target.get_object.return_value = {'Body': BytesIO(b'AI Story Book cutover write probe')}
    if upload_timeout:
        target.put_object.side_effect = TimeoutError
    monkeypatch.setattr(media, 'storage_client', lambda _: target)
    values = {'S3_BUCKET': 'fixture'}
    if upload_timeout:
        with pytest.raises(media.MediaCutoverError, match='could not be verified'):
            media.verify_staged_target_writer(values)
    else:
        media.verify_staged_target_writer(values)
    assert target.put_object.call_args.kwargs['IfNoneMatch'] == '*'
    assert target.get_object.call_count == 1
    target.delete_object.assert_called_once_with(**target.get_object.call_args.kwargs)
    target.close.assert_called_once_with()
