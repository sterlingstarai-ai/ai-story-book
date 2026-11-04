"""Synthetic-only PostgreSQL/MinIO restore inside a network-none container.

This is not an operational restore path. It accepts no real data, and success
never opens a restored service or proves journal completeness after a disaster.
"""
import asyncio
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import struct
import sys
import time
import uuid

ROOT = Path('/var/lib/asb-restore')
SCRIPTS = Path('/offline/scripts')
API = Path('/offline/apps/api')
PASSWORD = 'disposable-runtime-password'
BUCKET = 'restore-rehearsal'
VOICE_SAMPLE_KEY = 'voice-samples/00000000-0000-4000-8000-000000000003/sample.wav'


def require_synthetic_sandbox():
    if os.geteuid() != 65534 or os.environ.get('ASB_OFFLINE_SYNTHETIC_FIXTURE') != 'true':
        raise RuntimeError('Synthetic network-none container required')
    with socket.socket() as control:
        interfaces = socket.if_nameindex()
        if not any(name == 'lo' for _, name in interfaces):
            raise RuntimeError('Synthetic loopback interface is unavailable')
        for _, name in interfaces:
            if name != 'lo':
                request = struct.pack('256s', name.encode('ascii'))
                flags = struct.unpack('H', fcntl.ioctl(control.fileno(), 0x8913, request)[16:18])[0]
                if flags & 1:  # IFF_UP; Docker Desktop may include down tunnel interfaces.
                    raise RuntimeError('Unexpected active network interface')
    with open('/proc/mounts') as mounts:
        entries = [line.split() for line in mounts]
    if not any(len(parts) > 2 and parts[1] == str(ROOT) and parts[2] == 'tmpfs' for parts in entries):
        raise RuntimeError('Synthetic tmpfs workspace required')
    probe = socket.socket()
    try:
        probe.settimeout(2)
        if probe.connect_ex(('1.1.1.1', 53)) == 0:
            raise RuntimeError('Unexpected external network access')
    finally:
        probe.close()


def run(command, *, env=None, stdin=None, stdout=None):
    result = subprocess.run(command, cwd=API, env=env, stdin=stdin,
                            stdout=stdout or subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    if result.returncode:
        # Fixture process output contains no real user data or credentials.
        raise RuntimeError(f'Synthetic step failed: {Path(command[0]).name}: '
                           + result.stderr.decode(errors='replace')[-500:])
    return result.stdout or b''


def wait_http(url):
    import httpx
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2, trust_env=False).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise RuntimeError('Synthetic object store did not become ready')


def exercise_quarantined_replay(target_env, endpoint):
    """Exercise the real isolated replay command with one post-backup erasure."""
    import boto3
    from botocore.exceptions import ClientError

    token = uuid.uuid4().hex
    archive = ROOT / ('ingest-' + token)
    (archive / 'objects').mkdir(parents=True, mode=0o700)
    pg = dict(os.environ, PGHOST='127.0.0.1', PGPORT='15433', PGUSER='runtime_test', PGPASSWORD=PASSWORD)
    subject = '00000000-0000-4000-8000-000000000019'
    media_key = f'voice-samples/{subject}/quarantine.wav'
    original_base = f'{endpoint}/{BUCKET}'
    sample = b'isolated replay synthetic sample'
    run(['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-d', 'runtime_test', '-c',
         "INSERT INTO voice_profiles (id,user_key,label,sample_audio_url,consented,active) "
         f"VALUES ('quarantine-voice','{subject}','Synthetic','{original_base}/{media_key}',true,true)"], env=pg)
    dump = archive / 'database.dump'
    with dump.open('wb') as output:
        run(['pg_dump', '--format=custom', '--schema=public', '--no-owner', '--no-privileges', 'runtime_test'],
            env=pg, stdout=output)
    filename = 'objects/' + hashlib.sha256(media_key.encode()).hexdigest()
    (archive / filename).write_bytes(sample)
    revision = run(['psql', '-X', '-At', '-d', 'runtime_test', '-c',
                    'SELECT version_num FROM public.alembic_version'], env=pg).decode().strip()
    manifest = {'format_version': 1, 'database_scope': 'public', 'alembic_revision': revision,
                'requires_latest_deletion_and_identity_revocations': True,
                'database': {'file': 'database.dump', 'size': dump.stat().st_size,
                             'sha256': hashlib.sha256(dump.read_bytes()).hexdigest()},
                'objects': [{'key': media_key, 'file': filename, 'size': len(sample),
                             'sha256': hashlib.sha256(sample).hexdigest(), 'content_type': 'audio/wav'}]}
    manifest_bytes = json.dumps(manifest).encode()
    (archive / 'manifest.json').write_bytes(manifest_bytes)
    program = """
import json, sys
sys.path.insert(0, '/offline/scripts')
from fixture_journal_store import load_fixture_journal
from replay_privacy_journal import encode_replay_transfer
from src.services.privacy_journal_verify import fingerprint_entries
journal = load_fixture_journal()
backup = journal.scan()
event = journal.begin('voice_delete', sys.argv[1], revision=1, resource_id='quarantine-voice')
journal.commit(event)
scan = journal.scan()
print(json.dumps({'count': len(backup.committed), 'digest': fingerprint_entries(backup.committed),
    'transfer': encode_replay_transfer(scan, fingerprint_entries(scan.committed), sys.argv[2]).decode()}))
"""
    data = json.loads(run(['/opt/venv/bin/python', '-c', program, subject, original_base], env=target_env))
    (archive / 'quarantined.json').write_text(json.dumps({
        'status': 'BACKUP_IMPORTED_QUARANTINED', 'restore_authorized': False}))
    (archive / 'verified.json').write_text(json.dumps({
        'version': 1, 'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
        'journal_event_count': data['count'], 'journal_sha256': data['digest'], 'restore_authorized': False}))
    isolated = dict(os.environ, ASB_QUARANTINE_RESTORE='1')
    restored = json.loads(run(['/opt/venv/bin/python', str(SCRIPTS / 'quarantined_restore_runtime.py'), token], env=isolated))
    if restored['status'] != 'DATABASE_AND_MEDIA_RESTORED_QUARANTINED':
        raise RuntimeError('Synthetic operational restore failed')
    runtime = json.loads((ROOT / ('runtime-' + token) / 'runtime.json').read_bytes())
    media = boto3.client('s3', endpoint_url=runtime['storage_endpoint'], region_name='us-east-1',
                         aws_access_key_id=runtime['storage_user'], aws_secret_access_key=runtime['storage_password'])
    try:
        with media.get_object(Bucket=runtime['bucket'], Key=media_key)['Body'] as body:
            if body.read() != sample:
                raise RuntimeError('Synthetic quarantined sample differs from its backup')
        with (archive / 'transfer.fixture').open('w+b') as source:
            source.write(data['transfer'].encode())
            source.seek(0)
            result = json.loads(run(['/opt/venv/bin/python', str(SCRIPTS / 'quarantined_replay_preflight.py'),
                                     '--apply', token], env=isolated, stdin=source))
        if result != {'status': 'REPLAYED_STILL_QUARANTINED', 'applied_count': 1, 'restore_authorized': False}:
            raise RuntimeError('Synthetic quarantined replay did not apply exactly one event')
        try:
            media.head_object(Bucket=runtime['bucket'], Key=media_key)
        except ClientError as exc:
            if exc.response['ResponseMetadata']['HTTPStatusCode'] != 404:
                raise
        else:
            raise RuntimeError('Synthetic quarantined sample remains after erasure')
    finally:
        media.close()


def main():
    require_synthetic_sandbox()
    os.umask(0o077)
    sys.path.insert(0, str(SCRIPTS))
    from run_backup_restore_rehearsal import (copy_media, database_snapshot, finish_fixture_pending_task,
        mark_disposable_restore_target, object_inventory, seed_database, storage,
        verify_regranted_consent_preserved, verify_synthetic_account_replayed, verify_synthetic_consent_replayed)
    import httpx

    workspace = ROOT / ('storybook-restore-private-' + uuid.uuid4().hex[:12])
    workspace.mkdir(mode=0o700)
    keyfile = workspace / 'pw'
    keyfile.write_text(PASSWORD + '\n')
    clusters, minios = [], []
    try:
        for index, port in enumerate((15432, 15433)):
            data = workspace / f'pg{index}'
            run(['initdb', '-D', str(data), '-U', 'runtime_test', '--auth-local=trust',
                 '--auth-host=scram-sha-256', '--pwfile', str(keyfile), '--no-locale', '--no-sync'])
            options = f'-c listen_addresses=127.0.0.1 -p {port} -k /tmp -c max_connections=25'
            run(['pg_ctl', '-D', str(data), '-l', str(workspace / f'pg{index}.log'), '-o', options, '-w', 'start'])
            clusters.append(data)
            env = dict(os.environ, PGPASSWORD=PASSWORD)
            run(['createdb', '-h', '127.0.0.1', '-p', str(port), '-U', 'runtime_test', 'runtime_test'], env=env)
        for index, port in enumerate((19000, 19010)):
            data = workspace / f's3-{index}'
            data.mkdir(mode=0o700)
            env = dict(os.environ, MINIO_ROOT_USER='runtime_test', MINIO_ROOT_PASSWORD=PASSWORD, MINIO_BROWSER='off')
            process = subprocess.Popen(['minio', 'server', '--address', f'127.0.0.1:{port}',
                '--console-address', f'127.0.0.1:{port + 1}', str(data)], env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            minios.append(process)
            wait_http(f'http://127.0.0.1:{port}/minio/health/live')
        endpoints = ['http://127.0.0.1:19000', 'http://127.0.0.1:19010']
        source_s3, target_s3 = [storage(endpoint) for endpoint in endpoints]
        for client in (source_s3, target_s3):
            client.create_bucket(Bucket=BUCKET)
        env = dict(os.environ, TESTING='true', DATABASE_URL=f'postgresql+asyncpg://runtime_test:{PASSWORD}@127.0.0.1:15432/runtime_test',
            PYTHONPATH=str(API), S3_ENDPOINT=endpoints[0], S3_PUBLIC_URL=f'{endpoints[0]}/{BUCKET}', S3_BUCKET=BUCKET,
            S3_ACCESS_KEY='runtime_test', S3_SECRET_KEY=PASSWORD, S3_REGION='us-east-1',
            LLM_PROVIDER='mock', IMAGE_PROVIDER='mock', AUDIO_FEATURE_ENABLED='false', POD_ORDERING_ENABLED='false',
            PURCHASES_ENABLED='false', ASB_FIXTURE_JOURNAL_DIR=str(workspace / 'journal'),
            ASB_FIXTURE_JOURNAL_KEY='6b' * 32)
        run(['/opt/venv/bin/python', '-m', 'alembic', 'upgrade', 'head'], env=env)
        boundary_env = dict(env, ASB_SECOND_FIXTURE_S3=endpoints[1])
        boundary = json.loads(run(['/opt/venv/bin/python', str(SCRIPTS / 'run_privacy_boundary_integration.py')],
                                  env=boundary_env))
        if (boundary.get('status') != 'SYNTHETIC_FENCE_WITNESS_PASSED'
                or boundary.get('restore_authorized') is not False):
            raise RuntimeError('Synthetic boundary integration did not pass')
        run(['/opt/venv/bin/python', str(SCRIPTS / 'run_purge_health_fixture.py')], env=env)
        pixel = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+afo4AAAAASUVORK5CYII=')
        media = {'books/cover.png': (pixel, 'image/png'), 'books/page-1.png': (pixel, 'image/png'),
            'books/page-2.png': (pixel, 'image/png'), 'books/book.pdf': (b'%PDF-1.4\n%synthetic\n%%EOF\n', 'application/pdf'),
            'pending-erasure/asset.png': (pixel, 'image/png'), 'consent-fixture/photo.png': (pixel, 'image/png'),
            'consent-fixture/illustration.png': (pixel, 'image/png'),
            VOICE_SAMPLE_KEY: (b'synthetic voice fixture', 'audio/wav')}
        for key, (data, content_type) in media.items():
            source_s3.put_object(Bucket=BUCKET, Key=key, Body=data, ContentType=content_type, Metadata={'fixture':'synthetic'})
        asyncio.run(seed_database(15432, media, voice_media_base=f'{endpoints[0]}/{BUCKET}'))
        env['ASB_REPLAY_SCENARIO'] = 'failed_enrollment'
        run(['/opt/venv/bin/python', str(SCRIPTS / 'run_source_privacy_fixture.py')], env=env)
        env['ASB_REPLAY_SCENARIO'] = 'historical'
        run(['/opt/venv/bin/python', str(SCRIPTS / 'run_source_privacy_fixture.py')], env=env)
        env['ASB_FIXTURE_WITNESS_ENDPOINT'] = endpoints[1]
        env['ASB_FIXTURE_WITNESS_MODE'] = 'capture'
        run(['/opt/venv/bin/python', str(SCRIPTS / 'run_witness_fixture.py')], env=env)
        source_snapshot = asyncio.run(database_snapshot(15432))
        dump = workspace / 'synthetic.dump'
        pg_env = dict(os.environ, PGPASSWORD=PASSWORD)
        with dump.open('wb') as output:
            run(['pg_dump', '-h', '127.0.0.1', '-p', '15432', '-U', 'runtime_test', '--format=custom',
                 '--no-owner', '--no-privileges', 'runtime_test'], env=pg_env, stdout=output)
        with dump.open('rb') as data:
            run(['pg_restore', '-h', '127.0.0.1', '-p', '15433', '-U', 'runtime_test', '--dbname=runtime_test',
                 '--no-owner', '--no-privileges', '--exit-on-error', '--single-transaction'], env=pg_env, stdin=data)
        folder = workspace / 'media'
        folder.mkdir(mode=0o700)
        manifest = copy_media(source_s3, target_s3, folder)
        if source_snapshot != asyncio.run(database_snapshot(15433)) or manifest != object_inventory(target_s3):
            raise RuntimeError('Synthetic restored backup differs')
        env['ASB_REPLAY_SCENARIO'] = 'account'
        run(['/opt/venv/bin/python', str(SCRIPTS / 'run_source_privacy_fixture.py')], env=env)
        old_url = target_s3.generate_presigned_url('get_object', Params={'Bucket': BUCKET, 'Key': 'books/cover.png'}, ExpiresIn=60)
        target_s3.delete_object(Bucket=BUCKET, Key='pending-erasure/asset.png')
        asyncio.run(finish_fixture_pending_task(15433))
        token = uuid.uuid4().hex
        asyncio.run(mark_disposable_restore_target(15433, token, endpoints[1]))
        target_env = dict(env, DATABASE_URL=f'postgresql+asyncpg://runtime_test:{PASSWORD}@127.0.0.1:15433/runtime_test',
            S3_ENDPOINT=endpoints[1], S3_PUBLIC_URL=f'{endpoints[1]}/{BUCKET}',
            S3_LEGACY_PUBLIC_URLS=f'{endpoints[0]}/{BUCKET}', ASB_DISPOSABLE_REPLAY_TOKEN=token)
        for index in (1, 2):
            target_env['ASB_REPLAY_RUN'] = str(index)
            run(['/opt/venv/bin/python', str(SCRIPTS / 'run_restore_replay_fixture.py')], env=target_env)
        asyncio.run(verify_synthetic_account_replayed(15433))
        asyncio.run(verify_regranted_consent_preserved(15433))
        if httpx.get(old_url, timeout=5, trust_env=False).status_code not in (403, 404):
            raise RuntimeError('Synthetic deleted account media remains accessible')
        consent_url = target_s3.generate_presigned_url('get_object', Params={'Bucket': BUCKET, 'Key': 'consent-fixture/photo.png'}, ExpiresIn=60)
        voice_url = target_s3.generate_presigned_url('get_object', Params={'Bucket': BUCKET, 'Key': VOICE_SAMPLE_KEY}, ExpiresIn=60)
        if httpx.get(voice_url, timeout=5, trust_env=False).status_code != 200:
            raise RuntimeError('Synthetic voice media was not restored')
        env['ASB_FIXTURE_VOICE_ERASURE'] = target_env['ASB_FIXTURE_VOICE_ERASURE'] = '1'
        env['ASB_REPLAY_SCENARIO'] = 'consent'
        run(['/opt/venv/bin/python', str(SCRIPTS / 'run_source_privacy_fixture.py')], env=env)
        env['ASB_FIXTURE_WITNESS_MODE'] = 'verify'
        run(['/opt/venv/bin/python', str(SCRIPTS / 'run_witness_fixture.py')], env=env)
        target_env['ASB_REPLAY_SCENARIO'] = 'consent'
        for index in (1, 2):
            target_env['ASB_REPLAY_RUN'] = str(index)
            run(['/opt/venv/bin/python', str(SCRIPTS / 'run_restore_replay_fixture.py')], env=target_env)
        asyncio.run(verify_synthetic_consent_replayed(15433))
        if object_inventory(target_s3) or any(httpx.get(url, timeout=5, trust_env=False).status_code not in (403, 404)
                                              for url in (consent_url, voice_url)):
            raise RuntimeError('Synthetic revoked media remains accessible')
        exercise_quarantined_replay(target_env, endpoints[1])
        print(json.dumps({'status':'OFFLINE_SYNTHETIC_REPLAY_PASSED','network':'none','tmpfs':True,
            'account_delete':True,'consent_revoke':True,'credential_rotation':True,'old_media_denied':True,
            'voice_erasure':True,
            'quarantined_replay_command':True,
            'idempotent':True,'witness_prefix_tested':True,'anchored_head_tested':True,'witness_watch_tested':True,
            'fence_witness_concurrency': boundary,
            'purge_health_tested':True,
            'restore_authorized':False}, sort_keys=True))
    finally:
        for process in minios:
            process.terminate()
        for process in minios:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for data in reversed(clusters):
            subprocess.run(['pg_ctl', '-D', str(data), '-m', 'fast', '-w', 'stop'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


if __name__ == '__main__':
    main()
