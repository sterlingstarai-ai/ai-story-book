"""Prefetch is an exact S-result cache, never a live-read fallback."""

import importlib
from pathlib import Path
import re
from types import SimpleNamespace

from psycopg import sql
import pytest


@pytest.fixture
def sample(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    module = importlib.import_module('online_backup')

    class Cursor:
        def __init__(self, connection, result):
            self.connection = connection
            self.result = result
            self.fetched = False

        def fetchone(self):
            assert self.connection.batch_completed
            if self.fetched:
                return ('unexpected',) if self.connection.bad_results == 'extra_row' else None
            self.fetched = True
            return self.result

        def nextset(self):
            return True if self.connection.bad_results == 'extra_set' else None

    class Connection:
        closed = False
        connection = None
        info = SimpleNamespace(transaction_status='fixture-active')

        def __init__(self):
            self.batch_completed = False
            self.executed = []
            self.sends = 0
            self.bad_results = None
            self.results = {'SELECT idle': [('idle',)], 'SELECT refs': [('key',)], 'SELECT empty': []}

        def execute(self, statement, *, prepare):
            assert prepare is False
            self.sends += 1
            query = module._query_key(self, statement)
            assert query.startswith('SELECT ') and ';' not in query
            assert 'jsonb_agg(jsonb_build_array(' in query
            keys = re.findall(r'FROM \(\s*(SELECT (?:idle|refs|empty))\) AS q', query)
            self.executed.extend(keys)
            self.batch_completed = True
            result = [[list(row) for row in self.results[key]] for key in keys]
            if self.bad_results == 'missing_column':
                result.pop()
            elif self.bad_results == 'extra_column':
                result.append([])
            elif self.bad_results == 'row_width':
                result[0][0].append('unexpected')
            elif self.bad_results == 'not_array':
                result[0] = {}
            return Cursor(self, tuple(result))

    return module, Connection()


def test_prefetch_fetches_exact_results_after_one_aggregate_select(sample):
    module, connection = sample
    view = module._prefetch_cut_queries(connection, ('SELECT idle', sql.SQL('SELECT refs'), 'SELECT empty'), column_counts=(1, 1, 1))
    assert connection.executed == ['SELECT idle', 'SELECT refs', 'SELECT empty']
    assert view.execute('SELECT idle').fetchone() == ('idle',)
    assert view.execute(sql.SQL('SELECT refs')).fetchall() == [('key',)]
    assert list(view.execute('SELECT refs')) == [('key',)]
    assert view.execute('SELECT empty').fetchone() is None
    assert view.info is connection.info
    assert len(connection.executed) == 3
    assert connection.sends == 1


@pytest.mark.parametrize('query,parameters', [('SELECT other', None), ('SELECT idle', ('unreviewed',))])
def test_unknown_queries_and_parameters_cannot_fall_back_to_the_live_database(sample, query, parameters):
    module, connection = sample
    view = module._prefetch_cut_queries(connection, ('SELECT idle',), column_counts=(1,))
    with pytest.raises(module.OnlineBackupError):
        view.execute(query, parameters)
    assert connection.executed == ['SELECT idle']


def test_a_closed_snapshot_cannot_serve_even_known_prefetched_rows(sample):
    module, connection = sample
    view = module._prefetch_cut_queries(connection, ('SELECT idle',), column_counts=(1,))
    connection.closed = True
    with pytest.raises(module.OnlineBackupError):
        view.execute('SELECT idle')


@pytest.mark.parametrize('queries', [(), ('SELECT idle', 'SELECT idle')])
def test_duplicate_or_empty_query_sets_fail_before_source_execution(sample, queries):
    module, connection = sample
    with pytest.raises(module.OnlineBackupError):
        module._prefetch_cut_queries(connection, queries, column_counts=(1,) * len(queries))
    assert connection.executed == []


@pytest.mark.parametrize('damage', ['missing_column', 'extra_column', 'row_width', 'not_array', 'extra_row', 'extra_set'])
def test_invalid_aggregate_results_cannot_be_reinterpreted(sample, damage):
    module, connection = sample
    connection.bad_results = damage
    with pytest.raises(module.OnlineBackupError, match='results|positional rows'):
        module._prefetch_cut_queries(connection, ('SELECT idle', 'SELECT refs'), column_counts=(1, 1))


@pytest.mark.parametrize('counts', [(), (0,), (True,), (33,), (1, 1)])
def test_aggregate_column_counts_are_fixed_and_bounded(sample, counts):
    module, connection = sample
    with pytest.raises(module.OnlineBackupError):
        module._prefetch_cut_queries(connection, ('SELECT idle',), column_counts=counts)
    assert connection.executed == []
