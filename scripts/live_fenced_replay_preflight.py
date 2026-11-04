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
        applied = arguments.get('apply_legacy_public_url') is not None
        status = ('RESTORED_OUTBOX_MATCHES_FENCED_LIVE_HISTORY' if arguments['require_exact_backup']
                  else 'REPLAYED_STILL_QUARANTINED' if applied
                  else 'REPLAY_BLOCKED_LATEST_HISTORY_UNPROVEN')
        counts = {key: result.pop(key) for key in ('backup_event_count', 'later_event_count')}
        if any(type(value) is not int or not 0 <= value <= 100000 for value in counts.values()):
            raise ValueError('invalid child counts')
        if result != {'status': status,
                      'target_verified_at_preflight': True, 'privacy_replay_applied': applied,
                      'restore_authorized': False, 'service_publish_authorized': False}:
            raise ValueError('invalid child result')
        pipe.send({'status': 'CHILD_VERIFIED', **counts})
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


async def _wait_successful_exit(process, deadline):
    while process.is_alive() and time.monotonic() < deadline:
        await asyncio.sleep(.1)
    if process.is_alive():
        raise LiveFencedReplayError('Isolated preflight did not exit before its deadline')
    process.join(0)
    if process.exitcode != 0:
        raise LiveFencedReplayError('Isolated preflight did not exit cleanly')


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
                                   container_id, image_id, token, lock_dir, timeout_seconds=600,
                                   require_exact_backup=False, legacy_source=False, apply_legacy_public_url=None):
    """Keep the authenticated source fence while a spawned child checks target.

    `witness_factory` must be a spawn-picklable callable that creates fresh
    read-only clients in the child. Credentials are never placed on argv.
    """
    if (not callable(witness_factory) or not isinstance(container_id, str)
            or not re.fullmatch('[0-9a-f]{64}', container_id)
            or not isinstance(image_id, str) or not re.fullmatch('sha256:[0-9a-f]{64}', image_id)
            or not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token)
            or type(timeout_seconds) is not int or not 30 <= timeout_seconds <= 900
            or type(require_exact_backup) is not bool or type(legacy_source) is not bool
            or (apply_legacy_public_url is not None and (
                require_exact_backup or not isinstance(apply_legacy_public_url, str)
                or not re.fullmatch(r'https://[A-Za-z0-9.:-]+(?:/[A-Za-z0-9._/-]+)?', apply_legacy_public_url)))):
        raise LiveFencedReplayError('Live source preflight configuration is invalid')
    deadline = time.monotonic() + timeout_seconds
    parent = None
    child = None
    process = None
    group_ready = False
    completed = False
    try:
        async with asyncio.timeout(timeout_seconds):
            async with hold_live_privacy_boundary(db, journal, expected_source_identity=expected_source_identity,
                                                  legacy_source=legacy_source) as boundary:
                try:
                    source = await boundary.verify()
                    parent, child = multiprocessing.get_context('spawn').Pipe(duplex=False)
                    arguments = {'container_id': container_id, 'image_id': image_id, 'token': token,
                                 'lock_dir': Path(lock_dir), 'timeout_seconds': timeout_seconds,
                                 'live_journal_binding': source['journal_binding'],
                                 'require_exact_backup': require_exact_backup,
                                 'apply_legacy_public_url': apply_legacy_public_url}
                    process = multiprocessing.get_context('spawn').Process(target=_child,
                        args=(child, witness_factory, arguments))
                    process.start()
                    child.close()
                    first = await _wait_message(parent, process, deadline)
                    if first != {'status': 'CHILD_READY'}:
                        raise LiveFencedReplayError('Isolated preflight did not start safely')
                    group_ready = True
                    result = await _wait_message(parent, process, deadline)
                    if (not isinstance(result, dict)
                            or set(result) != {'status', 'backup_event_count', 'later_event_count'}
                            or result['status'] != 'CHILD_VERIFIED'
                            or any(type(result[key]) is not int or not 0 <= result[key] <= 100000
                                   for key in ('backup_event_count', 'later_event_count'))
                            or result['backup_event_count'] + result['later_event_count'] != source['journal_binding'][0]
                            or (require_exact_backup and result['later_event_count'] != 0)):
                        raise LiveFencedReplayError('Isolated preflight failed')
                    await _wait_successful_exit(process, deadline)
                    await boundary.verify()
                finally:
                    # The source transaction/fence remains open until the child
                    # has stopped, including under repeated cancellation.
                    await _stop_child_even_if_cancelled(process, group_ready)
        completed = True
        return {'status': ('LIVE_SOURCE_FENCED_BACKUP_ALREADY_CURRENT' if require_exact_backup
                           else 'LIVE_SOURCE_FENCED_REPLAYED_QUARANTINED' if apply_legacy_public_url is not None
                           else 'LIVE_SOURCE_FENCED_REPLAY_BLOCKED'),
                'writer_coverage_verified': False, 'latest_head_verified': False,
                'privacy_replay_applied': apply_legacy_public_url is not None, 'restore_authorized': False,
                'later_event_count': result['later_event_count'], 'backup_event_count': result['backup_event_count']}
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
