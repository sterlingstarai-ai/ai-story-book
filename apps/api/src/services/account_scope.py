"""Derive a non-bearer account cache scope from an independently pinned key."""

import hashlib
import hmac
import os
import re
import stat


class AccountScopeUnavailable(RuntimeError):
    """Scope cannot be established; no fallback to raw account credentials."""


def derive_account_scope(*, owner: str, namespace: str, key_path: str, expected_sha256: str) -> str:
    try:
        if (not isinstance(owner, str) or not re.fullmatch(
                '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', owner)
                or not isinstance(namespace, str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}', namespace)
                or not isinstance(key_path, str) or not os.path.isabs(key_path)
                or not isinstance(expected_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_sha256)):
            raise ValueError('invalid scope configuration')
        if not hasattr(os, 'O_NOFOLLOW'):
            raise ValueError('symlink-safe key reads are unavailable')
        fd = os.open(key_path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ValueError('key file is not private')
            key = os.read(fd, 33)
        finally:
            os.close(fd)
        if len(key) != 32 or not hmac.compare_digest(hashlib.sha256(key).hexdigest(), expected_sha256):
            raise ValueError('key pin mismatch')
        message = b'asb:account-media-scope:v1\0' + namespace.encode() + b'\0' + owner.encode()
        return hmac.new(key, message, hashlib.sha256).hexdigest()
    except Exception:
        raise AccountScopeUnavailable('Account media scope is unavailable') from None
