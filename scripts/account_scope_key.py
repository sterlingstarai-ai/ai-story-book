"""Create or recover an inactive account-scope key without displaying secrets.

The envelope, its reference and the separate recovery key need independently
controlled storage. This command neither activates the feature nor proves that
its key or backups will survive a disaster. Existing files are never replaced.
"""
import argparse
import hashlib
import hmac
import json
import re
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from recover_witness_key import write_new_private_file, write_new_private_key
from run_scheduled_backup import private_file

_MAGIC = b'ASB-SCOPE-KEY-V1\0'
_HASH = re.compile(r'^[0-9a-f]{64}$')
_NAMESPACE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def _aad(namespace):
    if not isinstance(namespace, str) or not _NAMESPACE.fullmatch(namespace):
        raise ValueError('Invalid namespace')
    return _MAGIC + namespace.encode('ascii')


def issue(*, recovery_key, namespace):
    if not isinstance(recovery_key, bytes) or len(recovery_key) != 32:
        raise ValueError('Invalid recovery key')
    key, nonce = secrets.token_bytes(32), secrets.token_bytes(12)
    envelope = _MAGIC + nonce + AESGCM(recovery_key).encrypt(nonce, key, _aad(namespace))
    reference = {'version': 1, 'namespace': namespace, 'scope_key_sha256': hashlib.sha256(key).hexdigest(),
                 'envelope_sha256': hashlib.sha256(envelope).hexdigest()}
    return key, envelope, reference


def recover(*, recovery_key, envelope, reference):
    if (not isinstance(recovery_key, bytes) or len(recovery_key) != 32
            or not isinstance(reference, dict)
            or set(reference) != {'version', 'namespace', 'scope_key_sha256', 'envelope_sha256'}
            or type(reference['version']) is not int or reference['version'] != 1
            or not isinstance(reference['scope_key_sha256'], str) or not _HASH.fullmatch(reference['scope_key_sha256'])
            or not isinstance(reference['envelope_sha256'], str) or not _HASH.fullmatch(reference['envelope_sha256'])
            or not isinstance(envelope, bytes) or len(envelope) != len(_MAGIC) + 12 + 32 + 16
            or not envelope.startswith(_MAGIC)
            or not hmac.compare_digest(hashlib.sha256(envelope).hexdigest(), reference['envelope_sha256'])):
        raise ValueError('Invalid recovery material')
    start = len(_MAGIC)
    key = AESGCM(recovery_key).decrypt(envelope[start:start + 12], envelope[start + 12:], _aad(reference['namespace']))
    if len(key) != 32 or not hmac.compare_digest(hashlib.sha256(key).hexdigest(), reference['scope_key_sha256']):
        raise ValueError('Recovered key pin does not match')
    return key


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('issue', 'recover'))
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--recovery-key-file', required=True, type=Path)
    parser.add_argument('--key-output', required=True, type=Path)
    parser.add_argument('--envelope-file', required=True, type=Path)
    parser.add_argument('--reference-file', required=True, type=Path)
    parser.add_argument('--namespace')
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({'status': 'DRY_RUN', 'activated': False}))
        return 0
    try:
        paths = [args.recovery_key_file, args.key_output, args.envelope_file, args.reference_file]
        if any(not path.is_absolute() for path in paths) or len({str(path) for path in paths}) != len(paths):
            raise ValueError('Distinct absolute paths are required')
        recovery_key = private_file(args.recovery_key_file, max_bytes=32)
        if args.operation == 'issue':
            key, envelope, reference = issue(recovery_key=recovery_key, namespace=args.namespace)
            # A partial run is inactive. Files that exist are never overwritten.
            write_new_private_file(args.envelope_file, envelope)
            write_new_private_file(args.reference_file, json.dumps(reference, sort_keys=True).encode() + b'\n')
            write_new_private_key(args.key_output, key)
            status = 'KEY_ISSUED_INACTIVE'
        else:
            if args.namespace is not None:
                raise ValueError('Namespace must come from the trusted reference')
            envelope = private_file(args.envelope_file, max_bytes=1024)
            reference = json.loads(private_file(args.reference_file, max_bytes=1024))
            key = recover(recovery_key=recovery_key, envelope=envelope, reference=reference)
            write_new_private_key(args.key_output, key)
            status = 'KEY_RECOVERED_INACTIVE'
        print(json.dumps({'status': status, 'activated': False}))
        return 0
    except Exception:
        print(json.dumps({'status': 'KEY_OPERATION_FAILED', 'activated': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
