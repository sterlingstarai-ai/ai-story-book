"""Run one child that Linux kills when its direct parent dies.

Internal release helper. It accepts no credentials in argv and refuses to run
on platforms without Linux PR_SET_PDEATHSIG. It does not replace service cgroup
controls, DB transaction verification, or the durable recovery marker.
"""
import ctypes
import os
import signal
import sys


def main():
    if not sys.platform.startswith('linux') or len(sys.argv) < 4 or sys.argv[2] != '--':
        return 1
    try:
        expected_parent = int(sys.argv[1])
        if expected_parent <= 1 or os.getppid() != expected_parent:
            return 1
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
            return 1
        # Closing the race between the first check and registering the signal.
        if os.getppid() != expected_parent:
            return 1
        os.execvp(sys.argv[3], sys.argv[3:])
    except (OSError, ValueError):
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
