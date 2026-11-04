"""Prove the pilot detach backup on the independently authenticated restore host."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/api'))

from narration_detach_attestation import restore_and_attest  # noqa: E402
from publish_backup_gcs import GCSBackupStore  # noqa: E402
from quarantined_restore_adapter import open_restore_sandbox  # noqa: E402
from run_scheduled_backup import private_file  # noqa: E402
from src.services.privacy_checkpoint_gcs import GCSCheckpointStore  # noqa: E402
from src.services.privacy_witness_receipt import verify_receipt  # noqa: E402


PROJECT = 'gen-lang-client-0308507618'


def _token():
    result = subprocess.run(['gcloud', 'auth', 'print-access-token', '--quiet'],
                            capture_output=True, check=True, timeout=30, text=True)
    return result.stdout.strip()


def _read_witness(path):
    anchor = json.loads(private_file(path / 'anchor.json', max_bytes=1024))
    if not isinstance(anchor, dict) or set(anchor) != {'version', 'namespace', 'head'} or anchor['version'] != 1:
        raise RuntimeError('Trusted checkpoint anchor is invalid')
    files = (p for p in path.glob('receipt-*.json') if re.fullmatch(r'receipt-[0-9]{1,12}\.json', p.name))
    receipt_path = max(files, key=lambda item: int(item.stem.split('-')[1]))
    receipt = json.loads(private_file(receipt_path, max_bytes=4096))
    public = load_pem_public_key(private_file(path / 'signing-public.pem', max_bytes=1024))
    verify_receipt(public, receipt, namespace=anchor['namespace'], trusted_head=anchor['head'],
                   now=int(time.time()), max_age=600)
    signer = Ed25519PrivateKey.from_private_bytes(private_file(path / 'detach-signing.key', max_bytes=32))
    return signer, {'receipt': receipt, 'public_key': public, 'namespace': anchor['namespace'],
                    'trusted_head': anchor['head'], 'head_key': private_file(path / 'head.key', max_bytes=32),
                    'checkpoint_key': private_file(path / 'checkpoint.key', max_bytes=32)}


def verify_remote_backup(challenge, *, image_id, witness_dir):
    signer, witness = _read_witness(witness_dir)
    with tempfile.TemporaryDirectory(prefix='asb-detach-restore-') as lock_dir, \
            open_restore_sandbox(image_id=image_id, state_dir=lock_dir) as sandbox, \
            closing(GCSBackupStore('asb-backups-' + PROJECT, _token)) as store, \
            closing(GCSCheckpointStore('asb-journal-head-' + PROJECT, token_provider=_token)) as heads, \
            closing(GCSCheckpointStore('asb-journal-checkpoint-' + PROJECT, token_provider=_token)) as snapshots:
        return restore_and_attest(challenge, store=store, sandbox=sandbox, signing_key=signer,
            signed_witness={**witness, 'head_store': heads, 'checkpoint_store': snapshots})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image-id', required=True)
    parser.add_argument('--witness-dir', required=True, type=Path)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(1025)
        if not 0 < len(raw) <= 1024:
            raise RuntimeError('Restore challenge is invalid')
        print(verify_remote_backup(json.loads(raw), image_id=args.image_id, witness_dir=args.witness_dir))
        return 0
    except Exception as exc:
        import traceback
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        print(json.dumps({'status': 'DETACH_NOT_CONFIRMED', 'type': type(exc).__name__,
                          'location': f'{Path(frame.filename).name}:{frame.lineno}'}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
