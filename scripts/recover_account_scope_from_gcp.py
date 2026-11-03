"""Recover an inactive scope key from pinned Google Secret Manager versions.

The Cloud SDK must already be authenticated by an authorized operator. This
uses numeric version 1, captures bytes only in memory, never prints secrets,
refuses to replace a file, and does not activate any application feature.
"""
import argparse
import base64
import binascii
import hmac
import json
from pathlib import Path
import re
import subprocess

from account_scope_key import recover
from recover_witness_key import write_new_private_key

_SECRET = re.compile(r'^[A-Za-z0-9_-]{1,255}$')
_PROJECT = re.compile(r'^[a-z][a-z0-9-]{4,28}[a-z0-9]$')
_HASH = re.compile(r'^[0-9a-f]{64}$')


def read_version(project, name):
    if not _PROJECT.fullmatch(project) or not _SECRET.fullmatch(name):
        raise ValueError('Invalid resource name')
    result = subprocess.run(['gcloud', 'secrets', 'versions', 'access', '1', '--project', project,
                             '--secret', name, '--format=get(payload.data)', '--quiet'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=60)
    encoded = result.stdout.strip()
    if not encoded or len(encoded) > 2048:
        raise ValueError('Invalid secret data')
    try:
        return base64.b64decode(encoded + b'=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
    except binascii.Error:
        raise ValueError('Invalid secret encoding') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--project', required=True)
    parser.add_argument('--recovery-secret', required=True)
    parser.add_argument('--envelope-secret', required=True)
    parser.add_argument('--reference-secret', required=True)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--expected-key-sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({'status': 'DRY_RUN', 'activated': False}))
        return 0
    try:
        names = (args.recovery_secret, args.envelope_secret, args.reference_secret)
        if len(set(names)) != 3 or not _HASH.fullmatch(args.expected_key_sha256) or not args.output.is_absolute():
            raise ValueError('Invalid recovery settings')
        recovery_key = read_version(args.project, args.recovery_secret)
        envelope = read_version(args.project, args.envelope_secret)
        reference = json.loads(read_version(args.project, args.reference_secret))
        if (not isinstance(reference, dict) or reference.get('namespace') != args.namespace
                or not isinstance(reference.get('scope_key_sha256'), str)
                or not hmac.compare_digest(reference['scope_key_sha256'], args.expected_key_sha256)):
            raise ValueError('Reference does not match operator pin')
        key = recover(recovery_key=recovery_key, envelope=envelope, reference=reference)
        write_new_private_key(args.output, key)
        print(json.dumps({'status': 'KEY_RECOVERED_INACTIVE', 'activated': False}))
        return 0
    except Exception:
        print(json.dumps({'status': 'RECOVERY_FAILED', 'activated': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
