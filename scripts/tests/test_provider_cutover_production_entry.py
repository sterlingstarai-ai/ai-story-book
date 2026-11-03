import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import provider_cutover_production_entry as entry


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.state, self.backup = root / 'state', root / 'backup'
        self.state.mkdir(mode=0o700)
        self.backup.mkdir(mode=0o700)
        self.ids = {'old_api': entry.OLD_API, 'old_worker': entry.OLD_WORKER,
                    'new_api': 'a' * 64, 'new_worker': 'b' * 64}
        self.events = []
        def stage_candidates(**kwargs):
            marker = json.loads((self.state / 'docker-mutation.json').read_text())
            self.assertEqual(marker['action'], 'candidate-create')
            self.assertTrue(kwargs['journaled_create'])
            self.events.append('stage')
            return {'ids': self.ids}
        def verify_staged(**kwargs):
            self.assertTrue(kwargs['candidate_create_in_progress'])
            self.assertTrue((self.state / 'docker-mutation.json').exists())
            self.events.append('verify')
        def run_state(**kwargs):
            self.assertFalse((self.state / 'docker-mutation.json').exists())
            owner = json.loads((self.state / 'candidate-owner.json').read_text())
            self.assertEqual(owner['containers'], self.ids)
            self.assertTrue(kwargs['production'])
            self.events.append('cutover')
            return {'status': 'TEST_ONLY'}
        self.patches = [patch.object(entry, 'STATE', self.state), patch.object(entry, 'BACKUP', self.backup),
            patch.object(entry, 'verify_instance'), patch.object(entry, 'verify_installed_guard_files'),
            patch.object(entry, 'verify_loaded_units'), patch.object(entry, '_read_env', return_value=b'SYNTHETIC=1\n'),
            patch.object(entry, '_expected_overlay', return_value=b'synthetic'),
            patch.object(entry, '_install_overlay_if_absent', return_value='c' * 64),
            patch.object(entry.stage, 'DockerStageRuntime', return_value=object()),
            patch.object(entry.stage, 'stage_candidates', side_effect=stage_candidates),
            patch.object(entry.stage, 'verify_staged', side_effect=verify_staged),
            patch.object(entry, 'ProductionAdapter', return_value=object()), patch.object(entry, '_run', side_effect=run_state)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_read_only_mode_does_not_stage(self):
        self.assertEqual(entry.run()['status'], 'READ_ONLY_PREFLIGHT_PASSED')
        self.assertEqual(self.events, [])
        self.assertEqual(list(self.state.iterdir()), [])

    def test_candidate_owner_durable_before_journal_removed(self):
        self.assertEqual(entry.run(execute=True)['status'], 'TEST_ONLY')
        self.assertEqual(self.events, ['stage', 'verify', 'cutover'])

    def test_failed_stage_leaves_journal_and_never_cuts_over(self):
        entry.stage.stage_candidates.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            entry.run(execute=True)
        self.assertTrue((self.state / 'docker-mutation.json').exists())
        self.assertNotIn('cutover', self.events)


if __name__ == '__main__':
    unittest.main()
