"""Read a bounded GCS XML inventory and download its exact generations.

Uses existing HMAC credentials only. No OAuth, fallback generation, writes,
redirects, proxy environment, content decoding or credential logging is used.
The caller owns the short cut and closes this adapter after all body readers.
"""

import base64
import binascii
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import hmac
import re
import time
from urllib.parse import quote
import xml.etree.ElementTree as ET

from botocore.auth import S3SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
import httpx


class GCSOnlineMediaError(RuntimeError):
    pass


_ORIGIN = 'https://storage.googleapis.com'
_MAX_LIST_BYTES = 2 * 1024 * 1024
_MAX_OBJECTS = 1000  # A multi-page listing cannot be one short, atomic cut.
_MAX_READ = 1024 * 1024
_POSITIVE = re.compile(r'[1-9][0-9]{0,19}')
_SIZE = re.compile(r'(?:0|[1-9][0-9]{0,19})')


def _etag(value):
    if (not isinstance(value, str) or not value or len(value) > 256
            or any(ord(c) < 32 or ord(c) == 127 for c in value) or value.startswith('W/')):
        raise GCSOnlineMediaError('Frozen media identity is invalid')
    return value[1:-1] if value.startswith('"') and value.endswith('"') else value


def _timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Missing timezone')
    return parsed.astimezone(timezone.utc)


def _key(value):
    if (not isinstance(value, str) or not value or len(value.encode('utf-8')) > 1024
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or any(part in ('', '.', '..') for part in value.split('/'))):
        raise GCSOnlineMediaError('Frozen media key is invalid')
    return value


def _decode_md5(value):
    try:
        digest = base64.b64decode(value, validate=True)
        if len(digest) != 16 or base64.b64encode(digest).decode('ascii') != value:
            raise ValueError
        return digest
    except (TypeError, ValueError, binascii.Error):
        raise GCSOnlineMediaError('Media checksum is unavailable or invalid') from None


class _RawBody:
    """Bounded reads; checksum verification happens before returning final EOF."""

    def __init__(self, response, size, digest):
        self._response = response
        self._iterator = response.iter_raw(chunk_size=65536)
        self._buffer = bytearray()
        self._size = size
        self._expected = digest
        self._hash = hashlib.md5(usedforsecurity=False)
        self._received = 0
        self._eof = False
        self._closed = False

    def read(self, size=65536):
        if type(size) is not int or not 1 <= size <= _MAX_READ:
            raise GCSOnlineMediaError('A bounded media read is required')
        if self._closed and not self._eof:
            raise GCSOnlineMediaError('Media stream closed before verification')
        try:
            while len(self._buffer) < size and not self._eof:
                try:
                    chunk = next(self._iterator)
                except StopIteration:
                    if self._received != self._size or not hmac.compare_digest(self._hash.digest(), self._expected):
                        raise GCSOnlineMediaError('Frozen media byte integrity does not match')
                    self._eof = True
                    self.close()
                    break
                self._received += len(chunk)
                if self._received > self._size:
                    raise GCSOnlineMediaError('Frozen media exceeds its captured size')
                self._hash.update(chunk)
                self._buffer.extend(chunk)
            result = bytes(self._buffer[:size])
            del self._buffer[:size]
            return result
        except GCSOnlineMediaError:
            self.close()
            raise
        except Exception:
            self.close()
            raise GCSOnlineMediaError('Frozen media stream could not be verified') from None

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self._response.close()
            except Exception:
                raise GCSOnlineMediaError('Media response could not be closed') from None


class GCSOnlineMedia:
    def __init__(self, values, *, transport=None, cut_timeout_seconds=0.5):
        try:
            if values.get('S3_ENDPOINT', '').rstrip('/') != _ORIGIN:
                raise ValueError
            bucket = values['S3_BUCKET']
            if (not isinstance(bucket, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]', bucket)
                    or '..' in bucket):
                raise ValueError
            access, secret, region = (values[name] for name in ('S3_ACCESS_KEY', 'S3_SECRET_KEY', 'S3_REGION'))
            if any(not isinstance(v, str) or not v or '\r' in v or '\n' in v for v in (access, secret, region)):
                raise ValueError
            if type(cut_timeout_seconds) not in (int, float) or not 0 < cut_timeout_seconds <= 0.5:
                raise ValueError
            self._bucket = bucket
            self._credentials = Credentials(access, secret)
            self._region = region
            self._cut_timeout = float(cut_timeout_seconds)
            self._frozen = None
            self._client = httpx.Client(
                transport=transport if transport is not None else httpx.HTTPTransport(retries=0, trust_env=False),
                timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=False, trust_env=False,
            )
        except Exception:
            raise GCSOnlineMediaError('Frozen GCS media configuration is invalid') from None

    def close(self):
        try:
            self._client.close()
        except Exception:
            raise GCSOnlineMediaError('Media adapter could not be closed') from None

    def _request(self, path, *, params=None, headers=None, timeout=None):
        request = self._client.build_request('GET', _ORIGIN + path, params=params,
                                             headers=headers, timeout=timeout)
        # Hop-by-hop headers may be removed by frontends and must not become
        # part of an object request's canonical authentication signature.
        request.headers.pop('connection', None)
        # GCS frontends normalize Accept-Encoding before authenticating XML
        # requests. Match the maintained S3 SDK: sign identity/conditions, not
        # optional HTTP client's negotiation defaults. Keep them on the wire.
        signing_headers = {name: value for name, value in request.headers.items()
                           if name.lower() in ('host', 'if-match')
                           or name.lower().startswith(('x-amz-', 'x-goog-'))}
        signed = AWSRequest(method='GET', url=str(request.url), headers=signing_headers)
        # Use the same S3 SigV4 path handling as the existing HMAC adapter.
        S3SigV4Auth(self._credentials, 's3', self._region).add_auth(signed)
        request.headers.update(dict(signed.headers))
        return self._client.send(request, stream=True, follow_redirects=False)

    def inventory(self):
        """Capture one complete native XML page; never accept a truncated cut."""
        started = time.monotonic()
        self._frozen = None
        response = None
        try:
            response = self._request('/' + self._bucket, params={'max-keys': str(_MAX_OBJECTS)},
                                     headers={'Accept-Encoding': 'identity'},
                                     timeout=httpx.Timeout(self._cut_timeout))
            if response.status_code != 200 or response.is_stream_consumed:
                raise ValueError
            if response.headers.get('content-encoding', '').lower() not in ('', 'identity'):
                raise ValueError
            raw = bytearray()
            for chunk in response.iter_raw(chunk_size=65536):
                if len(raw) + len(chunk) > _MAX_LIST_BYTES or time.monotonic() - started > self._cut_timeout:
                    raise ValueError
                raw.extend(chunk)
            text = raw.decode('utf-8')
            if '\x00' in text or re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.IGNORECASE):
                raise ValueError
            root = ET.fromstring(text)
            # Native GCS XML and S3 XML use the same local element names.
            for node in root.iter():
                node.tag = node.tag.rsplit('}', 1)[-1]
            def single(node, name, *, default=None):
                found = node.findall(name)
                if len(found) != 1:
                    if not found and default is not None:
                        return default
                    raise ValueError
                return found[0].text or ''
            if (root.tag != 'ListBucketResult' or single(root, 'Name') != self._bucket
                    or single(root, 'IsTruncated') != 'false' or root.findall('CommonPrefixes')
                    or any(len(root.findall(name)) > 1 or any((node.text or '').strip() for node in root.findall(name))
                           for name in ('NextMarker', 'NextContinuationToken'))
                    or single(root, 'Prefix', default='') or single(root, 'Marker', default='')
                    or single(root, 'EncodingType', default='')):
                raise ValueError
            objects = {}
            for item in root.findall('Contents'):
                name = _key(single(item, 'Key'))
                etag = single(item, 'ETag')
                generation, metageneration = single(item, 'Generation'), single(item, 'MetaGeneration')
                size, modified = single(item, 'Size'), single(item, 'LastModified')
                _etag(etag)
                _timestamp(modified)
                if (name in objects or len(objects) >= _MAX_OBJECTS or not _SIZE.fullmatch(size)
                        or not _POSITIVE.fullmatch(generation) or not _POSITIVE.fullmatch(metageneration)):
                    raise ValueError
                objects[name] = {'ETag': etag, 'Size': size, 'LastModified': modified,
                                 'generation': generation, 'metageneration': metageneration}
            if time.monotonic() - started > self._cut_timeout:
                raise ValueError
            self._frozen = deepcopy(objects)
            return deepcopy(objects)
        except Exception:
            raise GCSOnlineMediaError('A complete generation-bound media inventory could not be captured') from None
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    raise GCSOnlineMediaError('Media inventory response could not be closed') from None

    def get_object(self, *, Bucket, Key, IfMatch, Generation=None, Metageneration=None):
        response = None
        try:
            _key(Key)
            if Bucket != self._bucket or self._frozen is None or Key not in self._frozen:
                raise ValueError
            item = self._frozen[Key]
            if (IfMatch != item['ETag'] or (Generation is not None and Generation != item['generation'])
                    or (Metageneration is not None and Metageneration != item['metageneration'])):
                raise ValueError
            response = self._request('/' + self._bucket + '/' + quote(Key, safe='/'),
                params={'generation': item['generation']},
                headers={'If-Match': item['ETag'], 'Accept-Encoding': 'gzip',
                         # GCS accepts these exact XML preconditions under the
                         # S3 aliases. AWS4 authentication must not mix x-amz
                         # signing headers with x-goog request headers.
                         'x-amz-if-generation-match': item['generation'],
                         'x-amz-if-metageneration-match': item['metageneration']},
                timeout=httpx.Timeout(30.0, connect=10.0))
            headers = response.headers
            if (response.status_code != 200 or response.is_stream_consumed
                    or headers.get('x-goog-generation') != item['generation']
                    or headers.get('x-goog-metageneration') != item['metageneration']
                    or _etag(headers.get('etag')) != _etag(item['ETag'])
                    or headers.get('content-length') != item['Size'] or 'content-range' in headers):
                raise ValueError
            expected_size = int(item['Size'])
            stored_length = headers.get('x-goog-stored-content-length')
            if stored_length is not None and stored_length != item['Size']:
                raise ValueError
            # An absent coding and the explicit identity coding both mean the
            # stored bytes are uncompressed. GCS uses both representations.
            encoding = headers.get('content-encoding', '').strip().lower() or 'identity'
            stored_encoding = headers.get('x-goog-stored-content-encoding')
            if stored_encoding is not None and (stored_encoding.strip().lower() or 'identity') != encoding:
                raise ValueError
            modified = parsedate_to_datetime(headers['last-modified'])
            if modified.tzinfo is None:
                raise ValueError
            modified = modified.astimezone(timezone.utc)
            if modified.replace(microsecond=0) != _timestamp(item['LastModified']).replace(microsecond=0):
                raise ValueError
            hashes = [value.strip()[4:] for value in headers.get('x-goog-hash', '').split(',')
                      if value.strip().startswith('md5=')]
            native_md5 = _etag(item['ETag'])
            captured = bytes.fromhex(native_md5) if re.fullmatch('[0-9a-fA-F]{32}', native_md5) else None
            if hashes:
                if len(hashes) != 1:
                    raise ValueError
                digest = _decode_md5(hashes[0])
                if captured is not None and not hmac.compare_digest(captured, digest):
                    raise ValueError
            elif captured is not None:
                digest = captured
            else:
                raise ValueError
            metadata = {key[len('x-goog-meta-'):]: value for key, value in headers.items()
                        if key.startswith('x-goog-meta-')}
            return {'Body': _RawBody(response, expected_size, digest), 'ETag': item['ETag'],
                    'LastModified': modified, 'ContentLength': expected_size,
                    'Generation': item['generation'], 'Metageneration': item['metageneration'],
                    'ContentType': headers.get('content-type', 'application/octet-stream'), 'Metadata': metadata,
                    'CacheControl': headers.get('cache-control'), 'ContentDisposition': headers.get('content-disposition'),
                    'ContentEncoding': headers.get('content-encoding')}
        except Exception:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            raise GCSOnlineMediaError('The captured media generation could not be read') from None
