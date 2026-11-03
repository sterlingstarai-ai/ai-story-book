"""Hold a live privacy fence through isolated replay preflight, never release it.

An isolated source fence is not proof that every writer participates or that an
independent latest watermark exists. This code cannot apply privacy events or
authorize a restored system; it only keeps the fence alive through preparation.
"""
import asyncio
import multiprocessing
import os
from pathlib import Path
import re
import signal
import time

from live_privacy_boundary import hold_live_privacy_boundary
from quarantined_backup_ingest import _dispose_owned
from quarantined_replay_adapter import prepare_isolated_replay_direct


class LiveFencedReplayError(RuntimeError):
    pass


def _child(pipe, witness_factory, arguments):
    try:
        os.setsid()
        pipe.send({'status': 'CHILD_READY'})
        result = prepare_isolated_replay_direct(witness_factory=witness_factory, **arguments)
        if result != {'status': 'REPLAY_BLOCKED_LATEST_HISTORY_UNPROVEN',
                      'target_verified_at_preflight': True, 'privacy_replay_applied': False,
                      'restore_authorized': False, 'service_publish_authorized': False}:
            raise ValueError('invalid child result')
        pipe.send({'status': 'CHILD_BLOCKED'})
    except BaseException:
        try:
            pipe.send({'status': 'CHILD_FAILED'})
        except Exception:
            pass
    finally:
        pipe.close()


async def _wait_message(pipe, process, deadline):
    while time.monotonic() < deadline:
        if pipe.poll():
            return pipe.recv()
        if not process.is_alive():
            raise LiveFencedReplayError('Isolated preflight process exited')
        await asyncio.sleep(.1)
    raise LiveFencedReplayError('Isolated preflight deadline expired')


async def _stop_child(process, group_ready):
    if process is None:
        return
    if not process.is_alive():
        if process.pid is not None:
            process.join(0)
        return
    try:
        if group_ready:
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        pass
    for _ in range(50):
        if not process.is_alive():
            return
        await asyncio.sleep(.1)
    try:
        if group_ready:
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    for _ in range(50):
        if not process.is_alive():
            return
        await asyncio.sleep(.1)
    raise LiveFencedReplayError('Isolated preflight process could not be stopped')


async def _stop_child_even_if_cancelled(process, group_ready):
    """Do not release the source fence while the child can still operate."""
    task = asyncio.create_task(_stop_child(process, group_ready))
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    task.result()
    if cancelled:
        raise asyncio.CancelledError


async def prepare_with_live_source(*, db, journal, expected_source_identity, witness_factory,
                                   container_id, image_id, token, lock_dir, timeout_seconds=600):
    """Keep the authenticated source fence while a spawned child checks target.

    `witness_factory` must be a spawn-picklable callable that creates fresh
    read-only clients in the child. Credentials are never placed on argv.
    """
    if (not callable(witness_factory) or not isinstance(container_id, str)
            or not re.fullmatch('[0-9a-f]{64}', container_id)
            or not isinstance(image_id, str) or not re.fullmatch('sha256:[0-9a-f]{64}', image_id)
            or not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token)
            or type(timeout_seconds) is not int or not 30 <= timeout_seconds <= 900):
        raise LiveFencedReplayError('Live source preflight configuration is invalid')
    deadline = time.monotonic() + timeout_seconds
    parent = None
    child = None
    process = None
    group_ready = False
    completed = False
    try:
        async with asyncio.timeout(timeout_seconds):
            async with hold_live_privacy_boundary(db, journal, expected_source_identity=expected_source_identity) as boundary:
                try:
                    await boundary.verify()
                    parent, child = multiprocessing.get_context('spawn').Pipe(duplex=False)
                    arguments = {'container_id': container_id, 'image_id': image_id, 'token': token,
                                 'lock_dir': Path(lock_dir), 'timeout_seconds': timeout_seconds}
                    process = multiprocessing.get_context('spawn').Process(target=_child,
                        args=(child, witness_factory, arguments))
                    process.start()
                    child.close()
                    first = await _wait_message(parent, process, deadline)
                    if first != {'status': 'CHILD_READY'}:
                        raise LiveFencedReplayError('Isolated preflight did not start safely')
                    group_ready = True
                    result = await _wait_message(parent, process, deadline)
                    if result != {'status': 'CHILD_BLOCKED'}:
                        raise LiveFencedReplayError('Isolated preflight failed')
                    await _stop_child_even_if_cancelled(process, group_ready)
                    await boundary.verify()
                finally:
                    # The source transaction/fence remains open until the child
                    # has stopped, including under repeated cancellation.
                    await _stop_child_even_if_cancelled(process, group_ready)
        completed = True
        return {'status': 'LIVE_SOURCE_FENCED_REPLAY_BLOCKED',
                'writer_coverage_verified': False, 'latest_head_verified': False,
                'privacy_replay_applied': False, 'restore_authorized': False}
    finally:
        if parent is not None:
            parent.close()
        if child is not None:
            child.close()
        try:
            await _stop_child_even_if_cancelled(process, group_ready)
        finally:
            if not completed and not _dispose_owned(container_id, image_id, token):
                raise LiveFencedReplayError('Failed preflight sandbox cleanup could not be verified') from None
