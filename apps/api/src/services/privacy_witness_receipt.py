"""Signed, non-authorizing witness observations for a second machine.

A signature proves only that a holder of the signing key created the receipt.
It does not prove current source reachability, correct source selection, key
independence, or that newer records were not lost before the observation.
"""
import base64
import hmac
import json
import re

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from src.services.privacy_journal import JournalError

_ID = re.compile(r'^[0-9a-f]{32}$')
_HASH = re.compile(r'^[0-9a-f]{64}$')


def _payload(namespace, head, observed_at):
    if (not isinstance(namespace, str) or not _ID.fullmatch(namespace) or not isinstance(head, dict)
            or set(head) != {'sequence', 'sha256'} or type(head['sequence']) is not int
            or not 1 <= head['sequence'] <= 256 or not isinstance(head['sha256'], str)
            or not _HASH.fullmatch(head['sha256']) or type(observed_at) is not int or observed_at < 0):
        raise JournalError('Witness receipt input is invalid')
    return {'version': 1, 'namespace': namespace, 'head': head, 'observed_at': observed_at,
            'status': 'SNAPSHOT_MATCHES', 'restore_authorized': False}


def _bytes(payload):
    return json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()


def sign_receipt(private_key, *, namespace, head, observed_at, observation):
    if (not isinstance(private_key, Ed25519PrivateKey) or not isinstance(observation, dict)
            or set(observation) != {'status', 'restore_authorized'}
            or observation['status'] != 'SNAPSHOT_MATCHES' or observation['restore_authorized'] is not False):
        raise JournalError('Witness observation cannot be signed')
    payload = _payload(namespace, head, observed_at)
    return {'payload': payload, 'signature': base64.b64encode(private_key.sign(_bytes(payload))).decode('ascii')}


def verify_receipt(public_key, receipt, *, namespace, trusted_head, now, max_age):
    try:
        if (not isinstance(public_key, Ed25519PublicKey) or not isinstance(receipt, dict)
                or set(receipt) != {'payload', 'signature'} or not isinstance(receipt['payload'], dict)
                or not isinstance(receipt['signature'], str) or len(receipt['signature']) != 88
                or type(now) is not int or now < 0 or type(max_age) is not int or not 1 <= max_age <= 86400):
            raise ValueError('invalid receipt')
        supplied = receipt['payload']
        expected = _payload(namespace, trusted_head, supplied.get('observed_at'))
        _payload(namespace, supplied.get('head'), supplied.get('observed_at'))
        if (supplied != expected or type(supplied.get('version')) is not int
                or supplied.get('restore_authorized') is not False
                or supplied['observed_at'] > now or now - supplied['observed_at'] > max_age):
            raise ValueError('stale or mismatched receipt')
        signature = base64.b64decode(receipt['signature'], validate=True)
        if len(signature) != 64:
            raise ValueError('invalid signature')
        public_key.verify(signature, _bytes(supplied))
        if not hmac.compare_digest(supplied['head']['sha256'], trusted_head['sha256']):
            raise ValueError('anchor mismatch')
        return {'status': 'SIGNED_OBSERVATION_VALID', 'source_reachability': 'UNVERIFIED',
                'restore_authorized': False}
    except Exception:
        raise JournalError('Witness receipt cannot be verified') from None
