import hashlib

import pytest

from src.services.privacy_checkpoint_head import append_checkpoint_head, verify_anchored_checkpoint
from src.services.privacy_journal import JournalEntry, JournalError, JournalScan
from src.services.privacy_journal_checkpoint import _encode
from src.services.privacy_journal_outbox import DisposableMemoryJournalStore
from src.services.privacy_journal_verify import fingerprint_entries


NAMESPACE = 'a' * 32
HEAD_KEY = b'h' * 32
CHECKPOINT_KEY = b'c' * 32
USER = '00000000-0000-4000-8000-000000000001'


def make_checkpoint(store, sequence, scan, issued_at=100):
    source = {'status': 'CURRENT_OUTBOX_MATCHES_JOURNAL', 'restore_authorized': False,
              'event_count': len(scan.committed), 'journal_sha256': fingerprint_entries(scan.committed)}
    name, blob = _encode(NAMESPACE, sequence, CHECKPOINT_KEY, source, scan, issued_at)
    store.create(name, blob)
    return {'status': 'FENCED_WITNESS_CHECKPOINT_STORED', 'restore_authorized': False,
            'namespace': NAMESPACE, 'generation': sequence, 'sha256': hashlib.sha256(blob).hexdigest()}


def test_independently_anchored_head_rejects_rollback_and_missing_history():
    checkpoints, heads = DisposableMemoryJournalStore(), DisposableMemoryJournalStore()
    first = JournalEntry('1' * 32, 'consent_revoke', USER, 1)
    second = JournalEntry('2' * 32, 'account_delete', USER, 2)
    one, two = JournalScan((first,), 0), JournalScan((first, second), 0)
    head1 = append_checkpoint_head(heads, namespace=NAMESPACE, key=HEAD_KEY,
                                   checkpoint=make_checkpoint(checkpoints, 1, one))
    head2 = append_checkpoint_head(heads, namespace=NAMESPACE, key=HEAD_KEY,
                                   checkpoint=make_checkpoint(checkpoints, 2, two), previous=head1)
    args = {'namespace': NAMESPACE, 'head_key': HEAD_KEY, 'checkpoint_key': CHECKPOINT_KEY,
            'trusted_head': head2, 'now': 101, 'max_age': 10}
    result = verify_anchored_checkpoint(heads, checkpoints, two, candidate_head=head2, **args)
    assert result == {'status': 'ANCHORED_WITNESSED_PREFIX_MATCHES', 'head_sequence': 2,
                      'checkpoint_count': 2, 'journal_count': 2, 'restore_authorized': False}
    with pytest.raises(JournalError):
        verify_anchored_checkpoint(heads, checkpoints, one, candidate_head=head1, **args)
    with pytest.raises(JournalError):
        verify_anchored_checkpoint(heads, checkpoints, one, candidate_head=head2, **args)
    del heads.data[next(name for name in heads.data if name.endswith('1'))]
    with pytest.raises(JournalError):
        verify_anchored_checkpoint(heads, checkpoints, two, candidate_head=head2, **args)


def test_missing_or_wrong_anchor_and_wrong_previous_are_rejected():
    checkpoints, heads = DisposableMemoryJournalStore(), DisposableMemoryJournalStore()
    scan = JournalScan((), 0)
    checkpoint = make_checkpoint(checkpoints, 1, scan)
    head = append_checkpoint_head(heads, namespace=NAMESPACE, key=HEAD_KEY, checkpoint=checkpoint)
    assert append_checkpoint_head(heads, namespace=NAMESPACE, key=HEAD_KEY, checkpoint=checkpoint) == head
    with pytest.raises(JournalError):
        append_checkpoint_head(heads, namespace=NAMESPACE, key=HEAD_KEY,
                               checkpoint=dict(checkpoint, sha256='a' * 64))
    args = {'namespace': NAMESPACE, 'head_key': HEAD_KEY, 'checkpoint_key': CHECKPOINT_KEY,
            'candidate_head': head, 'now': 101, 'max_age': 10}
    for anchor in (None, {'sequence': 1, 'sha256': '0' * 64}):
        with pytest.raises(JournalError):
            verify_anchored_checkpoint(heads, checkpoints, scan, trusted_head=anchor, **args)
    with pytest.raises(JournalError):
        append_checkpoint_head(heads, namespace=NAMESPACE, key=HEAD_KEY,
                               checkpoint=make_checkpoint(checkpoints, 2, scan), previous=None)


def test_prior_checkpoint_membership_cannot_disappear_from_newer_head():
    checkpoints, heads = DisposableMemoryJournalStore(), DisposableMemoryJournalStore()
    first = JournalEntry('1' * 32, 'consent_revoke', USER, 1)
    original = JournalScan((first,), 0)
    lost = JournalScan((), 0)
    head1 = append_checkpoint_head(heads, namespace=NAMESPACE, key=HEAD_KEY,
                                   checkpoint=make_checkpoint(checkpoints, 1, original))
    head2 = append_checkpoint_head(heads, namespace=NAMESPACE, key=HEAD_KEY,
                                   checkpoint=make_checkpoint(checkpoints, 2, lost), previous=head1)
    with pytest.raises(JournalError):
        verify_anchored_checkpoint(heads, checkpoints, lost, namespace=NAMESPACE,
            head_key=HEAD_KEY, checkpoint_key=CHECKPOINT_KEY, candidate_head=head2,
            trusted_head=head2, now=101, max_age=10)


def test_old_checkpoints_remain_valid_but_time_must_not_reverse():
    checkpoints, heads = DisposableMemoryJournalStore(), DisposableMemoryJournalStore()
    empty = JournalScan((), 0)
    head1 = append_checkpoint_head(heads, namespace=NAMESPACE, key=HEAD_KEY,
        checkpoint=make_checkpoint(checkpoints, 1, empty, issued_at=100))
    head2 = append_checkpoint_head(heads, namespace=NAMESPACE, key=HEAD_KEY,
        checkpoint=make_checkpoint(checkpoints, 2, empty, issued_at=200_000), previous=head1)
    args = dict(namespace=NAMESPACE, head_key=HEAD_KEY, checkpoint_key=CHECKPOINT_KEY,
                now=200_001, max_age=10, candidate_head=head2, trusted_head=head2)
    assert verify_anchored_checkpoint(heads, checkpoints, empty, **args)['restore_authorized'] is False
    with pytest.raises(JournalError):
        verify_anchored_checkpoint(heads, checkpoints, empty, **dict(args, now=200_020))
    checkpoints2, heads2 = DisposableMemoryJournalStore(), DisposableMemoryJournalStore()
    later = append_checkpoint_head(heads2, namespace=NAMESPACE, key=HEAD_KEY,
        checkpoint=make_checkpoint(checkpoints2, 1, empty, issued_at=101))
    backwards = append_checkpoint_head(heads2, namespace=NAMESPACE, key=HEAD_KEY,
        checkpoint=make_checkpoint(checkpoints2, 2, empty, issued_at=100), previous=later)
    with pytest.raises(JournalError, match='append-only'):
        verify_anchored_checkpoint(heads2, checkpoints2, empty, namespace=NAMESPACE,
            head_key=HEAD_KEY, checkpoint_key=CHECKPOINT_KEY, candidate_head=backwards,
            trusted_head=backwards, now=102, max_age=10)


@pytest.mark.parametrize('change', ['missing', 'modified'])
def test_prior_checkpoint_must_exist_and_authenticate(change):
    checkpoints, heads = DisposableMemoryJournalStore(), DisposableMemoryJournalStore()
    empty = JournalScan((), 0)
    head1 = append_checkpoint_head(heads, namespace=NAMESPACE, key=HEAD_KEY,
        checkpoint=make_checkpoint(checkpoints, 1, empty))
    head2 = append_checkpoint_head(heads, namespace=NAMESPACE, key=HEAD_KEY,
        checkpoint=make_checkpoint(checkpoints, 2, empty), previous=head1)
    key = next(name for name in checkpoints.data if name.endswith('1'))
    if change == 'missing':
        del checkpoints.data[key]
    else:
        checkpoints.data[key] = b'tampered synthetic checkpoint'
    with pytest.raises(JournalError):
        verify_anchored_checkpoint(heads, checkpoints, empty, namespace=NAMESPACE,
            head_key=HEAD_KEY, checkpoint_key=CHECKPOINT_KEY, candidate_head=head2,
            trusted_head=head2, now=101, max_age=10)


def test_verification_has_explicit_chain_deadline(monkeypatch):
    from src.services import privacy_checkpoint_head as module
    checkpoints, heads = DisposableMemoryJournalStore(), DisposableMemoryJournalStore()
    empty = JournalScan((), 0)
    head = append_checkpoint_head(heads, namespace=NAMESPACE, key=HEAD_KEY,
        checkpoint=make_checkpoint(checkpoints, 1, empty))
    ticks = iter((0, 31))
    monkeypatch.setattr(module.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(JournalError, match='timed out'):
        verify_anchored_checkpoint(heads, checkpoints, empty, namespace=NAMESPACE,
            head_key=HEAD_KEY, checkpoint_key=CHECKPOINT_KEY, candidate_head=head,
            trusted_head=head, now=101, max_age=10)


def test_checkpoint_head_generation_limit_is_enforced():
    heads = DisposableMemoryJournalStore()
    invalid = {'status': 'FENCED_WITNESS_CHECKPOINT_STORED', 'restore_authorized': False,
               'namespace': NAMESPACE, 'generation': 257, 'sha256': 'b' * 64}
    with pytest.raises(JournalError):
        append_checkpoint_head(heads, namespace=NAMESPACE, key=HEAD_KEY,
                               checkpoint=invalid, previous={'sequence': 256, 'sha256': 'c' * 64})
