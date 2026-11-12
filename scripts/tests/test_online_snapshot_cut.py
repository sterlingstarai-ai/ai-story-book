"""Unit checks for cut ownership and timeout; real PostgreSQL is a separate gate."""

import importlib
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import time

import pytest
from psycopg.pq import TransactionStatus


@pytest.fixture
def sample(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    module = importlib.import_module('postgres_backup_fence')
    events = []

    class Cursor:
        def __init__(self, rows, *, sets=None):
            self.sets = [rows] if sets is None else sets
            self.position = 0

        def fetchone(self):
            return self.sets[self.position][0]

        def fetchall(self):
            return self.sets[self.position]

        def nextset(self):
            if self.position + 1 < len(self.sets):
                self.position += 1
                return True
            return None

    class Connection:
        def __init__(self, name):
            self.name = name
            self.closed = False
            self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE, backend_pid=100)
            self.tables = [(1, 'books'), (2, 'pages')]
            self.media_busy = False
            self.lock_busy = False
            self.released = True
            self.read_only = True
            self.bad_results = None
            self.export = '00000001-00000002-1' if name == 'cut' else '00000001-00000003-1'

        def execute(self, statement, parameters=None, **kwargs):
            command = str(statement)
            events.append((self.name, command))
            if kwargs:
                assert kwargs == {'prepare': False}
                events.append((self.name, 'single_batch'))
            if self.closed:
                raise RuntimeError('closed fixture connection')
            if 'BEGIN ISOLATION' in command:
                self.info.transaction_status = TransactionStatus.INTRANS
            if 'LOCK TABLE' in command and self.lock_busy:
                raise RuntimeError('fixture table is busy')
            if 'LOCK TABLE' in command:
                sets = [[], [], [], self.tables]
                if self.bad_results == 'missing':
                    sets.pop(0)
                elif self.bad_results == 'extra':
                    sets.append([])
                return Cursor([], sets=sets)
            if 'pg_try_advisory_lock' in command:
                return Cursor([(not self.media_busy,)])
            if 'pg_catalog.pg_class' in command:
                return Cursor(self.tables)
            if 'pg_export_snapshot' in command and 'pg_backend_pid()' in command:
                return Cursor([(True, self.export)])
            if 'SET TRANSACTION SNAPSHOT' in command and 'pg_export_snapshot' in command:
                sets = [[], [(self.export,)]]
                if self.bad_results == 'missing':
                    sets.pop(0)
                elif self.bad_results == 'extra':
                    sets.append([])
                return Cursor([], sets=sets)
            if 'pid = pg_backend_pid()' in command:
                return Cursor([(True,)])
            if 'pg_export_snapshot' in command:
                return Cursor([(self.export,)])
            if 'SELECT NOT EXISTS' in command:
                return Cursor([(self.released,)])
            if 'SHOW transaction_read_only' in command:
                return Cursor([('on' if self.read_only else 'off',)])
            return Cursor([(1,)])

        def close(self):
            events.append((self.name, 'close'))
            self.closed = True
            self.info.transaction_status = TransactionStatus.IDLE

        @contextmanager
        def pipeline(self):
            events.append((self.name, 'pipeline_enter'))
            try:
                yield
            finally:
                events.append((self.name, 'pipeline_sync'))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    class Socket:
        def __init__(self, connection):
            self.connection = connection

        def shutdown(self, _direction):
            events.append((self.connection.name, 'socket_shutdown'))
            self.connection.closed = True

        def close(self):
            pass

    cut, holder, fresh = (Connection(name) for name in ('cut', 'holder', 'fresh'))
    queue = iter((cut, holder, fresh))

    def connect(_self):
        connection = next(queue, None) or Connection('fresh')
        events.append((connection.name, 'connect'))
        return connection

    monkeypatch.setattr(module.OnlineSnapshotCut, '_connect', connect)
    monkeypatch.setattr(module.OnlineSnapshotCut, '_socket_copy', staticmethod(Socket))
    return module, cut, holder, fresh, events


def test_cut_prewarms_connections_transfers_snapshot_and_releases_locks(sample):
    module, cut, holder, fresh, events = sample
    with module.OnlineSnapshotCut({'PGHOST': 'fixture'}) as snapshot:
        assert [name for name, command in events if command == 'connect'] == ['cut', 'holder']
        assert not any('pg_try_advisory_lock' in command for _, command in events)
        result = snapshot.capture(lambda connection: {'same_connection': connection is cut})
        assert result == {'same_connection': True}
        assert cut.closed and not holder.closed
        assert snapshot.cut_released is True
        assert snapshot.snapshot_id == holder.export
        assert type(snapshot.cut_elapsed_ms) is int and 0 <= snapshot.cut_elapsed_ms < 2000
        assert any('SHARE MODE NOWAIT' in command for _, command in events)
        assert any('SET TRANSACTION READ ONLY' in command for _, command in events)
        assert sum(command == 'single_batch' for _, command in events) == 2
        assert any('SET TRANSACTION SNAPSHOT' in command and cut.export in command for _, command in events)
        snapshot.verify()
        assert fresh.closed and not holder.closed
    assert holder.closed and snapshot.snapshot_id is None


@pytest.mark.parametrize('failure', ['media_busy', 'table_busy', 'callback_error', 'callback_commit',
                                   'bad_cut_snapshot', 'bad_holder_snapshot', 'locks_remain',
                                   'missing_cut_results', 'extra_cut_results',
                                   'missing_holder_results', 'extra_holder_results'])
def test_failed_cut_closes_both_sessions_without_returning_a_snapshot(sample, failure):
    module, cut, holder, _fresh, _events = sample
    cut.media_busy = failure == 'media_busy'
    cut.lock_busy = failure == 'table_busy'
    if failure == 'bad_cut_snapshot':
        cut.export = 'not-an-exported-snapshot'
    if failure == 'bad_holder_snapshot':
        holder.export = 'not-an-exported-snapshot'
    holder.released = failure != 'locks_remain'
    if failure.endswith('_cut_results'):
        cut.bad_results = failure.partition('_')[0]
    elif failure.endswith('_holder_results'):
        holder.bad_results = failure.partition('_')[0]

    def callback(connection):
        if failure == 'callback_error':
            raise RuntimeError('fixture private provider error must stay suppressed')
        if failure == 'callback_commit':
            connection.info.transaction_status = TransactionStatus.IDLE
        return {}

    with module.OnlineSnapshotCut({}) as snapshot:
        with pytest.raises(module.BackupFenceError) as caught:
            snapshot.capture(callback)
        assert 'private provider' not in str(caught.value)
        assert cut.closed and holder.closed and snapshot.snapshot_id is None
        assert snapshot.cut_released is False


def test_watchdog_breaks_both_connections_while_a_callback_is_still_blocked(sample):
    module, cut, holder, _fresh, events = sample
    observed = []

    def stalled_callback(_connection):
        time.sleep(0.15)
        observed.append(cut.closed and holder.closed)
        return {}

    with module.OnlineSnapshotCut({}, cut_timeout_seconds=0.03) as snapshot:
        with pytest.raises(module.BackupFenceError, match='deadline'):
            snapshot.capture(stalled_callback)
        assert observed == [True]
        assert ('cut', 'socket_shutdown') in events and ('holder', 'socket_shutdown') in events
        assert 0 <= snapshot.cut_elapsed_ms < 150
        assert not snapshot.cut_released


@pytest.mark.parametrize('failure', ['closed', 'read_write', 'schema_changed'])
def test_lost_or_drifted_read_only_snapshot_cannot_verify(sample, failure):
    module, _cut, holder, fresh, _events = sample
    with module.OnlineSnapshotCut({}) as snapshot:
        snapshot.capture(lambda _connection: {})
        if failure == 'closed':
            holder.closed = True
        elif failure == 'read_write':
            holder.read_only = False
        else:
            fresh.tables = [(1, 'books')]
        with pytest.raises(module.BackupFenceError):
            snapshot.verify()


def test_a_cut_is_single_use_and_success_cancels_the_watchdog(sample):
    module, cut, holder, _fresh, _events = sample
    with module.OnlineSnapshotCut({}, cut_timeout_seconds=0.2) as snapshot:
        snapshot.capture(lambda _connection: {})
        with pytest.raises(module.BackupFenceError, match='fresh'):
            snapshot.capture(lambda _connection: {})
        time.sleep(0.25)
        assert cut.closed and not holder.closed


def test_full_validation_reads_only_the_original_holder_after_cut_release(sample):
    module, cut, holder, _fresh, _events = sample
    with module.OnlineSnapshotCut({}) as snapshot:
        with pytest.raises(module.BackupFenceError):
            snapshot.read_snapshot(lambda _connection: {})
        snapshot.capture(lambda _connection: {})
        def inspect(connection):
            assert cut.closed and snapshot.cut_released
            assert connection is holder and not holder.closed
            return {'validated': True}
        assert snapshot.read_snapshot(inspect) == {'validated': True}


def test_deferred_validation_cannot_fall_back_after_holder_loss(sample):
    module, _cut, holder, _fresh, _events = sample
    observed = []
    with module.OnlineSnapshotCut({}) as snapshot:
        snapshot.capture(lambda _connection: {})
        holder.close()
        with pytest.raises(module.BackupFenceError):
            snapshot.read_snapshot(lambda connection: observed.append(connection))
        assert observed == []


def test_deferred_validation_checks_holder_again_before_returning(sample):
    module, _cut, holder, _fresh, _events = sample
    with module.OnlineSnapshotCut({}) as snapshot:
        snapshot.capture(lambda _connection: {})
        with pytest.raises(module.BackupFenceError):
            snapshot.read_snapshot(lambda connection: connection.close())
        assert holder.closed


@pytest.mark.parametrize('value', [0, -1, True, 2.01, float('nan'), float('inf'), '2'])
def test_cut_deadline_cannot_be_disabled_or_extended_beyond_the_bound(sample, value):
    module, *_ = sample
    with pytest.raises(module.BackupFenceError, match='bounded timeout'):
        module.OnlineSnapshotCut({}, cut_timeout_seconds=value)
