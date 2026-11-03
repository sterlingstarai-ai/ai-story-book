import os
from pathlib import Path
import tempfile
import unittest

from scripts.provider_iap_session_ledger import LedgerError, SenderSessionLedger


class SenderSessionLedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='asb-iap-ledger-test-')
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name).resolve())

    def test_confirmed_operations_and_cleanup_allow_new_session(self):
        with SenderSessionLedger(self.path) as ledger:
            ledger.assert_quiescent()
            session = ledger.begin_session('/synthetic/directory')
            operation, _ = ledger.begin_operation(session, 'synthetic-public-entry', metadata_fingerprint='fingerprint', action='insert')
            ledger.record_operation(operation, session, 'operation-1')
            ledger.finish_operation(operation, session, 'applied')
            ledger.close_session(session, metadata_removed=True, identity_removed=True, tunnel_closed=True)
        with SenderSessionLedger(self.path) as ledger:
            ledger.assert_quiescent()
            self.assertTrue(ledger.begin_session('/synthetic/next'))

    def test_interrupted_session_blocks_new_session_after_reopen(self):
        with SenderSessionLedger(self.path) as ledger:
            ledger.begin_session('/synthetic/directory')
        with SenderSessionLedger(self.path) as ledger:
            with self.assertRaises(LedgerError):
                ledger.begin_session('/synthetic/next')

    def test_uncertain_operation_cannot_be_closed_or_ignored(self):
        with SenderSessionLedger(self.path) as ledger:
            session = ledger.begin_session('/synthetic/directory')
            ledger.begin_operation(session, 'synthetic-public-entry', metadata_fingerprint='fingerprint', action='insert')
            with self.assertRaises(LedgerError):
                ledger.close_session(session, metadata_removed=True, identity_removed=True, tunnel_closed=True)
        with SenderSessionLedger(self.path) as ledger:
            with self.assertRaises(LedgerError):
                ledger.assert_quiescent()

    def test_known_rejection_is_terminal_but_cleanup_still_required(self):
        with SenderSessionLedger(self.path) as ledger:
            session = ledger.begin_session('/synthetic/directory')
            operation, _ = ledger.begin_operation(session, 'synthetic-public-entry', metadata_fingerprint='fingerprint', action='insert')
            ledger.finish_operation(operation, session, 'rejected')
            with self.assertRaises(LedgerError):
                ledger.close_session(session, metadata_removed=False, identity_removed=True, tunnel_closed=True)
            ledger.close_session(session, metadata_removed=True, identity_removed=True, tunnel_closed=True)
            ledger.assert_quiescent()

    def test_accepted_operation_needs_recorded_identity(self):
        with SenderSessionLedger(self.path) as ledger:
            session = ledger.begin_session('/synthetic/directory')
            operation, _ = ledger.begin_operation(session, 'synthetic-public-entry', metadata_fingerprint='fingerprint', action='insert')
            with self.assertRaises(LedgerError):
                ledger.finish_operation(operation, session, 'applied')

    def test_lock_rejects_concurrent_session(self):
        with SenderSessionLedger(self.path):
            with self.assertRaises(LedgerError):
                SenderSessionLedger(self.path)

    def test_corrupt_or_unknown_files_fail_closed(self):
        with SenderSessionLedger(self.path) as ledger:
            Path(self.path, 'unknown').write_text('synthetic')
            with self.assertRaises(LedgerError):
                ledger.assert_quiescent()

    def test_symlink_journal_is_rejected(self):
        alias = Path(self.path).parent / (Path(self.path).name + '-alias')
        alias.symlink_to(self.path)
        self.addCleanup(alias.unlink)
        with self.assertRaises(LedgerError):
            SenderSessionLedger(str(alias))

    def test_wrong_permissions_fail_closed(self):
        os.chmod(self.path, 0o755)
        self.addCleanup(os.chmod, self.path, 0o700)
        with self.assertRaises(LedgerError):
            SenderSessionLedger(self.path)


if __name__ == '__main__':
    unittest.main()
