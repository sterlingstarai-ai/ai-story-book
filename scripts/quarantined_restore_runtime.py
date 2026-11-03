"""Restore an ingested backup only into local tmpfs services, never publish it.

The host must independently inspect the exact sandbox before and after calling
this helper. No later privacy events are applied here, so a successful result
must remain quarantined and must not be used to authorize a real restore.
"""
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import time
import urllib.request

import boto3
from botocore.config import Config

from verify_backup_set import verify
from quarantined_db_fingerprint import fingerprint

ROOT = Path('/var/lib/asb-restore')
PG_BIN = Path('/usr/lib/postgresql/16/bin')
MINIO = '/usr/local/bin/minio'


class RestoreRuntimeError(RuntimeError):
    pass


def _run(args, *, env=None, timeout=60):
    try:
        return subprocess.run(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              check=True, timeout=timeout).stdout
    except Exception:
        raise RestoreRuntimeError('Isolated restore process failed') from None


def _assert_local_sandbox():
    if os.geteuid() != 65534 or os.environ.get('ASB_QUARANTINE_RESTORE') != '1':
        raise RestoreRuntimeError('Isolated restore identity is required')
    interfaces = {name for _, name in socket.if_nameindex()}
    if 'lo' not in interfaces:
        raise RestoreRuntimeError('Loopback interface is required')
    # Docker Desktop may expose inactive tunnel interfaces in a network-none
    # namespace. They are safe only while down; the host inspection separately
    # requires network=none and drops all capabilities before and after use.
    with socket.socket() as control:
        for name in interfaces - {'lo'}:
            request = struct.pack('256s', name.encode('ascii'))
            flags = struct.unpack('H', fcntl.ioctl(control.fileno(), 0x8913, request)[16:18])[0]
            if flags & 1:
                raise RestoreRuntimeError('External network interfaces are not allowed')
    mounts = Path('/proc/mounts').read_text().splitlines()
    if not any(line.split()[1:3] == [str(ROOT), 'tmpfs'] for line in mounts if len(line.split()) >= 3):
        raise RestoreRuntimeError('Isolated temporary storage is required')
    if ROOT.is_symlink() or not ROOT.is_dir():
        raise RestoreRuntimeError('Restore storage is invalid')


def _free_port(port):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', port))


def _wait_minio(process):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RestoreRuntimeError('Isolated storage exited')
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open('http://127.0.0.1:59000/minio/health/ready', timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(.25)
    raise RestoreRuntimeError('Isolated storage did not become ready')


def _read_media(client, bucket, objects):
    expected = {item['key']: item for item in objects}
    actual = set()
    versioning = client.get_bucket_versioning(Bucket=bucket)
    if not isinstance(versioning, dict) or 'Status' in versioning:
        raise RestoreRuntimeError('Versioned quarantine storage is unsupported')
    # Do not equate an incomplete listing with a verified empty or complete
    # inventory. A broken provider/adapter can stop pagination after a page
    # marked truncated, repeat a continuation token, or return no pages.
    saw_page = False
    expecting_page = False
    seen_tokens = set()
    for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket):
        if (not isinstance(page, dict) or type(page.get('IsTruncated')) is not bool
                or (saw_page and not expecting_page)):
            raise RestoreRuntimeError('Restored media listing is incomplete')
        saw_page = True
        expecting_page = page['IsTruncated']
        if expecting_page:
            continuation = page.get('NextContinuationToken')
            if (not isinstance(continuation, str) or not continuation
                    or continuation in seen_tokens):
                raise RestoreRuntimeError('Restored media listing is incomplete')
            seen_tokens.add(continuation)
        entries = page.get('Contents', [])
        if not isinstance(entries, list):
            raise RestoreRuntimeError('Restored media listing is incomplete')
        for item in entries:
            if not isinstance(item, dict):
                raise RestoreRuntimeError('Restored media listing is incomplete')
            key = item.get('Key')
            if key not in expected or key in actual:
                raise RestoreRuntimeError('Restored media inventory differs')
            actual.add(key)
            result = client.get_object(Bucket=bucket, Key=key)
            for source, target in (('content_type', 'ContentType'), ('metadata', 'Metadata'),
                                   ('cache_control', 'CacheControl'), ('content_disposition', 'ContentDisposition'),
                                   ('content_encoding', 'ContentEncoding')):
                if expected[key].get(source) is not None and result.get(target) != expected[key][source]:
                    raise RestoreRuntimeError('Restored media metadata differs')
            body = result['Body']
            digest = hashlib.sha256()
            count = 0
            try:
                for chunk in iter(lambda: body.read(65536), b''):
                    count += len(chunk)
                    if count > expected[key]['size']:
                        raise RestoreRuntimeError('Restored media size differs')
                    digest.update(chunk)
            finally:
                body.close()
            if count != expected[key]['size'] or digest.hexdigest() != expected[key]['sha256']:
                raise RestoreRuntimeError('Restored media checksum differs')
    if not saw_page or expecting_page or actual != set(expected):
        raise RestoreRuntimeError('Restored media inventory differs')


def restore(token):
    _assert_local_sandbox()
    if not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token):
        raise RestoreRuntimeError('Sandbox token is invalid')
    folder = ROOT / ('ingest-' + token)
    marker = folder / 'quarantined.json'
    if (folder.is_symlink() or not marker.is_file() or marker.is_symlink()
            or json.loads(marker.read_text()) != {'status': 'BACKUP_IMPORTED_QUARANTINED', 'restore_authorized': False}):
        raise RestoreRuntimeError('Quarantined backup import is missing')
    verified = verify(folder)
    if verified.get('restore_verified') is not False:
        raise RestoreRuntimeError('Backup verification is invalid')
    manifest = json.loads((folder / 'manifest.json').read_bytes())
    revision = manifest.get('alembic_revision')
    if not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{12}', revision):
        raise RestoreRuntimeError('Backup revision is invalid')
    # The restored media is a second copy alongside the ingested backup. DB
    # expansion is not predictable; ENOSPC later still aborts and quarantines.
    required = sum(item['size'] for item in manifest['objects']) + 32 * 1024 * 1024
    if shutil.disk_usage(ROOT).free < required:
        raise RestoreRuntimeError('Insufficient isolated temporary capacity')
    _free_port(54321)
    _free_port(59000)
    _free_port(59001)
    data = ROOT / ('runtime-' + token)
    data.mkdir(mode=0o700)
    pgdata = data / 'pg'
    pgdata.mkdir(mode=0o700)
    media = data / 'media'
    media.mkdir(mode=0o700)
    started = False
    minio = None
    complete = False
    try:
        _run([str(PG_BIN / 'initdb'), '-D', str(pgdata), '-U', 'sandbox', '--auth=trust',
              '--no-locale', '--encoding=UTF8'], timeout=60)
        _run([str(PG_BIN / 'pg_ctl'), '-D', str(pgdata), '-l', str(data / 'postgres.log'),
              '-o', '-h 127.0.0.1 -p 54321 -k /tmp', '-w', 'start'], timeout=60)
        started = True
        env = dict(os.environ, PGHOST='127.0.0.1', PGPORT='54321', PGUSER='sandbox')
        _run([str(PG_BIN / 'createdb'), 'restored'], env=env)
        _run([str(PG_BIN / 'psql'), '-X', '-v', 'ON_ERROR_STOP=1', '-d', 'restored',
              '-c', 'DROP SCHEMA public CASCADE'], env=env)
        _run([str(PG_BIN / 'pg_restore'), '--exit-on-error', '--no-owner', '--no-privileges',
              '-d', 'restored', str(folder / 'database.dump')], env=env, timeout=180)
        current = _run([str(PG_BIN / 'psql'), '-X', '-At', '-d', 'restored', '-c',
                        'SELECT version_num FROM public.alembic_version ORDER BY version_num'], env=env).decode().strip()
        if current != revision:
            raise RestoreRuntimeError('Restored database revision differs')
        database_fingerprint = fingerprint()
        user = 'asb' + secrets.token_hex(12)
        password = secrets.token_urlsafe(32)
        minio_env = dict(os.environ, MINIO_ROOT_USER=user, MINIO_ROOT_PASSWORD=password, MINIO_BROWSER='off')
        minio = subprocess.Popen([MINIO, 'server', '--address', '127.0.0.1:59000',
                                  '--console-address', '127.0.0.1:59001', str(media)],
                                 env=minio_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
        _wait_minio(minio)
        client = boto3.client('s3', endpoint_url='http://127.0.0.1:59000',
            aws_access_key_id=user, aws_secret_access_key=password, region_name='us-east-1',
            config=Config(signature_version='s3v4', s3={'addressing_style': 'path'},
                          proxies={}, connect_timeout=3, read_timeout=15, retries={'max_attempts': 1}))
        bucket = 'quarantine-restore'
        client.create_bucket(Bucket=bucket)
        for item in manifest['objects']:
            kwargs = {'Bucket': bucket, 'Key': item['key']}
            for source, target in (('content_type', 'ContentType'), ('metadata', 'Metadata'),
                                   ('cache_control', 'CacheControl'), ('content_disposition', 'ContentDisposition'),
                                   ('content_encoding', 'ContentEncoding')):
                if item.get(source) is not None:
                    kwargs[target] = item[source]
            with (folder / item['file']).open('rb') as body:
                client.put_object(Body=body, **kwargs)
        _read_media(client, bucket, manifest['objects'])
        runtime = data / 'runtime.json'
        fd = os.open(runtime, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump({'version': 1, 'database': 'restored', 'db_port': 54321,
                       'storage_endpoint': 'http://127.0.0.1:59000', 'bucket': bucket,
                       'storage_user': user, 'storage_password': password, 'minio_pid': minio.pid,
                       'database_fingerprint': database_fingerprint,
                       'restore_authorized': False}, output)
            output.flush()
            os.fsync(output.fileno())
        complete = True
        return {'status': 'DATABASE_AND_MEDIA_RESTORED_QUARANTINED',
                'privacy_replay_verified': False, 'restore_authorized': False}
    finally:
        if not complete:
            if minio is not None and minio.poll() is None:
                minio.terminate()
                try:
                    minio.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    minio.kill()
                    minio.wait(timeout=5)
            if started:
                try:
                    _run([str(PG_BIN / 'pg_ctl'), '-D', str(pgdata), '-m', 'immediate', '-w', 'stop'], timeout=20)
                except RestoreRuntimeError:
                    pass  # Host destroys the owned sandbox on any failure.
            shutil.rmtree(data)


def main():
    try:
        if len(sys.argv) != 2:
            raise RestoreRuntimeError('Sandbox token is required')
        print(json.dumps(restore(sys.argv[1]), sort_keys=True))
        return 0
    except BaseException:
        print(json.dumps({'status': 'QUARANTINED_RESTORE_FAILED', 'restore_authorized': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
