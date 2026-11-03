"""Local temporary directories and synthetic public keys only."""

import base64
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.gcp_ssh_host_pin import HostPinError, strict_known_hosts_entry
from scripts.gcp_ssh_recovery_journal import JournalError, RecoveryJournal
from scripts.tests.test_gcp_instance_ssh_guard import ENTRY, NOW, PUBLIC, WIRE


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="asb-ssh-journal-test-")
        self.addCleanup(self.temp.cleanup)
        os.chmod(self.temp.name, 0o700)

    def intent(self, journal):
        return journal.create_intent(
            project="test-project",
            zone="us-central1-c",
            instance="test-instance",
            owned_entry=ENTRY,
            clock=lambda: NOW,
        )

    def test_records_survive_reopen_and_never_authorize_cleanup_alone(self):
        with RecoveryJournal(self.temp.name) as journal:
            ident = self.intent(journal)
            self.assertEqual(journal.inspect(ident).phase, "not_started")
            request_id = journal.mark_started(ident)
        with RecoveryJournal(self.temp.name) as journal:
            self.assertEqual(journal.inspect(ident).phase, "operation_unknown")
            self.assertEqual(journal.inspect(ident).request_id, request_id)
            self.assertNotIn(request_id, repr(journal.inspect(ident)))
            self.assertFalse(journal.inspect(ident).may_auto_cleanup())
            journal.record_operation(ident, "op-123")
        with RecoveryJournal(self.temp.name) as journal:
            state = journal.inspect(ident)
            self.assertEqual(state.phase, "operation_recorded")
            self.assertFalse(state.may_auto_cleanup())
        paths = list(Path(self.temp.name).glob("*.json"))
        self.assertEqual(len(paths), 3)
        self.assertTrue(all((p.stat().st_mode & 0o777) == 0o600 for p in paths))

    def test_file_and_directory_fsync_are_required(self):
        with RecoveryJournal(self.temp.name) as journal:
            with patch(
                "scripts.gcp_ssh_recovery_journal.os.fsync", wraps=os.fsync
            ) as sync:
                self.intent(journal)
                self.assertGreaterEqual(sync.call_count, 2)
        with RecoveryJournal(self.temp.name) as journal:
            with patch(
                "scripts.gcp_ssh_recovery_journal.os.fsync", side_effect=OSError("fail")
            ):
                with self.assertRaises(JournalError):
                    self.intent(journal)

    def test_refuses_loose_permissions_and_symlink_directory(self):
        os.chmod(self.temp.name, 0o755)
        with self.assertRaises(JournalError):
            RecoveryJournal(self.temp.name)
        os.chmod(self.temp.name, 0o700)
        with tempfile.TemporaryDirectory() as parent:
            link = Path(parent) / "link"
            link.symlink_to(self.temp.name, target_is_directory=True)
            with self.assertRaises(OSError):
                RecoveryJournal(str(link))

    def test_symlink_corrupt_and_world_readable_record_are_refused(self):
        with RecoveryJournal(self.temp.name) as journal:
            ident = self.intent(journal)
            path = Path(self.temp.name) / f"{ident}.intent.json"
            raw = path.read_bytes()
            path.write_bytes(raw + b"broken")
            with self.assertRaises(JournalError):
                journal.inspect(ident)
            path.write_bytes(raw)
            os.chmod(path, 0o644)
            with self.assertRaises(JournalError):
                journal.inspect(ident)
            path.unlink()
            path.symlink_to("/dev/null")
            with self.assertRaises(JournalError):
                journal.inspect(ident)

    def test_refuses_duplicate_events_and_operation_without_start(self):
        with RecoveryJournal(self.temp.name) as journal:
            ident = self.intent(journal)
            with self.assertRaises(JournalError):
                journal.record_operation(ident, "op-1")
            journal.mark_started(ident)
            with self.assertRaises(JournalError):
                journal.mark_started(ident)
            journal.record_operation(ident, "op-1")
            with self.assertRaises(JournalError):
                journal.record_operation(ident, "op-2")

    def test_untrusted_target_and_key_refused_before_file_creation(self):
        with RecoveryJournal(self.temp.name) as journal:
            with self.assertRaises(JournalError):
                journal.create_intent(
                    project="../wrong",
                    zone="us-central1-c",
                    instance="test",
                    owned_entry=ENTRY,
                    clock=lambda: NOW,
                )
            with self.assertRaises(JournalError):
                journal.create_intent(
                    project="project",
                    zone="us-central1-c",
                    instance="test",
                    owned_entry="private-key",
                    clock=lambda: NOW,
                )
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])


class HostPinTests(unittest.TestCase):
    @staticmethod
    def fingerprint():
        return "SHA256:" + base64.b64encode(
            hashlib.sha256(WIRE).digest()
        ).decode().rstrip("=")

    def test_verified_pin_produces_exact_known_hosts_entry(self):
        self.assertEqual(
            strict_known_hosts_entry(
                "example.com", 22, PUBLIC, expected_fingerprint=self.fingerprint()
            ),
            f"example.com {PUBLIC}\n",
        )
        self.assertEqual(
            strict_known_hosts_entry(
                "127.0.0.1", 2222, PUBLIC, expected_fingerprint=self.fingerprint()
            ),
            f"[127.0.0.1]:2222 {PUBLIC}\n",
        )
        self.assertEqual(
            strict_known_hosts_entry(
                "::1", 22, PUBLIC, expected_fingerprint=self.fingerprint()
            ),
            f"::1 {PUBLIC}\n",
        )

    def test_changed_key_untrusted_pin_and_injection_are_rejected(self):
        for host, key, pin in (
            ("example.com", PUBLIC, "SHA256:" + "A" * 43),
            ("host\nother", PUBLIC, self.fingerprint()),
            ("example.com", PUBLIC + " extra", self.fingerprint()),
            ("example.com", "ssh-ed25519 AAAA", self.fingerprint()),
        ):
            with self.subTest(host=host, key=key):
                with self.assertRaises(HostPinError):
                    strict_known_hosts_entry(host, 22, key, expected_fingerprint=pin)


if __name__ == "__main__":
    unittest.main()
