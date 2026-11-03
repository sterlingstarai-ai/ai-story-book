from contextlib import contextmanager
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import provider_cutover_queue_probe as probe


class Inspect:
    def __init__(self):
        self.data = {'active_queues': [{'name': 'celery'}], 'active': [], 'reserved': [], 'scheduled': []}
    def __getattr__(self, method):
        return lambda: {'worker1': self.data[method]}


class QueueTests(unittest.TestCase):
    def test_inspection_budget_leaves_time_for_database_and_broker(self):
        # Four requests each in the before and after snapshots.
        self.assertLessEqual(8 * probe.INSPECT_TIMEOUT_SECONDS, 30)

    def test_worker_single_expected_idle_queue(self):
        inspect = Inspect()
        probe._worker_empty(inspect, 'worker1')
        inspect.data['reserved'] = [{'id': 'synthetic'}]
        with self.assertRaises(probe.QueueProbeError):
            probe._worker_empty(inspect, 'worker1')
        inspect.data['reserved'] = []
        inspect.data['active_queues'] = [{'name': 'unexpected'}]
        with self.assertRaises(probe.QueueProbeError):
            probe._worker_empty(inspect, 'worker1')

    def test_unavailable_or_additional_worker_is_not_treated_as_empty(self):
        for reply in (None, {}, {'worker1': [], 'worker2': []}):
            inspect = SimpleNamespace(active_queues=lambda: reply)
            with self.subTest(reply=reply), self.assertRaises(probe.QueueProbeError):
                probe._worker_empty(inspect, 'worker1')

    def test_database_counts_and_read_only(self):
        calls = []
        class Result:
            def scalar_one(self):
                return 0
        class Connection:
            def execute(self, query):
                calls.append(query)
                return Result()
        @contextmanager
        def connect():
            yield Connection()
        probe._database_empty(SimpleNamespace(connect=connect), lambda query: query)
        self.assertEqual(calls[0], 'SET TRANSACTION READ ONLY')
        self.assertEqual(len(calls), 4)
        class BusyConnection(Connection):
            def execute(self, query):
                class Busy:
                    def scalar_one(self): return 1
                return Busy()
        @contextmanager
        def busy_connect():
            yield BusyConnection()
        with self.assertRaises(probe.QueueProbeError):
            probe._database_empty(SimpleNamespace(connect=busy_connect), lambda query: query)

    def test_broker_all_queues_and_unacked_must_be_empty(self):
        counts = {'queued': 0, 'unacked': 0, 'index': 0}
        client = SimpleNamespace(hlen=lambda _: counts['unacked'], zcard=lambda _: counts['index'])
        channel = SimpleNamespace(_size=lambda _: counts['queued'], client=client, unacked_key='unacked',
                                  unacked_index_key='unacked_index', close=lambda: None)
        @contextmanager
        def connect():
            yield SimpleNamespace(channel=lambda: channel)
        app = SimpleNamespace(connection_for_read=connect, conf=SimpleNamespace(beat_schedule={}))
        settings = SimpleNamespace(celery_broker_url='redis://asb-pilot-redis:6379/1', celery_redis_namespace='')
        probe._broker_empty(app, settings)
        counts['unacked'] = 1
        with self.assertRaises(probe.QueueProbeError):
            probe._broker_empty(app, settings)
        counts['unacked'] = 0
        settings.celery_broker_url = 'redis://other:6379/1'
        with self.assertRaises(probe.QueueProbeError):
            probe._broker_empty(app, settings)


if __name__ == '__main__':
    unittest.main()
