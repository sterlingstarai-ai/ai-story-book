"""Issue a new witness key and export its encrypted offline recovery envelope.

Inputs and outputs are private files; no secret is printed. Completion does
not prove that the recovery key, reference, and envelope have been moved to a
separately administered, durable location. Do not activate the key until that
independent copy has been verified and recovery tested.
"""
import argparse
import hashlib
import hmac
import json
from pathlib import Path
import sys

from recover_witness_key import write_new_private_file, write_new_private_key
from run_scheduled_backup import private_file

API = Path(__file__).resolve().parents[1] / 'apps' / 'api'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recovery-key-file', required=True, type=Path)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--envelope-bucket', required=True)
    parser.add_argument('--key-output', required=True, type=Path)
    parser.add_argument('--reference-output', required=True, type=Path)
    parser.add_argument('--envelope-output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        recovery_key = private_file(args.recovery_key_file, max_bytes=32)
        sys.path.insert(0, str(API))
        from src.services.privacy_checkpoint_gcs import GCSCheckpointStore
        from src.services.privacy_checkpoint_keys import issue_checkpoint_key

        store = GCSCheckpointStore(args.envelope_bucket)
        try:
            key, reference = issue_checkpoint_key(store, namespace=args.namespace, recovery_key=recovery_key)
            name = f'privacy-checkpoint-keys/v1/{reference["namespace"]}/{reference["key_id"]}'
            blob = store.read(name)
            if not hmac.compare_digest(hashlib.sha256(blob).hexdigest(), reference['sha256']):
                raise ValueError('Envelope export mismatch')
        finally:
            store.close()
        # Encrypted recovery material is written first. Any incomplete run is
        # inactive and its outputs must not overwrite pre-existing files.
        write_new_private_file(args.envelope_output, blob)
        write_new_private_file(args.reference_output, json.dumps(reference, sort_keys=True).encode() + b'\n')
        write_new_private_key(args.key_output, key)
        print(json.dumps({'status': 'KEY_ENROLLED_INACTIVE', 'restore_authorized': False}))
        return 0
    except Exception:
        print(json.dumps({'status': 'KEY_ENROLLMENT_INCOMPLETE', 'restore_authorized': False}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
