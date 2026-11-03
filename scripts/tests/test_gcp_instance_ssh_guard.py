"""Offline, isolated checks; no GCP account, keys or network are used."""

import base64
import copy
import datetime as dt
import unittest

from scripts.gcp_instance_ssh_guard import (
    CleanupFailure,
    Conflict,
    GuardError,
    InstanceKeyGuard,
    UncertainUpdate,
    make_entry,
    with_temporary_key,
)


NOW = dt.datetime(2026, 11, 3, 0, 0, tzinfo=dt.timezone.utc)
WIRE = b"\0\0\0\x0bssh-ed25519\0\0\0\x20" + b"x" * 32
PUBLIC = "ssh-ed25519 " + base64.b64encode(WIRE).decode()
ENTRY = make_entry("asb_temp", PUBLIC, now=NOW)


class FakeMetadata:
    def __init__(self, metadata):
        self.value = copy.deepcopy(metadata)
        self.attempts = 0
        self.conflict = None
        self.fail = None

    def read(self):
        return copy.deepcopy(self.value)

    def compare_and_set(self, metadata):
        self.attempts += 1
        if self.conflict:
            cb, self.conflict = self.conflict, None
            cb(self)
            raise Conflict()
        if self.fail:
            raise self.fail
        if metadata["fingerprint"] != self.value["fingerprint"]:
            raise Conflict()
        self.value = copy.deepcopy(metadata)
        self.value["fingerprint"] = "next-" + self.value["fingerprint"]


def md(value=None):
    result = {"fingerprint": "1", "items": [{"key": "unrelated", "value": "unchanged"}]}
    if value is not None:
        result["items"].append({"key": "ssh-keys", "value": value})
    return result


def guard(fake, attempts=5):
    return InstanceKeyGuard(fake, attempts=attempts, clock=lambda: NOW)


class TemporaryInstanceKeyTests(unittest.TestCase):
    def test_other_metadata_and_unterminated_key_preserved_byte_for_byte(self):
        old = "another:ssh-ed25519 OTHER no-terminator"
        fake = FakeMetadata(md(old))
        with_temporary_key(
            guard(fake),
            ENTRY,
            lambda: self.assertEqual(
                fake.value["items"][1]["value"], ENTRY + "\n" + old
            ),
        )
        self.assertEqual(fake.value["items"], md(old)["items"])

    def test_existing_empty_field_and_absent_field_restored(self):
        for value in ("", None):
            with self.subTest(value=value):
                fake = FakeMetadata(md(value))
                with_temporary_key(guard(fake), ENTRY, lambda: None)
                self.assertEqual(fake.value["items"], md(value)["items"])

    def test_conflict_reloads_and_preserves_concurrent_addition(self):
        fake = FakeMetadata(md("old\n"))

        def add_concurrent(target):
            target.value["items"][1]["value"] += "new-concurrent\n"
            target.value["fingerprint"] = "concurrent"

        fake.conflict = add_concurrent
        with_temporary_key(guard(fake), ENTRY, lambda: None)
        self.assertEqual(fake.value["items"][1]["value"], "old\nnew-concurrent\n")
        self.assertEqual(fake.attempts, 3)

    def test_cleanup_conflict_reloads_and_keeps_other_user(self):
        fake = FakeMetadata(md("old\n"))

        def action():
            def change(target):
                target.value["items"][1]["value"] += "new-user\n"
                target.value["fingerprint"] = "new-fingerprint"

            fake.conflict = change

        with_temporary_key(guard(fake), ENTRY, action)
        self.assertEqual(fake.value["items"][1]["value"], "old\nnew-user\n")

    def test_preexisting_identical_line_is_never_deleted(self):
        fake = FakeMetadata(md(ENTRY))
        with self.assertRaises(GuardError):
            with_temporary_key(guard(fake), ENTRY, lambda: self.fail("must not run"))
        self.assertEqual(fake.value["items"][1]["value"], ENTRY)
        self.assertEqual(fake.attempts, 0)

    def test_action_exception_runs_cleanup(self):
        fake = FakeMetadata(md("other\n"))

        def action():
            raise ValueError("action failed")

        with self.assertRaises(ValueError):
            with_temporary_key(guard(fake), ENTRY, action)
        self.assertEqual(fake.value["items"][1]["value"], "other\n")

    def test_uncertain_submission_is_not_reported_as_clean(self):
        fake = FakeMetadata(md("other\n"))
        fake.fail = UncertainUpdate("lost response")
        with self.assertRaises(CleanupFailure):
            with_temporary_key(guard(fake), ENTRY, lambda: self.fail("must not run"))
        self.assertEqual(fake.value["items"][1]["value"], "other\n")

    def test_uncertain_applied_submission_attempts_exact_cleanup_but_stays_uncertain(
        self,
    ):
        class Ambiguous(FakeMetadata):
            def compare_and_set(self, metadata):
                if self.attempts == 0:
                    self.attempts += 1
                    self.value = copy.deepcopy(metadata)
                    self.value["fingerprint"] = "changed"
                    raise UncertainUpdate("lost response")
                super().compare_and_set(metadata)

        fake = Ambiguous(md("other\n"))
        with self.assertRaises(CleanupFailure):
            with_temporary_key(guard(fake), ENTRY, lambda: self.fail("must not run"))
        self.assertEqual(fake.value["items"][1]["value"], "other\n")

    def test_duplicate_owned_lines_refuse_cleanup(self):
        fake = FakeMetadata(md("other"))
        owner = guard(fake)
        receipt = owner.insert(ENTRY)
        fake.value["items"][1]["value"] = ENTRY + "\n" + ENTRY
        with self.assertRaises(CleanupFailure):
            owner.remove(ENTRY, receipt)
        self.assertEqual(fake.value["items"][1]["value"], ENTRY + "\n" + ENTRY)

    def test_receipt_cannot_remove_a_different_line_or_use_another_guard(self):
        fake = FakeMetadata(md("other"))
        owner = guard(fake)
        receipt = owner.insert(ENTRY)
        with self.assertRaises(CleanupFailure):
            owner.remove("other", receipt)
        with self.assertRaises(CleanupFailure):
            guard(fake).remove(ENTRY, receipt)
        owner.remove(ENTRY, receipt)
        self.assertEqual(fake.value["items"][1]["value"], "other")

    def test_ambiguous_or_invalid_metadata_refused(self):
        for value in (
            {"items": []},
            {"fingerprint": "", "items": []},
            {
                "fingerprint": "1",
                "items": [
                    {"key": "ssh-keys", "value": ""},
                    {"key": "ssh-keys", "value": ""},
                ],
            },
        ):
            with self.subTest(value=value):
                fake = FakeMetadata(value)
                with self.assertRaises(GuardError):
                    guard(fake).insert(ENTRY)
                self.assertEqual(fake.attempts, 0)

    def test_invalid_and_expired_entries_never_submit(self):
        fake = FakeMetadata(md("other"))
        for entry in (
            "user:ssh-rsa aaa",
            ENTRY + "\nother",
            ENTRY.replace("asb_temp", "-bad"),
        ):
            with self.subTest(entry=entry):
                with self.assertRaises(GuardError):
                    guard(fake).insert(entry)
        with self.assertRaises(GuardError):
            InstanceKeyGuard(fake, clock=lambda: NOW + dt.timedelta(minutes=6)).insert(
                ENTRY
            )
        self.assertEqual(fake.attempts, 0)

    def test_failed_cleanup_is_reported(self):
        fake = FakeMetadata(md("other\n"))

        def action():
            fake.fail = RuntimeError("unavailable")

        with self.assertRaises(CleanupFailure):
            with_temporary_key(guard(fake), ENTRY, action)
        self.assertIn(ENTRY, fake.value["items"][1]["value"])


if __name__ == "__main__":
    unittest.main()
