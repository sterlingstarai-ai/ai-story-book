"""Prepare a passphrase-encrypted offline account-scope recovery package.

This tool does not choose a storage device, transfer a package, activate a
scope key or establish physical/admin independence. Use a separately held
passphrase and verify the media and an actual recovery before activation.
"""
import argparse
import base64
import getpass
import json
from pathlib import Path
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from account_scope_key import recover
from recover_witness_key import write_new_private_file, write_new_private_key
from run_scheduled_backup import private_file

MAGIC = b'ASB-SCOPE-OFFLINE-V1\0'
SALT_SIZE = 16
NONCE_SIZE = 12


def derive(passphrase, salt):
    if not isinstance(passphrase, str) or len(passphrase) < 20 or len(passphrase) > 1024:
        raise ValueError('A passphrase of 20 to 1024 characters is required')
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode('utf-8'))


def create_package(*, recovery_key, envelope, reference, passphrase):
    # Refuse to package unrelated or corrupt inputs.
    recover(recovery_key=recovery_key, envelope=envelope, reference=reference)
    salt, nonce = secrets.token_bytes(SALT_SIZE), secrets.token_bytes(NONCE_SIZE)
    value = {'version': 1, 'recovery_key': base64.b64encode(recovery_key).decode('ascii'),
             'envelope': base64.b64encode(envelope).decode('ascii'), 'reference': reference}
    body = json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return MAGIC + salt + nonce + AESGCM(derive(passphrase, salt)).encrypt(nonce, body, MAGIC + salt)


def recover_package(*, package, passphrase):
    if (not isinstance(package, bytes) or not package.startswith(MAGIC)
            or not len(MAGIC) + SALT_SIZE + NONCE_SIZE + 16 < len(package) <= 1024):
        raise ValueError('Invalid recovery package')
    offset = len(MAGIC)
    salt = package[offset:offset + SALT_SIZE]
    nonce = package[offset + SALT_SIZE:offset + SALT_SIZE + NONCE_SIZE]
    ciphertext = package[offset + SALT_SIZE + NONCE_SIZE:]
    payload = AESGCM(derive(passphrase, salt)).decrypt(nonce, ciphertext, MAGIC + salt)
    value = json.loads(payload)
    if (not isinstance(value, dict) or set(value) != {'version', 'recovery_key', 'envelope', 'reference'}
            or type(value['version']) is not int or value['version'] != 1):
        raise ValueError('Invalid recovery package')
    recovery_key = base64.b64decode(value['recovery_key'], validate=True)
    envelope = base64.b64decode(value['envelope'], validate=True)
    return recover(recovery_key=recovery_key, envelope=envelope, reference=value['reference'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('create', 'recover'))
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--package', required=True, type=Path)
    parser.add_argument('--recovery-key-file', type=Path)
    parser.add_argument('--envelope-file', type=Path)
    parser.add_argument('--reference-file', type=Path)
    parser.add_argument('--key-output', type=Path)
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({'status': 'DRY_RUN', 'activated': False}))
        return 0
    try:
        if not args.package.is_absolute():
            raise ValueError('Absolute paths required')
        if args.operation == 'create':
            if (not all((args.recovery_key_file, args.envelope_file, args.reference_file)) or args.key_output
                    or any(not p.is_absolute() for p in (args.recovery_key_file, args.envelope_file, args.reference_file))):
                raise ValueError('Invalid inputs')
            recovery_key = private_file(args.recovery_key_file, max_bytes=32)
            envelope = private_file(args.envelope_file, max_bytes=1024)
            reference = json.loads(private_file(args.reference_file, max_bytes=1024))
            passphrase = getpass.getpass('Recovery passphrase: ')
            if passphrase != getpass.getpass('Repeat recovery passphrase: '):
                raise ValueError('Passphrases differ')
            package = create_package(recovery_key=recovery_key, envelope=envelope, reference=reference, passphrase=passphrase)
            write_new_private_file(args.package, package)
            status = 'OFFLINE_PACKAGE_CREATED'
        else:
            if (not args.key_output or not args.key_output.is_absolute()
                    or any((args.recovery_key_file, args.envelope_file, args.reference_file))):
                raise ValueError('Invalid inputs')
            package = private_file(args.package, max_bytes=1024)
            passphrase = getpass.getpass('Recovery passphrase: ')
            key = recover_package(package=package, passphrase=passphrase)
            write_new_private_key(args.key_output, key)
            status = 'KEY_RECOVERED_INACTIVE'
        print(json.dumps({'status': status, 'activated': False, 'independence_verified': False}))
        return 0
    except Exception:
        print(json.dumps({'status': 'OFFLINE_KEY_OPERATION_FAILED', 'activated': False, 'independence_verified': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
