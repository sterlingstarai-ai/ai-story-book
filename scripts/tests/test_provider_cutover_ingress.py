from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from provider_cutover_ingress import DrainError, drain_proxy
from provider_cutover_journal import JournalError


class DrainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.item = dict(id='b' * 64, running=True, restart_policy='unless-stopped', identity_verified=True)
        self.events = []
        self.fenced = True

    def tearDown(self):
        self.tmp.cleanup()

    def drain(self, quit_ok=True, fence=None):
        def disable(_):
            self.events.append('disable')
            self.item['restart_policy'] = 'no'
        def quit_proxy(_):
            self.events.append('quit')
            if quit_ok:
                self.item['running'] = False
        return drain_proxy(directory=self.root, transaction='a' * 32, nginx_id='b' * 64,
                           inspect=lambda _: dict(self.item), disable_restart=disable, graceful_quit=quit_proxy,
                           direct_writer_fence=fence or (lambda: self.fenced), timeout=0.01, sleep=lambda _: None)

    def test_fence_required_before_any_mutation(self):
        self.fenced = False
        with self.assertRaises(DrainError):
            self.drain()
        self.assertEqual(self.events, [])

    def test_success_and_idempotent_stopped(self):
        self.drain()
        self.assertEqual(self.events, ['disable', 'quit'])
        self.assertFalse((self.root / 'docker-mutation.json').exists())
        self.drain()
        self.assertEqual(self.events, ['disable', 'quit'])

    def test_timeout_keeps_marker_and_rejects_retry(self):
        with self.assertRaises(JournalError):
            self.drain(quit_ok=False)
        self.assertTrue((self.root / 'docker-mutation.json').exists())
        with self.assertRaises(JournalError):
            self.drain()

    def test_identity_change_prevents_mutations(self):
        self.item['identity_verified'] = False
        with self.assertRaises(DrainError):
            self.drain()
        self.assertEqual(self.events, [])


if __name__ == '__main__':
    unittest.main()
