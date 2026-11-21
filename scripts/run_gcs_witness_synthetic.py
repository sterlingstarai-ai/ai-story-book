"""Exercise two temporary GCS buckets with fictional data; never authorize restore.

This uses one approved Google project/account and therefore DOES NOT prove
independent administration or latest-head availability during a disaster.
Only this run's randomly named buckets and known objects may be removed.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from urllib.parse import quote

import httpx

PROJECT = 'gen-lang-client-0308507618'
from gcloud_operator_config import operator_gcloud_config
API = Path(__file__).resolve().parents[1] / 'apps' / 'api'
sys.path.insert(0, str(API))

from src.services.privacy_checkpoint_gcs import GCSCheckpointStore  # noqa: E402
from src.services.privacy_checkpoint_head import append_checkpoint_head, verify_anchored_checkpoint  # noqa: E402
from src.services.privacy_checkpoint_keys import issue_checkpoint_key, recover_checkpoint_key  # noqa: E402
from src.services.privacy_journal import JournalEntry, JournalError, JournalScan  # noqa: E402
from src.services.privacy_journal_checkpoint import _encode  # noqa: E402
from src.services.privacy_journal_verify import fingerprint_entries  # noqa: E402


def main():
    env = dict(os.environ, CLOUDSDK_CONFIG=operator_gcloud_config())
    result = {'status': 'FAILED', 'synthetic_data_only': True, 'same_google_account': True,
              'independent_administration_proven': False, 'restore_authorized': False}
    owned = {}
    known = {}
    cleanup = True
    nonce = secrets.token_hex(10)
    names = [f'asb-witness-synthetic-{nonce}-{suffix}' for suffix in ('a', 'b')]
    try:
        token = subprocess.run(['gcloud', 'auth', 'print-access-token'], env=env, capture_output=True,
                               check=True, timeout=20, text=True).stdout.strip()
        if not token or '\n' in token:
            raise RuntimeError('Cloud authentication unavailable')
        headers = {'Authorization': 'Bearer ' + token}
        with httpx.Client(timeout=httpx.Timeout(15, connect=10), trust_env=False, follow_redirects=False) as http:
            try:
                for name in names:
                    response = http.post('https://storage.googleapis.com/storage/v1/b', params={'project': PROJECT},
                        headers=headers, json={'name': name, 'location': 'ASIA-NORTHEAST3',
                            'iamConfiguration': {'uniformBucketLevelAccess': {'enabled': True}},
                            'labels': {'asb-synthetic': nonce}})
                    if response.status_code != 200:
                        raise RuntimeError('Synthetic bucket creation failed')
                    item = response.json()
                    if item.get('name') != name or item.get('labels', {}).get('asb-synthetic') != nonce:
                        raise RuntimeError('Synthetic bucket identity invalid')
                    owned[name] = item.get('timeCreated')
                    known[name] = set()
                witness, head_store = [GCSCheckpointStore(name, token_provider=lambda: token, client=http) for name in names]
                namespace, recovery_key, head_key = secrets.token_hex(16), secrets.token_bytes(32), secrets.token_bytes(32)
                key, key_ref = issue_checkpoint_key(witness, namespace=namespace, recovery_key=recovery_key)
                known[names[0]].add(f'privacy-checkpoint-keys/v1/{namespace}/{key_ref["key_id"]}')
                if recover_checkpoint_key(witness, namespace=namespace, key_id=key_ref['key_id'],
                        expected_sha256=key_ref['sha256'], recovery_key=recovery_key) != key:
                    raise RuntimeError('Synthetic key recovery failed')
                user = '00000000-0000-4000-8000-000000000001'
                first = JournalEntry('1' * 32, 'consent_revoke', user, 1)
                second = JournalEntry('2' * 32, 'account_delete', user, 2)
                scans = [JournalScan((first,), 0), JournalScan((first, second), 0)]
                heads = []
                for generation, scan in enumerate(scans, 1):
                    source = {'status': 'CURRENT_OUTBOX_MATCHES_JOURNAL', 'restore_authorized': False,
                              'event_count': len(scan.committed), 'journal_sha256': fingerprint_entries(scan.committed)}
                    name, blob = _encode(namespace, generation, key, source, scan, 100)
                    witness.create(name, blob)
                    known[names[0]].add(name)
                    try:
                        witness.create(name, b'overwrite')
                    except JournalError:
                        pass
                    else:
                        raise RuntimeError('GCS create-only overwrite was accepted')
                    checkpoint = {'status': 'FENCED_WITNESS_CHECKPOINT_STORED', 'restore_authorized': False,
                                  'namespace': namespace, 'generation': generation, 'sha256': hashlib.sha256(blob).hexdigest()}
                    head = append_checkpoint_head(head_store, namespace=namespace, key=head_key, checkpoint=checkpoint,
                                                  previous=heads[-1] if heads else None)
                    heads.append(head)
                    known[names[1]].add(f'privacy-checkpoint-heads/v1/{namespace}/{generation:020d}')
                args = {'namespace': namespace, 'head_key': head_key, 'checkpoint_key': key,
                        'trusted_head': heads[-1], 'now': 101, 'max_age': 10}
                check = verify_anchored_checkpoint(head_store, witness, scans[-1], candidate_head=heads[-1], **args)
                if check['status'] != 'ANCHORED_WITNESSED_PREFIX_MATCHES' or check['restore_authorized'] is not False:
                    raise RuntimeError('Synthetic head verification failed')
                for candidate, scan in ((heads[0], scans[0]), (heads[-1], scans[0])):
                    try:
                        verify_anchored_checkpoint(head_store, witness, scan, candidate_head=candidate, **args)
                    except JournalError:
                        pass
                    else:
                        raise RuntimeError('Synthetic rollback or lost event accepted')
                result.update(status='PASSED', create_only=True, key_recovered=True, chain_verified=True,
                              old_head_rejected=True, missing_event_rejected=True)
            finally:
                for bucket, created in owned.items():
                    try:
                        bucket_url = f'https://storage.googleapis.com/storage/v1/b/{bucket}'
                        metadata = http.get(bucket_url, headers=headers)
                        objlist = http.get(bucket_url + '/o', headers=headers, params={'maxResults': '1000'})
                        item, listing = metadata.json(), objlist.json()
                        if (metadata.status_code != 200 or objlist.status_code != 200
                                or item.get('name') != bucket or item.get('timeCreated') != created
                                or item.get('labels', {}).get('asb-synthetic') != nonce
                                or 'nextPageToken' in listing or not isinstance(listing.get('items', []), list)):
                            raise RuntimeError('Synthetic cleanup identity check failed')
                        found = listing.get('items', [])
                        if {o.get('name') for o in found} != known[bucket]:
                            raise RuntimeError('Synthetic cleanup object inventory mismatch')
                        for obj in found:
                            generation = obj.get('generation')
                            if not isinstance(generation, str) or not generation.isdigit():
                                raise RuntimeError('Synthetic object generation invalid')
                            response = http.delete(bucket_url + '/o/' + quote(obj['name'], safe=''), headers=headers,
                                                   params={'ifGenerationMatch': generation})
                            if response.status_code != 204:
                                raise RuntimeError('Synthetic object cleanup failed')
                        if http.delete(bucket_url, headers=headers).status_code != 204:
                            raise RuntimeError('Synthetic bucket cleanup failed')
                    except Exception:
                        cleanup = False
    except Exception as exc:
        result['error_type'] = type(exc).__name__
    result['owned_cleanup_complete'] = cleanup and len(owned) == 2
    if not result['owned_cleanup_complete']:
        result['status'] = 'FAILED'
        # Needed for manual inspection if a create response was lost. Never
        # delete an object whose ownership cannot be confirmed by its label.
        result['cleanup_inspection_bucket_names'] = names
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'PASSED' else 1


if __name__ == '__main__':
    sys.exit(main())
