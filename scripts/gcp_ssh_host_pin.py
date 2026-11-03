"""Construct strict SSH known_hosts data from an independently verified pin.

Only validation is implemented here: there is no SSH invocation, remote keyscan,
or claim about how a caller obtained the trusted host key.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import re


class HostPinError(Exception):
    pass


_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_FINGERPRINT = re.compile(r"SHA256:[A-Za-z0-9+/]{43}\Z")


def strict_known_hosts_entry(
    host: str, port: int, public_key: str, *, expected_fingerprint: str
) -> str:
    """Return one pinned host entry; the fingerprint must come from an independent source."""
    if type(port) is not int or not 1 <= port <= 65535 or not isinstance(host, str):
        raise HostPinError("invalid SSH host")
    try:
        host = str(ipaddress.ip_address(host))
    except ValueError:
        host = host.lower()
        if len(host) > 253 or not all(
            _LABEL.fullmatch(label) for label in host.split(".")
        ):
            raise HostPinError("invalid SSH host") from None
    pieces = public_key.split(" ") if isinstance(public_key, str) else []
    if len(pieces) != 2 or pieces[0] != "ssh-ed25519":
        raise HostPinError("invalid SSH host key")
    try:
        raw = base64.b64decode(pieces[1], validate=True)
    except (ValueError, binascii.Error):
        raise HostPinError("invalid SSH host key") from None
    if (
        len(raw) != 51
        or raw[:15] != b"\0\0\0\x0bssh-ed25519"
        or raw[15:19] != b"\0\0\0\x20"
    ):
        raise HostPinError("invalid SSH host key")
    actual = "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip(
        "="
    )
    if (
        not isinstance(expected_fingerprint, str)
        or not _FINGERPRINT.fullmatch(expected_fingerprint)
        or not hmac.compare_digest(actual, expected_fingerprint)
    ):
        raise HostPinError("SSH host pin mismatch")
    # OpenSSH uses the literal host for the default port, including IPv6.
    destination = f"[{host}]:{port}" if port != 22 else host
    return f"{destination} {public_key}\n"
