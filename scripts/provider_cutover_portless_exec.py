"""Execute the pinned queue and paid probes inside an owned portless container.

The caller must already hold the backup lock and an owned compound mutation
journal spanning probe start through stop/removal. A timeout is indeterminate;
this function never retries and never clears the caller's journal.
"""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import stat
import subprocess

import provider_candidate_stage as stage
from provider_cutover_probe_runner import API_IMAGE, PROBE_SHA256

QUEUE_SHA256 = 'a09aa529f0af92061f3183bcc9c661743354915238b95058917201969cc4ebf4'


class PortlessProbeError(RuntimeError):
    pass


def _source(name, digest):
    fd = None
    try:
        fd = os.open(Path(__file__).with_name(name), os.O_RDONLY | os.O_NOFOLLOW)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or before.st_nlink != 1
                or before.st_mode & 0o022 or before.st_size > 100_000):
            raise ValueError()
        data = bytearray()
        while True:
            block = os.read(fd, 8192)
            if not block:
                break
            data.extend(block)
        after = os.fstat(fd)
        if (hashlib.sha256(data).hexdigest() != digest
                or any(getattr(before, field) != getattr(after, field) for field in
                       ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))):
            raise ValueError()
        return bytes(data)
    except Exception:
        raise PortlessProbeError('Pinned probe source is unavailable or differs') from None
    finally:
        if fd is not None:
            os.close(fd)


def run_inside_owned_probe(*, runtime, probe_id, candidate_id, image_id, transaction_id,
                           lock_fd, state_dir, evidence, overlay_path, overlay_sha256, key_path,
                           runner=subprocess.run):
    """Check queues and then perform at most one request per provider model."""
    try:
        if image_id != API_IMAGE or str(state_dir) != stage._PROVIDER_STATE:
            raise ValueError()
        stage._verify_backup_lock_fd(lock_fd)
        owner = stage._probe_owner_record(transaction_id=transaction_id, candidate_id=candidate_id,
                                          probe_id=probe_id, image_id=image_id)
        stage._read_owned_record(os.path.join(state_dir, 'probe-owner.json'), owner)
        stage._read_owned_record(os.path.join(state_dir, 'docker-mutation.json'), {
            'version': 1, 'transaction': transaction_id, 'action': 'provider-probe', 'container': probe_id,
        })
        candidate, running = runtime.inspect(candidate_id), runtime.inspect(probe_id)
        if (candidate.get('Id') != candidate_id or candidate.get('Image') != image_id
                or candidate.get('State', {}).get('Running') is not False
                or candidate.get('Name', '').lstrip('/') != 'asb-provider-next-api'
                or (candidate.get('Config', {}).get('Labels') or {}).get('asb.provider.transaction') != transaction_id
                or candidate.get('HostConfig', {}).get('RestartPolicy', {}).get('Name') != 'no'
                or running.get('State', {}).get('Running') is not True
                or running.get('State', {}).get('Restarting') is not False):
            raise ValueError()
        # Reuse the complete stopped-probe config contract; only its already
        # checked Running field differs while the owned sleep process is alive.
        as_stopped = copy.deepcopy(running)
        as_stopped['State']['Running'] = False
        stage._probe_contract(as_stopped, identifier=probe_id, image_id=image_id, transaction_id=transaction_id,
                              candidate=candidate, overlay_path=overlay_path, key_path=key_path)
        stage.verify_running_bound_files(runtime=runtime, identifier=probe_id, image_id=image_id,
                                         transaction_id=transaction_id, evidence=evidence,
                                         overlay_path=overlay_path, overlay_sha256=overlay_sha256,
                                         key_path=key_path)
        queue_source = _source('provider_cutover_queue_probe.py', QUEUE_SHA256)
        provider_source = _source('provider_cutover_probe.py', PROBE_SHA256)
        for source, argument, expected in (
            (queue_source, '--broker-only', b'QUEUE_DRAIN_OK\n'),
            (provider_source, '--inside-pinned-candidate', b'PROVIDER_PROBE_OK\n'),
        ):
            result = runner(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock',
                             'exec', '-i', probe_id, 'python', '-', argument], input=source,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=300, check=False,
                            env={'PATH': '/usr/bin:/bin', 'HOME': '/root'})
            if result.returncode != 0 or result.stdout != expected:
                raise ValueError()
        # Prevent an old host bind or restarted process from being accepted.
        stage.verify_running_bound_files(runtime=runtime, identifier=probe_id, image_id=image_id,
                                         transaction_id=transaction_id, evidence=evidence,
                                         overlay_path=overlay_path, overlay_sha256=overlay_sha256,
                                         key_path=key_path)
        return True
    except BaseException:
        raise PortlessProbeError('Portless provider probe failed or is indeterminate') from None
