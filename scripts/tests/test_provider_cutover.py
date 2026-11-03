"""Offline state-machine tests; no real credentials or production services."""
import fcntl
import json
import os
from pathlib import Path
import tempfile
import unittest

from provider_cutover import CutoverError, recover_fixture, run_fixture_cutover


class Runtime:
    def __init__(self, state, backup, ids, images, fail=None):
        self.state, self.backup, self.ids = state, backup, ids
        self.fail = fail
        self.events = []
        self.counts = {}
        self.drained = False
        self.items = {
            v: {'id': v, 'name': {'old_api': 'asb-pilot-api', 'old_worker': 'asb-pilot-worker',
                                  'new_api': 'asb-provider-next-api', 'new_worker': 'asb-provider-next-worker'}[k],
                'image_id': images[k], 'running': k.startswith('old_'),
                'restart_policy': 'unless-stopped' if k.startswith('old_') else 'no'}
            for k, v in ids.items()
        }

    def step(self, event):
        self.events.append(event)
        self.counts[event] = self.counts.get(event, 0) + 1
        if self.fail in (event, event + '@' + str(self.counts[event])):
            self.fail = None
            raise RuntimeError('synthetic fault')

    def inspect(self, identifier):
        return dict(self.items[identifier])

    def assert_candidate_and_interlocks(self, ids, images, *, lock_fd, old_restart):
        self.step('preflight')
        self.assert_lock_held(lock_fd)
        assert all(self.items[ids[slot]]['restart_policy'] == old_restart
                   for slot in ('old_api', 'old_worker'))

    def assert_lock_held(self, lock_fd):
        assert os.fstat(lock_fd).st_ino == (self.backup / 'backup.lock').stat().st_ino
        fd = os.open(self.backup / 'backup.lock', os.O_RDWR)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            raise AssertionError('exclusive lock not held')
        finally:
            os.close(fd)

    def _marked(self):
        assert (self.state / 'recovery.json').is_file()

    def drain_ingress(self):
        self.step('drain')
        self.drained = True

    def assert_ingress_drained(self):
        self.step('assert_drain')
        assert self.drained

    def assert_worker_idle(self):
        self.step('idle')

    def disable_restart(self, identifier):
        self.step('disable:' + identifier[0])
        self.items[identifier]['restart_policy'] = 'no'

    def stop(self, identifier):
        self._marked()
        self.step('stop:' + identifier[0])
        self.items[identifier]['running'] = False

    def rename(self, identifier, name):
        self._marked()
        self.step('rename:' + identifier[0])
        if any(item['name'] == name for item in self.items.values()):
            raise RuntimeError('name occupied')
        self.items[identifier]['name'] = name

    def start(self, identifier):
        self._marked()
        self.step('start:' + identifier[0])
        assert identifier not in (self.ids['old_api'], self.ids['old_worker'])
        self.items[identifier]['running'] = True

    def probe_provider_and_assert_readiness(self, identifier):
        self.step('probe')
        assert self.drained and self.items[identifier]['running']
        assert not self.items[self.ids['new_worker']]['running']

    def assert_worker_healthy(self, identifier):
        self.step('worker_healthy')
        assert self.items[identifier]['running']

    def assert_no_unresolved_daemon_operations(self):
        self.step('daemon_confirmed')

    def enable_restart(self, identifier):
        self._marked()
        self.step('enable:' + identifier[0])
        assert identifier not in (self.ids['old_api'], self.ids['old_worker'])
        self.items[identifier]['restart_policy'] = 'unless-stopped'

    def reload_proxy(self):
        self.step('reload')

    def open_ingress(self):
        self.step('open')
        self.drained = False

    def assert_live_candidate(self, api, worker):
        self.step('live')
        assert not self.drained and self.items[api]['running'] and self.items[worker]['running']


class FixtureCutoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.state, self.backup = root / 'state', root / 'backup'
        self.state.mkdir(mode=0o700)
        self.backup.mkdir(mode=0o700)
        self.ids = {'old_api': 'a' * 64, 'old_worker': 'b' * 64,
                    'new_api': 'c' * 64, 'new_worker': 'd' * 64}
        self.images = {'old_api': 'sha256:' + 'a' * 64, 'new_api': 'sha256:' + 'a' * 64,
                       'old_worker': 'sha256:' + 'b' * 64, 'new_worker': 'sha256:' + 'b' * 64}
        self.runtime = Runtime(self.state, self.backup, self.ids, self.images)
        self.other = [root / 'privacy.json', root / 'backup.json', root / 'narration.json']

    def run_cutover(self):
        return run_fixture_cutover(state_dir=self.state, backup_dir=self.backup,
                                   ids=self.ids, images=self.images, other_markers=self.other,
                                   runtime=self.runtime)

    def test_success_requires_probe_before_worker_and_never_starts_old(self):
        result = self.run_cutover()
        self.assertEqual(result['status'], 'FIXTURE_CUTOVER_PASSED')
        self.assertFalse(result['production_authorized'])
        self.assertFalse((self.state / 'recovery.json').exists())
        events = self.runtime.events
        self.assertLess(events.index('drain'), events.index('stop:a'))
        self.assertLess(events.index('probe'), events.index('start:d'))
        self.assertLess(events.index('worker_healthy'), events.index('open'))
        self.assertNotIn('start:a', events)
        self.assertNotIn('start:b', events)
        self.assertFalse(self.runtime.items[self.ids['old_api']]['running'])
        self.assertEqual(self.runtime.items[self.ids['old_api']]['restart_policy'], 'no')

    def test_failures_keep_marker_close_ingress_and_quarantine_all(self):
        for event in ('idle@3', 'stop:a', 'stop:b', 'rename:a', 'rename:b', 'rename:c', 'rename:d',
                      'start:c', 'probe', 'start:d', 'worker_healthy', 'enable:c', 'enable:d',
                      'reload', 'open', 'live'):
            with self.subTest(event=event):
                self.runtime = Runtime(self.state, self.backup, self.ids, self.images, event)
                with self.assertRaises(CutoverError):
                    self.run_cutover()
                self.assertTrue((self.state / 'recovery.json').is_file())
                self.assertTrue(self.runtime.drained)
                for item in self.runtime.items.values():
                    self.assertFalse(item['running'])
                    self.assertEqual(item['restart_policy'], 'no')
                self.assertNotIn('start:a', self.runtime.events)
                self.assertNotIn('start:b', self.runtime.events)
                result = recover_fixture(state_dir=self.state, backup_dir=self.backup, runtime=self.runtime)
                self.assertEqual(result['status'], 'FIXTURE_QUARANTINED')
                self.assertTrue((self.state / 'recovery.json').is_file())
                (self.state / 'recovery.json').unlink()

    def test_pre_marker_failures_never_start_or_swap_a_candidate(self):
        for event in ('drain', 'idle', 'disable:a', 'disable:b', 'preflight@2', 'daemon_confirmed@2'):
            with self.subTest(event=event):
                self.runtime = Runtime(self.state, self.backup, self.ids, self.images, event)
                with self.assertRaises(CutoverError):
                    self.run_cutover()
                self.assertFalse((self.state / 'recovery.json').exists())
                self.assertTrue(self.runtime.items[self.ids['old_api']]['running'])
                self.assertTrue(self.runtime.items[self.ids['old_worker']]['running'])
                self.assertFalse(self.runtime.items[self.ids['new_api']]['running'])
                self.assertFalse(self.runtime.items[self.ids['new_worker']]['running'])
                self.assertFalse(any(event.startswith(('start:', 'rename:')) for event in self.runtime.events))

    def test_preexisting_recovery_or_busy_lock_prevents_all_mutations(self):
        self.other[0].write_text('{}')
        with self.assertRaises(CutoverError):
            self.run_cutover()
        self.assertEqual(self.runtime.events, [])
        self.other[0].unlink()
        fd = os.open(self.backup / 'backup.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(CutoverError):
                self.run_cutover()
            self.assertEqual(self.runtime.events, [])
        finally:
            os.close(fd)

    def test_tampered_marker_never_touches_containers(self):
        marker = self.state / 'recovery.json'
        marker.write_text(json.dumps({'version': True, 'containers': self.ids}))
        marker.chmod(0o600)
        with self.assertRaises(CutoverError):
            recover_fixture(state_dir=self.state, backup_dir=self.backup, runtime=self.runtime)
        self.assertEqual(self.runtime.events, [])
        self.assertTrue(marker.exists())

    def test_preexisting_unresolved_daemon_request_blocks_before_marker(self):
        self.runtime.fail = 'daemon_confirmed'
        with self.assertRaises(CutoverError):
            self.run_cutover()
        self.assertFalse((self.state / 'recovery.json').exists())
        self.assertTrue(self.runtime.items[self.ids['old_api']]['running'])
        self.assertNotIn('start:a', self.runtime.events)

    def test_noop_stop_or_interrupt_never_reports_success(self):
        self.runtime.stop = lambda _id: None
        with self.assertRaises(CutoverError):
            self.run_cutover()
        self.assertTrue((self.state / 'recovery.json').exists())
        self.assertNotIn('start:a', self.runtime.events)
        (self.state / 'recovery.json').unlink()
        self.runtime = Runtime(self.state, self.backup, self.ids, self.images)
        def interrupt(_id):
            raise KeyboardInterrupt()
        self.runtime.probe_provider_and_assert_readiness = interrupt
        with self.assertRaises(CutoverError):
            self.run_cutover()
        self.assertTrue((self.state / 'recovery.json').exists())
        self.assertTrue(self.runtime.drained)
        self.assertTrue(all(not item['running'] for item in self.runtime.items.values()))

    def test_unknown_id_or_inflight_daemon_leaves_marker_and_failure(self):
        self.runtime.fail = 'probe'
        with self.assertRaises(CutoverError):
            self.run_cutover()
        del self.runtime.items[self.ids['new_worker']]
        with self.assertRaises(CutoverError):
            recover_fixture(state_dir=self.state, backup_dir=self.backup, runtime=self.runtime)
        self.assertTrue((self.state / 'recovery.json').exists())


if __name__ == '__main__':
    unittest.main()
