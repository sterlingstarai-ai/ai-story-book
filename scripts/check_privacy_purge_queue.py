"""Read-only, secret-free signal for stuck privacy erasure tasks.

The selected database must match both live writers. This is not evidence of
physical erasure or of privacy work never recorded in the queue. This command
is disabled unless the operator explicitly supplies --execute and inputs.
"""
import argparse
import asyncio
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

API = Path(__file__).resolve().parents[1] / 'apps' / 'api'


def private_file(path, *, max_bytes):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError('A private owner-only input is required')
        data = os.read(fd, max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError('Private input is too large')
        return data
    finally:
        os.close(fd)


class DockerInspector:
    """Only the read-only inspection used for source binding."""
    def _run(self, command, *, timeout):
        try:
            return subprocess.run(['docker', *command], check=True, capture_output=True,
                                  text=True, timeout=timeout).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            raise ValueError('Writer inspection unavailable') from None

def source_identity(raw):
    if not isinstance(raw, str) or not raw:
        raise ValueError('Database source unavailable')
    if raw.startswith('postgres://'):
        raw = 'postgresql://' + raw[len('postgres://'):]
    url = make_url(raw)
    if (url.get_backend_name() != 'postgresql' or not url.host or not url.database
            or any(key.lower() in {'host', 'hostaddr', 'port', 'dbname', 'service', 'options'} for key in url.query)
            or ',' in url.host or '/' in url.host):
        raise ValueError('Database source identity is invalid')
    return url.host.lower(), url.port or 5432, url.database


def check_live_source_binding(runtime, expected_url):
    expected = source_identity(expected_url)
    for container in ('asb-pilot-api', 'asb-pilot-worker'):
        # A guarded backup stops both containers without changing their DB
        # configuration. Availability is monitored elsewhere; this read-only
        # queue check must not report a false failure during that stop.
        values = json.loads(runtime._run(['inspect', '--format', '{{json .Config.Env}}', container], timeout=15))
        if not isinstance(values, list):
            raise ValueError('Writer source unavailable')
        db_urls = [value.partition('=')[2] for value in values
                   if isinstance(value, str) and value.startswith('DATABASE_URL=')]
        if len(db_urls) != 1 or source_identity(db_urls[0]) != expected:
            raise ValueError('Writer source differs')


async def check(args):
    if not args.env_file or not args.ca_file:
        raise ValueError('Private settings required')
    settings = dotenv_values(stream=io.StringIO(private_file(args.env_file, max_bytes=1024 * 1024).decode()),
                             interpolate=False)
    raw = settings.get('DATABASE_URL') or ''
    source_identity(raw)
    if settings.get('DATABASE_SSL_MODE') != 'verify-full':
        raise ValueError('Verified database TLS required')
    ca = args.ca_file.lstat()
    if (not stat.S_ISREG(ca.st_mode) or stat.S_ISLNK(ca.st_mode) or ca.st_uid != os.geteuid() or ca.st_mode & 0o022):
        raise ValueError('Invalid CA file')
    check_live_source_binding(DockerInspector(), raw)
    if raw.startswith('postgres://'):
        raw = 'postgresql://' + raw[len('postgres://'):]
    url = make_url(raw).difference_update_query(['sslrootcert'])
    os.environ['DATABASE_URL'] = url.render_as_string(hide_password=False)
    os.environ['DATABASE_SSL_MODE'] = 'verify-full'
    os.environ['DATABASE_SSL_ROOT_CERT'] = str(args.ca_file)
    os.environ['TESTING'] = 'false'
    sys.path.insert(0, str(API))
    from sqlalchemy import text
    from src.core.database import AsyncSessionLocal, async_engine
    from src.core.utils import utcnow
    from src.services.privacy_purge_health import assess_purge_queue

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text('SET TRANSACTION READ ONLY'))
            await db.execute(text('SET LOCAL search_path = pg_catalog, public'))
            return await assess_purge_queue(db, now=utcnow())
    finally:
        await async_engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--ca-file', type=Path)
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({'status': 'DISABLED', 'restore_authorized': False}))
        return 0
    try:
        result = asyncio.run(check(args))
    except Exception:
        result = {'status': 'ALERT', 'restore_authorized': False}
    print(json.dumps(result, sort_keys=True))
    return 0 if result == {'status': 'OK', 'restore_authorized': False} else 1


if __name__ == '__main__':
    sys.exit(main())
