from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import provider_cutover_portless_exec as portless


class PortlessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.probe_id = 'a' * 64
        self.candidate = 'b' * 64
        self.transaction = 'c' * 32
        self.records = []
        self.calls = []
        candidate = {'Id': self.candidate, 'Image': portless.API_IMAGE, 'Name': '/asb-provider-next-api',
                     'State': {'Running': False}, 'Config': {'Labels': {'asb.provider.transaction': self.transaction}},
                     'HostConfig': {'RestartPolicy': {'Name': 'no'}}}
        running = {'Id': self.probe_id, 'State': {'Running': True, 'Restarting': False}}
        self.runtime = SimpleNamespace(inspect=lambda ident: candidate if ident == self.candidate else running)
        self.patches = [
            patch.object(portless.stage, '_PROVIDER_STATE', self.root),
            patch.object(portless.stage, '_verify_backup_lock_fd', lambda _: None),
            patch.object(portless.stage, '_read_owned_record', lambda path, expected: self.records.append((path, expected))),
            patch.object(portless.stage, '_probe_contract', lambda *args, **kwargs: None),
            patch.object(portless.stage, 'verify_running_bound_files', lambda **kwargs: True),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def call(self, runner):
        return portless.run_inside_owned_probe(runtime=self.runtime, probe_id=self.probe_id,
            candidate_id=self.candidate, image_id=portless.API_IMAGE, transaction_id=self.transaction,
            lock_fd=1, state_dir=self.root, evidence=object(), overlay_path='/test/config', overlay_sha256='d' * 64,
            key_path='/test/key', runner=runner)

    def success(self, args, **kwargs):
        self.calls.append((args, kwargs))
        output = b'QUEUE_DRAIN_OK\n' if args[-1] == '--broker-only' else b'PROVIDER_PROBE_OK\n'
        return SimpleNamespace(returncode=0, stdout=output)

    def test_queue_precedes_provider_under_owned_compound_marker(self):
        self.assertTrue(self.call(self.success))
        self.assertEqual([call[0][-1] for call in self.calls], ['--broker-only', '--inside-pinned-candidate'])
        self.assertEqual(len(self.records), 2)
        self.assertEqual(self.records[1][1]['container'], self.probe_id)
        self.assertEqual(self.calls[0][0][1:3], ['--host', 'unix:///var/run/docker.sock'])
        self.assertEqual(self.calls[0][1]['env'], {'PATH': '/usr/bin:/bin', 'HOME': '/root'})

    def test_busy_queue_or_timeout_never_runs_provider(self):
        with self.assertRaises(portless.PortlessProbeError):
            self.call(lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=b'QUEUE_DRAIN_FAILED\n'))
        self.assertEqual(self.calls, [])
        with self.assertRaises(portless.PortlessProbeError):
            self.call(lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired('docker', 300)))
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
