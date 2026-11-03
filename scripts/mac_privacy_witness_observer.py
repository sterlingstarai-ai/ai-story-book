"""Check an externally supplied signed witness observation on a second host.

No production key or record is copied by this script. Source reachability and
independent administration are not proven; a missing/stale file alerts and
restoration is never authorized. Requires a separately authenticated feed and
trusted head file provisioned outside this script.
"""
import argparse
import json
from pathlib import Path
import sys
import time

from cryptography.hazmat.primitives.serialization import load_pem_public_key

from run_scheduled_backup import private_file

API = Path(__file__).resolve().parents[1] / 'apps' / 'api'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--receipt-file', type=Path)
    parser.add_argument('--public-key-file', type=Path)
    parser.add_argument('--trusted-reference-file', type=Path)
    parser.add_argument('--max-age', type=int, default=600)
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({'status': 'DISABLED', 'restore_authorized': False}))
        return 0
    try:
        if not all((args.receipt_file, args.public_key_file, args.trusted_reference_file)):
            raise ValueError('Missing observer configuration')
        receipt = json.loads(private_file(args.receipt_file, max_bytes=4096))
        reference = json.loads(private_file(args.trusted_reference_file, max_bytes=1024))
        public_key = load_pem_public_key(private_file(args.public_key_file, max_bytes=1024))
        if (not isinstance(reference, dict) or set(reference) != {'version', 'namespace', 'head'}
                or type(reference['version']) is not int or reference['version'] != 1):
            raise ValueError('Invalid independent reference')
        sys.path.insert(0, str(API))
        from src.services.privacy_witness_receipt import verify_receipt
        result = verify_receipt(public_key, receipt, namespace=reference['namespace'], trusted_head=reference['head'],
                                now=int(time.time()), max_age=args.max_age)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({'status': 'ALERT', 'source_reachability': 'UNVERIFIED', 'restore_authorized': False},
                         sort_keys=True))
        return 1


if __name__ == '__main__':
    sys.exit(main())
