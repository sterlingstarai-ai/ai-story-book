"""Prepare an in-memory-only Docker env file without old provider keys.

Other existing runtime credentials remain present, so resulting bytes and the
memfd must never be printed or written to a persistent file. This module does
not deploy containers or read any credential by itself.
"""
import os
import re


class ProviderEnvironmentError(RuntimeError):
    pass


_MAX_ENV_BYTES = 1024 * 1024
_KEY = re.compile(rb'[A-Za-z_][A-Za-z0-9_]*\Z')
_OLD = frozenset({b'LLM_API_KEY', b'IMAGE_API_KEY'})
_NEW = frozenset({b'LLM_API_KEY_FILE', b'IMAGE_API_KEY_FILE'})


def sanitize_environment(source, *, container_key_path='/run/asb-provider-keys/provider.key'):
    """Preserve other Docker env lines byte-for-byte, remove old key values."""
    if (not isinstance(source, bytes) or len(source) > _MAX_ENV_BYTES or b'\0' in source or b'\r' in source
            or not isinstance(container_key_path, str)
            or not re.fullmatch(r'/run/asb-provider-keys/[A-Za-z0-9_-]{1,64}\.key', container_key_path)):
        raise ProviderEnvironmentError('Provider environment is invalid')
    seen = set()
    output = []
    for line in source.split(b'\n'):
        if not line or line.startswith(b'#'):
            output.append(line)
            continue
        if b'=' not in line:
            raise ProviderEnvironmentError('Provider environment format is unsupported')
        key, _ = line.split(b'=', 1)
        if not _KEY.fullmatch(key) or key in seen or key in _NEW:
            raise ProviderEnvironmentError('Provider environment format is unsupported')
        seen.add(key)
        if key not in _OLD:
            output.append(line)
    if not _OLD.issubset(seen):
        raise ProviderEnvironmentError('Provider environment is missing expected fields')
    path = container_key_path.encode('ascii')
    output.extend([b'LLM_API_KEY_FILE=' + path, b'IMAGE_API_KEY_FILE=' + path])
    return b'\n'.join(output) + b'\n'


def create_environment_memfd(source, *, container_key_path='/run/asb-provider-keys/provider.key'):
    """Create a Linux anonymous memory-backed env file; caller must close fd.

    To use it with a child Docker CLI, pass `/proc/self/fd/<fd>` as the
    env-file path and use `subprocess` with `pass_fds=(fd,)`. On platforms
    without memfd the operation is rejected rather than writing a disk file.
    """
    if not hasattr(os, 'memfd_create'):
        raise ProviderEnvironmentError('Anonymous in-memory environment is unavailable')
    data = sanitize_environment(source, container_key_path=container_key_path)
    fd = None
    try:
        fd = os.memfd_create('asb-provider-environment', getattr(os, 'MFD_CLOEXEC', 0))
        os.fchmod(fd, 0o600)
        view = memoryview(data)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise OSError('short write')
            view = view[count:]
        os.lseek(fd, 0, os.SEEK_SET)
        return fd
    except Exception:
        if fd is not None:
            os.close(fd)
        raise ProviderEnvironmentError('Anonymous environment could not be prepared') from None
