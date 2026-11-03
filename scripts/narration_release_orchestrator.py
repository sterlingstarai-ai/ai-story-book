"""Fail-closed choreography for an additive narration release.

This is an orchestration primitive, NOT a runnable deploy command. A future
operator adapter must implement and independently verify each operation below.
In particular it must stop external admission and all writers, hold the
appropriate source fence, and install/test the boot recovery controls first.
No production adapter is provided here.
"""
import os
from pathlib import Path

import narration_deploy_safety as safety
from narration_container_controls import NarrationContainerControls
from backup_service_guard import BackupServiceGuard, assert_no_narration_recovery
from narration_deploy_safety import (
    PRIVACY_RECOVERY_MARKER,
    NarrationSafetyError,
    _assert_shared_paths,
    _private_directory,
    _validate_ids,
    _write_marker,
    quarantine,
)


class NarrationReleaseError(RuntimeError):
    pass


# No operator flag can lift this gate. Remove it only after independent host
# reboot testing, external write fencing and privacy/media restore evidence
# have been implemented and reviewed. Local isolated fixture paths still work.
PRODUCTION_MARKER = Path('/var/lib/ai-story-book/narration-deploy/narration-recovery.json')


def _must_be_absent(path):
    try:
        path.lstat()
    except FileNotFoundError:
        return
    except OSError:
        raise NarrationReleaseError('Recovery state cannot be verified') from None
    raise NarrationReleaseError('Another recovery is pending')


def _require_true(value, label):
    if value is not True:
        raise NarrationReleaseError(label)


def _require_restart_disabled(runtime, ids):
    """Verify the daemon's actual state, not just an adapter's assertion."""
    for slot, identifier in ids.items():
        try:
            item = runtime.inspect(identifier)
        except Exception:
            raise NarrationReleaseError('Restart policy cannot be verified') from None
        if (item.get('id') != identifier or item.get('name') not in safety._SLOTS[slot]
                or item.get('restart_policy') != 'no'):
            raise NarrationReleaseError('Restart policy is unsafe')


def _require_old_stopped(runtime, ids):
    for slot in ('old_api', 'old_worker'):
        try:
            item = runtime.inspect(ids[slot])
        except Exception:
            raise NarrationReleaseError('Old container state cannot be verified') from None
        if (item.get('id') != ids[slot] or item.get('name') not in safety._SLOTS[slot]
                or item.get('running') is not False):
            raise NarrationReleaseError('Old container is still running or unverified')


def release(*, state_dir, backup_state_dir, identities, image_ids, runtime, operations):
    """Execute a trusted adapter under the backup lock; retain marker on error.

    Adapter responsibilities are intentionally explicit: `preflight` must
    prove DB and image identity, IAM, source fences and boot unit installation;
    `stop_and_drain` must remove admission, stop API and drain worker;
    `disable_restart` must disarm all four exact containers before migration;
    `backup_and_restore_verify` must take and restore-check a fresh backup while
    writers are fenced; `migrate` must check the expected source and target
    revisions; `start_isolated` must not admit outside traffic; `publish` must
    only happen after readiness, and `verify_published` must recheck readiness
    and worker health. All checks return exactly True only after verification.
    """
    path = _private_directory(state_dir)
    backup_path = _private_directory(backup_state_dir)
    _assert_shared_paths(path, backup_path)
    if path / 'narration-recovery.json' == PRODUCTION_MARKER:
        raise NarrationReleaseError('Production narration release is blocked pending reboot and recovery verification')
    ids = _validate_ids(identities)
    guard = BackupServiceGuard(backup_path, runtime)
    fd = guard._locked()
    armed = False
    try:
        assert_no_narration_recovery()
        for marker in (path / 'narration-recovery.json', backup_path / 'restart-required.json',
                       PRIVACY_RECOVERY_MARKER):
            _must_be_absent(marker)
        # Never rely on the caller's success boolean for image identity.
        NarrationContainerControls(runtime).verify_pinned_images(ids, image_ids)
        _require_true(operations.preflight(ids), 'Preflight failed')
        # arm while holding the same backup lock used by legacy recoveries.
        _write_marker(path, ids)
        armed = True
        _require_true(operations.stop_and_drain(ids), 'Drain failed')
        _require_old_stopped(runtime, ids)
        _require_true(operations.disable_restart(ids), 'Restart policy is unsafe')
        _require_restart_disabled(runtime, ids)
        _require_true(operations.backup_and_restore_verify(), 'Backup verification failed')
        _require_true(operations.migrate(), 'Migration verification failed')
        _require_true(operations.start_isolated(ids), 'Isolated start failed')
        _require_true(operations.verify_isolated(), 'Isolated readiness failed')
        _require_true(operations.publish(), 'Publication failed')
        _require_true(operations.verify_published(), 'Published readiness failed')
        _require_restart_disabled(runtime, ids)
        # All containers remain restart=no while the recovery marker exists.
        # Docker may restart containers before the recovery unit on a host
        # reboot, so enabling restart with an armed marker defeats quarantine.
        (path / 'narration-recovery.json').unlink()
        dir_fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        # A crash between marker removal and this step may leave the new
        # services stopped after reboot; it cannot revive the older images.
        # If this operation fails in-process, re-arm and quarantine below.
        _require_true(operations.enable_new_restart(ids), 'Restart policy verification failed')
        armed = False
        return {'status': 'RELEASE_SEQUENCE_COMPLETED', 'restore_authorized': False}
    except BaseException:
        if armed:
            try:
                # An error after unlink but before directory fsync leaves the
                # marker's persistence ambiguous. Recreate it before trying
                # quarantine so boot recovery is not silently disarmed.
                marker = path / 'narration-recovery.json'
                if not marker.exists() and not marker.is_symlink():
                    _write_marker(path, ids)
                quarantine(path, runtime)
            except (NarrationSafetyError, OSError):
                # Recovery requires manual intervention if the filesystem or
                # container runtime cannot persist or enforce this fence.
                pass
        raise
    finally:
        os.close(fd)
