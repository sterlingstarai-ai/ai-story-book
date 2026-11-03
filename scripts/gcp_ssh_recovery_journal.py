"""Secret-free, crash-aware local journal building block for future SSH access.

No GCP or SSH calls are made here. A journal by itself does not authorize any
metadata write, recovery, or deletion. In particular, if submission began but
the operation ID was not persisted, the operation may still apply later.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import uuid
from dataclasses import dataclass, field

from scripts.gcp_instance_ssh_guard import InstanceKeyGuard


class JournalError(Exception):
    pass


_RESOURCE = re.compile(r"[a-z][a-z0-9-]{0,62}\Z")
_JOURNAL_ID = re.compile(r"[0-9a-f]{32}\Z")
_OPERATION = re.compile(r"[a-zA-Z0-9_-]{1,128}\Z")
_MAX_RECORD = 16384


def _canonical(value: dict) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _encode(value: dict) -> bytes:
    data = _canonical(value)
    return _canonical({"data": value, "sha256": hashlib.sha256(data).hexdigest()})


class RecoveryJournal:
    """Records only public SSH entry and target; never accept private keys/tokens.

    The supplied directory must already exist, be owned by this user and have
    no group/other permissions. Records are immutable and individually fsynced.
    This does not protect against another process running as the same OS user.
    """

    def __init__(self, directory: str):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            self._dir = os.open(directory, flags)
            st = os.fstat(self._dir)
            if (
                not stat.S_ISDIR(st.st_mode)
                or st.st_uid != os.geteuid()
                or stat.S_IMODE(st.st_mode) & 0o077
            ):
                raise JournalError("private, user-owned journal directory required")
        except BaseException:
            if hasattr(self, "_dir"):
                os.close(self._dir)
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        os.close(self._dir)

    @staticmethod
    def _name(journal_id: str, kind: str) -> str:
        if not _JOURNAL_ID.fullmatch(journal_id) or kind not in {
            "intent",
            "started",
            "operation",
        }:
            raise JournalError("invalid journal record")
        return journal_id + "." + kind + ".json"

    def _write(self, journal_id: str, kind: str, value: dict) -> None:
        name = self._name(journal_id, kind)
        raw = _encode(value)
        if len(raw) > _MAX_RECORD:
            raise JournalError("journal record too large")
        temp = ".tmp-" + secrets.token_hex(16)
        fd = None
        try:
            fd = os.open(
                temp,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=self._dir,
            )
            remaining = memoryview(raw)
            while remaining:
                count = os.write(fd, remaining)
                if count <= 0:
                    raise JournalError("journal write incomplete")
                remaining = remaining[count:]
            os.fsync(fd)
            os.close(fd)
            fd = None
            # link is atomic and cannot overwrite an existing record.
            os.link(
                temp,
                name,
                src_dir_fd=self._dir,
                dst_dir_fd=self._dir,
                follow_symlinks=False,
            )
            os.fsync(self._dir)
        except Exception:
            raise JournalError("journal persistence not confirmed") from None
        finally:
            if fd is not None:
                os.close(fd)
            try:
                os.unlink(temp, dir_fd=self._dir)
                os.fsync(self._dir)
            except FileNotFoundError:
                pass
            except OSError:
                # An orphan private temp file is not proof of successful persistence.
                pass

    def _read(self, journal_id: str, kind: str) -> dict | None:
        name = self._name(journal_id, kind)
        try:
            fd = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self._dir
            )
        except FileNotFoundError:
            return None
        except OSError:
            raise JournalError("journal record cannot be opened safely") from None
        try:
            st = os.fstat(fd)
            if (
                not stat.S_ISREG(st.st_mode)
                or st.st_uid != os.geteuid()
                or stat.S_IMODE(st.st_mode) & 0o077
                or st.st_size > _MAX_RECORD
                or st.st_nlink != 1
            ):
                raise JournalError("unsafe journal record")
            raw = b""
            while len(raw) <= _MAX_RECORD:
                chunk = os.read(fd, _MAX_RECORD + 1 - len(raw))
                if not chunk:
                    break
                raw += chunk
            envelope = json.loads(raw)
            data = envelope["data"]
            if (
                not isinstance(data, dict)
                or set(envelope) != {"data", "sha256"}
                or hashlib.sha256(_canonical(data)).hexdigest() != envelope["sha256"]
            ):
                raise ValueError()
            if (
                data.get("id") != journal_id
                or data.get("kind") != kind
                or data.get("version") != 1
            ):
                raise ValueError()
            return data
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            raise JournalError("invalid or damaged journal record") from None
        finally:
            os.close(fd)

    def create_intent(
        self, *, project: str, zone: str, instance: str, owned_entry: str, clock
    ) -> str:
        if not all(_RESOURCE.fullmatch(v) for v in (project, zone, instance)):
            raise JournalError("invalid instance identity")
        # Validate exact public-key type, owner and expiring metadata syntax.
        try:
            InstanceKeyGuard(None, clock=clock)._validate_entry(owned_entry)
        except Exception:
            raise JournalError("invalid expiring public entry") from None
        journal_id = secrets.token_hex(16)
        self._write(
            journal_id,
            "intent",
            {
                "version": 1,
                "id": journal_id,
                "kind": "intent",
                "project": project,
                "zone": zone,
                "instance": instance,
                "owned_entry": owned_entry,
            },
        )
        return journal_id

    def mark_started(self, journal_id: str) -> str:
        if self._read(journal_id, "intent") is None:
            raise JournalError("intent missing")
        request_id = str(uuid.uuid4())
        self._write(
            journal_id,
            "started",
            {
                "version": 1,
                "id": journal_id,
                "kind": "started",
                "request_id": request_id,
            },
        )
        return request_id

    def record_operation(self, journal_id: str, operation: str) -> None:
        if (
            self._read(journal_id, "intent") is None
            or self._read(journal_id, "started") is None
            or not _OPERATION.fullmatch(operation)
        ):
            raise JournalError("operation identity or submission record missing")
        self._write(
            journal_id,
            "operation",
            {
                "version": 1,
                "id": journal_id,
                "kind": "operation",
                "operation": operation,
            },
        )

    def inspect(self, journal_id: str) -> "RecoveryState":
        intent = self._read(journal_id, "intent")
        started = self._read(journal_id, "started")
        operation = self._read(journal_id, "operation")
        if intent is None or (operation is not None and started is None):
            raise JournalError("incomplete or inconsistent journal")
        request_id = None
        if started is not None:
            try:
                request_id = started["request_id"]
                parsed = uuid.UUID(request_id)
                if str(parsed) != request_id or parsed.int == 0:
                    raise ValueError()
            except (KeyError, ValueError, TypeError, AttributeError):
                raise JournalError("invalid request ID") from None
        if started is None:
            phase = "not_started"
        elif operation is None:
            phase = "operation_unknown"
        else:
            phase = "operation_recorded"
        return RecoveryState(phase=phase, request_id=request_id)


@dataclass(frozen=True)
class RecoveryState:
    phase: str
    request_id: str | None = field(default=None, repr=False)

    def may_auto_cleanup(self) -> bool:
        # Operation identity and terminal state must first be independently
        # confirmed against the exact instance and operation. Not wired yet.
        return False
