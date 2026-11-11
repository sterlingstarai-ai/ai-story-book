"""Read-only Celery control checks without importing the application or its tasks."""

import json


def worker_control_source(kinds, *, timeout, expected_hostnames=None, target_only=False,
                          process_timeout=None):
    """Return a bounded in-container probe that prints booleans, never task data."""
    if (not isinstance(kinds, tuple) or not kinds or len(set(kinds)) != len(kinds)
            or not set(kinds) <= {'ping', 'active', 'reserved', 'scheduled'}
            or type(timeout) is not int or not 1 <= timeout <= 10
            or type(target_only) is not bool or (target_only and kinds != ('ping',))):
        raise ValueError('Invalid worker control probe')
    if process_timeout is not None and (
            type(process_timeout) is not int or not 1 <= process_timeout <= 120):
        raise ValueError('Invalid worker probe lifetime')
    if expected_hostnames is not None:
        import re

        if (not isinstance(expected_hostnames, tuple) or not 1 <= len(expected_hostnames) <= 2
                or len(set(expected_hostnames)) != len(expected_hostnames)
                or any(not isinstance(host, str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,253}', host) is None
                       for host in expected_hostnames)):
            raise ValueError('Invalid expected worker identities')
    watchdog = ('' if process_timeout is None else
                'import os, signal\n'
                'signal.signal(signal.SIGALRM, lambda *_: os._exit(124))\n'
                f'signal.alarm({process_timeout})\n')
    return watchdog + '''
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
import re
from socket import gethostname
from celery import Celery
from celery.app.control import Control

app = Celery('storybook-readonly-control', broker=os.environ['CELERY_BROKER_URL'])
namespace = os.environ.get('CELERY_REDIS_NAMESPACE', '')
if re.fullmatch(r'[A-Za-z0-9_-]{0,64}', namespace) is None:
    raise RuntimeError('Invalid worker namespace')
if namespace:
    app.conf.broker_transport_options = {'global_keyprefix': namespace + ':broker:'}
kinds = KINDS
hosts = HOSTS
if hosts is None:
    hosts = [gethostname()]
controls = {kind: Control(app=app) for kind in kinds}

def check(kind):
    expected = {f'celery@{host}': {'ok': 'pong'} if kind == 'ping' else [] for host in hosts}
    # Health can finish on this exact worker's reply. Quiescence must still
    # collect the complete broadcast window and reject unexpected responders.
    options = {'destination': list(expected), 'limit': len(expected)} if TARGET_ONLY else {}
    with app.connection_for_read() as connection:
        replies = controls[kind].broadcast(kind, connection=connection, reply=True, timeout=TIMEOUT, **options)
    if type(replies) is not list or len(replies) != len(expected):
        return False
    observed = {}
    for reply in replies:
        if type(reply) is not dict or len(reply) != 1 or observed.keys() & reply.keys():
            return False
        observed.update(reply)
    return observed == expected

with closing(app), ThreadPoolExecutor(max_workers=len(kinds)) as pool:
    print(json.dumps(dict(zip(kinds, pool.map(check, kinds), strict=True))))
'''.replace('KINDS', json.dumps(kinds)).replace('TIMEOUT', str(timeout)).replace(
        'HOSTS', repr(expected_hostnames)).replace('TARGET_ONLY', repr(target_only))
