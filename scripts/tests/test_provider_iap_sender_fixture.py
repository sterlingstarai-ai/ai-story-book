import unittest

from scripts.provider_iap_sender_fixture import run_fixture


class IapSenderFixtureTest(unittest.TestCase):
    def test_master_authentication_and_cleanup_precede_synthetic_keychain(self):
        result = run_fixture()
        self.assertEqual(result['status'], 'SYNTHETIC_PASSED')
        self.assertEqual(result['events'], ['metadata_inserted', 'master_authenticated', 'cleanup_started',
                                            'metadata_removed', 'identity_removed', 'synthetic_keychain_read',
                                            'master_closed'])
        self.assertFalse(result['production_authorized'])
        self.assertTrue(result['unrelated_metadata_preserved'])

    def test_master_failure_blocks_keychain_and_cleans_owned_metadata(self):
        result = run_fixture('master_failure')
        self.assertEqual(result['status'], 'SYNTHETIC_BLOCKED')
        self.assertNotIn('synthetic_keychain_read', result['events'])
        self.assertIn('best_effort_metadata_cleanup', result['events'])
        self.assertTrue(result['unrelated_metadata_preserved'])

    def test_uncertain_insert_never_reads_keychain_even_after_cleanup(self):
        result = run_fixture('insert_uncertain')
        self.assertEqual(result['status'], 'SYNTHETIC_BLOCKED')
        self.assertTrue(result['metadata_outcome_uncertain'])
        self.assertNotIn('synthetic_keychain_read', result['events'])
        self.assertTrue(result['unrelated_metadata_preserved'])

    def test_uncertain_removal_never_reads_keychain_even_if_row_disappears(self):
        result = run_fixture('remove_uncertain')
        self.assertEqual(result['status'], 'SYNTHETIC_BLOCKED')
        self.assertTrue(result['metadata_outcome_uncertain'])
        self.assertNotIn('synthetic_keychain_read', result['events'])
        self.assertIn('master_closed', result['events'])

    def test_identity_cleanup_failure_blocks_keychain(self):
        result = run_fixture('identity_cleanup_failure')
        self.assertEqual(result['status'], 'SYNTHETIC_BLOCKED')
        self.assertNotIn('synthetic_keychain_read', result['events'])
        self.assertIn('metadata_removed', result['events'])
        self.assertIn('master_closed', result['events'])


if __name__ == '__main__':
    unittest.main()
