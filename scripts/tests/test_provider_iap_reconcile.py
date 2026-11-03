"""Read-only operation reconciliation with synthetic GCE responses only."""
import base64
import copy
import datetime as dt
from pathlib import Path
import tempfile
import unittest

from scripts.gcp_instance_ssh_guard import make_entry
from scripts.provider_iap_reconcile import INSTANCE, INSTANCE_ID, PROJECT, ZONE, ReconcileError, reconcile_operation
from scripts.provider_iap_session_ledger import SenderSessionLedger


class FakeGce:
    def __init__(self, entry, request_id):
        self.op = {'name': 'operation-1', 'clientOperationId': request_id, 'operationType': 'setMetadata',
                   'targetId': INSTANCE_ID,
                   'targetLink': f'https://www.googleapis.com/compute/v1/projects/{PROJECT}/zones/{ZONE}/instances/{INSTANCE}',
                   'zone': f'https://www.googleapis.com/compute/v1/projects/{PROJECT}/zones/{ZONE}', 'status': 'DONE'}
        self.instance = {'id': INSTANCE_ID, 'name': INSTANCE,
                         'metadata': {'fingerprint': 'changed==',
                                      'items': [{'key': 'ssh-keys', 'value': entry}]}}
        self.matches = None

    def operation(self, _name):
        return copy.deepcopy(self.op)

    def find_operation(self, _request_id):
        return copy.deepcopy(self.matches if self.matches is not None else [self.op])

    def metadata(self):
        return copy.deepcopy(self.instance)


class ReconcileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='asb-reconcile-test-')
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name).resolve())
        self.ledger = SenderSessionLedger(self.path)
        self.addCleanup(self.ledger.close)
        self.sid = self.ledger.begin_session('/synthetic/private')
        wire = b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20' + bytes(range(32))
        public = 'ssh-ed25519 ' + base64.b64encode(wire).decode('ascii')
        self.entry = make_entry('jmac', public, now=dt.datetime.now(dt.timezone.utc))
        self.opid, request_id = self.ledger.begin_operation(self.sid, self.entry,
                                                             metadata_fingerprint='initial==', action='insert')
        self.client = FakeGce(self.entry, request_id)

    def check(self):
        return reconcile_operation(ledger=self.ledger, operation_id=self.opid, client=self.client)

    def test_confirmed_exact_operation_records_terminal_without_closing_session(self):
        result = self.check()
        self.assertEqual(result['status'], 'CONFIRMED_APPLIED')
        self.assertFalse(result['session_closed'])
        self.assertEqual(result['owned_entry_count'], 1)
        self.assertFalse(result['fingerprint_matches_submitted'])
        self.assertEqual(self.ledger._records()[(self.opid, 'op-done')]['outcome'], 'applied')
        self.assertNotIn((self.sid, 'session-closed'), self.ledger._records())

    def test_recorded_operation_is_confirmed_by_exact_name(self):
        self.ledger.record_operation(self.opid, self.sid, 'operation-1')
        self.assertEqual(self.check()['status'], 'CONFIRMED_APPLIED')

    def test_unknown_or_multiple_matches_remain_unconfirmed(self):
        for matches in ([], [self.client.op, self.client.op]):
            self.client.matches = matches
            with self.subTest(count=len(matches)):
                self.assertEqual(self.check()['status'], 'UNCONFIRMED')
                self.assertNotIn((self.opid, 'op-done'), self.ledger._records())

    def test_pending_or_failed_operation_is_never_marked_success(self):
        self.client.op['status'] = 'RUNNING'
        self.assertEqual(self.check()['status'], 'PENDING')
        self.client.op['status'] = 'DONE'
        self.client.op['error'] = {'errors': [{'code': 'synthetic'}]}
        self.assertEqual(self.check()['status'], 'FAILED')
        self.assertNotIn((self.opid, 'op-done'), self.ledger._records())

    def test_wrong_request_target_zone_or_type_is_unconfirmed(self):
        for key, bad in [('clientOperationId', '00000000-0000-0000-0000-000000000000'),
                         ('targetId', '999'), ('targetLink', 'https://example.invalid/other'),
                         ('zone', 'https://example.invalid/other'), ('operationType', 'delete')]:
            old = self.client.op[key]
            self.client.op[key] = bad
            with self.subTest(key=key):
                self.assertEqual(self.check()['status'], 'UNCONFIRMED')
                self.assertNotIn((self.opid, 'op-done'), self.ledger._records())
            self.client.op[key] = old

    def test_untrusted_google_lookalike_host_is_unconfirmed(self):
        self.client.op['targetLink'] = (
            f'https://www.googleapis.com.attacker.invalid/compute/v1/projects/{PROJECT}/zones/{ZONE}/instances/{INSTANCE}')
        self.assertEqual(self.check()['status'], 'UNCONFIRMED')
        self.assertNotIn((self.opid, 'op-done'), self.ledger._records())

    def test_entry_absence_or_duplicate_refuses_terminal_success(self):
        self.client.instance['metadata']['items'] = []
        self.assertEqual(self.check()['status'], 'UNCONFIRMED')
        self.client.instance['metadata']['items'] = [{'key': 'ssh-keys', 'value': self.entry + '\n' + self.entry}]
        with self.assertRaises(ReconcileError):
            self.check()
        self.assertNotIn((self.opid, 'op-done'), self.ledger._records())

    def test_unknown_operation_and_wrong_instance_are_rejected(self):
        with self.assertRaises(ReconcileError):
            reconcile_operation(ledger=self.ledger, operation_id='f' * 32, client=self.client)
        self.client.instance['id'] = '999'
        with self.assertRaises(ReconcileError):
            self.check()
        self.assertNotIn((self.opid, 'op-done'), self.ledger._records())

    def test_removal_requires_the_exact_owned_entry_to_be_absent(self):
        other, request_id = self.ledger.begin_operation(self.sid, self.entry,
                                                         metadata_fingerprint='initial==', action='remove')
        client = FakeGce(self.entry, request_id)
        self.assertEqual(reconcile_operation(ledger=self.ledger, operation_id=other, client=client)['status'],
                         'UNCONFIRMED')
        client.instance['metadata']['items'] = []
        self.assertEqual(reconcile_operation(ledger=self.ledger, operation_id=other, client=client)['status'],
                         'CONFIRMED_APPLIED')

    def test_later_reconciliation_does_not_rewrite_terminal_record(self):
        self.assertEqual(self.check()['status'], 'CONFIRMED_APPLIED')
        self.assertEqual(self.check()['status'], 'ALREADY_RECORDED')


if __name__ == '__main__':
    unittest.main()
