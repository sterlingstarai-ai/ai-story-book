"""Docker restart controls for a future narration release adapter.

This component does not drain traffic, take a backup, migrate data, install
boot recovery or deploy an image. Those independent gates remain mandatory.
"""
import json
import re

import narration_deploy_safety as safety

_ACTIVE_NAMES = {'old_api': 'asb-pilot-api', 'old_worker': 'asb-pilot-worker'}


class ContainerControlError(RuntimeError):
    pass


class NarrationContainerControls:
    def __init__(self, runtime):
        self.runtime = runtime

    def _inspect(self, slot, identifier):
        try:
            item = self.runtime.inspect(identifier)
            if (item.get('id') != identifier or item.get('name') not in safety._SLOTS[slot]
                    or type(item.get('running')) is not bool):
                raise ValueError('identity mismatch')
            return item
        except Exception:
            raise ContainerControlError('Container identity cannot be confirmed') from None

    def verify_pinned_images(self, identities, image_ids):
        """Read the running containers' image IDs without modifying them."""
        ids = safety._validate_ids(identities)
        if (not isinstance(image_ids, dict) or set(image_ids) != set(ids)
                or any(not isinstance(value, str) or not re.fullmatch('sha256:[0-9a-f]{64}', value)
                       for value in image_ids.values())):
            raise ContainerControlError('Pinned image identities are invalid')
        for slot, identifier in ids.items():
            if self._inspect(slot, identifier).get('image_id') != image_ids[slot]:
                raise ContainerControlError('Container image differs from the reviewed image')
        return True

    def disable_restart(self, identities):
        ids = safety._validate_ids(identities)
        # Inspect every target before changing any target; never operate on an
        # unverified identifier. The release layer quarantines upon any error.
        for slot, identifier in ids.items():
            self._inspect(slot, identifier)
        for identifier in ids.values():
            self.runtime.disable_restart(identifier)
        for slot, identifier in ids.items():
            if self._inspect(slot, identifier).get('restart_policy') != 'no':
                raise ContainerControlError('Restart disable did not take effect')
        return True

    def stop_and_drain(self, identities):
        """Stop the old API, confirm an idle single worker, then stop it.

        This prevents API admission through the recorded container only. It
        does not prove external database or object-storage writes are blocked.
        """
        ids = safety._validate_ids(identities)
        api = self._inspect('old_api', ids['old_api'])
        worker = self._inspect('old_worker', ids['old_worker'])
        if api['name'] != _ACTIVE_NAMES['old_api'] or worker['name'] != _ACTIVE_NAMES['old_worker']:
            raise ContainerControlError('Active pilot names do not match')
        if not api['running'] or not worker['running']:
            raise ContainerControlError('Pilot containers are not both running')
        self.runtime.stop(ids['old_api'])
        if self._inspect('old_api', ids['old_api'])['running']:
            raise ContainerControlError('API admission did not stop')
        workers = None
        for kind in ('active', 'reserved', 'scheduled'):
            try:
                raw = self.runtime._run('exec', ids['old_worker'], 'celery', '-A',
                                        'src.worker', 'inspect', kind, '--timeout', '10', '--json')
                value = json.loads(raw)
                if (not isinstance(value, dict) or len(value) != 1
                        or any(not isinstance(tasks, list) or tasks for tasks in value.values())):
                    raise ValueError('worker is not idle')
                current = frozenset(value)
                if workers is not None and current != workers:
                    raise ValueError('worker identity changed')
                workers = current
            except Exception:
                raise ContainerControlError('Worker drain cannot be verified') from None
        self.runtime.stop(ids['old_worker'])
        if self._inspect('old_worker', ids['old_worker'])['running']:
            raise ContainerControlError('Worker did not stop')
        return True

    def enable_new_restart(self, identities):
        ids = safety._validate_ids(identities)
        # Old images cannot run against newly generated narration data. A
        # confirmed healthy publication and durable marker removal are the
        # responsibility of the enclosing release orchestrator.
        for slot, identifier in ids.items():
            item = self._inspect(slot, identifier)
            should_run = slot.startswith('new_')
            if item.get('restart_policy') != 'no' or item['running'] is not should_run:
                raise ContainerControlError('Container state is unsafe for restart enablement')
        for slot in ('new_api', 'new_worker'):
            self.runtime.enable_restart(ids[slot])
        for slot, identifier in ids.items():
            item = self._inspect(slot, identifier)
            wanted = 'unless-stopped' if slot.startswith('new_') else 'no'
            if (item.get('restart_policy') != wanted
                    or item['running'] is not slot.startswith('new_')):
                raise ContainerControlError('Restart enablement could not be verified')
        return True
