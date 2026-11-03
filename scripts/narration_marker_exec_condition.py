"""Prevent legacy recovery start when narration recovery may be pending.

For a systemd ExecCondition: 0 permits start, 1 skips it, 255 fails the unit.
This does not serialize checks with later marker creation and is not an
alternative to holding the shared backup lock and proving boot ordering.
"""
import os
from pathlib import Path
import stat

MARKER = Path('/var/lib/ai-story-book/narration-deploy/narration-recovery.json')
PROVIDER_ROTATION_MARKER = Path('/var/lib/ai-story-book/provider-rotation/recovery.json')


def exit_code(path):
    path = Path(path)
    try:
        parent = path.parent.lstat()
    except FileNotFoundError:
        return 0  # The guard has not been installed yet.
    except OSError:
        return 255
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid()
            or parent.st_mode & 0o077):
        return 255
    try:
        os.lstat(path)
    except FileNotFoundError:
        return 0
    except OSError:
        return 255
    return 1  # Includes dangling symlinks and malformed marker files.


def combined_exit_code(narration_marker, provider_rotation_marker):
    """Skip old recovery when either marker exists; fail on either uncertainty."""
    results = (exit_code(narration_marker), exit_code(provider_rotation_marker))
    if 255 in results:
        return 255
    return 1 if 1 in results else 0


if __name__ == '__main__':
    raise SystemExit(combined_exit_code(MARKER, PROVIDER_ROTATION_MARKER))
