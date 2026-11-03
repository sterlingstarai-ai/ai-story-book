"""REST state machine checks against fake responses only; never contacts GCP."""

import copy
import unittest

from scripts.gcp_instance_metadata_rest import InstanceMetadataRest, WriteBlocked
from scripts.gcp_instance_ssh_guard import (
    Conflict,
    InstanceKeyGuard,
    UncertainUpdate,
    with_temporary_key,
)
from scripts.tests.test_gcp_instance_ssh_guard import ENTRY, NOW


class Response:
    def __init__(self, status, data):
        self.status_code = status
        self.data = data

    def json(self):
        return copy.deepcopy(self.data)


class FakeSession:
    def __init__(self):
        self.metadata = {
            "fingerprint": "initial",
            "items": [
                {"key": "ssh-keys", "value": "existing-without-newline"},
                {"key": "other", "value": "preserve"},
            ],
        }
        self.requests = []
        self.fingerprint_conflict = False
        self.post_exception = None
        self.post_response = None
        self.statuses = []
        self.pending = None

    def request(self, method, url, **kwargs):
        self.requests.append((method, url))  # no metadata/credentials in log
        if method == "POST":
            if self.post_exception:
                raise self.post_exception
            if self.post_response:
                return self.post_response
            submitted = kwargs["json"]
            if self.fingerprint_conflict:
                self.fingerprint_conflict = False
                self.metadata["items"][0]["value"] += "-concurrent"
                self.metadata["fingerprint"] = "concurrent"
                return Response(412, {})
            if submitted["fingerprint"] != self.metadata["fingerprint"]:
                return Response(412, {})
            self.pending = copy.deepcopy(submitted)
            return Response(200, {"name": "op-1", "status": "PENDING"})
        if "/operations/" in url:
            if self.statuses:
                value = self.statuses.pop(0)
                if isinstance(value, Exception):
                    raise value
                return value
            self.metadata = self.pending
            self.metadata["fingerprint"] = "next-" + self.metadata["fingerprint"]
            return Response(200, {"name": "op-1", "status": "DONE"})
        return Response(200, {"metadata": self.metadata})


class FixtureRest(InstanceMetadataRest):
    def _require_write_controls(self):
        if not isinstance(self._session, FakeSession):
            raise AssertionError("fixture session required")


def adapter(fake, *, fixture=False, **kwargs):
    klass = FixtureRest if fixture else InstanceMetadataRest
    return klass(
        fake,
        project="test-project",
        zone="us-central1-c",
        instance="test-instance",
        pause=lambda _: None,
        **kwargs,
    )


class MetadataRestTests(unittest.TestCase):
    def test_default_and_explicit_optin_both_block_real_writes(self):
        for optin in (False, True):
            fake = FakeSession()
            a = adapter(fake, enable_write=optin)
            self.assertEqual(a.read()["fingerprint"], "initial")
            with self.assertRaises(WriteBlocked):
                a.compare_and_set(fake.metadata)
            with self.assertRaises(WriteBlocked):
                a._set_and_wait(fake.metadata)
            self.assertTrue(all(method == "GET" for method, _ in fake.requests))

    def test_guard_does_not_report_uncertain_when_writes_blocked_before_submit(self):
        fake = FakeSession()
        a = adapter(fake, enable_write=True)
        g = InstanceKeyGuard(a, clock=lambda: NOW)
        with self.assertRaises(WriteBlocked):
            with_temporary_key(g, ENTRY, lambda: self.fail("never run"))
        self.assertEqual(fake.metadata["items"][0]["value"], "existing-without-newline")
        self.assertFalse(any(method == "POST" for method, _ in fake.requests))

    def test_fake_only_end_to_end_conflict_retry_and_cleanup(self):
        class FakeOnlyRest(FixtureRest):
            def compare_and_set(self, metadata):
                self._set_and_wait(metadata)

        fake = FakeSession()
        fake.fingerprint_conflict = True
        a = FakeOnlyRest(
            fake,
            project="test-project",
            zone="us-central1-c",
            instance="test-instance",
            pause=lambda _: None,
        )
        g = InstanceKeyGuard(a, clock=lambda: NOW)
        self.assertEqual(
            with_temporary_key(g, ENTRY, lambda: "read-only-observation"),
            "read-only-observation",
        )
        self.assertEqual(
            fake.metadata["items"],
            [
                {"key": "ssh-keys", "value": "existing-without-newline-concurrent"},
                {"key": "other", "value": "preserve"},
            ],
        )
        self.assertEqual(sum(m == "POST" for m, _ in fake.requests), 3)
        self.assertTrue(
            all(
                "/projects/test-project/zones/us-central1-c/" in url
                for _, url in fake.requests
            )
        )

    def test_fingerprint_rejection_is_conflict(self):
        fake = FakeSession()
        fake.post_response = Response(412, {})
        with self.assertRaises(Conflict):
            adapter(fake, fixture=True)._set_and_wait(fake.metadata)

    def test_post_unknowns_are_not_misreported_as_rejected(self):
        for result in (
            TimeoutError("secret must never surface"),
            Response(500, {}),
            Response(200, {"status": "DONE"}),
            Response(200, {"name": "../invalid"}),
        ):
            with self.subTest(result=type(result)):
                fake = FakeSession()
                if isinstance(result, Exception):
                    fake.post_exception = result
                else:
                    fake.post_response = result
                with self.assertRaises(UncertainUpdate) as error:
                    adapter(fake, fixture=True)._set_and_wait(fake.metadata)
                self.assertNotIn("secret", str(error.exception))

    def test_waits_for_exact_terminal_operation(self):
        fake = FakeSession()
        fake.statuses = [
            Response(200, {"name": "op-1", "status": "RUNNING"}),
            Response(200, {"name": "op-1", "status": "DONE"}),
        ]
        adapter(fake, fixture=True)._set_and_wait(fake.metadata)
        self.assertEqual(sum("/operations/" in u for _, u in fake.requests), 2)

    def test_failed_wrong_or_never_finished_operation_is_uncertain(self):
        for result in (
            Response(200, {"name": "op-1", "status": "DONE", "error": {}}),
            Response(200, {"name": "different", "status": "DONE"}),
            Response(500, {}),
            TimeoutError("hidden"),
            Response(200, {"name": "op-1", "status": "RUNNING"}),
        ):
            with self.subTest(result=type(result)):
                fake = FakeSession()
                fake.statuses = [result]
                with self.assertRaises(UncertainUpdate):
                    adapter(fake, fixture=True, polls=1)._set_and_wait(fake.metadata)

    def test_invalid_target_is_rejected_before_any_network(self):
        fake = FakeSession()
        with self.assertRaises(ValueError):
            InstanceMetadataRest(
                fake, project="p/other", zone="us-central1-c", instance="test"
            )
        self.assertEqual(fake.requests, [])


if __name__ == "__main__":
    unittest.main()
