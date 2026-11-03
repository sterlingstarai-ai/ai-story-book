"""Systemd reload verification primitives for a future guard installer.

These functions do not install units or provide a production activation entry
point. A caller must persist the pre-change baseline in its durable recovery
record, hold the shared locks and verify all pinned file identities first.
"""
from __future__ import annotations

import re
import subprocess

from provider_cutover_production_guards import verify_installed_guard_files, verify_loaded_units


UNITS = ('asb-provider-rotation-quarantine.service', 'asb-backup-recover.service',
         'asb-privacy-deploy-recover.service')
PROPERTIES = ('Id', 'LoadState', 'UnitFileState', 'FragmentPath', 'DropInPaths', 'NeedDaemonReload',
              'KillMode', 'Requires', 'After', 'Wants', 'ExecStart')
_LIST_FIELDS = frozenset({'DropInPaths', 'Requires', 'After', 'Wants'})


class SystemdActivationError(RuntimeError):
    pass


def show(unit, *, runner=subprocess.run):
    if unit not in UNITS:
        raise SystemdActivationError('Unexpected systemd unit')
    try:
        result = runner(['/usr/bin/systemctl', 'show', unit, *['--property=' + p for p in PROPERTIES]],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, timeout=20,
                        env={'PATH': '/usr/bin:/bin', 'HOME': '/root'})
        if len(result.stdout) > 65536 or result.returncode not in (0, 1):
            raise ValueError()
        data = {}
        for line in result.stdout.decode('utf-8').splitlines():
            key, value = line.split('=', 1)
            if key not in PROPERTIES or key in data:
                raise ValueError()
            data[key] = value
        if (data.get('Id') != unit or data.get('LoadState') not in ('loaded', 'not-found')
                or (data.get('LoadState') == 'loaded' and set(data) != set(PROPERTIES))
                or (result.returncode != 0 and data.get('LoadState') != 'not-found')):
            raise ValueError()
        return data
    except Exception:
        raise SystemdActivationError('Systemd unit state is unavailable') from None


def _normalized(data):
    if not isinstance(data, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                         for key, value in data.items()):
        raise SystemdActivationError('Systemd baseline is invalid')
    result = {}
    for key in PROPERTIES:
        value = data.get(key, '')
        if key == 'ExecStart':
            value = re.findall(r'argv\[\]=([^;}]+)', value)
        elif key in _LIST_FIELDS:
            value = sorted(value.split())
        result[key] = value
    return result


def capture_baseline(*, query=show):
    """Capture only fixed unit properties; no environment or secrets."""
    return {unit: _normalized(query(unit)) for unit in UNITS}


def _reload(*, runner=subprocess.run):
    try:
        result = runner(['/usr/bin/systemctl', 'daemon-reload'], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, check=False, timeout=30,
                        env={'PATH': '/usr/bin:/bin', 'HOME': '/root'})
        if result.returncode != 0:
            raise ValueError()
    except Exception:
        raise SystemdActivationError('Systemd reload was not confirmed') from None


def reload_new(*, runner=subprocess.run, query=show):
    """Reload and validate pinned installed files and loaded unit behavior."""
    _reload(runner=runner)
    try:
        verify_installed_guard_files()
        verify_loaded_units(query)
        return True
    except Exception:
        raise SystemdActivationError('New systemd guard verification failed') from None


def reload_old(baseline, *, runner=subprocess.run, query=show):
    """Reload and compare every fixed property against the pre-change baseline."""
    if not isinstance(baseline, dict) or set(baseline) != set(UNITS):
        raise SystemdActivationError('Systemd baseline is invalid')
    _reload(runner=runner)
    for unit in UNITS:
        current = _normalized(query(unit))
        if (current != baseline[unit]
                or (current['LoadState'] == 'loaded' and current['NeedDaemonReload'] != 'no')):
            raise SystemdActivationError('Restored systemd baseline differs')
    return True
