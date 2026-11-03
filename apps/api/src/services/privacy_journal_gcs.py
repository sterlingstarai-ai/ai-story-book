"""Create-only GCS adapter for the unconnected privacy-journal prototype.

Requires a dedicated private bucket and separately configured least-privilege
credentials. A successful request is not proof of complete journal coverage.
This module does not create buckets, grant access, or contact GCS on import.
"""

import json
import re
from urllib.parse import quote

import httpx

from src.services.privacy_journal import JournalError


_BUCKET = re.compile(r'^[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]$')
_PREFIX = 'privacy-journal/v1/'
_MAX_RECORD = 4096
_MAX_LIST_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_NAMES = 100000
_MAX_PAGES = 1024
_OBJECT_NAME = re.compile(r'^privacy-journal/v1/[0-9a-f]{32}/(?:intent|commit|abort)$')


def application_default_token() -> str:
    """Obtain an ADC token without writing it to files, arguments or output."""
    try:
        import google.auth
        from google.auth.transport.requests import Request
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/devstorage.read_write'])
        if not credentials.valid:
            credentials.refresh(Request())
        token = credentials.token
        if not token:
            raise ValueError('missing token')
        return token
    except Exception:
        raise JournalError('Journal storage credentials are unavailable') from None


class GCSImmutableStore:
    def __init__(self, bucket: str, *, token_provider=application_default_token, client=None):
        if not isinstance(bucket, str) or not _BUCKET.fullmatch(bucket) or '..' in bucket:
            raise JournalError('Invalid journal bucket')
        self._bucket = bucket
        self._token_provider = token_provider
        self._client = client or httpx.Client(timeout=httpx.Timeout(15.0, connect=10.0),
                                              follow_redirects=False, trust_env=False)
        self._owns_client = client is None

    def close(self):
        if self._owns_client:
            self._client.close()

    def _headers(self):
        try:
            token = self._token_provider()
            if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
                raise ValueError('invalid token')
            return {'Authorization': 'Bearer ' + token}
        except Exception:
            raise JournalError('Journal storage credentials are unavailable') from None

    def _name(self, name):
        if not isinstance(name, str) or not name.startswith(_PREFIX) or len(name) > 200:
            raise JournalError('Invalid journal object name')
        return quote(name, safe='')

    def create(self, name: str, data: bytes) -> None:
        self._name(name)
        if not isinstance(data, bytes) or not 1 <= len(data) <= _MAX_RECORD:
            raise JournalError('Invalid journal object')
        try:
            response = self._client.post(
                f'https://storage.googleapis.com/upload/storage/v1/b/{self._bucket}/o',
                params={'uploadType': 'media', 'name': name, 'ifGenerationMatch': '0'},
                headers={**self._headers(), 'Content-Type': 'application/octet-stream'}, content=data,
            )
            if response.status_code not in (200, 201):
                raise JournalError('Journal create-only write failed')
        except JournalError:
            raise
        except Exception:
            # A network error can mean the write succeeded; callers must treat
            # the outcome as unknown and reconcile the immutable object.
            raise JournalError('Journal write outcome is unknown') from None

    def read(self, name: str) -> bytes:
        encoded = self._name(name)
        try:
            with self._client.stream(
                'GET', f'https://storage.googleapis.com/storage/v1/b/{self._bucket}/o/{encoded}',
                params={'alt': 'media'}, headers={**self._headers(), 'Accept-Encoding': 'identity'},
            ) as response:
                if response.status_code != 200:
                    raise JournalError('Journal object could not be read')
                # Reject compressed content before reading it. iter_bytes()
                # can expand a small untrusted response before the record
                # limit is checked; journal writers upload uncompressed data.
                if response.headers.get('content-encoding', '').strip().lower() not in ('', 'identity'):
                    raise JournalError('Journal object encoding is invalid')
                chunks = []
                size = 0
                source = ([response.content] if response.is_stream_consumed
                          else response.iter_raw(chunk_size=_MAX_RECORD))
                for chunk in source:
                    size += len(chunk)
                    if size > _MAX_RECORD:
                        raise JournalError('Journal object is too large')
                    chunks.append(chunk)
                return b''.join(chunks)
        except JournalError:
            raise
        except Exception:
            raise JournalError('Journal object could not be read') from None

    def list_names(self, prefix: str) -> list[str]:
        if prefix != _PREFIX and not re.fullmatch(r'privacy-journal/v1/[0-9a-f]{32}/', prefix):
            raise JournalError('Invalid journal prefix')
        names = []
        seen_names = set()
        seen_tokens = set()
        page_token = None
        page_count = 0
        try:
            while True:
                page_count += 1
                if page_count > _MAX_PAGES:
                    raise JournalError('Journal pagination exceeds the supported limit')
                # Only names and pagination metadata are required to validate
                # the journal. Excluding arbitrary object metadata keeps a
                # valid 1000-item response small and avoids parsing unrelated
                # provider-controlled fields.
                params = {'prefix': prefix, 'maxResults': '1000',
                          'fields': 'kind,items(name),nextPageToken,prefixes'}
                if page_token:
                    params['pageToken'] = page_token
                with self._client.stream(
                    'GET', f'https://storage.googleapis.com/storage/v1/b/{self._bucket}/o',
                    params=params, headers={**self._headers(), 'Accept-Encoding': 'identity'},
                ) as response:
                    if response.status_code != 200:
                        raise JournalError('Journal listing could not be completed')
                    if response.headers.get('content-encoding', '').strip().lower() not in ('', 'identity'):
                        raise JournalError('Journal listing encoding is invalid')
                    body = bytearray()
                    # Injected transports may provide an already-buffered
                    # response; the real HTTP transport remains streaming.
                    chunks = ([response.content] if response.is_stream_consumed
                              else response.iter_raw(chunk_size=65536))
                    for chunk in chunks:
                        if len(body) + len(chunk) > _MAX_LIST_RESPONSE_BYTES:
                            raise JournalError('Journal listing exceeds the supported size')
                        body.extend(chunk)
                    data = json.loads(body)
                if (not isinstance(data, dict) or data.get('kind') != 'storage#objects'
                        or not isinstance(data.get('items', []), list)
                        or data.get('prefixes', []) != []):
                    raise JournalError('Journal listing is invalid')
                for item in data.get('items', []):
                    if (not isinstance(item, dict) or not isinstance(item.get('name'), str)
                            or not item['name'].startswith(prefix) or not _OBJECT_NAME.fullmatch(item['name'])
                            or item['name'] in seen_names):
                        raise JournalError('Journal listing is invalid')
                    names.append(item['name'])
                    seen_names.add(item['name'])
                    if len(names) > _MAX_NAMES:
                        raise JournalError('Journal listing exceeds the supported limit')
                if 'nextPageToken' not in data:
                    return names
                page_token = data['nextPageToken']
                if not isinstance(page_token, str) or not page_token or page_token in seen_tokens:
                    raise JournalError('Journal pagination is invalid')
                seen_tokens.add(page_token)
        except JournalError:
            raise
        except Exception:
            raise JournalError('Journal listing could not be completed') from None
