"""S3-compatible create-only journal adapter, not enabled in production.

A compatible provider must be verified to enforce If-None-Match and strong
read/list consistency. Object deletion, versioning and account independence
are outside this adapter; none of these calls authorizes a restore.
"""
import re

from src.services.privacy_journal import JournalError

_PREFIX = 'privacy-journal/v1/'
_NAME = re.compile(r'^privacy-journal/v1/[0-9a-f]{32}/(?:intent|commit|abort)$')
_EVENT_PREFIX = re.compile(r'^privacy-journal/v1/[0-9a-f]{32}/$')
_MAX_RECORD = 4096
_MAX_NAMES = 100000
_MAX_PAGES = 1024


class S3ImmutableJournalStore:
    def __init__(self, client, bucket, *, owns_client=False):
        if not isinstance(bucket, str) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket):
            raise JournalError('Invalid journal bucket')
        self._client = client
        self._bucket = bucket
        self._owns_client = owns_client

    def close(self):
        if self._owns_client:
            self._client.close()

    @staticmethod
    def _name(name):
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise JournalError('Invalid journal object name')

    def create(self, name, data):
        self._name(name)
        if not isinstance(data, bytes) or not 1 <= len(data) <= _MAX_RECORD:
            raise JournalError('Invalid journal object')
        try:
            response = self._client.put_object(Bucket=self._bucket, Key=name, Body=data,
                                               ContentType='application/octet-stream', IfNoneMatch='*')
            status = response.get('ResponseMetadata', {}).get('HTTPStatusCode')
            if status not in (200, 201) or self.read(name) != data:
                raise JournalError('Journal create-only write could not be verified')
        except JournalError:
            raise
        except Exception:
            raise JournalError('Journal create-only write failed or its outcome is unknown') from None

    def read(self, name):
        self._name(name)
        body = None
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=name)
            if response.get('ResponseMetadata', {}).get('HTTPStatusCode') != 200:
                raise JournalError('Journal object could not be read')
            size = response.get('ContentLength')
            if type(size) is not int or not 1 <= size <= _MAX_RECORD:
                raise JournalError('Journal object has invalid size')
            body = response['Body']
            data = body.read(_MAX_RECORD + 1)
            if not isinstance(data, bytes) or len(data) != size:
                raise JournalError('Journal object is truncated')
            return data
        except JournalError:
            raise
        except Exception:
            raise JournalError('Journal object could not be read') from None
        finally:
            if body is not None:
                try:
                    body.close()
                except Exception:
                    raise JournalError('Journal object stream could not be closed') from None

    def list_names(self, prefix):
        if prefix != _PREFIX and (not isinstance(prefix, str) or not _EVENT_PREFIX.fullmatch(prefix)):
            raise JournalError('Invalid journal prefix')
        names, tokens = [], set()
        token = None
        pages = 0
        try:
            while True:
                pages += 1
                if pages > _MAX_PAGES:
                    raise JournalError('Journal pagination exceeds the supported limit')
                args = {'Bucket': self._bucket, 'Prefix': prefix, 'MaxKeys': 1000}
                if token is not None:
                    args['ContinuationToken'] = token
                response = self._client.list_objects_v2(**args)
                if (response.get('ResponseMetadata', {}).get('HTTPStatusCode') != 200
                        or type(response.get('IsTruncated')) is not bool
                        or not isinstance(response.get('Contents', []), list)):
                    raise JournalError('Journal listing is invalid')
                contents = response.get('Contents', [])
                # No delimiter is requested, so an S3 listing must not hide
                # names under CommonPrefixes. Some compatible providers omit
                # KeyCount; when supplied it must account for every item.
                count = response.get('KeyCount')
                if (('KeyCount' in response and (type(count) is not int or count != len(contents)))
                        or response.get('CommonPrefixes', []) != []
                        or ('Prefix' in response and response['Prefix'] != prefix)
                        or ('Name' in response and response['Name'] != self._bucket)):
                    raise JournalError('Journal listing is invalid')
                for item in contents:
                    name = item.get('Key') if isinstance(item, dict) else None
                    if not isinstance(name, str) or not name.startswith(prefix) or not _NAME.fullmatch(name):
                        raise JournalError('Journal listing is invalid')
                    names.append(name)
                    if len(names) > _MAX_NAMES:
                        raise JournalError('Journal listing exceeds the supported limit')
                if not response['IsTruncated']:
                    if len(set(names)) != len(names):
                        raise JournalError('Journal listing contains duplicate names')
                    return names
                token = response.get('NextContinuationToken')
                if not isinstance(token, str) or not token or token in tokens:
                    raise JournalError('Journal pagination is invalid')
                tokens.add(token)
        except JournalError:
            raise
        except Exception:
            raise JournalError('Journal listing could not be completed') from None
