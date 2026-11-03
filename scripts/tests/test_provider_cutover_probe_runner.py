from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from provider_cutover_probe_runner import API_IMAGE, CandidateProbeError, run_candidate_probe
from provider_cutover_journal import JournalError


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.id = 'b' * 64
        self.item = dict(id=self.id, name='asb-pilot-api', image_id=API_IMAGE, running=True,
                         restart_policy='no', candidate_config_verified=True)
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_probe(self, runner, fence=lambda: True):
        return run_candidate_probe(directory=self.root, transaction='a' * 32, candidate_id=self.id,
                                   inspect=lambda _: dict(self.item), ingress_fenced=fence, runner=runner)

    def ok(self, args, **kwargs):
        self.calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=b'PROVIDER_PROBE_OK\n')

    def test_pinned_success_has_no_secret_in_argv(self):
        self.assertTrue(self.run_probe(self.ok))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0][5], self.id)
        self.assertIn(b'async def probe_inside', self.calls[0][1]['input'])
        self.assertEqual(self.calls[0][1]['env'], {'PATH': '/usr/bin:/bin', 'HOME': '/root'})
        self.assertEqual(self.calls[0][0][1:3], ['--host', 'unix:///var/run/docker.sock'])
        self.assertFalse((self.root / 'docker-mutation.json').exists())

    def test_unfenced_and_unpinned_fail_before_exec(self):
        with self.assertRaises(CandidateProbeError):
            self.run_probe(self.ok, fence=lambda: False)
        self.item['candidate_config_verified'] = False
        with self.assertRaises(CandidateProbeError):
            self.run_probe(self.ok)
        self.assertEqual(self.calls, [])

    def test_timeout_stays_indeterminate_and_cannot_retry(self):
        def timeout(*_, **__):
            raise subprocess.TimeoutExpired('docker', 300)
        with self.assertRaises(CandidateProbeError):
            self.run_probe(timeout)
        self.assertTrue((self.root / 'docker-mutation.json').exists())
        with self.assertRaises(JournalError):
            self.run_probe(self.ok)
        self.assertEqual(self.calls, [])

    def test_invalid_output_keeps_marker(self):
        with self.assertRaises(JournalError):
            self.run_probe(lambda *_, **__: SimpleNamespace(returncode=0, stdout=b'unexpected'))
        self.assertTrue((self.root / 'docker-mutation.json').exists())


if __name__ == '__main__':
    unittest.main()
