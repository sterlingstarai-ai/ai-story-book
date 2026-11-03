"""Pinned proxy drain primitive for a future production cutover adapter.

Direct local/network writers require a real admission fence supplied by the
caller; a snapshot of zero connections is not a fence. No production fence or
Docker adapter is provided here, and this module must not be used as one.
"""
from __future__ import annotations

import time

from provider_cutover_journal import run_journaled


class DrainError(RuntimeError):
    pass


def _drain(*, directory, transaction, nginx_id, inspect, disable_restart, graceful_quit,
           direct_writer_fence, timeout=120, clock=time.monotonic, sleep=time.sleep):
    """Gracefully stop the pinned proxy only after a real direct-writer fence.

    `inspect` must independently pin the exact ID, image, mounted nginx config,
    and network. A timeout or failed verification leaves durable mutation intent.
    The caller owns the shared cutover lock. There is no automatic reopen.
    """
    if direct_writer_fence() is not True:
        raise DrainError('Direct API writers are not fenced')

    def state():
        item = inspect(nginx_id)
        if not isinstance(item, dict) or item.get('id') != nginx_id or item.get('identity_verified') is not True:
            raise DrainError('Pinned proxy identity differs')
        if type(item.get('running')) is not bool or item.get('restart_policy') not in ('no', 'unless-stopped'):
            raise DrainError('Pinned proxy state is invalid')
        return item

    current = state()
    if current['restart_policy'] != 'no':
        run_journaled(directory, transaction=transaction, action='restart-no', container=nginx_id,
                      execute=lambda: disable_restart(nginx_id),
                      verify=lambda: state()['restart_policy'] == 'no')
    current = state()
    if current['running']:
        def stopped():
            deadline = clock() + timeout
            while clock() < deadline:
                item = state()
                if item['running'] is False and item['restart_policy'] == 'no':
                    return True
                sleep(0.1)
            return False
        run_journaled(directory, transaction=transaction, action='nginx-quit', container=nginx_id,
                      execute=lambda: graceful_quit(nginx_id), verify=stopped)
    if state()['running'] is not False or direct_writer_fence() is not True:
        raise DrainError('Proxy drain or direct-writer fence was lost')


def drain_proxy(*, directory, transaction, nginx_id, inspect, disable_restart, graceful_quit,
                direct_writer_fence, timeout=120, clock=time.monotonic, sleep=time.sleep):
    """Drain nginx and require an independently established direct-writer fence."""
    return _drain(directory=directory, transaction=transaction, nginx_id=nginx_id, inspect=inspect,
                  disable_restart=disable_restart, graceful_quit=graceful_quit,
                  direct_writer_fence=direct_writer_fence, timeout=timeout, clock=clock, sleep=sleep)


def drain_public_proxy(*, directory, transaction, nginx_id, inspect, disable_restart, graceful_quit,
                       timeout=120, clock=time.monotonic, sleep=time.sleep):
    """Drain only nginx; callers must account for direct API admission separately."""
    return _drain(directory=directory, transaction=transaction, nginx_id=nginx_id, inspect=inspect,
                  disable_restart=disable_restart, graceful_quit=graceful_quit,
                  direct_writer_fence=lambda: True, timeout=timeout, clock=clock, sleep=sleep)
