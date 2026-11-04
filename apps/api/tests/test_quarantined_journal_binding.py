"""Synthetic stream and witness binding checks; never touch an external store."""
import hashlib
import importlib
import io
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from src.services.privacy_journal import JournalEntry, JournalScan
from src.services.privacy_journal_verify import fingerprint_entries


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('quarantined_backup_receiver'), importlib.import_module('quarantined_replay_adapter')


def test_live_boundary_source_disallows_driver_endpoint_overrides(modules):
    boundary = importlib.import_module('live_privacy_boundary')
    url = make_url('postgresql+psycopg://fixture@source.example/storybook'
                   '?sslmode=verify-full&channel_binding=require')
    assert boundary.source_identity(url)
    for override in ({'host': 'other.example'}, {'hostaddr': '192.0.2.1'}, {'dbname': 'other'}):
        with pytest.raises(boundary.LivePrivacyBoundaryError):
            boundary.source_identity(url.update_query_dict(override))


@pytest.mark.asyncio
async def test_live_boundary_rejects_replaced_transaction(modules):
    boundary = importlib.import_module('live_privacy_boundary')
    session = SimpleNamespace(get_transaction=lambda: SimpleNamespace(is_active=True))
    db = SimpleNamespace(sync_session=session)
    fence = boundary.LivePrivacyBoundary(db, None, {}, 'fixture', 1)
    with pytest.raises(boundary.LivePrivacyBoundaryError, match='no longer verified'):
        await fence.verify()


@pytest.mark.asyncio
async def test_isolated_replay_does_not_accept_success_message_from_failed_child(modules):
    live = importlib.import_module('live_fenced_replay_preflight')
    process = SimpleNamespace(is_alive=lambda: False, join=lambda timeout: None, exitcode=1)
    with pytest.raises(live.LiveFencedReplayError, match='did not exit cleanly'):
        await live._wait_successful_exit(process, time.monotonic() + 1)


def _frame(kind, value):
    header = {'kind': kind, 'size': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
    return json.dumps(header).encode() + b'\n' + value


def test_receiver_keeps_checkpoint_and_rejects_mismatched_marker(tmp_path, monkeypatch, modules):
    receiver, _ = modules
    monkeypatch.setattr(receiver, 'ROOT', tmp_path)
    dump = b'invented database bytes'
    manifest = json.dumps({'format_version': 1, 'database_scope': 'public',
        'requires_latest_deletion_and_identity_revocations': True,
        'database': {'file': 'database.dump', 'size': len(dump), 'sha256': hashlib.sha256(dump).hexdigest()},
        'objects': []}).encode()
    marker = json.dumps({'version': 1, 'manifest_sha256': hashlib.sha256(manifest).hexdigest(),
                         'restore_authorized': False}).encode()
    object_header = {'kind': 'object', 'name': 'database.dump', 'size': len(dump),
                     'sha256': hashlib.sha256(dump).hexdigest()}
    stream = (_frame('manifest', manifest) + _frame('verification', marker)
              + json.dumps(object_header).encode() + b'\n' + dump + b'{"kind":"end"}\n')
    assert receiver.receive(io.BytesIO(stream), 'a' * 32)['restore_authorized'] is False
    assert (tmp_path / ('ingest-' + 'a' * 32) / 'verified.json').read_bytes() == marker
    for child in tmp_path.iterdir():
        import shutil
        shutil.rmtree(child)
    wrong = json.dumps({'version': 1, 'manifest_sha256': '0' * 64, 'restore_authorized': False}).encode()
    with pytest.raises(receiver.ReceiveError, match='marker'):
        receiver.receive(io.BytesIO(_frame('manifest', manifest) + _frame('verification', wrong)), 'a' * 32)
    assert not list(tmp_path.iterdir())


def test_verified_witness_must_contain_exact_restored_outbox(monkeypatch, modules):
    _, adapter = modules
    item = JournalEntry('a' * 32, 'account_delete', '00000000-0000-4000-8000-000000000011', 1)
    scan = JournalScan((item,), 0)
    monkeypatch.setattr(adapter, '_verified_witnessed_scan', lambda **_: scan)
    digest = fingerprint_entries((item,))
    target = {'status': 'RESTORED_TARGET_MATCHES_BACKUP_QUARANTINED', 'latest_journal_verified': False,
              'privacy_replay_authorized': False, 'restore_authorized': False}
    binding = {'status': 'BACKUP_OUTBOX_CHECKPOINT_MATCHES', 'event_ids': [item.event_id],
               'journal_sha256': digest, 'restore_authorized': False}
    def run(argv, **_kwargs):
        result = binding if argv[-2].endswith('quarantined_outbox_binding.py') else target
        return SimpleNamespace(returncode=0, stdout=json.dumps(result).encode())
    monkeypatch.setattr(adapter.subprocess, 'run', run)
    counts = {'backup_event_count': 1, 'later_event_count': 0}
    assert adapter._evaluate(lambda: {}, 'b' * 64, 'c' * 32, timeout=10) == counts
    assert adapter._evaluate(lambda: {}, 'b' * 64, 'c' * 32, timeout=10,
                             live_journal_binding=(1, digest), require_exact_backup=True) == counts
    newer = JournalEntry('d' * 32, 'account_delete', '00000000-0000-4000-8000-000000000012', 1)
    newer_scan = JournalScan((item, newer), 0)
    monkeypatch.setattr(adapter, '_verified_witnessed_scan', lambda **_: newer_scan)
    assert adapter._evaluate(lambda: {}, 'b' * 64, 'c' * 32, timeout=10,
                             live_journal_binding=(2, fingerprint_entries(newer_scan.committed))) == {
                                 'backup_event_count': 1, 'later_event_count': 1}
    with pytest.raises(ValueError, match='newer privacy events'):
        adapter._evaluate(lambda: {}, 'b' * 64, 'c' * 32, timeout=10,
                          live_journal_binding=(2, fingerprint_entries(newer_scan.committed)), require_exact_backup=True)
    monkeypatch.setattr(adapter, '_verified_witnessed_scan', lambda **_: scan)
    for stale in ((2, digest), (1, '0' * 64)):
        with pytest.raises(ValueError, match='fenced live source'):
            adapter._evaluate(lambda: {}, 'b' * 64, 'c' * 32, timeout=10,
                              live_journal_binding=stale)
    binding['event_ids'] = ['d' * 32]
    with pytest.raises(ValueError, match='does not contain'):
        adapter._evaluate(lambda: {}, 'b' * 64, 'c' * 32, timeout=10)
    binding['event_ids'] = [item.event_id]
    binding['journal_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='does not contain'):
        adapter._evaluate(lambda: {}, 'b' * 64, 'c' * 32, timeout=10)


def test_signed_prefix_must_cover_all_scanned_events_for_binding(monkeypatch, modules):
    evidence = importlib.import_module('independent_journal_evidence')
    from src.services.privacy_journal import PrivacyJournal
    journal = PrivacyJournal(object(), b'k' * 32)
    item = JournalEntry('a' * 32, 'account_delete', '00000000-0000-4000-8000-000000000011', 1)
    monkeypatch.setattr(journal, 'scan', lambda: JournalScan((item,), 0))
    monkeypatch.setattr(evidence, 'verify_receipt', lambda *_a, **_k:
                        {'status': 'SIGNED_OBSERVATION_VALID', 'restore_authorized': False})
    monkeypatch.setattr(evidence, 'verify_anchored_checkpoint', lambda *_a, **_k:
                        {'status': 'ANCHORED_WITNESSED_PREFIX_MATCHES', 'checkpoint_count': 0,
                         'journal_count': 1, 'restore_authorized': False})
    args = dict(journal=journal, head_store=object(), checkpoint_store=object(), public_key=None, receipt=None,
                namespace='fixture', trusted_head={}, candidate_head={}, head_key=b'', checkpoint_key=b'',
                now=1, max_age=1)
    assert evidence.verify_witnessed_journal(**args)['restore_authorized'] is False
    with pytest.raises(evidence.IndependentJournalEvidenceError, match='does not cover'):
        evidence._verified_witnessed_scan(require_full_coverage=True, **args)
