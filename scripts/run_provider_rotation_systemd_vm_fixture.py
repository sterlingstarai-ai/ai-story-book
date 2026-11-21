#!/usr/bin/env python3
"""Disposable GCE/systemd experiment; never operates on the pilot VM.

Uses synthetic state and the repository's actual marker/lock guards. It does
not run Docker or test production traffic, keys, containers, or rollback. The
version using a Docker-ordering stand-in has not completed an end-to-end run.
Requires an explicitly selected gcloud account/project and --execute.
"""

import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'gen-lang-client-0308507618'
ZONE = 'us-central1-c'
GCLOUD = '/opt/homebrew/bin/gcloud'
from gcloud_operator_config import operator_gcloud_config


def cloud(*args, timeout=90):
    env = os.environ.copy()
    env['CLOUDSDK_CONFIG'] = operator_gcloud_config()
    return subprocess.run([GCLOUD, *args, '--project', PROJECT, '--quiet'],
                          env=env, text=True, capture_output=True, timeout=timeout)


def startup_script():
    sources = {}
    for name in ('backup_service_guard.py', 'narration_marker_exec_condition.py'):
        sources[name] = base64.b64encode((ROOT / 'scripts' / name).read_bytes()).decode()
    payload = base64.b64encode(json.dumps(sources).encode()).decode()
    return r'''#!/bin/bash
set -eu
exec >/dev/ttyS0 2>&1
echo ASB_FIXTURE_STARTUP
if test -f /var/lib/asb-rotation-fixture/phase; then exit 0; fi
mkdir -m 700 -p /var/lib/asb-rotation-fixture /var/lib/ai-story-book/provider-rotation /opt/ai-story-book/current/scripts
python3 - <<'PY'
import base64, json, os
from pathlib import Path
p = json.loads(base64.b64decode('PAYLOAD'))
for name, data in p.items():
    Path('/opt/ai-story-book/current/scripts', name).write_bytes(base64.b64decode(data))
marker = Path('/var/lib/ai-story-book/provider-rotation/recovery.json')
with marker.open('x') as f:
    f.write('{"synthetic":true}\n'); f.flush(); os.fsync(f.fileno())
os.chmod(marker, 0o600)
fd = os.open(marker.parent, os.O_RDONLY); os.fsync(fd); os.close(fd)
Path('/var/lib/asb-rotation-fixture/first-boot').write_text(Path('/proc/sys/kernel/random/boot_id').read_text())
PY
python3 - <<'PY'
import os, sys
from pathlib import Path
sys.path.insert(0, '/opt/ai-story-book/current/scripts')
import backup_service_guard as b
g = b.BackupServiceGuard(Path('/var/lib/asb-rotation-fixture/guard'), None)
fd = g._locked()
try:
    try: g._locked()
    except b.GuardError: pass
    else: raise RuntimeError('lock did not exclude competing recovery')
    try: b.assert_no_narration_recovery()
    except b.GuardError: pass
    else: raise RuntimeError('marker did not block recovery')
finally: os.close(fd)
Path('/var/lib/asb-rotation-fixture/lock-passed').touch()
PY
cat > /etc/systemd/system/asb-fixture-docker.service <<'UNIT'
[Unit]
Description=Test-only Docker ordering stand-in (no containers)
[Service]
Type=oneshot
ExecStart=/usr/bin/true
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/asb-fixture-quarantine.service <<'UNIT'
[Unit]
After=asb-fixture-docker.service
Requires=asb-fixture-docker.service
Before=asb-fixture-backup.service asb-fixture-privacy.service
[Service]
Type=oneshot
ExecStart=/usr/bin/test -f /var/lib/ai-story-book/provider-rotation/recovery.json
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
for unit in backup privacy; do
cat > /etc/systemd/system/asb-fixture-$unit.service <<'UNIT'
[Unit]
After=asb-fixture-docker.service
Requires=asb-fixture-docker.service
UNIT
if test "$unit" = privacy; then echo 'Before=asb-fixture-backup.service' >> /etc/systemd/system/asb-fixture-$unit.service; fi
cat >> /etc/systemd/system/asb-fixture-$unit.service <<'UNIT'
[Service]
Type=oneshot
ExecCondition=/usr/bin/python3 /opt/ai-story-book/current/scripts/narration_marker_exec_condition.py
ExecStart=/usr/bin/touch /var/lib/asb-rotation-fixture/UNSAFE-OLD-RESTART
[Install]
WantedBy=multi-user.target
UNIT
done
cat > /usr/local/bin/asb-fixture-verify <<'PY'
#!/usr/bin/python3
import json, re, subprocess
from pathlib import Path
p = Path('/var/lib/asb-rotation-fixture')
def show(unit, field):
    return subprocess.check_output(['systemctl','show',unit,'-p',field,'--value'], text=True).strip()
checks = {
    'actual_reboot': (p / 'first-boot').read_text() != Path('/proc/sys/kernel/random/boot_id').read_text(),
    'quarantine_active': show('asb-fixture-quarantine.service', 'ActiveState') == 'active',
    'backup_skipped': bool(re.search(r'status=1(?:[/; }]|$)', show('asb-fixture-backup.service', 'ExecCondition'))),
    'privacy_skipped': bool(re.search(r'status=1(?:[/; }]|$)', show('asb-fixture-privacy.service', 'ExecCondition'))),
    'no_old_restart': not (p / 'UNSAFE-OLD-RESTART').exists(),
    'lock_and_marker': (p / 'lock-passed').is_file(),
}
result = {'checks': checks, 'real_docker': False, 'production_authorized': False,
          'condition_details': {u: show('asb-fixture-' + u + '.service', 'ExecCondition')
                                for u in ('backup', 'privacy')}}
with open('/dev/ttyS0','w') as serial:
    serial.write('ASB_ROT_FIXTURE:' + json.dumps(result, sort_keys=True) + '\n')
PY
chmod 755 /usr/local/bin/asb-fixture-verify
cat > /etc/systemd/system/asb-fixture-verify.service <<'UNIT'
[Unit]
After=asb-fixture-quarantine.service asb-fixture-backup.service asb-fixture-privacy.service
Wants=asb-fixture-quarantine.service asb-fixture-backup.service asb-fixture-privacy.service
[Service]
Type=oneshot
ExecStart=/usr/local/bin/asb-fixture-verify
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable asb-fixture-docker.service asb-fixture-quarantine.service asb-fixture-backup.service asb-fixture-privacy.service asb-fixture-verify.service
touch /var/lib/asb-rotation-fixture/phase
sync
systemd-run --on-active=3s /usr/bin/systemctl reboot
'''.replace('PAYLOAD', payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='create one disposable VM')
    args = parser.parse_args()
    if not args.execute:
        print('Dry run: no cloud resources created. Pass --execute to run the synthetic fixture.')
        return 0
    token = secrets.token_hex(8)
    name = 'asb-rotation-fixture-' + token
    identity = None
    result = None
    try:
        with tempfile.TemporaryDirectory(prefix='asb-fixture-') as temp:
            metadata = Path(temp) / 'startup.sh'
            metadata.write_text(startup_script())
            create = cloud('compute', 'instances', 'create', name, '--zone', ZONE,
                           '--machine-type', 'e2-micro', '--image-family', 'debian-12',
                           '--image-project', 'debian-cloud', '--boot-disk-size', '10GB',
                           '--boot-disk-type', 'pd-standard', '--no-address',
                           '--no-service-account', '--no-scopes', '--max-run-duration', '1800s',
                           '--instance-termination-action', 'STOP',
                           '--labels', f'asb-purpose=rotation-fixture,asb-run={token}',
                           '--metadata-from-file', f'startup-script={metadata}',
                           '--format=json', timeout=180)
            if create.returncode:
                print('CREATE_FAILED:', create.stderr.strip())
                return 1
            info = json.loads(create.stdout)[0]
            identity = str(info['id'])
            print('Created isolated fixture:', name, 'id:', identity, flush=True)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            serial = cloud('compute', 'instances', 'get-serial-port-output', name,
                           '--zone', ZONE, '--port', '1', '--start', '0', timeout=45)
            if serial.returncode == 0:
                for line in serial.stdout.splitlines():
                    if line.startswith('ASB_ROT_FIXTURE:'):
                        result = json.loads(line.split(':', 1)[1])
            if result is not None:
                break
            time.sleep(10)
        print('RESULT:', json.dumps(result, sort_keys=True), flush=True)
        expected = {'actual_reboot', 'quarantine_active', 'backup_skipped',
                    'privacy_skipped', 'no_old_restart', 'lock_and_marker'}
        if (not result or set(result.get('checks', {})) != expected
                or any(value is not True for value in result['checks'].values())
                or result.get('production_authorized') is not False
                or result.get('real_docker') is not False):
            return 1
        return 0
    finally:
        if identity is not None:
            cleanup_ok = False
            try:
                describe = cloud('compute', 'instances', 'describe', name, '--zone', ZONE,
                                 '--format=json')
                if describe.returncode:
                    print('CLEANUP_NOT_VERIFIED:', name, 'describe failed', flush=True)
                else:
                    instance = json.loads(describe.stdout)
                    labels = instance.get('labels', {})
                    if (str(instance.get('id')) != identity or labels.get('asb-run') != token
                            or labels.get('asb-purpose') != 'rotation-fixture'):
                        print('CLEANUP_REFUSED: ownership mismatch', name, flush=True)
                    else:
                        delete = cloud('compute', 'instances', 'delete', name, '--zone', ZONE,
                                       '--delete-disks=boot', timeout=180)
                        if delete.returncode:
                            print('CLEANUP_FAILED:', name, delete.stderr.strip(), flush=True)
                        else:
                            print('CLEANUP_COMPLETE:', name, flush=True)
                            cleanup_ok = True
            except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
                print('CLEANUP_FAILED:', name, type(exc).__name__, flush=True)
            if not cleanup_ok:
                raise SystemExit(1)


if __name__ == '__main__':
    raise SystemExit(main())
