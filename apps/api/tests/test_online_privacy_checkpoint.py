"""Online privacy cuts keep exact content checks and import the real DB snapshot."""

from contextlib import asynccontextmanager
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from psycopg.pq import TransactionStatus
import pytest

from src.services.privacy_journal import (
    ConsentState, CredentialState, DeletionReceipt, JournalEntry, JournalScan,
    consent_state_to_payload, credential_state_to_payload, deletion_receipt_to_payload,
)
from src.services.privacy_journal_verify import fingerprint_entries


@pytest.fixture
def checkpoint_module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('online_privacy_checkpoint')


def _entry(event_id='1' * 32, revision=1, **changes):
    values = {'event_id': event_id, 'action': 'consent_grant',
              'subject': '10000000-0000-4000-8000-000000000001', 'revision': revision,
              'consent_state': ConsentState(True, False, True, 'v1')}
    return JournalEntry(**(values | changes))


def _row(entry, *, published=True):
    return (entry.event_id, entry.action, entry.subject, entry.revision,
            credential_state_to_payload(entry.credential_state), entry.resource_id,
            consent_state_to_payload(entry.consent_state), deletion_receipt_to_payload(entry.deletion_receipt),
            'published' if published else None)


def _connection(rows):
    connection = Mock(closed=False, info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS))
    connection.execute.return_value.fetchall.return_value = rows
    return connection


def _checkpoint(scan):
    return {'status': 'CURRENT_OUTBOX_MATCHES_JOURNAL', 'event_count': len(scan.committed),
            'journal_sha256': fingerprint_entries(scan.committed), 'restore_authorized': False}


@pytest.mark.parametrize('mapping_rows', [False, True])
def test_cut_covers_all_snapshot_rows_and_full_canonical_payload(checkpoint_module, mapping_rows):
    events = (_entry(), _entry('2' * 32, 2, action='book_delete', consent_state=None,
                              resource_id='book-one', deletion_receipt=DeletionReceipt('3' * 32)))
    rows = [_row(entry) for entry in events]
    if mapping_rows:
        rows = [dict(zip(checkpoint_module._FIELDS, row)) for row in rows]
    scan = JournalScan(events, 0)
    connection = _connection(rows)
    assert checkpoint_module.cut_checkpoint(connection, scan) == _checkpoint(scan)
    query = connection.execute.call_args.args[0]
    assert 'FROM public.privacy_journal_outbox' in query and 'WHERE' not in query and 'LIMIT' not in query


def test_credential_hash_state_is_compared_without_exposing_it(checkpoint_module):
    event = _entry(action='credential_revoke', consent_state=None,
                   credential_state=CredentialState('a' * 64, None, None, None))
    scan = JournalScan((event,), 0)
    altered = _entry(action='credential_revoke', consent_state=None,
                     credential_state=CredentialState('b' * 64, None, None, None))
    with pytest.raises(checkpoint_module.OnlinePrivacyCheckpointError) as captured:
        checkpoint_module.cut_checkpoint(_connection([_row(altered)]), scan)
    assert 'a' * 64 not in str(captured.value) and 'b' * 64 not in str(captured.value)


@pytest.mark.parametrize('fault', ['unpublished', 'revision_gap', 'duplicate_db', 'different_body', 'missing_row'])
def test_incomplete_or_changed_snapshot_cannot_match_an_old_scan(checkpoint_module, fault):
    event = _entry()
    rows = [_row(event)]
    if fault == 'unpublished':
        rows = [_row(event, published=False)]
    elif fault == 'revision_gap':
        rows = [_row(_entry(revision=2))]
    elif fault == 'duplicate_db':
        rows *= 2
    elif fault == 'different_body':
        rows = [_row(_entry(consent_state=ConsentState(True, True, True, 'v1')))]
    elif fault == 'missing_row':
        rows = []
    with pytest.raises(checkpoint_module.OnlinePrivacyCheckpointError):
        checkpoint_module.cut_checkpoint(_connection(rows), JournalScan((event,), 0))


@pytest.mark.parametrize('fault', ['pending', 'boolean_pending', 'authorized', 'duplicate_scan', 'extra_event'])
def test_cut_never_ignores_pending_or_extra_journal_records(checkpoint_module, fault):
    event = _entry()
    scan = JournalScan((event,), 0)
    if fault == 'pending':
        scan = JournalScan((event,), 1)
    elif fault == 'boolean_pending':
        scan = JournalScan((event,), False)
    elif fault == 'authorized':
        scan = JournalScan((event,), 0, True)
    elif fault == 'duplicate_scan':
        scan = JournalScan((event, event), 0)
    elif fault == 'extra_event':
        scan = JournalScan((event, _entry('2' * 32, 2)), 0)
    with pytest.raises(checkpoint_module.OnlinePrivacyCheckpointError):
        checkpoint_module.cut_checkpoint(_connection([_row(event)]), scan)


def test_cut_requires_an_active_transaction_and_redacts_database_errors(checkpoint_module):
    connection = _connection([])
    connection.info.transaction_status = TransactionStatus.IDLE
    with pytest.raises(checkpoint_module.OnlinePrivacyCheckpointError):
        checkpoint_module.cut_checkpoint(connection, JournalScan((), 0))
    connection.execute.assert_not_called()
    connection.info.transaction_status = TransactionStatus.INTRANS
    connection.execute.side_effect = RuntimeError('dummy-private-payload-must-not-be-shown')
    with pytest.raises(checkpoint_module.OnlinePrivacyCheckpointError) as captured:
        checkpoint_module.cut_checkpoint(connection, JournalScan((), 0))
    assert 'dummy-private-payload' not in str(captured.value)


class _SnapshotSession:
    def __init__(self, rows):
        self.rows = [SimpleNamespace(**dict(zip(
            ('event_id', 'action', 'user_key', 'revision', 'credential_state', 'resource_id',
             'consent_state', 'deletion_receipt', 'published_at'), row,
        ))) for row in rows]
        self.commands = []
        self.modes = ('repeatable read', 'on')
        self.active = False
        self.dialect = 'postgresql'
        self.import_error = False
        self.connection = AsyncMock()
        self.scalar_reads = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.active = False

    def in_transaction(self):
        return self.active

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name=self.dialect))

    @asynccontextmanager
    async def begin(self):
        self.active = True
        try:
            yield self
        finally:
            self.active = False

    async def execute(self, statement):
        sql = str(statement)
        self.commands.append(sql)
        if sql.startswith('SET TRANSACTION SNAPSHOT') and self.import_error:
            raise RuntimeError('dummy-database-secret')
        return SimpleNamespace(one=lambda: self.modes)

    async def scalars(self, statement):
        self.scalar_reads += 1
        values = ([row.event_id for row in self.rows]
                  if len(statement.selected_columns) == 1 else self.rows)
        return SimpleNamespace(all=lambda: values)


@pytest.mark.asyncio
async def test_verification_imports_before_query_and_uses_real_checkpoint_verifier(checkpoint_module):
    event = _entry()
    scan0 = JournalScan((event,), 0)
    # A later event is allowed only because the immutable snapshot itself still
    # contains exactly all original rows, not a filtered current-DB query.
    latest = JournalScan((event, _entry('2' * 32, 2)), 0)
    session = _SnapshotSession([_row(event)])
    result = await checkpoint_module.verify_online_checkpoint(
        lambda: session, '00000003-0000001B-1', latest, _checkpoint(scan0),
    )
    assert result == {'status': 'BACKUP_CHECKPOINT_MATCHES', 'event_count': 1, 'restore_authorized': False}
    session.connection.assert_awaited_once_with(execution_options={'isolation_level': 'REPEATABLE READ'})
    assert session.commands[:2] == [
        'SET TRANSACTION READ ONLY', "SET TRANSACTION SNAPSHOT '00000003-0000001B-1'",
    ]
    assert session.commands[2].startswith('SELECT current_setting')
    assert session.scalar_reads == 2
    assert not session.active


@pytest.mark.parametrize('snapshot_id', [None, '', 'not-a-snapshot', '00000003-0000001B-0',
                                        "00000003-0000001B-1'; SELECT 1; --"])
@pytest.mark.asyncio
async def test_invalid_snapshot_token_is_rejected_before_opening_a_session(checkpoint_module, snapshot_id):
    factory = Mock()
    with pytest.raises(checkpoint_module.OnlinePrivacyCheckpointError):
        await checkpoint_module.verify_online_checkpoint(factory, snapshot_id, JournalScan((), 0), _checkpoint(JournalScan((), 0)))
    factory.assert_not_called()


@pytest.mark.parametrize('fault', ['pending', 'missing_event', 'changed_body', 'incorrect_count', 'incorrect_hash'])
@pytest.mark.asyncio
async def test_imported_snapshot_and_captured_checkpoint_must_match_exactly(checkpoint_module, fault):
    event = _entry()
    original = JournalScan((event,), 0)
    latest = original
    checkpoint = _checkpoint(original)
    session = _SnapshotSession([_row(event)])
    if fault == 'pending':
        latest = JournalScan((event,), 1)
    elif fault == 'missing_event':
        latest = JournalScan((), 0)
    elif fault == 'changed_body':
        latest = JournalScan((_entry(consent_state=ConsentState(True, True, True, 'v1')),), 0)
    elif fault == 'incorrect_count':
        checkpoint['event_count'] = 0
    elif fault == 'incorrect_hash':
        checkpoint['journal_sha256'] = '0' * 64
    with pytest.raises(checkpoint_module.OnlinePrivacyCheckpointError):
        await checkpoint_module.verify_online_checkpoint(lambda: session, '00000003-0000001B-1', latest, checkpoint)
    assert not session.active


@pytest.mark.parametrize('fault', ['active_session', 'wrong_dialect', 'import_failure', 'wrong_modes'])
@pytest.mark.asyncio
async def test_failed_import_or_wrong_transaction_never_falls_back_to_live_state(checkpoint_module, fault):
    session = _SnapshotSession([])
    if fault == 'active_session':
        session.active = True
    elif fault == 'wrong_dialect':
        session.dialect = 'sqlite'
    elif fault == 'import_failure':
        session.import_error = True
    elif fault == 'wrong_modes':
        session.modes = ('read committed', 'off')
    with pytest.raises(checkpoint_module.OnlinePrivacyCheckpointError) as captured:
        await checkpoint_module.verify_online_checkpoint(
            lambda: session, '00000003-0000001B-1', JournalScan((), 0), _checkpoint(JournalScan((), 0)),
        )
    assert 'dummy-database-secret' not in str(captured.value)
    assert session.scalar_reads == 0
