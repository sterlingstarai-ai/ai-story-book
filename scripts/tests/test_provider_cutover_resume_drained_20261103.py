import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import provider_cutover_resume_drained_20261103 as resume


class RecoveryResumeTests(unittest.TestCase):
    def setUp(self):
        self.transaction = 'a' * 32
        self.probe_id = 'b' * 64
        self.ids = {'old_api': resume.OLD_API, 'old_worker': resume.OLD_WORKER,
                    'new_api': resume.NEW_API, 'new_worker': resume.NEW_WORKER}
        self.images = {'old_api': resume.API_IMAGE, 'new_api': resume.API_IMAGE,
                       'old_worker': resume.WORKER_IMAGE, 'new_worker': resume.WORKER_IMAGE}

    def test_tail_never_starts_old_and_drains_before_worker_stop(self):
        events = []
        class Runtime:
            def __getattr__(self, method):
                def call(*args):
                    events.append((method, *args))
                return call
        with patch.object(resume, '_assert_slot'), patch.object(resume, '_sync_dir'), \
             patch.object(Path, 'unlink'):
            result = resume._finish(Runtime(), self.ids, self.images)
        self.assertEqual(result['status'], 'PRODUCTION_CUTOVER_PASSED')
        self.assertEqual(events[:2], [('drain_worker_and_queues',), ('stop', self.ids['old_worker'])])
        self.assertEqual([row[1] for row in events if row[0] == 'start'],
                         [self.ids['new_api'], self.ids['new_worker']])
        self.assertLess(events.index(('probe_equivalent_provider', self.ids['new_api'])),
                        events.index(('start', self.ids['new_api'])))

    def test_failed_drain_never_stops_or_starts_any_container(self):
        class Runtime:
            def drain_worker_and_queues(self):
                raise resume.ResumeError('busy')
            def __getattr__(self, method):
                raise AssertionError('unexpected operation ' + method)
        with self.assertRaises(resume.ResumeError):
            resume._finish(Runtime(), self.ids, self.images)

    def test_stopped_config_cp_requires_pinned_plain_single_file(self):
        def archive(name, payload):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w') as output:
                member = tarfile.TarInfo(name)
                member.size = len(payload)
                output.addfile(member, io.BytesIO(payload))
            return stream.getvalue()
        with patch.object(resume.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, archive('config.py', b'x'))), \
             patch.object(resume, 'build_overlay', return_value=b'expected') as build:
            self.assertEqual(resume._expected_overlay_from_stopped_api(), b'expected')
            build.assert_called_once_with(b'x', resume.CONFIG_SHA256)
        with patch.object(resume.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, archive('../bad', b'x'))):
            with self.assertRaises(resume.ResumeError):
                resume._expected_overlay_from_stopped_api()

    def test_validation_fails_before_mutation(self):
        with patch.object(resume, 'verify_instance'), patch.object(resume, 'verify_installed_guard_files'), \
             patch.object(resume, 'verify_loaded_units'), patch.object(resume, '_read_marker', return_value={}), \
             patch.object(resume, '_lock') as lock:
            with self.assertRaises(resume.ResumeError):
                resume.run(transaction=self.transaction, probe_id=self.probe_id, execute=True)
        lock.assert_not_called()

    def test_locked_stage_failure_never_enters_tail(self):
        with patch.object(resume, 'verify_instance'), patch.object(resume, 'verify_installed_guard_files'), \
             patch.object(resume, 'verify_loaded_units'), patch.object(resume, '_read_marker', return_value=self.ids), \
             patch.object(resume.stage, '_read_owned_record'), patch.object(resume, '_read_env', return_value=b'private'), \
             patch.object(resume, '_expected_overlay_from_stopped_api', return_value=b'config'), \
             patch.object(resume.stage, 'capture_bound_file_evidence'), \
             patch.object(resume, '_lock', side_effect=lambda _: os.open('/dev/null', os.O_RDONLY)), \
             patch.object(resume, '_absent'), patch.object(resume, 'DrainedRecoveryAdapter', autospec=True) as factory, \
             patch.object(resume, '_finish') as finish:
            factory.return_value.assert_candidate_and_interlocks.side_effect = resume.ResumeError('bad state')
            with self.assertRaises(resume.ResumeError):
                resume.run(transaction=self.transaction, probe_id=self.probe_id, execute=True)
            finish.assert_not_called()
            factory.return_value.preserve_accepted_work_and_quarantine.assert_not_called()


if __name__ == '__main__':
    unittest.main()
