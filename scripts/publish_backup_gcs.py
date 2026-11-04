"""Publish a verified private backup set to GCS, with a last-written marker.

This module is not a scheduler and does not authorize restore or retention
deletion. Callers must separately establish quiescence, journal completeness,
private bucket policy and least-privilege credentials.
"""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote

import httpx

from verify_backup_set import verify


class BackupPublishError(RuntimeError):
    """Provider or integrity failure without disclosing backup contents."""


def _valid_checkpoint(checkpoint):
    return (isinstance(checkpoint, dict)
            and checkpoint.get('status') == 'CURRENT_OUTBOX_MATCHES_JOURNAL'
            and checkpoint.get('restore_authorized') is False
            and type(checkpoint.get('event_count')) is int and checkpoint['event_count'] >= 0
            and isinstance(checkpoint.get('journal_sha256'), str)
            and bool(re.fullmatch('[0-9a-f]{64}', checkpoint['journal_sha256'])))


class GCSBackupStore:
    def __init__(self, bucket, token_provider, client=None):
        if not isinstance(bucket, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]', bucket) or '..' in bucket:
            raise BackupPublishError('Invalid backup bucket')
        self._bucket = bucket
        self._token_provider = token_provider
        self._client = client or httpx.Client(timeout=httpx.Timeout(300, connect=15),
                                              follow_redirects=False, trust_env=False)
        self._owned = client is None

    def close(self):
        if self._owned:
            self._client.close()

    def _headers(self):
        token = self._token_provider()
        if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
            raise BackupPublishError('Backup credentials are unavailable')
        return {'Authorization': 'Bearer ' + token}

    def _check_remote(self, name, expected_size, expected_hash):
        encoded = quote(name, safe='')
        try:
            with self._client.stream('GET', f'https://storage.googleapis.com/storage/v1/b/{self._bucket}/o/{encoded}',
                                     params={'alt': 'media'}, headers=self._headers()) as response:
                if response.status_code != 200:
                    raise BackupPublishError('Backup object could not be read')
                digest = hashlib.sha256()
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > expected_size:
                        raise BackupPublishError('Backup object size differs')
                    digest.update(chunk)
                if size != expected_size or digest.hexdigest() != expected_hash:
                    raise BackupPublishError('Backup object checksum differs')
        except BackupPublishError:
            raise
        except Exception:
            raise BackupPublishError('Backup object could not be verified') from None

    def iter_verified(self, name, *, expected_size, expected_hash):
        """Stream a named backup object without staging its plaintext on disk.

        The caller must discard all bytes if this iterator fails, including a
        failure discovered at the end. This does not establish latest privacy
        history, restore safety, or authenticity of the expected hash.
        """
        if (not isinstance(name, str) or not re.fullmatch(
                r'backups/v1/[0-9a-f]{32}/(?:database\.dump|objects/[0-9a-f]{64})', name)
                or type(expected_size) is not int or expected_size < 0
                or not isinstance(expected_hash, str) or not re.fullmatch('[0-9a-f]{64}', expected_hash)):
            raise BackupPublishError('Invalid backup stream descriptor')
        try:
            encoded = quote(name, safe='')
            with self._client.stream('GET', f'https://storage.googleapis.com/storage/v1/b/{self._bucket}/o/{encoded}',
                                     params={'alt': 'media'}, headers=self._headers()) as response:
                if response.status_code != 200:
                    raise BackupPublishError('Backup object could not be read')
                digest = hashlib.sha256()
                size = 0
                for chunk in response.iter_bytes():
                    if not isinstance(chunk, bytes):
                        raise BackupPublishError('Backup stream is invalid')
                    size += len(chunk)
                    if size > expected_size:
                        raise BackupPublishError('Backup object size differs')
                    digest.update(chunk)
                    if chunk:
                        yield chunk
                if size != expected_size or digest.hexdigest() != expected_hash:
                    raise BackupPublishError('Backup object checksum differs')
        except BackupPublishError:
            raise
        except Exception:
            raise BackupPublishError('Backup object could not be streamed') from None

    def read_small(self, name, max_size):
        if not re.fullmatch(r'backups/v1/[0-9a-f]{32}/(?:manifest|verified)\.json', name):
            raise BackupPublishError('Invalid backup object name')
        try:
            encoded = quote(name, safe='')
            with self._client.stream('GET', f'https://storage.googleapis.com/storage/v1/b/{self._bucket}/o/{encoded}',
                                     params={'alt': 'media'}, headers=self._headers()) as response:
                if response.status_code != 200:
                    raise BackupPublishError('Backup object could not be read')
                chunks = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_size:
                        raise BackupPublishError('Backup object is too large')
                    chunks.append(chunk)
                return b''.join(chunks)
        except BackupPublishError:
            raise
        except Exception:
            raise BackupPublishError('Backup object could not be read') from None

    def put_verified(self, name, path, *, expected_size=None, expected_hash=None):
        if not re.fullmatch(r'backups/v1/[0-9a-f]{32}/(?:database\.dump|manifest\.json|verified\.json|objects/[0-9a-f]{64})', name):
            raise BackupPublishError('Invalid backup object name')
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            raise BackupPublishError('Invalid backup input')
        size = path.stat().st_size
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        actual_hash = digest.hexdigest()
        if ((expected_size is not None and size != expected_size)
                or (expected_hash is not None and actual_hash != expected_hash)):
            raise BackupPublishError('Local backup changed after validation')
        try:
            with path.open('rb') as source:
                response = self._client.post(
                    f'https://storage.googleapis.com/upload/storage/v1/b/{self._bucket}/o',
                    params={'uploadType': 'media', 'name': name, 'ifGenerationMatch': '0'},
                    headers={**self._headers(), 'Content-Type': 'application/octet-stream', 'Content-Length': str(size)},
                    content=source,
                )
            if response.status_code not in (200, 201, 412):
                raise BackupPublishError('Backup object upload failed')
        except BackupPublishError:
            raise
        except Exception:
            # A lost response can follow a successful write. The comparison
            # below decides whether the immutable object is the intended one.
            pass
        self._check_remote(name, size, actual_hash)


def publish_verified_backup(folder, run_id, store, *, journal_checkpoint=None, verify_before_marker=None):
    """Upload data, verify every remote byte, and publish the marker last."""
    import tempfile

    if not isinstance(run_id, str) or not re.fullmatch('[0-9a-f]{32}', run_id):
        raise BackupPublishError('Invalid backup run identifier')
    if journal_checkpoint is not None and not _valid_checkpoint(journal_checkpoint):
        raise BackupPublishError('Invalid journal checkpoint')
    try:
        folder = Path(folder)
        manifest_path = folder / 'manifest.json'
        manifest_bytes = manifest_path.read_bytes()
        local = verify(folder)
        if manifest_path.read_bytes() != manifest_bytes:
            raise BackupPublishError('Backup manifest changed during validation')
        manifest = json.loads(manifest_bytes)
        prefix = f'backups/v1/{run_id}/'
        descriptors = [manifest['database'], *manifest['objects']]
        for descriptor in descriptors:
            relative = descriptor['file']
            store.put_verified(prefix + relative, folder / relative,
                               expected_size=descriptor['size'], expected_hash=descriptor['sha256'])
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        store.put_verified(prefix + 'manifest.json', manifest_path,
                           expected_size=len(manifest_bytes), expected_hash=manifest_hash)
        marker_value = {'version': 1, 'manifest_sha256': manifest_hash, 'restore_authorized': False}
        if journal_checkpoint is not None:
            marker_value['journal_sha256'] = journal_checkpoint['journal_sha256']
            marker_value['journal_event_count'] = journal_checkpoint['event_count']
        marker = json.dumps(marker_value, sort_keys=True, separators=(',', ':')).encode()
        with tempfile.TemporaryDirectory(prefix='asb-backup-marker-') as tmp:
            marker_path = Path(tmp) / 'verified.json'
            marker_path.write_bytes(marker)
            if verify_before_marker is not None:
                verify_before_marker()
            store.put_verified(prefix + 'verified.json', marker_path)
        return {'status': 'REMOTE_CHECKSUMS_VERIFIED_NOT_RESTORED', 'object_count': local['object_count'],
                'restore_authorized': False}
    except BackupPublishError:
        raise
    except Exception:
        raise BackupPublishError('Backup publication failed') from None


def verify_remote_backup(run_id, store, *, expected_revision=None, expected_journal_checkpoint=None):
    """Recheck remote bytes and an optional known checkpoint; never authorize restore.

    A checkpoint obtained from the same backup is not independent evidence of
    the newest privacy events. A caller may supply a separately authenticated
    expected checkpoint to reject a missing, corrupted, or different marker.
    """
    if not isinstance(run_id, str) or not re.fullmatch('[0-9a-f]{32}', run_id):
        raise BackupPublishError('Invalid backup run identifier')
    prefix = f'backups/v1/{run_id}/'
    try:
        marker = json.loads(store.read_small(prefix + 'verified.json', 4096))
        raw = store.read_small(prefix + 'manifest.json', 16 * 1024 * 1024)
        if (not isinstance(marker, dict) or type(marker.get('version')) is not int or marker['version'] != 1
                or marker.get('restore_authorized') is not False
                or marker.get('manifest_sha256') != hashlib.sha256(raw).hexdigest()):
            raise BackupPublishError('Remote backup marker is invalid')
        checkpoint_keys = {'journal_sha256', 'journal_event_count'}
        present = checkpoint_keys.intersection(marker)
        if present:
            if (present != checkpoint_keys or type(marker['journal_event_count']) is not int
                    or marker['journal_event_count'] < 0 or not isinstance(marker['journal_sha256'], str)
                    or not re.fullmatch('[0-9a-f]{64}', marker['journal_sha256'])):
                raise BackupPublishError('Remote journal checkpoint is invalid')
        if expected_journal_checkpoint is not None:
            checkpoint = expected_journal_checkpoint
            if (not _valid_checkpoint(checkpoint) or present != checkpoint_keys
                    or marker['journal_event_count'] != checkpoint['event_count']
                    or marker['journal_sha256'] != checkpoint['journal_sha256']):
                raise BackupPublishError('Remote journal checkpoint does not match')
        manifest = json.loads(raw)
        if (not isinstance(manifest, dict) or type(manifest.get('format_version')) is not int
                or manifest['format_version'] != 1
                or manifest.get('database_scope') != 'public'
                or manifest.get('requires_latest_deletion_and_identity_revocations') is not True
                or (expected_revision is not None and manifest.get('alembic_revision') != expected_revision)):
            raise BackupPublishError('Remote backup manifest is invalid')
        objects = manifest.get('objects')
        if not isinstance(objects, list):
            raise BackupPublishError('Remote backup inventory is invalid')
        descriptors = [manifest.get('database'), *objects]
        names = set()
        for index, descriptor in enumerate(descriptors):
            if not isinstance(descriptor, dict):
                raise BackupPublishError('Remote backup inventory is invalid')
            name, size, digest = descriptor.get('file'), descriptor.get('size'), descriptor.get('sha256')
            if index == 0:
                expected = 'database.dump'
            else:
                key = descriptor.get('key')
                if not isinstance(key, str) or not key:
                    raise BackupPublishError('Remote backup inventory is invalid')
                expected = 'objects/' + hashlib.sha256(key.encode()).hexdigest()
            if (name != expected or name in names or type(size) is not int or size < 0
                    or (index == 0 and size == 0)
                    or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)):
                raise BackupPublishError('Remote backup inventory is invalid')
            names.add(name)
            store._check_remote(prefix + name, size, digest)
        return {'status': 'REMOTE_CHECKSUMS_VERIFIED_NOT_RESTORED', 'object_count': len(objects),
                'restore_authorized': False}
    except BackupPublishError:
        raise
    except Exception:
        raise BackupPublishError('Remote backup could not be verified') from None
