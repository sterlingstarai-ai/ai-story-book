"""Build a minimal pinned-source provider-key-file overlay; no keys are read.

This creates source bytes only. It neither deploys nor authenticates a server,
and must be paired with a verified image, ingress drain and recovery procedure.
"""
import ast
import hashlib
import re


class OverlayError(RuntimeError):
    pass


_PAYLOAD = '''
\n# Provider-key-file support added to the pinned production config.
import os as _asb_os
import re as _asb_re
import stat as _asb_stat

def _asb_read_key(path):
    descriptors = []
    try:
        if (not isinstance(path, str) or not path.startswith('/') or path.startswith('//')
                or _asb_os.path.normpath(path) != path or path == '/'
                or not hasattr(_asb_os, 'O_NOFOLLOW') or not hasattr(_asb_os, 'O_DIRECTORY')):
            raise ValueError('invalid path')
        parts = path[1:].split('/')
        dflags = _asb_os.O_RDONLY | _asb_os.O_DIRECTORY | _asb_os.O_NOFOLLOW | getattr(_asb_os, 'O_CLOEXEC', 0)
        descriptors.append(_asb_os.open('/', dflags))
        for part in parts[:-1]:
            descriptors.append(_asb_os.open(part, dflags, dir_fd=descriptors[-1]))
        fd = _asb_os.open(parts[-1], _asb_os.O_RDONLY | _asb_os.O_NOFOLLOW
                          | getattr(_asb_os, 'O_NONBLOCK', 0) | getattr(_asb_os, 'O_CLOEXEC', 0),
                          dir_fd=descriptors[-1])
        descriptors.append(fd)
        before = _asb_os.fstat(fd)
        if (not _asb_stat.S_ISREG(before.st_mode) or before.st_uid != _asb_os.geteuid()
                or before.st_mode & 0o077 or before.st_size > 4098):
            raise ValueError('invalid file')
        raw = _asb_os.read(fd, 4099)
        after = _asb_os.fstat(fd)
        if (len(raw) != before.st_size or any(getattr(before, n) != getattr(after, n) for n in
                ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_uid', 'st_mode'))):
            raise ValueError('changed file')
        if raw.endswith(b'\\r\\n'):
            raw = raw[:-2]
        elif raw.endswith(b'\\n'):
            raw = raw[:-1]
        value = raw.decode('ascii')
        if not _asb_re.fullmatch(r'[\\x21-\\x7e]{1,4096}', value):
            raise ValueError('invalid key')
        return value
    except Exception:
        raise RuntimeError('Provider key file is unavailable or unsafe') from None
    finally:
        for descriptor in reversed(descriptors):
            _asb_os.close(descriptor)

for _asb_name in ('llm_api_key', 'image_api_key'):
    if _asb_name not in Settings.model_fields:
        raise RuntimeError('Provider key settings are unavailable')
    Settings.model_fields[_asb_name].exclude = True
    Settings.model_fields[_asb_name].repr = False
Settings.model_rebuild(force=True)
settings = Settings()
_asb_llm_file = _asb_os.environ.get('LLM_API_KEY_FILE', '')
_asb_image_file = _asb_os.environ.get('IMAGE_API_KEY_FILE', '')
if _asb_llm_file or _asb_image_file:
    if (not _asb_llm_file or _asb_llm_file != _asb_image_file
            or settings.llm_api_key or settings.image_api_key):
        raise RuntimeError('Provider key file configuration is inconsistent')
    _asb_key = _asb_read_key(_asb_llm_file)
    settings.llm_api_key = _asb_key
    settings.image_api_key = _asb_key
    del _asb_key
'''


def build_overlay(source, expected_sha256):
    """Return overlay code only if a pinned config has the expected shape."""
    if (not isinstance(source, bytes) or len(source) > 512 * 1024
            or not isinstance(expected_sha256, str)
            or not re.fullmatch('[0-9a-f]{64}', expected_sha256)
            or hashlib.sha256(source).hexdigest() != expected_sha256):
        raise OverlayError('Pinned configuration source did not match')
    try:
        text = source.decode('utf-8')
        tree = ast.parse(text)
        classes = [item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == 'Settings']
        assignments = [item for item in tree.body if isinstance(item, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == 'settings' for target in item.targets)]
        if (len(classes) != 1 or len(assignments) != 1 or tree.body[-1] is not assignments[0]
                or not isinstance(assignments[0].value, ast.Call)
                or not isinstance(assignments[0].value.func, ast.Name)
                or assignments[0].value.func.id != 'Settings'
                or assignments[0].value.args or assignments[0].value.keywords):
            raise ValueError('unsupported settings shape')
        fields = {item.target.id for item in classes[0].body
                  if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)}
        if not {'llm_api_key', 'image_api_key'}.issubset(fields):
            raise ValueError('unsupported fields')
        lines = text.splitlines(keepends=True)
        start = assignments[0].lineno - 1
        output = (''.join(lines[:start]) + _PAYLOAD).encode('utf-8')
        ast.parse(output)
        return output
    except (SyntaxError, UnicodeDecodeError, ValueError):
        raise OverlayError('Pinned configuration source is unsupported') from None
