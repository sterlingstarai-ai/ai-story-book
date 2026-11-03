"""Fingerprint-CAS guard for a temporary, instance-only GCE SSH metadata entry.

This module deliberately has no network or credential adapter and performs no SSH.
A future adapter must implement the protocol and the operation-completion contract
below before this can be used against a real instance. Never use project metadata.
"""

from __future__ import annotations

import copy
import base64
import binascii
import datetime as dt
import json
import re
from dataclasses import dataclass, field
from typing import Callable, Protocol, TypeVar


class GuardError(Exception):
    """A safe metadata operation could not be established."""


class Conflict(GuardError):
    """The remote fingerprint changed; the caller may read and retry."""


class NotSubmitted(GuardError):
    """The adapter guarantees no metadata request was sent."""


class UncertainUpdate(GuardError):
    """The request may have been accepted but its terminal outcome is unknown."""


class CleanupFailure(GuardError):
    """The caller must not represent the temporary entry as removed."""


class InstanceMetadataTransport(Protocol):
    """Single explicitly selected instance. No project-metadata operations.

    read() returns its current metadata and fingerprint. compare_and_set() must
    return only after the corresponding GCE operation has completed successfully;
    raise Conflict for a proven rejected fingerprint and UncertainUpdate if the
    request might have been accepted but completion cannot be established.
    """

    def read(self) -> dict: ...

    def compare_and_set(self, metadata: dict) -> None: ...


_USER = re.compile(r"[a-z_][a-z0-9_-]{0,31}\Z")
_PUBLIC_KEY = re.compile(r"ssh-ed25519 ([A-Za-z0-9+/]+={0,3})\Z")


def _valid_public_key(value: str) -> bool:
    match = _PUBLIC_KEY.fullmatch(value)
    if match is None:
        return False
    try:
        data = base64.b64decode(match.group(1), validate=True)
    except (binascii.Error, ValueError):
        return False
    # SSH wire encoding: algorithm length/name, then the 32-byte Ed25519 key.
    return (
        len(data) == 51
        and data[:15] == b"\x00\x00\x00\x0bssh-ed25519"
        and data[15:19] == b"\x00\x00\x00\x20"
    )


def make_entry(
    username: str,
    public_key: str,
    *,
    now: dt.datetime,
    lifetime: dt.timedelta = dt.timedelta(minutes=5),
) -> str:
    """Build the complete exact owned line, with a short GCE-enforced expiry."""
    if not _USER.fullmatch(username) or not _valid_public_key(public_key):
        raise GuardError("invalid temporary SSH identity")
    if now.tzinfo is None or now.utcoffset() is None:
        raise GuardError("UTC-aware time required")
    if lifetime <= dt.timedelta(0) or lifetime > dt.timedelta(minutes=5):
        raise GuardError("SSH expiry must be within five minutes")
    expires = (
        (now.astimezone(dt.timezone.utc) + lifetime)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    value = json.dumps(
        {"userName": username, "expireOn": expires}, separators=(",", ":")
    )
    return f"{username}:{public_key} google-ssh {value}"


def _metadata(raw: dict) -> tuple[dict, list[dict], int | None]:
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("fingerprint"), str)
        or not raw["fingerprint"]
    ):
        raise GuardError("instance metadata fingerprint missing")
    md = copy.deepcopy(raw)
    items = md.get("items", [])
    if not isinstance(items, list):
        raise GuardError("invalid instance metadata")
    matches = [
        n
        for n, item in enumerate(items)
        if isinstance(item, dict) and item.get("key") == "ssh-keys"
    ]
    if len(matches) > 1 or any(
        not isinstance(item, dict) or not isinstance(item.get("key"), str)
        for item in items
    ):
        raise GuardError("ambiguous instance metadata")
    idx = matches[0] if matches else None
    if idx is not None and not isinstance(items[idx].get("value"), str):
        raise GuardError("invalid SSH metadata")
    md["items"] = items
    return md, items, idx


def _count(value: str, entry: str) -> int:
    return sum(line.rstrip("\r\n") == entry for line in value.splitlines(keepends=True))


@dataclass(frozen=True)
class InsertReceipt:
    field_existed: bool
    _entry: str = field(repr=False)
    _owner: object = field(repr=False)


class InstanceKeyGuard:
    def __init__(
        self,
        transport: InstanceMetadataTransport,
        *,
        attempts: int = 5,
        clock: Callable[[], dt.datetime] | None = None,
    ):
        if attempts < 1 or attempts > 20:
            raise ValueError("invalid retry count")
        self.transport = transport
        self.attempts = attempts
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self._owner = object()
        self._pending = None

    def _validate_entry(self, entry: str) -> None:
        match = re.fullmatch(
            r"([^:\r\n]+):(ssh-ed25519 [A-Za-z0-9+/=]+) google-ssh (\{[^\r\n]+\})",
            entry,
        )
        if (
            not match
            or not _USER.fullmatch(match.group(1))
            or not _valid_public_key(match.group(2))
        ):
            raise GuardError("invalid owned line")
        try:
            info = json.loads(match.group(3))
            now = self.clock()
            expiry = dt.datetime.fromisoformat(info["expireOn"].replace("Z", "+00:00"))
            if set(info) != {"userName", "expireOn"} or info["userName"] != match.group(
                1
            ):
                raise ValueError()
            if (
                now.tzinfo is None
                or expiry.tzinfo is None
                or not dt.timedelta(0) < expiry - now <= dt.timedelta(minutes=5)
            ):
                raise ValueError()
        except (ValueError, TypeError, KeyError, AttributeError):
            raise GuardError("invalid or expired temporary SSH identity") from None

    def insert(self, entry: str) -> InsertReceipt:
        if self._pending is not None:
            raise GuardError("a temporary insertion is already pending cleanup")
        self._validate_entry(entry)
        for _ in range(self.attempts):
            self._validate_entry(entry)
            md, items, idx = _metadata(self.transport.read())
            old = items[idx]["value"] if idx is not None else ""
            if _count(old, entry):
                raise GuardError("owned line already exists; ownership is ambiguous")
            # Insert first, so deleting our line restores an unterminated old value
            # without changing another entry's bytes or line endings.
            new = entry + ("\n" + old if old else "")
            if idx is None:
                items.append({"key": "ssh-keys", "value": new})
            else:
                items[idx]["value"] = new
            self._pending = InsertReceipt(
                field_existed=idx is not None, _entry=entry, _owner=self._owner
            )
            try:
                self.transport.compare_and_set(md)
            except Conflict:
                self._pending = None
                continue
            except NotSubmitted:
                self._pending = None
                raise
            except BaseException as exc:
                raise UncertainUpdate("temporary insertion outcome unknown") from exc
            try:
                _, check_items, check_idx = _metadata(self.transport.read())
            except BaseException as exc:
                raise UncertainUpdate(
                    "temporary insertion confirmation unavailable"
                ) from exc
            if check_idx is None or _count(check_items[check_idx]["value"], entry) != 1:
                raise UncertainUpdate("temporary entry not confirmed")
            return self._pending
        raise GuardError("metadata changed repeatedly")

    def remove(self, entry: str, receipt: InsertReceipt) -> None:
        if (
            receipt is not self._pending
            or receipt._owner is not self._owner
            or receipt._entry != entry
        ):
            raise CleanupFailure("entry was not inserted by this guard")
        for _ in range(self.attempts):
            md, items, idx = _metadata(self.transport.read())
            if idx is None:
                self._pending = None
                return
            value = items[idx]["value"]
            count = _count(value, entry)
            if count == 0:
                self._pending = None
                return
            if count != 1:
                raise CleanupFailure("duplicate owned line; automatic cleanup refused")
            kept = "".join(
                line
                for line in value.splitlines(keepends=True)
                if line.rstrip("\r\n") != entry
            )
            if kept or receipt.field_existed:
                items[idx]["value"] = kept
            else:
                del items[idx]
            try:
                self.transport.compare_and_set(md)
            except Conflict:
                continue
            _, after_items, after_idx = _metadata(self.transport.read())
            if after_idx is not None and _count(after_items[after_idx]["value"], entry):
                raise CleanupFailure("owned line still present")
            self._pending = None
            return
        raise CleanupFailure("metadata changed repeatedly")


T = TypeVar("T")


def with_temporary_key(
    guard: InstanceKeyGuard, entry: str, action: Callable[[], T]
) -> T:
    """Run an action only after insertion; always attempt narrowly scoped cleanup.

    An uncertain insertion always raises CleanupFailure, even when a subsequent
    lookup is empty: the accepted operation could complete after that lookup.
    Abrupt process termination is outside this guarantee; the key expiry limits
    its lifetime but is not proof that its metadata was removed.
    """
    receipt = None
    uncertain = False
    try:
        try:
            receipt = guard.insert(entry)
        except UncertainUpdate:
            uncertain = True
            raise
        return action()
    finally:
        if receipt is not None or uncertain:
            try:
                guard.remove(entry, receipt or guard._pending)
            except BaseException as exc:
                raise CleanupFailure("temporary SSH cleanup unverified") from exc
        if uncertain:
            raise CleanupFailure("insertion outcome unknown; cleanup unverified")
