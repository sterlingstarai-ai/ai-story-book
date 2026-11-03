"""Exercise provider recovery on an explicitly owned disposable GCE VM only.

The caller provisions and destroys the VM and disk; this script never creates
cloud resources. It uses synthetic containers without network or secrets. A
successful boot result does not prove production ingress, provider, or daemon
request quiescence. Never run on a persistent or production VM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path('/opt/ai-story-book/current')
STATE = Path('/var/lib/ai-story-book')
UNIT = Path('/etc/systemd/system')
PRIVACY_HASH = 'e7aa61afc9de1f658f75a1946f1a9525a480369d751f0ee9f2e2ed84712fa16a'
BACKUP_HASH = '9de56dad4e7535116124f3f2fe89136c3e9c604679e86a4f350ab8117d504e86'
NAMES = {'old_api': 'asb-pilot-api', 'old_worker': 'asb-pilot-worker',
         'new_api': 'asb-provider-next-api', 'new_worker': 'asb-provider-next-worker'}
POST_NAMES = {'old_api': 'asb-pilot-api-before-provider',
              'old_worker': 'asb-pilot-worker-before-provider',
              'new_api': 'asb-pilot-api', 'new_worker': 'asb-pilot-worker'}


class FixtureError(RuntimeError):
    pass


def metadata(path):
    request = urllib.request.Request('http://169.254.169.254/computeMetadata/v1/instance/' + path,
                                     headers={'Metadata-Flavor': 'Google'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=3) as response:
        if response.headers.get('Metadata-Flavor') != 'Google':
            raise FixtureError('metadata authenticity header missing')
        return response.read(512).decode().strip()


def run(*args):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, timeout=120).stdout.strip()


def assert_fixture(token, instance_id):
    if os.geteuid() != 0 or not re.fullmatch(r'[0-9a-f]{32}', token) or not re.fullmatch(r'[0-9]+', instance_id):
        raise FixtureError('invalid fixture identity')
    if run('ps', '-p', '1', '-o', 'comm=') != 'systemd':
        raise FixtureError('real systemd is required')
    if (metadata('id') != instance_id or metadata('name') != 'asb-boot-fixture-' + token[:16]
            or metadata('attributes/asb-fixture-owner') != token):
        raise FixtureError('VM is not the exact owned fixture')
    run('docker', 'info', '--format', '{{.ServerVersion}}')


def verify_package(package, privacy):
    p = Path(package)
    manifest = json.loads((p / 'manifest.json').read_text())
    expected_files = {'scripts/backup_service_guard.py', 'scripts/narration_deploy_safety.py',
                      'scripts/provider_recovery_interlock.py', 'scripts/provider_rotation_quarantine.py',
                      'systemd/asb-provider-rotation-quarantine.service',
                      'systemd/asb-privacy-deploy-recover.service.d/provider-interlock.conf',
                      'systemd/asb-backup-recover.service.d/provider-order.conf'}
    if (manifest.get('version') != 1 or manifest.get('backup_source_sha256') != BACKUP_HASH
            or manifest.get('privacy_source_sha256') != PRIVACY_HASH
            or set(manifest.get('files', {})) != expected_files):
        raise FixtureError('fixture package is invalid')
    for name, digest in manifest['files'].items():
        path = p / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise FixtureError('fixture package digest mismatch')
    original = Path(privacy)
    if original.is_symlink() or hashlib.sha256(original.read_bytes()).hexdigest() != PRIVACY_HASH:
        raise FixtureError('legacy fixture source differs')
    return p


def prepare(token, instance_id, package, privacy, image, *, test_mutation=False):
    assert_fixture(token, instance_id)
    p = verify_package(package, privacy)
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
        raise FixtureError('an exact synthetic image ID is required')
    if run('docker', 'image', 'inspect', image, '--format', '{{.Id}}') != image:
        raise FixtureError('fixture image is unavailable')
    owned = [ROOT, STATE, UNIT / 'asb-provider-rotation-quarantine.service',
             UNIT / 'asb-backup-recover.service', UNIT / 'asb-privacy-deploy-recover.service',
             UNIT / 'asb-backup-recover.service.d', UNIT / 'asb-privacy-deploy-recover.service.d']
    if any(path.exists() or path.is_symlink() for path in owned):
        raise FixtureError('fixture paths already exist')
    for name in set(NAMES.values()) | set(POST_NAMES.values()):
        if subprocess.run(['docker', 'inspect', name], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=20).returncode == 0:
            raise FixtureError('fixture container name already exists')
    (ROOT / 'scripts').mkdir(parents=True, mode=0o700)
    (ROOT / 'apps/api/venv/bin').mkdir(parents=True, mode=0o700)
    (ROOT / 'apps/api/venv/bin/python').symlink_to('/usr/bin/python3')
    for name in ('backup_service_guard.py', 'narration_deploy_safety.py',
                 'provider_recovery_interlock.py', 'provider_rotation_quarantine.py'):
        shutil.copyfile(p / 'scripts' / name, ROOT / 'scripts' / name)
    shutil.copyfile(privacy, ROOT / 'scripts/deploy_pilot_privacy.py')
    # This dependency is not involved in --recover; the fixture has no worker.
    (ROOT / 'scripts/run_scheduled_backup.py').write_text(
        'def assert_idle_worker(*args, **kwargs):\n    raise RuntimeError("fixture worker unavailable")\n')
    for sub in ('backup-state', 'provider-rotation', 'privacy-deploy'):
        (STATE / sub).mkdir(parents=True, mode=0o700)
    for sub in ('asb-backup-recover.service.d', 'asb-privacy-deploy-recover.service.d'):
        (UNIT / sub).mkdir(mode=0o755)
        for file in (p / 'systemd' / sub).iterdir():
            shutil.copyfile(file, UNIT / sub / file.name)
    shutil.copyfile(p / 'systemd/asb-provider-rotation-quarantine.service',
                    UNIT / 'asb-provider-rotation-quarantine.service')
    (UNIT / 'asb-backup-recover.service').write_text('[Unit]\nDescription=Fixture backup recovery\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 /opt/ai-story-book/current/scripts/backup_service_guard.py --recover --state-dir /var/lib/ai-story-book/backup-state\n[Install]\nWantedBy=multi-user.target\n')
    (UNIT / 'asb-privacy-deploy-recover.service').write_text('[Unit]\nDescription=Fixture privacy recovery\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 /opt/ai-story-book/current/scripts/deploy_pilot_privacy.py --recover\n[Install]\nWantedBy=multi-user.target\n')
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', 'asb-provider-rotation-quarantine.service',
        'asb-backup-recover.service', 'asb-privacy-deploy-recover.service')
    # Establish that the exact legacy recovery paths work without a marker,
    # so the subsequent refusal cannot be a missing-dependency false positive.
    run('/usr/bin/python3', str(ROOT / 'scripts/backup_service_guard.py'), '--recover',
        '--state-dir', str(STATE / 'backup-state'))
    run('/usr/bin/python3', str(ROOT / 'scripts/provider_recovery_interlock.py'))
    ids = {}
    for slot, name in NAMES.items():
        identifier = run('docker', 'create', '--network', 'none', '--restart', 'no',
                         '--label', 'asb.boot-fixture.owner=' + token, '--name', name,
                         image, 'sleep', '86400')
        if not re.fullmatch(r'[0-9a-f]{64}', identifier):
            raise FixtureError('fixture container creation did not return exact ID')
        ids[slot] = identifier
    # Simulate a crash after the new API started; no container can restart
    # before the boot recovery unit. The marker uses the actual guard format.
    for slot in ('old_api', 'old_worker'):
        run('docker', 'start', ids[slot])
        run('docker', 'stop', '--time', '2', ids[slot])
    sys.path.insert(0, str(ROOT / 'scripts'))
    import provider_rotation_quarantine as guard
    guard._write_marker(STATE / 'provider-rotation', ids)
    for slot in ('old_api', 'old_worker', 'new_api', 'new_worker'):
        run('docker', 'rename', ids[slot], POST_NAMES[slot])
    run('docker', 'start', ids['new_api'])
    if test_mutation:
        # A synthetic durable marker represents an interrupted daemon request;
        # its presence, not its contents, must block recovery.
        fd = os.open(STATE / 'provider-rotation/docker-mutation.json',
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, b'{}\n')
            os.fsync(fd)
        finally:
            os.close(fd)
        fd = os.open(STATE / 'provider-rotation', os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    (STATE / 'fixture-identities.json').write_text(json.dumps(
        {'ids': ids, 'test_mutation': test_mutation,
         'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}, sort_keys=True))
    os.chmod(STATE / 'fixture-identities.json', 0o600)
    return {'status': 'REBOOT_REQUIRED', 'production_changed': False}


def verify(token, instance_id):
    assert_fixture(token, instance_id)
    record = json.loads((STATE / 'fixture-identities.json').read_text())
    if record.get('boot_id') == Path('/proc/sys/kernel/random/boot_id').read_text().strip():
        raise FixtureError('fixture has not rebooted')
    ids = record['ids']
    if set(ids) != set(NAMES) or len(set(ids.values())) != 4:
        raise FixtureError('fixture identity record invalid')
    if not (STATE / 'provider-rotation/recovery.json').is_file():
        raise FixtureError('durable marker disappeared')
    # The unit must itself have run successfully after the caller rebooted.
    expected_result = 'exit-code' if record.get('test_mutation') is True else 'success'
    if record.get('test_mutation') is True and not (STATE / 'provider-rotation/docker-mutation.json').is_file():
        raise FixtureError('durable mutation marker disappeared')
    if (run('systemctl', 'show', 'asb-provider-rotation-quarantine.service',
            '--property=Result', '--value') != expected_result
            or int(run('systemctl', 'show', 'asb-provider-rotation-quarantine.service',
                       '--property=ExecMainStartTimestampMonotonic', '--value')) == 0):
        raise FixtureError('quarantine unit did not succeed')
    for unit in ('asb-backup-recover.service', 'asb-privacy-deploy-recover.service'):
        after = run('systemctl', 'show', unit, '--property=After', '--value').split()
        if 'asb-provider-rotation-quarantine.service' not in after:
            raise FixtureError('recovery unit ordering missing')
    for slot, identifier in ids.items():
        item = json.loads(run('docker', 'inspect', identifier))[0]
        if (item['Name'].lstrip('/') != POST_NAMES[slot] or item['Config']['Labels'].get('asb.boot-fixture.owner') != token
                or item['State']['Running'] or item['HostConfig']['RestartPolicy']['Name'] != 'no'):
            raise FixtureError('fixture container was not quarantined')
    # The two actual recovery guards must refuse to run while marker is present.
    for command in (['/usr/bin/python3', str(ROOT / 'scripts/backup_service_guard.py'), '--recover', '--state-dir', str(STATE / 'backup-state')],
                    ['/usr/bin/python3', str(ROOT / 'scripts/provider_recovery_interlock.py')]):
        if subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120).returncode == 0:
            raise FixtureError('legacy recovery guard did not block')
    return {'status': 'BOOT_QUARANTINE_VERIFIED_ON_FIXTURE', 'production_changed': False,
            'mutation_marker_tested': record.get('test_mutation') is True,
            'real_provider_verified': False, 'daemon_quiescence_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('prepare', 'verify'))
    parser.add_argument('--token', required=True)
    parser.add_argument('--instance-id', required=True)
    parser.add_argument('--package')
    parser.add_argument('--privacy-source')
    parser.add_argument('--synthetic-image-id')
    parser.add_argument('--test-mutation', action='store_true')
    args = parser.parse_args()
    try:
        if args.phase == 'prepare':
            if not all((args.package, args.privacy_source, args.synthetic_image_id)):
                raise FixtureError('prepare inputs missing')
            result = prepare(args.token, args.instance_id, args.package, args.privacy_source,
                             args.synthetic_image_id, test_mutation=args.test_mutation)
        else:
            result = verify(args.token, args.instance_id)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        print(json.dumps({'status': 'FIXTURE_FAILED',
                          'reason': str(error) if isinstance(error, FixtureError) else type(error).__name__,
                          'production_changed': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
