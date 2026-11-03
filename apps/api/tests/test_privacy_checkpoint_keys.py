import pytest

from src.services.privacy_checkpoint_keys import issue_checkpoint_key, recover_checkpoint_key
from src.services.privacy_journal import JournalError
from src.services.privacy_journal_outbox import DisposableMemoryJournalStore


def test_checkpoint_key_recovery_requires_envelope_reference_and_offline_key():
    store = DisposableMemoryJournalStore()
    recovery = b'r' * 32
    key, ref = issue_checkpoint_key(store, namespace='a' * 32, recovery_key=recovery)
    assert len(key) == 32 and key != recovery
    args = {'namespace': ref['namespace'], 'key_id': ref['key_id'], 'expected_sha256': ref['sha256']}
    assert recover_checkpoint_key(store, **args, recovery_key=recovery) == key
    with pytest.raises(JournalError):
        recover_checkpoint_key(store, **args, recovery_key=b'x' * 32)
    with pytest.raises(JournalError):
        recover_checkpoint_key(store, **{**args, 'expected_sha256': '0' * 64}, recovery_key=recovery)
    store.data[next(iter(store.data))] = b'corrupt'
    with pytest.raises(JournalError):
        recover_checkpoint_key(store, **args, recovery_key=recovery)
