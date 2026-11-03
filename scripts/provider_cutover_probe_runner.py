"""Journaled wrapper for the pinned, bounded candidate-only provider probe.

This wrapper does not establish the production lock, identity, or ingress
fence. The caller must verify them before and after running it; no production
cutover entry point is implemented here.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess

from provider_cutover_journal import run_journaled


PROBE_SHA256 = '549c8218ed9341319bc01e72ffcb88d8509d35565b555ce1a93f59192708b1ee'
API_IMAGE = 'sha256:47dcb13c52033638740a93463cded3d61c28bc9c85ccfd7ce4932e681be139b1'
_ID = re.compile(r'[0-9a-f]{64}\Z')


class CandidateProbeError(RuntimeError):
    pass


def _source():
    fd = None
    try:
        fd = os.open(Path(__file__).with_name('provider_cutover_probe.py'), os.O_RDONLY | os.O_NOFOLLOW)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or before.st_mode & 0o022 or before.st_nlink != 1 or before.st_size > 100_000):
            raise ValueError()
        parts = []
        while True:
            part = os.read(fd, 8192)
            if not part:
                break
            parts.append(part)
        source = b''.join(parts)
        after = os.fstat(fd)
        if (hashlib.sha256(source).hexdigest() != PROBE_SHA256
                or any(getattr(before, name) != getattr(after, name) for name in
                       ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))):
            raise ValueError()
        return source
    except (OSError, ValueError):
        raise CandidateProbeError('Pinned probe source is unavailable or differs') from None
    finally:
        if fd is not None:
            os.close(fd)


def run_candidate_probe(*, directory, transaction, candidate_id, inspect, ingress_fenced,
                        runner=subprocess.run, timeout=300):
    """Run at most one text and one image probe; preserve uncertainty on failure."""
    if not isinstance(candidate_id, str) or not _ID.fullmatch(candidate_id):
        raise CandidateProbeError('Invalid candidate identity')
    item = inspect(candidate_id)
    if (not isinstance(item, dict) or item.get('id') != candidate_id
            or item.get('image_id') != API_IMAGE or item.get('name') != 'asb-pilot-api'
            or item.get('running') is not True or item.get('restart_policy') != 'no'
            or item.get('candidate_config_verified') is not True or ingress_fenced() is not True):
        raise CandidateProbeError('Candidate or ingress precondition failed')
    source = _source()
    result = None

    def execute():
        nonlocal result
        try:
            result = runner(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', 'exec', '-i', candidate_id, 'python', '-',
                             '--inside-pinned-candidate'], input=source, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=timeout, check=False,
                            env={'PATH': '/usr/bin:/bin', 'HOME': '/root'})
        except Exception:
            # The daemon may still be executing or charging; the journal remains.
            raise CandidateProbeError('Candidate probe completion is indeterminate') from None

    def verify():
        return (result is not None and result.returncode == 0 and result.stdout == b'PROVIDER_PROBE_OK\n'
                and ingress_fenced() is True)

    run_journaled(directory, transaction=transaction, action='provider-probe', container=candidate_id,
                  execute=execute, verify=verify)
    return True
