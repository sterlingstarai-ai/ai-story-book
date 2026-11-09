import base64
import datetime as dt
from pathlib import Path
import tempfile
import unittest

from scripts.gcp_instance_ssh_guard import make_entry
from scripts.gcp_ssh_recovery_journal import RecoveryJournal
from scripts.provider_iap_legacy_audit import LegacyAuditError, audit_owned_legacy_journals
from scripts.provider_iap_reconcile import INSTANCE, INSTANCE_ID, PROJECT, ZONE


class FakeGce:
    def __init__(self, request_id):
        self.request_id = request_id
        self.fingerprint = 'before=='
        self.calls = 0
        self.entry = None
        self.status = 'DONE'

    def metadata(self):
        self.calls += 1
        items = [] if self.entry is None else [{'key': 'ssh-keys', 'value': self.entry}]
        return {'id': INSTANCE_ID, 'name': INSTANCE,
                'metadata': {'fingerprint': self.fingerprint, 'items': items}}

    def operation(self, name):
        return {'name': name, 'clientOperationId': self.request_id, 'operationType': 'setMetadata',
                'targetId': INSTANCE_ID,
                'targetLink': f'https://www.googleapis.com/compute/v1/projects/{PROJECT}/zones/{ZONE}/instances/{INSTANCE}',
                'zone': f'https://www.googleapis.com/compute/v1/projects/{PROJECT}/zones/{ZONE}',
                'status': self.status}


class LegacyAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='asb-legacy-audit-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.directory = self.root / 'asb-ssh-recovery-fixture1'
        self.directory.mkdir(mode=0o700)
        wire = b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20' + bytes(range(32))
        self.entry = make_entry('jmac', 'ssh-ed25519 ' + base64.b64encode(wire).decode('ascii'),
                                now=dt.datetime.now(dt.timezone.utc))
        with RecoveryJournal(str(self.directory)) as journal:
            ident = journal.create_intent(project=PROJECT, zone=ZONE, instance=INSTANCE,
                                           owned_entry=self.entry, clock=lambda: dt.datetime.now(dt.timezone.utc))
            request_id = journal.mark_started(ident)
            journal.record_operation(ident, 'operation-1')
        self.client = FakeGce(request_id)

    def audit(self):
        return audit_owned_legacy_journals(client=self.client, root=str(self.root), _expected={'fixture1'})

    def test_complete_exact_owned_operation_and_absent_entry_pass(self):
        before = {x.name: x.read_bytes() for x in self.directory.iterdir()}
        self.assertEqual(self.audit(), {'sessions_confirmed': 1, 'operations_confirmed': 1,
                                         'submitted_fingerprints_recorded': False})
        self.assertEqual(before, {x.name: x.read_bytes() for x in self.directory.iterdir()})

    def test_unknown_or_missing_directory_is_rejected_before_network(self):
        (self.root / 'asb-ssh-recovery-unknown').mkdir()
        with self.assertRaises(LegacyAuditError):
            self.audit()
        self.assertEqual(self.client.calls, 0)

    def test_new_journal_requires_two_verified_operations_from_the_operator(self):
        directory = self.root / 'asb-ssh-recovery-fixture2'
        directory.mkdir(mode=0o700)
        operations = {}
        with RecoveryJournal(str(directory)) as journal:
            for name in ('operation-2', 'operation-3'):
                ident = journal.create_intent(project=PROJECT, zone=ZONE, instance=INSTANCE,
                                               owned_entry=self.entry, clock=lambda: dt.datetime.now(dt.timezone.utc))
                operations[name] = journal.mark_started(ident)
                journal.record_operation(ident, name)

        original = self.client.operation
        operator = 'operator@example.test'

        def operation(name):
            value = original(name)
            if name in operations:
                value.update(clientOperationId=operations[name], user=operator)
            return value

        self.client.operation = operation
        def audit(identity):
            return audit_owned_legacy_journals(client=self.client, root=str(self.root), operator=identity,
                                               _expected={'fixture1'})
        with self.assertRaises(LegacyAuditError):
            audit('different@example.test')
        self.assertEqual(audit(operator)['operations_confirmed'], 3)
        next(directory.glob('*.operation.json')).unlink()
        with self.assertRaises(LegacyAuditError):
            audit(operator)

    def test_pending_operation_or_current_owned_entry_blocks(self):
        self.client.status = 'RUNNING'
        with self.assertRaises(LegacyAuditError):
            self.audit()
        self.client.status = 'DONE'
        self.client.entry = self.entry
        with self.assertRaises(LegacyAuditError):
            self.audit()

    def test_fingerprint_change_during_audit_blocks(self):
        previous = self.client.metadata

        def changed():
            value = previous()
            if self.client.calls > 1:
                value['metadata']['fingerprint'] = 'after=='
            return value

        self.client.metadata = changed
        with self.assertRaises(LegacyAuditError):
            self.audit()

    def test_replaced_instance_during_audit_blocks_even_with_same_fingerprint(self):
        previous = self.client.metadata

        def changed():
            value = previous()
            if self.client.calls > 1:
                value['id'] = '123'
            return value

        self.client.metadata = changed
        with self.assertRaises(LegacyAuditError):
            self.audit()

    def test_unexpected_or_damaged_legacy_record_blocks(self):
        (self.directory / 'unrecognized').write_text('synthetic')
        with self.assertRaises(LegacyAuditError):
            self.audit()


if __name__ == '__main__':
    unittest.main()
