from pathlib import Path
import tempfile
import unittest

from provider_cutover import CutoverError, _quarantine
from provider_cutover_drained import run_fixture
from test_provider_cutover import Runtime


class DrainedRuntime(Runtime):
    def preserve_accepted_work_and_quarantine(self, ids):
        self.step('preserve_work')
        self.drain_ingress()
        assert _quarantine(self, ids)

    def complete_candidate_owner(self):
        self.step('complete_owner')

    def prepare_equivalent_probe(self, identifier, *, lock_fd):
        self.step('prepare_probe')
        assert identifier == self.ids['new_api']
        self.assert_lock_held(lock_fd)

    def drain_worker_and_queues(self):
        self.step('drain_queues')
        assert not self.items[self.ids['old_api']]['running']
        assert self.items[self.ids['old_worker']]['running']

    def probe_equivalent_provider(self, identifier):
        self._marked()
        self.step('portless_probe')
        assert identifier == self.ids['new_api']
        assert not self.items[self.ids['new_api']]['running']
        assert not self.items[self.ids['old_api']]['running']
        assert not self.items[self.ids['old_worker']]['running']
        self.step('assert_queues')

    def assert_api_ready(self, identifier):
        self.step('api_ready')
        assert self.items[identifier]['running']
        assert not self.items[self.ids['new_worker']]['running']


class DrainedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.state, self.backup = root / 'state', root / 'backup'
        self.state.mkdir(mode=0o700)
        self.backup.mkdir(mode=0o700)
        self.ids = {'old_api': 'a' * 64, 'old_worker': 'b' * 64, 'new_api': 'c' * 64, 'new_worker': 'd' * 64}
        self.images = {'old_api': 'sha256:' + 'a' * 64, 'new_api': 'sha256:' + 'a' * 64,
                       'old_worker': 'sha256:' + 'b' * 64, 'new_worker': 'sha256:' + 'b' * 64}
        self.runtime = DrainedRuntime(self.state, self.backup, self.ids, self.images)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cutover(self):
        return run_fixture(state_dir=self.state, backup_dir=self.backup, ids=self.ids, images=self.images,
                           other_markers=[], runtime=self.runtime)

    def test_probe_without_candidate_listener_then_candidate_ready(self):
        self.assertEqual(self.run_cutover()['status'], 'FIXTURE_DRAINED_CUTOVER_PASSED')
        events = self.runtime.events
        self.assertLess(events.index('stop:a'), events.index('drain_queues'))
        self.assertLess(events.index('drain_queues'), events.index('stop:b'))
        self.assertLess(events.index('assert_queues'), events.index('start:c'))
        self.assertLess(events.index('portless_probe'), events.index('start:c'))
        self.assertLess(events.index('api_ready'), events.index('start:d'))
        self.assertLess(events.index('worker_healthy'), events.index('open'))
        self.assertNotIn('start:a', events)
        self.assertNotIn('start:b', events)

    def test_failure_keeps_marker_and_does_not_start_old(self):
        for event in ('drain_queues', 'assert_queues', 'portless_probe', 'start:c', 'api_ready', 'start:d'):
            with self.subTest(event=event):
                self.runtime = DrainedRuntime(self.state, self.backup, self.ids, self.images, event)
                with self.assertRaises(CutoverError):
                    self.run_cutover()
                self.assertTrue((self.state / 'recovery.json').exists())
                self.assertNotIn('start:a', self.runtime.events)
                self.assertNotIn('start:b', self.runtime.events)
                (self.state / 'recovery.json').unlink()


if __name__ == '__main__':
    unittest.main()
