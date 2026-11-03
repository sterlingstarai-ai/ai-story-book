import copy

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.services.privacy_journal import JournalError
from src.services.privacy_witness_receipt import sign_receipt, verify_receipt


def test_signed_observation_is_only_a_time_bounded_non_authorizing_receipt():
    key = Ed25519PrivateKey.generate()
    head = {'sequence': 2, 'sha256': 'a' * 64}
    receipt = sign_receipt(key, namespace='b' * 32, head=head, observed_at=100,
        observation={'status': 'SNAPSHOT_MATCHES', 'restore_authorized': False})
    args = {'namespace': 'b' * 32, 'trusted_head': head, 'now': 105, 'max_age': 10}
    assert verify_receipt(key.public_key(), receipt, **args) == {
        'status': 'SIGNED_OBSERVATION_VALID', 'source_reachability': 'UNVERIFIED', 'restore_authorized': False}
    for override in ({'now': 111}, {'trusted_head': {'sequence': 1, 'sha256': 'c' * 64}},
                     {'namespace': 'c' * 32}, {'now': 99}):
        with pytest.raises(JournalError):
            verify_receipt(key.public_key(), receipt, **{**args, **override})
    forged = copy.deepcopy(receipt)
    forged['payload']['head']['sha256'] = 'd' * 64
    with pytest.raises(JournalError):
        verify_receipt(key.public_key(), forged, **args)
    with pytest.raises(JournalError):
        verify_receipt(Ed25519PrivateKey.generate().public_key(), receipt, **args)


def test_cannot_sign_alert_as_success():
    with pytest.raises(JournalError):
        sign_receipt(Ed25519PrivateKey.generate(), namespace='a' * 32,
            head={'sequence': 1, 'sha256': 'a' * 64}, observed_at=100,
            observation={'status': 'ALERT', 'restore_authorized': False})
