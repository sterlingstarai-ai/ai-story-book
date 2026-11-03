"""Create-only GCS witness adapter. A separate account must be provisioned.

The adapter establishes neither account independence nor a trusted latest head.
It must not share the journal's administrator, credentials or encryption key.
"""
import re
from urllib.parse import quote

from src.services.privacy_journal import JournalError
from src.services.privacy_journal_checkpoint import _MAX_BYTES
from src.services.privacy_journal_gcs import GCSImmutableStore

_NAME = re.compile(r'^(?:privacy-checkpoints/v1/[0-9a-f]{32}/[0-9]{20}|'
                   r'privacy-checkpoint-heads/v1/[0-9a-f]{32}/[0-9]{20}|'
                   r'privacy-checkpoint-keys/v1/[0-9a-f]{32}/[0-9a-f]{32})$')


class GCSCheckpointStore(GCSImmutableStore):
    @staticmethod
    def _name(name):
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise JournalError('Invalid checkpoint object name')
        return quote(name, safe='')

    def create(self, name, data):
        self._name(name)
        if not isinstance(data, bytes) or not 1 <= len(data) <= _MAX_BYTES:
            raise JournalError('Invalid checkpoint object')
        try:
            response = self._client.post(
                f'https://storage.googleapis.com/upload/storage/v1/b/{self._bucket}/o',
                params={'uploadType': 'media', 'name': name, 'ifGenerationMatch': '0'},
                headers={**self._headers(), 'Content-Type': 'application/octet-stream'}, content=data,
            )
            if response.status_code not in (200, 201):
                raise JournalError('Checkpoint create-only write failed')
        except JournalError:
            raise
        except Exception:
            raise JournalError('Checkpoint write outcome is unknown') from None

    def read(self, name):
        encoded = self._name(name)
        try:
            with self._client.stream(
                'GET', f'https://storage.googleapis.com/storage/v1/b/{self._bucket}/o/{encoded}',
                params={'alt': 'media'}, headers=self._headers(),
            ) as response:
                if response.status_code != 200:
                    raise JournalError('Checkpoint object could not be read')
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > _MAX_BYTES:
                        raise JournalError('Checkpoint object is too large')
                    chunks.append(chunk)
                if not size:
                    raise JournalError('Checkpoint object is empty')
                return b''.join(chunks)
        except JournalError:
            raise
        except Exception:
            raise JournalError('Checkpoint object could not be read') from None

    def list_names(self, prefix):
        # Listing is not a substitute for an independently trusted head.
        raise JournalError('Checkpoint head must be supplied independently')
