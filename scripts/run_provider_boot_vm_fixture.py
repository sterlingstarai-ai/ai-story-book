"""Run one synthetic provider boot fixture on one disposable GCE VM.

Explicit --execute is required. A durable singleton intent prevents duplicate
runs. The one VM and its auto-deleted boot disk are checked by identity and
finally cleaned. An uncertain create/delete is reported as uncertain, never as
successful cleanup. No production data, environment file, or key is sent.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import time

PROJECT = 'gen-lang-client-0308507618'
ZONE = 'us-central1-c'
INITIAL_JOURNAL = Path('/private/tmp/asb-provider-boot-vm-singleton.json')
RETEST_JOURNAL = Path('/private/tmp/asb-provider-boot-vm-retest.json')
REPAIR_JOURNAL = Path('/private/tmp/asb-provider-boot-vm-repair.json')
JOURNAL = INITIAL_JOURNAL
LOCK = Path('/private/tmp/asb-provider-boot-vm-singleton.lock')


class FixtureError(RuntimeError):
    pass


def gcloud(*args, timeout=90):
    env = dict(os.environ, CLOUDSDK_CORE_DISABLE_FILE_LOGGING='true')
    return subprocess.run(['gcloud', '--quiet', '--project', PROJECT, *args], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                          check=True, text=True).stdout


def resource(kind, name):
    # A successful list response, parsed locally by exact name, distinguishes
    # confirmed absence from a CLI/permission/network failure.
    obj = json.loads(gcloud('compute', kind, 'list', '--filter', f'name=({name})',
                            '--format=json', timeout=60))
    if not isinstance(obj, list):
        raise FixtureError('resource list invalid')
    exact = [item for item in obj if item.get('name') == name and
             item.get('zone', '').rsplit('/', 1)[-1] == ZONE]
    if len(exact) > 1:
        raise FixtureError('resource identity ambiguous')
    return exact[0] if exact else None


def persist(record):
    data = (json.dumps(record, sort_keys=True) + '\n').encode()
    temporary = JOURNAL.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, JOURNAL)
        dfd = os.open(JOURNAL.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def startup(payload, digest, token, *, test_mutation=False):
    encoded = base64.b64encode(payload).decode('ascii')
    mutation_flag = '--test-mutation' if test_mutation else ''
    expected_status = ('BOOT_MUTATION_QUARANTINE_VERIFIED_ON_FIXTURE' if test_mutation
                       else 'BOOT_QUARANTINE_VERIFIED_ON_FIXTURE')
    # The payload consists only of pinned source and synthetic test code.
    return f'''#!/bin/bash
set -euo pipefail
exec >/dev/ttyS0 2>&1
trap 'printf "ASB_RESULT=%s\\n" "FIXTURE_FAILED"' ERR
export DEBIAN_FRONTEND=noninteractive
work=/opt/asb-fixture-payload
if [ ! -d "$work" ]; then
  install -d -m 700 "$work"
  base64 -d > "$work/payload.tar.gz" <<'ASB_PAYLOAD'
{encoded}
ASB_PAYLOAD
  printf '%s  %s\\n' '{digest}' "$work/payload.tar.gz" | sha256sum -c - >/dev/null
  tar -xzf "$work/payload.tar.gz" -C "$work" --no-same-owner
  apt-get update -qq >/dev/null
  apt-get install -y -qq docker.io curl >/dev/null
  systemctl enable --now docker >/dev/null
  docker pull busybox:1.36 >/dev/null
  image=$(docker image inspect busybox:1.36 --format '{{{{.Id}}}}')
  id=$(curl --silent --fail -H 'Metadata-Flavor: Google' http://169.254.169.254/computeMetadata/v1/instance/id)
  python3 "$work/provider_boot_guest_fixture.py" prepare --token '{token}' --instance-id "$id" --package "$work/package" --privacy-source "$work/legacy_privacy.py" --synthetic-image-id "$image" {mutation_flag}
  sync
  touch "$work/prepared"
  sync
  systemctl reboot
elif [ -f "$work/prepared" ]; then
  id=$(curl --silent --fail -H 'Metadata-Flavor: Google' http://169.254.169.254/computeMetadata/v1/instance/id)
  # Startup scripts and the recovery units may start concurrently on boot.
  # Wait for the actual unit invocation to complete before inspecting it.
  complete=false
  for _ in $(seq 1 180); do
    state=$(systemctl show asb-provider-rotation-quarantine.service --property=ActiveState --value)
    stamp=$(systemctl show asb-provider-rotation-quarantine.service --property=ExecMainStartTimestampMonotonic --value)
    if [ "${{stamp:-0}}" -gt 0 ] && [ "$state" != activating ]; then complete=true; break; fi
    sleep 1
  done
  [ "$complete" = true ]
  if result=$(python3 "$work/provider_boot_guest_fixture.py" verify --token '{token}' --instance-id "$id"); then :; else
    printf 'ASB_DETAIL=%s\\n' "$result"
    printf 'ASB_RESULT=%s\\n' 'FIXTURE_FAILED'
    exit 1
  fi
  if printf '%s' "$result" | grep -q 'BOOT_QUARANTINE_VERIFIED_ON_FIXTURE' && \
     {{ [ '{str(test_mutation).lower()}' = 'false' ] || printf '%s' "$result" | grep -q '"mutation_marker_tested": true'; }}; then
    printf 'ASB_RESULT=%s\\n' '{expected_status}'
  else
    printf 'ASB_RESULT=%s\\n' 'FIXTURE_FAILED'
  fi
fi
'''


def own_instance(instance, name, token):
    if (not isinstance(instance, dict) or instance.get('name') != name
            or instance.get('labels', {}).get('asb-fixture-owner') != token
            or not re.fullmatch(r'[0-9]+', str(instance.get('id', '')))):
        raise FixtureError('VM ownership cannot be confirmed')
    boots = [disk for disk in instance.get('disks', []) if disk.get('boot') is True]
    if (len(boots) != 1 or boots[0].get('source', '').rsplit('/', 1)[-1] != name
            or boots[0].get('autoDelete') is not True):
        raise FixtureError('boot disk identity cannot be confirmed')
    return str(instance['id'])


def run_fixture(payload_path, digest, *, retest=False, repair_retest=False):
    payload_file = Path(payload_path)
    if (payload_file.is_symlink() or not payload_file.is_file()
            or payload_file.stat().st_uid != os.geteuid() or payload_file.stat().st_mode & 0o077):
        raise FixtureError('private payload required')
    payload = payload_file.read_bytes()
    if len(payload) > 160000 or hashlib.sha256(payload).hexdigest() != digest:
        raise FixtureError('payload digest or size mismatch')
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    work = None
    record = None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if repair_retest and not retest:
            raise FixtureError('repair requires mutation retest')
        if retest:
            journals = (INITIAL_JOURNAL, RETEST_JOURNAL) if repair_retest else (INITIAL_JOURNAL,)
            for previous_path in journals:
                previous = json.loads(previous_path.read_text())
                if (previous.get('cleanup_confirmed') is not True
                        or previous.get('vm_absent_observed') is not True
                        or previous.get('disk_absent_observed') is not True):
                    raise FixtureError('the previous fixture cleanup is not confirmed')
        if JOURNAL.exists() or JOURNAL.is_symlink():
            raise FixtureError('a previous singleton intent exists; inspect it before another run')
        token = secrets.token_hex(16)
        name = 'asb-boot-fixture-' + token[:16]
        record = {'version': 1, 'project': PROJECT, 'zone': ZONE, 'name': name,
                  'owner_token': token, 'vm_id': None, 'disk_id': None,
                  'create_confirmed': False, 'cleanup_confirmed': False,
                  'result': 'NOT_RUN', 'cost_cap': 'one e2-small and one 10GB standard disk; VM auto-stop at 30 minutes'}
        persist(record)
        if resource('instances', name) is not None or resource('disks', name) is not None:
            raise FixtureError('generated resource name already exists')
        work = Path(tempfile.mkdtemp(prefix='asb-boot-vm-', dir='/private/tmp'))
        boot = work / 'startup.sh'
        boot.write_text(startup(payload, digest, token, test_mutation=retest))
        os.chmod(boot, 0o600)
        record['result'] = 'CREATE_REQUEST_PENDING'
        persist(record)
        try:
            gcloud('compute', 'instances', 'create', name, '--zone', ZONE,
                   '--machine-type=e2-small', '--image-family=debian-12', '--image-project=debian-cloud',
                   '--boot-disk-size=10GB', '--boot-disk-type=pd-standard',
                   '--no-service-account', '--no-scopes', '--max-run-duration=1800s',
                   '--instance-termination-action=STOP', '--labels', 'asb-fixture-owner=' + token,
                   '--metadata', 'asb-fixture-owner=' + token,
                   '--metadata-from-file', 'startup-script=' + str(boot), '--format=value(id)', timeout=300)
            record['create_confirmed'] = True
            record['result'] = 'CREATED_WAITING_FOR_RESULT'
            persist(record)
        except (subprocess.SubprocessError, OSError):
            # A lost response may still create a VM. The final discovery and
            # cleanup tries to remove an exactly identified one but never calls
            # an absence proof final while creation is still uncertain.
            record['result'] = 'CREATE_RESPONSE_UNCERTAIN'
            persist(record)
            raise FixtureError('creation result uncertain') from None
        instance = resource('instances', name)
        record['vm_id'] = own_instance(instance, name, token)
        disk = resource('disks', name)
        if not disk or not re.fullmatch(r'[0-9]+', str(disk.get('id', ''))):
            raise FixtureError('boot disk could not be identified')
        if not any(str(x).rsplit('/', 1)[-1] == name for x in disk.get('users', [])):
            raise FixtureError('boot disk is not attached to fixture VM')
        record['disk_id'] = str(disk['id'])
        persist(record)
        expected_status = ('BOOT_MUTATION_QUARANTINE_VERIFIED_ON_FIXTURE' if retest
                           else 'BOOT_QUARANTINE_VERIFIED_ON_FIXTURE')
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline:
            try:
                output = gcloud('compute', 'instances', 'get-serial-port-output', name,
                                '--zone', ZONE, '--port=1', timeout=45)
                if 'ASB_RESULT=' + expected_status in output:
                    record['result'] = expected_status
                    break
                if 'ASB_RESULT=FIXTURE_FAILED' in output:
                    record['result'] = 'FIXTURE_FAILED'
                    details = re.findall(r'ASB_DETAIL=(\{[^\r\n]{0,1000}\})', output)
                    if details:
                        try:
                            detail = json.loads(details[-1])
                            allowed = {'fixture has not rebooted', 'durable marker disappeared',
                                       'durable mutation marker disappeared', 'quarantine unit did not succeed',
                                       'recovery unit ordering missing', 'fixture container was not quarantined',
                                       'legacy recovery guard did not block', 'fixture identity record invalid'}
                            if (detail.get('status') == 'FIXTURE_FAILED'
                                    and detail.get('reason') in allowed):
                                record['fixture_detail'] = detail['reason']
                        except (TypeError, ValueError):
                            pass
                    break
            except (subprocess.SubprocessError, OSError):
                pass
            time.sleep(15)
        else:
            record['result'] = 'RESULT_TIMEOUT'
        persist(record)
    finally:
        if record is not None:
            try:
                instance = resource('instances', record['name'])
                # If create timed out, allow a bounded interval for a late
                # resource to appear. Even observed absence afterward cannot
                # prove the abandoned create operation will never complete.
                if instance is None and not record['create_confirmed'] and record['result'] in ('CREATE_RESPONSE_UNCERTAIN', 'CREATE_REQUEST_PENDING'):
                    discovery_deadline = time.monotonic() + 180
                    while instance is None and time.monotonic() < discovery_deadline:
                        time.sleep(10)
                        instance = resource('instances', record['name'])
                if instance:
                    current = own_instance(instance, record['name'], record['owner_token'])
                    if record['vm_id'] is not None and current != record['vm_id']:
                        raise FixtureError('VM identity changed during fixture')
                    record['vm_id'] = current
                    disk = resource('disks', record['name'])
                    if disk:
                        did = str(disk.get('id', ''))
                        if (not re.fullmatch(r'[0-9]+', did)
                                or (record['disk_id'] is not None and record['disk_id'] != did)
                                or not any(str(x).rsplit('/', 1)[-1] == record['name'] for x in disk.get('users', []))):
                            raise FixtureError('disk identity changed during fixture')
                        record['disk_id'] = did
                    persist(record)
                    gcloud('compute', 'instances', 'delete', record['name'], '--zone', ZONE,
                           '--delete-disks=all', timeout=300)
                vm_absent = resource('instances', record['name']) is None
                remaining_disk = resource('disks', record['name'])
                if remaining_disk is not None and vm_absent:
                    # Only a disk whose immutable ID was recorded while it was
                    # attached to our confirmed VM may be deleted separately.
                    if (record['disk_id'] is None or str(remaining_disk.get('id', '')) != record['disk_id']
                            or remaining_disk.get('users')):
                        raise FixtureError('remaining disk identity or attachment is uncertain')
                    gcloud('compute', 'disks', 'delete', record['name'], '--zone', ZONE, timeout=300)
                    remaining_disk = resource('disks', record['name'])
                disk_absent = remaining_disk is None
                record['cleanup_confirmed'] = bool(vm_absent and disk_absent and record['create_confirmed'])
                record['vm_absent_observed'] = vm_absent
                record['disk_absent_observed'] = disk_absent
            except Exception:
                record['cleanup_confirmed'] = False
            finally:
                persist(record)
        if work is not None:
            shutil.rmtree(work)
        os.close(fd)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--retest', action='store_true', help='single mutation-guard retest after confirmed initial cleanup')
    parser.add_argument('--repair-retest', action='store_true', help='one repaired-fixture retry after both prior cleanups')
    parser.add_argument('--payload', required=True)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({'status': 'EXECUTION_NOT_REQUESTED', 'cloud_resources_created': False}))
        return 0
    global JOURNAL
    if args.retest and args.repair_retest:
        parser.error('choose only one retest mode')
    if args.repair_retest:
        JOURNAL = REPAIR_JOURNAL
    elif args.retest:
        JOURNAL = RETEST_JOURNAL
    try:
        result = run_fixture(args.payload, args.sha256, retest=args.retest or args.repair_retest,
                             repair_retest=args.repair_retest)
        print(json.dumps({key: result.get(key) for key in ('result', 'create_confirmed', 'cleanup_confirmed',
                                                            'vm_absent_observed', 'disk_absent_observed', 'cost_cap')}))
        return 0 if result['result'] in ('BOOT_QUARANTINE_VERIFIED_ON_FIXTURE',
                                         'BOOT_MUTATION_QUARANTINE_VERIFIED_ON_FIXTURE') and result['cleanup_confirmed'] else 1
    except Exception:
        print(json.dumps({'status': 'FIXTURE_INCOMPLETE', 'consult_owned_journal': str(JOURNAL)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
