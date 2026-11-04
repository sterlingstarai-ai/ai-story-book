"""Order the release steps and enforce the adapter's production boundary.

The adapter must stop admission and writers, keep the source fenced through
backup and isolated restore, and verify the installed boot recovery controls.
"""
import os
from pathlib import Path
import syslog
import traceback

import narration_deploy_safety as safety
from narration_container_controls import NarrationContainerControls
from backup_service_guard import BackupServiceGuard, assert_no_narration_recovery
from narration_deploy_safety import (
    PRIVACY_RECOVERY_MARKER,
    NarrationSafetyError,
    WorkerDrainUnverified,
    _assert_shared_paths,
    _private_directory,
    _validate_ids,
    _write_marker,
    quarantine,
)


class NarrationReleaseError(RuntimeError):
    pass


# Production accepts only the pinned storage detach and post-detach
# narration modes. Neither mode promotes a restored database.
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


def _require_production_detach(operations, runtime, ids, images):
    from narration_pilot_adapter import NarrationPilotAdapter

    if (type(operations) is not NarrationPilotAdapter or operations.runtime is not runtime
            or operations.storage_only is not True or operations.expected_gcs_media is not True
            or operations.expected_narration_only is not False or operations.offhost_restore is None
            or operations.identities != ids or operations.image_ids != images
            or any(images.get('old_' + role) != images.get('new_' + role) for role in ('api', 'worker'))):
        raise NarrationReleaseError('Production narration release is blocked; only a pinned storage detach may run')


def _require_production_narration(operations, runtime, ids, images):
    from narration_pilot_adapter import NarrationPilotAdapter

    if (type(operations) is not NarrationPilotAdapter or operations.runtime is not runtime
            or operations.gcs_narration is not True or operations.storage_only is not False
            or operations.expected_gcs_media is not True or operations.expected_narration_only is not True
            or operations.offhost_restore is None or operations.identities != ids or operations.image_ids != images
            or any(images.get('old_' + role) == images.get('new_' + role) for role in ('api', 'worker'))):
        raise NarrationReleaseError('Production narration requires the pinned post-detach adapter')


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
    recovery_marker = path / 'narration-recovery.json'
    ids = _validate_ids(identities)
    production = recovery_marker == PRODUCTION_MARKER
    production_narration = production and getattr(operations, 'gcs_narration', False) is True
    production_detach = production and not production_narration
    if production_detach:
        _require_production_detach(operations, runtime, ids, image_ids)
    if production_narration:
        _require_production_narration(operations, runtime, ids, image_ids)
    guard = BackupServiceGuard(backup_path, runtime)
    fd = guard._locked()
    armed = False
    publication_recorded = False
    publish_attempted = False
    proxy = None

    def phase(name):
        if production_detach:
            syslog.syslog(syslog.LOG_NOTICE, 'asb-media-detach phase=' + name)
        if production_narration:
            syslog.syslog(syslog.LOG_NOTICE, 'asb-narration-release phase=' + name)

    try:
        assert_no_narration_recovery()
        for marker in (recovery_marker, backup_path / 'restart-required.json',
                       PRIVACY_RECOVERY_MARKER):
            _must_be_absent(marker)
        # Never rely on the caller's success boolean for image identity.
        NarrationContainerControls(runtime).verify_pinned_images(ids, image_ids)
        _require_true(operations.preflight(ids), 'Preflight failed')
        phase('preflight_verified')
        # Docker may start containers before systemd can read the marker.
        # Disarm them before persisting a recovery state or stopping admission.
        _require_true(operations.disable_restart(ids), 'Restart policy is unsafe')
        _require_restart_disabled(runtime, ids)
        recovery_proxy = getattr(operations, 'recovery_proxy', None)
        if recovery_proxy is not None:
            proxy = recovery_proxy()
            if proxy is not None:
                proxy = safety._validate_proxy(proxy, ids)
                item = runtime.inspect(proxy['id'])
                if (item.get('id') != proxy['id'] or item.get('name') != 'asb-pilot-nginx'
                        or item.get('image_id') != proxy['image_id'] or item.get('restart_policy') != 'no'):
                    raise NarrationReleaseError('Proxy restart policy is unsafe')
        # arm while holding the same backup lock used by legacy recoveries.
        try:
            _write_marker(path, ids, proxy=proxy)
        except BaseException:
            # The marker can be visible even if directory fsync failed.
            armed = os.path.lexists(recovery_marker)
            raise
        armed = True
        phase('draining')
        _require_true(operations.stop_and_drain(ids), 'Drain failed')
        _require_old_stopped(runtime, ids)
        _require_restart_disabled(runtime, ids)
        if production_narration:
            phase('freezing_storage')
        phase('backup_restore')
        _require_true(operations.backup_and_restore_verify(), 'Backup verification failed')
        _require_true(operations.migrate(), 'Migration verification failed')
        phase('isolated_start')
        _require_true(operations.start_isolated(ids), 'Isolated start failed')
        _require_true(operations.verify_isolated(), 'Isolated readiness failed')
        publish_attempted = True
        phase('publishing')
        _require_true(operations.publish(), 'Publication failed')
        _require_true(operations.verify_published(), 'Published readiness failed')
        _require_restart_disabled(runtime, ids)
        if proxy is not None:
            item = runtime.inspect(proxy['id'])
            if (item.get('id') != proxy['id'] or item.get('name') != 'asb-pilot-nginx'
                    or item.get('image_id') != proxy['image_id'] or item.get('restart_policy') != 'no'):
                raise NarrationReleaseError('Proxy identity or restart policy changed')
            # Persist a distinct record before enabling restarts. Boot
            # recovery may resume only this verified published generation.
            _write_marker(path, ids, proxy=proxy, published_images=image_ids)
            publication_recorded = True
            _require_true(operations.enable_new_restart(ids), 'Restart policy verification failed')
        # Once the published generation has restart policies in place, the
        # recovery record can be removed.
        recovery_marker.unlink()
        dir_fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        if proxy is None:
            _require_true(operations.enable_new_restart(ids), 'Restart policy verification failed')
        armed = False
        phase('published_verified')
        return {'status': 'RELEASE_SEQUENCE_COMPLETED', 'restore_authorized': False}
    except WorkerDrainUnverified:
        # Ingress and the old API have stopped. Keep the armed marker and
        # leave the old worker alive so it can finish previously accepted work.
        phase('worker_drain_unverified')
        raise
    except BaseException as exc:
        location = traceback.extract_tb(exc.__traceback__)[-1]
        phase(f'failed type={type(exc).__name__} location={Path(location.filename).name}:{location.lineno}')
        if armed and not publication_recorded:
            try:
                # An error after unlink but before directory fsync leaves the
                # marker's persistence ambiguous. Recreate it before trying
                # quarantine so boot recovery is not silently disarmed.
                if not os.path.lexists(recovery_marker):
                    _write_marker(path, ids, proxy=proxy)
                quarantine(path, runtime)
                if production_detach and not getattr(operations, '_publication_started', publish_attempted):
                    try:
                        _require_true(operations.resume_original_storage_before_publication(), 'Original storage recovery failed')
                        recovery_marker.unlink()
                        directory = os.open(path, os.O_DIRECTORY | os.O_NOFOLLOW)
                        try:
                            os.fsync(directory)
                        finally:
                            os.close(directory)
                        phase('original_recovered')
                    except Exception as recovery_error:
                        location = traceback.extract_tb(recovery_error.__traceback__)[-1]
                        phase(f'original_recovery_failed type={type(recovery_error).__name__} '
                              f'location={Path(location.filename).name}:{location.lineno}')
                        if not os.path.lexists(recovery_marker):
                            _write_marker(path, ids, proxy=proxy)
                        quarantine(path, runtime)
            except (NarrationSafetyError, OSError):
                # Recovery requires manual intervention if the filesystem or
                # container runtime cannot persist or enforce this fence.
                pass
        raise
    finally:
        os.close(fd)
