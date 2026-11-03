"""Read-only worker/DB/Redis drain check for the pinned pilot deployment.

Run in the pinned worker before it stops or the verified portless equivalent
probe afterwards. Only fixed counts are inspected; no customer rows or secrets
are printed. A caller still needs to exclude other admission paths/writers.
"""
from __future__ import annotations

import contextlib
import io
import socket
import sys
from urllib.parse import urlsplit


class QueueProbeError(RuntimeError):
    pass


# Celery broadcast inspection collects replies for the entire timeout even if
# the expected worker answers immediately. Eight broadcasts run in worker mode;
# 3 seconds each leaves time for DB/Redis checks inside the caller's 60-second
# subprocess limit. Missing or late workers remain a failed, not an empty, check.
INSPECT_TIMEOUT_SECONDS = 3


def _worker_empty(inspect, expected_worker):
    workers = None
    for method in ('active_queues', 'active', 'reserved', 'scheduled'):
        reply = getattr(inspect, method)()
        if not isinstance(reply, dict) or set(reply) != {expected_worker}:
            raise QueueProbeError('Worker inspection is unavailable')
        names = frozenset(reply)
        if workers is not None and names != workers:
            raise QueueProbeError('Worker identity changed during inspection')
        workers = names
        value = next(iter(reply.values()))
        if not isinstance(value, list):
            raise QueueProbeError('Worker state is invalid')
        if method == 'active_queues':
            if len(value) != 1 or not isinstance(value[0], dict) or value[0].get('name') != 'celery':
                raise QueueProbeError('Unexpected worker queues')
        elif value:
            raise QueueProbeError('Worker has pending tasks')


def _database_empty(engine, text):
    queries = (
        "SELECT count(*) FROM public.jobs WHERE status IS NULL OR status NOT IN ('done','failed','cancelled')",
        "SELECT count(*) FROM public.storage_purge_tasks WHERE status NOT IN ('done','cancelled')",
        'SELECT count(*) FROM public.privacy_journal_outbox WHERE published_at IS NULL',
    )
    with engine.connect() as connection:
        connection.execute(text('SET TRANSACTION READ ONLY'))
        for query in queries:
            value = connection.execute(text(query)).scalar_one()
            if type(value) is not int or value != 0:
                raise QueueProbeError('Database work remains')


def _broker_empty(app, settings):
    parsed = urlsplit(settings.celery_broker_url)
    if (parsed.scheme != 'redis' or parsed.hostname != 'asb-pilot-redis' or parsed.path != '/1'
            or settings.celery_redis_namespace != '' or app.conf.beat_schedule):
        raise QueueProbeError('Unexpected broker configuration')
    with app.connection_for_read() as connection:
        channel = connection.channel()
        try:
            queued = channel._size('celery')
            unacked = channel.client.hlen(channel.unacked_key)
            index = channel.client.zcard(channel.unacked_index_key)
            if any(type(value) is not int or value != 0 for value in (queued, unacked, index)):
                raise QueueProbeError('Broker has queued or unacknowledged tasks')
        finally:
            channel.close()


def inspect_drain(*, worker_expected):
    from sqlalchemy import text
    from src.core.config import settings
    from src.core.database import engine
    from src.worker import celery_app

    if type(worker_expected) is not bool:
        raise QueueProbeError('Worker mode is invalid')
    if worker_expected:
        _worker_empty(celery_app.control.inspect(timeout=INSPECT_TIMEOUT_SECONDS), 'celery@' + socket.gethostname())
    _database_empty(engine, text)
    _broker_empty(celery_app, settings)
    if worker_expected:
        _worker_empty(celery_app.control.inspect(timeout=INSPECT_TIMEOUT_SECONDS), 'celery@' + socket.gethostname())
    return True


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('--worker', '--broker-only'):
        raise SystemExit('Explicit probe mode required')
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            success = inspect_drain(worker_expected=sys.argv[1] == '--worker')
        except Exception:
            success = False
    sys.stdout.write('QUEUE_DRAIN_OK\n' if success else 'QUEUE_DRAIN_FAILED\n')
    raise SystemExit(0 if success else 1)


if __name__ == '__main__':
    main()
