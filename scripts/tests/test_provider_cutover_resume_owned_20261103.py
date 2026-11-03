import unittest
from unittest.mock import patch

import provider_cutover_resume_owned_20261103 as resume


class ResumeOwnedTests(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch.object(resume, 'verify_instance'),
            patch.object(resume, 'verify_installed_guard_files'),
            patch.object(resume, 'verify_loaded_units'),
            patch.object(resume.stage, '_read_owned_record'),
            patch.object(resume, '_read_env', return_value=b'private'),
            patch.object(resume, '_expected_overlay', return_value=b'pinned config'),
            patch.object(resume.stage, 'capture_bound_file_evidence'),
            patch.object(resume, 'ProductionAdapter'),
            patch.object(resume, '_run', return_value={'status': 'TEST_ONLY'}),
        ]
        self.mocks = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)
        self.transaction = 'a' * 32

    def test_default_checks_exact_owner_and_does_not_run_cutover(self):
        result = resume.run(transaction=self.transaction)
        self.assertFalse(result['production_changed'])
        self.assertFalse(result['cutover_ready'])
        expected = {'version': 1, 'transaction': self.transaction, 'containers': {
            'old_api': resume.OLD_API, 'old_worker': resume.OLD_WORKER,
            'new_api': resume.NEW_API, 'new_worker': resume.NEW_WORKER}}
        self.mocks[3].assert_called_once_with(resume.STATE / 'candidate-owner.json', expected)
        self.mocks[7].assert_not_called()
        self.mocks[8].assert_not_called()

    def test_execute_reuses_only_pinned_candidates(self):
        result = resume.run(transaction=self.transaction, execute=True)
        self.assertEqual(result['status'], 'TEST_ONLY')
        kwargs = self.mocks[8].call_args.kwargs
        self.assertEqual(kwargs['ids']['new_api'], resume.NEW_API)
        self.assertEqual(kwargs['ids']['new_worker'], resume.NEW_WORKER)
        self.assertTrue(kwargs['production'])
        self.assertEqual(kwargs['other_markers'], resume.OTHER_MARKERS)

    def test_wrong_or_unreadable_owner_prevents_execution(self):
        self.mocks[3].side_effect = ValueError('bad owner')
        with self.assertRaises(ValueError):
            resume.run(transaction=self.transaction, execute=True)
        self.mocks[7].assert_not_called()
        self.mocks[8].assert_not_called()

    def test_invalid_transaction_fails_before_any_access(self):
        with self.assertRaises(ValueError):
            resume.run(transaction='wrong', execute=True)
        self.mocks[0].assert_not_called()

    def test_bad_binding_prevents_execution(self):
        self.mocks[6].side_effect = ValueError('bad bind')
        with self.assertRaises(ValueError):
            resume.run(transaction=self.transaction, execute=True)
        self.mocks[8].assert_not_called()


if __name__ == '__main__':
    unittest.main()
