"""Cutover ordering with a portless equivalent provider probe.

This state machine uses a supplied runtime. The fixture entry point cannot
perform a production cutover; a production caller must use the separately
pinned adapter and exact production paths. Direct host requests may reach the
new API once it starts, before nginx and the new worker have reopened.
"""
from pathlib import Path
import os

from provider_cutover import (
    CutoverError, _PRE_NAMES, _POST_NAMES, _PRODUCTION_STATE, _absent, _assert_slot,
    _directory, _ids, _images, _lock, _preflight, _sync_dir, _write_marker,
)


def _run(*, state_dir, backup_dir, ids, images, other_markers, runtime, production=False):
    state, backup = _directory(state_dir, allow_production=production), _directory(backup_dir)
    if production and (state != _PRODUCTION_STATE or backup != Path('/var/lib/ai-story-book/backup-state')):
        raise CutoverError('Production paths differ')
    ids, images = _ids(ids), _images(images)
    if not isinstance(other_markers, (list, tuple)) or any(not isinstance(p, Path) or not p.is_absolute() for p in other_markers):
        raise CutoverError('Recovery paths are invalid')
    lock = _lock(backup / 'backup.lock')
    recovery_lock = None
    marked = False
    try:
        recovery_lock = _lock(state / 'recovery.lock')
        for marker in (state / 'recovery.json', *other_markers):
            _absent(marker)
        _preflight(runtime, ids, images, lock, old_restart='unless-stopped')
        runtime.prepare_equivalent_probe(ids['new_api'], lock_fd=lock)
        runtime.assert_no_unresolved_daemon_operations()
        runtime.drain_ingress()  # nginx only; direct host requests may continue
        runtime.assert_ingress_drained()
        for slot in ('old_api', 'old_worker'):
            runtime.disable_restart(ids[slot])
            _assert_slot(runtime, ids[slot], name=_PRE_NAMES[slot], image=images[slot], running=True, restart='no')
        _preflight(runtime, ids, images, lock, old_restart='no')
        runtime.assert_no_unresolved_daemon_operations()
        _write_marker(state, ids)
        marked = True
        # Production stop must signal TERM only and wait: never escalate to KILL.
        runtime.stop(ids['old_api'])
        _assert_slot(runtime, ids['old_api'], name=_PRE_NAMES['old_api'], image=images['old_api'],
                     running=False, restart='no')
        # No API admission remains; let accepted jobs and privacy work finish.
        runtime.drain_worker_and_queues()
        runtime.stop(ids['old_worker'])
        _assert_slot(runtime, ids['old_worker'], name=_PRE_NAMES['old_worker'], image=images['old_worker'],
                     running=False, restart='no')
        # The equivalent probe checks DB/broker again after worker shutdown,
        # before making any billable provider request.
        runtime.probe_equivalent_provider(ids['new_api'])
        runtime.assert_no_unresolved_daemon_operations()
        for slot in ('old_api', 'old_worker', 'new_api', 'new_worker'):
            runtime.rename(ids[slot], _POST_NAMES[slot])
            _assert_slot(runtime, ids[slot], name=_POST_NAMES[slot], image=images[slot], running=False, restart='no')
        runtime.start(ids['new_api'])
        _assert_slot(runtime, ids['new_api'], name=_POST_NAMES['new_api'], image=images['new_api'],
                     running=True, restart='no')
        # From this point a local process or network peer can address the API.
        runtime.assert_api_ready(ids['new_api'])
        runtime.start(ids['new_worker'])
        _assert_slot(runtime, ids['new_worker'], name=_POST_NAMES['new_worker'], image=images['new_worker'],
                     running=True, restart='no')
        runtime.assert_worker_healthy(ids['new_worker'])
        runtime.assert_no_unresolved_daemon_operations()
        for slot in ('new_api', 'new_worker'):
            runtime.enable_restart(ids[slot])
            _assert_slot(runtime, ids[slot], name=_POST_NAMES[slot], image=images[slot],
                         running=True, restart='unless-stopped')
        runtime.reload_proxy()
        runtime.open_ingress()
        runtime.assert_live_candidate(ids['new_api'], ids['new_worker'])
        runtime.assert_no_unresolved_daemon_operations()
        for slot in ('old_api', 'old_worker'):
            _assert_slot(runtime, ids[slot], name=_POST_NAMES[slot], image=images[slot], running=False, restart='no')
        for slot in ('new_api', 'new_worker'):
            _assert_slot(runtime, ids[slot], name=_POST_NAMES[slot], image=images[slot],
                         running=True, restart='unless-stopped')
        runtime.complete_candidate_owner()
        (state / 'recovery.json').unlink()
        _sync_dir(state)
        return {'status': 'PRODUCTION_CUTOVER_PASSED' if production else 'FIXTURE_DRAINED_CUTOVER_PASSED',
                'production_authorized': production}
    except BaseException:
        if marked:
            try:
                # Public or direct clients may already have submitted work.
                # Do not stop a worker until accepted work is drained.
                runtime.preserve_accepted_work_and_quarantine(ids)
            except Exception:
                pass  # Marker remains; recovery is explicitly indeterminate.
        raise CutoverError('Cutover failed; durable recovery may be required') from None
    finally:
        if recovery_lock is not None:
            os.close(recovery_lock)
        os.close(lock)


def run_fixture(*, state_dir, backup_dir, ids, images, other_markers, runtime):
    return _run(state_dir=state_dir, backup_dir=backup_dir, ids=ids, images=images,
                other_markers=other_markers, runtime=runtime)
