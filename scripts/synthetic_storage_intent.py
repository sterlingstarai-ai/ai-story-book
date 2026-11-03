"""Reusable durable-intent experiment for the disposable local fixture only.

This is not connected to the application, storage clients, or scheduler and
never authorizes a production backup. The caller owns the supplied synthetic
storage callback. A pending record must be reconciled manually, never cleared
just because an operation timed out or a process restarted.
"""
import os
import re
from urllib.parse import urlsplit

import psycopg

from run_restore_replay_fixture import require_local_fixture

LOCK = 0x4153425746495831  # Isolated fixture namespace; not a production fence.
_OPERATION_ID = re.compile(r'^[a-z0-9_-]{1,64}$')


def _connection_params():
    require_local_fixture()
    url = urlsplit(os.environ['DATABASE_URL'])
    if not url.port:
        raise RuntimeError('Explicit local fixture port is required')
    return {'host': url.hostname, 'port': url.port, 'user': url.username,
            'password': url.password, 'dbname': url.path.lstrip('/'), 'sslmode': 'disable'}


def run_durable_mutation(operation_id, mutation, *, on_locked=None, before_io=None):
    """Commit an intent on the lock-owning session before synthetic S3 I/O.

    Any error, cancellation or ambiguous database acknowledgement prevents
    completion from being recorded; a repeated ID never runs I/O again. This
    cannot fence unrelated writers or prove an external store's durability.
    """
    if (not isinstance(operation_id, str) or not _OPERATION_ID.fullmatch(operation_id)
            or not callable(mutation) or (on_locked is not None and not callable(on_locked))
            or (before_io is not None and not callable(before_io))):
        raise RuntimeError('Invalid synthetic mutation')
    with psycopg.connect(**_connection_params(), autocommit=True) as connection:
        connection.execute("SET lock_timeout = '300ms'")
        connection.execute('SELECT pg_advisory_lock_shared(%s)', (LOCK,))
        if on_locked is not None:
            on_locked(connection)
        created = connection.execute("""
            INSERT INTO public.asb_storage_intent_fixture (operation_id, status)
            VALUES (%s, 'pending') ON CONFLICT DO NOTHING RETURNING operation_id
        """, (operation_id,)).fetchone()
        if created is None:
            return 'reconciliation_required'
        if before_io is not None:
            before_io()
        mutation()
        completed = connection.execute("""
            UPDATE public.asb_storage_intent_fixture SET status='done'
            WHERE operation_id=%s AND status='pending' RETURNING operation_id
        """, (operation_id,)).fetchone()
        if completed is None:
            raise RuntimeError('Synthetic intent completion could not be verified')
        return 'done'
