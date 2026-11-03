"""Synthetic, in-memory mirror crash and race checks without a shared test DB."""
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest

from src.services.privacy_journal import JournalError, PrivacyJournal
from src.services.privacy_journal_mirror import MirroredJournalStore


class Store:
    def __init__(self):
        self.records = {}
        self.lock = threading.Lock()
        self.fail = False

    def create(self, name, data):
        with self.lock:
            if self.fail or name in self.records:
                raise RuntimeError('unavailable or exists')
            self.records[name] = data

    def read(self, name):
        with self.lock:
            return self.records[name]

    def list_names(self, prefix):
        with self.lock:
            return [name for name in self.records if name.startswith(prefix)]


class MirrorRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.primary, self.witness = Store(), Store()
        self.mirror = MirroredJournalStore(self.primary, self.witness)
        self.journal = PrivacyJournal(self.mirror, b'k' * 32)
        self.subject = '00000000-0000-4000-8000-000000000001'
        self.event = 'a' * 32

    def test_partial_intent_and_commit_recover_exact_original_bytes(self):
        self.witness.fail = True
        with self.assertRaises(JournalError):
            self.journal.begin('account_delete', self.subject, revision=1, event_id=self.event)
        name = f'privacy-journal/v1/{self.event}/intent'
        original = self.primary.read(name)
        self.witness.fail = False
        self.journal.begin('account_delete', self.subject, revision=1, event_id=self.event)
        self.assertEqual(self.witness.read(name), original)
        self.witness.fail = True
        with self.assertRaises(JournalError):
            self.journal.commit(self.event)
        commit = f'privacy-journal/v1/{self.event}/commit'
        original_commit = self.primary.read(commit)
        self.witness.fail = False
        self.journal.commit(self.event)
        self.assertEqual(self.witness.read(commit), original_commit)
        self.assertEqual(len(self.journal.scan().committed), 1)

    def test_different_payload_or_event_id_never_copied(self):
        self.witness.fail = True
        with self.assertRaises(JournalError):
            self.journal.begin('account_delete', self.subject, revision=1, event_id=self.event)
        self.witness.fail = False
        with self.assertRaises(JournalError):
            self.journal.begin('consent_revoke', self.subject, revision=1, event_id=self.event)
        self.assertEqual(self.witness.records, {})
        source = f'privacy-journal/v1/{self.event}/intent'
        other = 'b' * 32
        self.primary.records[f'privacy-journal/v1/{other}/intent'] = self.primary.read(source)
        with self.assertRaises(JournalError):
            self.journal.begin('account_delete', self.subject, revision=1, event_id=other)
        self.assertEqual(self.witness.records, {})

    def test_conflicting_existing_ciphertext_never_overwritten(self):
        name = f'privacy-journal/v1/{self.event}/intent'
        self.primary.records[name] = b'ciphertext A'
        self.witness.records[name] = b'ciphertext B'
        with self.assertRaises(JournalError):
            self.mirror.reconcile(name, lambda _: True)
        self.assertEqual(self.primary.read(name), b'ciphertext A')
        self.assertEqual(self.witness.read(name), b'ciphertext B')

    def test_competing_retries_converge_without_overwrite(self):
        self.witness.fail = True
        with self.assertRaises(JournalError):
            self.journal.begin('account_delete', self.subject, revision=1, event_id=self.event)
        name = f'privacy-journal/v1/{self.event}/intent'
        original = self.primary.read(name)
        self.witness.fail = False
        def retry(_):
            return self.journal.begin('account_delete', self.subject, revision=1, event_id=self.event)
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(list(pool.map(retry, range(30))), [self.event] * 30)
        self.assertEqual(self.primary.read(name), original)
        self.assertEqual(self.witness.read(name), original)

    def test_concurrent_conflicting_payloads_only_one_can_win(self):
        for index in range(20):
            event = f'{index + 16:032x}'
            gate = threading.Barrier(2)
            def attempt(action):
                gate.wait(timeout=5)
                try:
                    self.journal.begin(action, self.subject, revision=index + 1, event_id=event)
                    return action
                except JournalError:
                    return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(attempt, ('account_delete', 'consent_revoke')))
            self.assertEqual(sum(result is not None for result in results), 1)
            name = f'privacy-journal/v1/{event}/intent'
            self.assertEqual(self.primary.read(name), self.witness.read(name))
            self.assertEqual(self.journal._open(name, self.primary.read(name))['action'],
                             next(result for result in results if result is not None))


if __name__ == '__main__':
    unittest.main()
