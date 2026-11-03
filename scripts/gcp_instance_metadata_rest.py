"""GCE instance-metadata REST adapter, with all live writes hard-blocked.

The caller supplies an authorized HTTP session; this module never creates or
prints credentials.  Reads are opt-in through an explicit read() call.  The
private operation driver is exercised with fake sessions only.  compare_and_set
will remain blocked until durable cleanup recovery and SSH host identity checks
have been implemented and independently verified.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable, Protocol

from scripts.gcp_instance_ssh_guard import (
    Conflict,
    GuardError,
    NotSubmitted,
    UncertainUpdate,
)


class WriteBlocked(NotSubmitted):
    pass


class Response(Protocol):
    status_code: int

    def json(self) -> Any: ...


class Session(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> Response: ...


_RESOURCE = re.compile(r"[a-z][a-z0-9-]{0,62}\Z")
_OPERATION = re.compile(r"[a-zA-Z0-9_-]{1,128}\Z")
_BASE = "https://compute.googleapis.com/compute/v1"
# This is intentionally not a runtime option. The controls do not exist yet.
_DURABLE_RECOVERY_AND_HOST_IDENTITY_IMPLEMENTED = False


class InstanceMetadataRest:
    def __init__(
        self,
        session: Session,
        *,
        project: str,
        zone: str,
        instance: str,
        enable_write: bool = False,
        polls: int = 20,
        pause: Callable[[float], None] = time.sleep,
    ):
        if not all(_RESOURCE.fullmatch(x) for x in (project, zone, instance)):
            raise ValueError("invalid GCE instance identity")
        if not 1 <= polls <= 120:
            raise ValueError("invalid poll count")
        self._session = session
        self._project = project
        self._zone = zone
        self._instance = instance
        self._enable_write = enable_write
        self._polls = polls
        self._pause = pause
        self._instance_url = (
            f"{_BASE}/projects/{project}/zones/{zone}/instances/{instance}"
        )

    def read(self) -> dict:
        try:
            response = self._session.request("GET", self._instance_url, timeout=15)
            if response.status_code != 200:
                raise GuardError("instance metadata unavailable")
            payload = response.json()
            metadata = payload.get("metadata") if isinstance(payload, dict) else None
            if not isinstance(metadata, dict) or not isinstance(
                metadata.get("fingerprint"), str
            ):
                raise GuardError("invalid instance metadata response")
            return metadata
        except GuardError:
            raise
        except Exception:
            # Do not include exception text: clients may embed URLs or headers.
            raise GuardError("instance metadata unavailable") from None

    def compare_and_set(self, metadata: dict) -> None:
        self._require_write_controls()
        self._set_and_wait(metadata)

    def _require_write_controls(self) -> None:
        if (
            not self._enable_write
            or not _DURABLE_RECOVERY_AND_HOST_IDENTITY_IMPLEMENTED
        ):
            raise WriteBlocked(
                "instance metadata writes disabled; recovery and host identity are incomplete"
            )

    def _set_and_wait(self, metadata: dict) -> None:
        """Internal request state machine; exercise solely against a fake session.

        A timeout or malformed response after POST means the update may still be
        applied. Only a definitive fingerprint rejection may be retried as such.
        """
        self._require_write_controls()
        if (
            not isinstance(metadata, dict)
            or not isinstance(metadata.get("fingerprint"), str)
            or not metadata["fingerprint"]
        ):
            raise GuardError("metadata fingerprint missing")
        try:
            response = self._session.request(
                "POST", self._instance_url + "/setMetadata", json=metadata, timeout=15
            )
        except Exception:
            raise UncertainUpdate("metadata request outcome unknown") from None
        if response.status_code == 412:
            raise Conflict("instance metadata fingerprint changed")
        if response.status_code not in (200, 201):
            raise UncertainUpdate("metadata request not confirmed")
        try:
            operation = response.json()
            name = operation.get("name") if isinstance(operation, dict) else None
            if not isinstance(name, str) or not _OPERATION.fullmatch(name):
                raise ValueError()
        except Exception:
            raise UncertainUpdate("metadata operation identity unavailable") from None
        operation_url = (
            f"{_BASE}/projects/{self._project}/zones/{self._zone}/operations/{name}"
        )
        for _ in range(self._polls):
            try:
                check = self._session.request("GET", operation_url, timeout=15)
                if check.status_code != 200:
                    raise ValueError()
                state = check.json()
                if not isinstance(state, dict) or state.get("name") != name:
                    raise ValueError()
                if state.get("status") == "DONE":
                    if "error" in state:
                        raise UncertainUpdate(
                            "metadata operation failed; final state unverified"
                        )
                    return
                if state.get("status") not in ("PENDING", "RUNNING"):
                    raise ValueError()
            except UncertainUpdate:
                raise
            except Exception:
                raise UncertainUpdate("metadata operation status unavailable") from None
            self._pause(1)
        raise UncertainUpdate("metadata operation completion not observed")
