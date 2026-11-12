"""GCS XML generation pins fail closed without writes or real credentials."""

from datetime import datetime, timezone
from email.utils import format_datetime
import gzip
import hashlib
import importlib
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def media(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('online_gcs_media')


VALUES = {'S3_ENDPOINT': 'https://storage.googleapis.com', 'S3_BUCKET': 'fixture-bucket',
          'S3_ACCESS_KEY': 'dummy-access', 'S3_SECRET_KEY': 'dummy-secret', 'S3_REGION': 'auto'}
STAMP = datetime(2026, 11, 12, tzinfo=timezone.utc)
KEY = 'assets/fictional.png'


def _etag(data):
    return '"' + hashlib.md5(data, usedforsecurity=False).hexdigest() + '"'


def _xml(data):
    return (f'<ListBucketResult xmlns="http://doc.s3.amazonaws.com/2006-03-01">'
            f'<Name>fixture-bucket</Name><Prefix/><Marker/><IsTruncated>false</IsTruncated>'
            f'<Contents><Key>{KEY}</Key><Generation>123456</Generation><MetaGeneration>7</MetaGeneration>'
            f'<LastModified>2026-11-12T00:00:00.000Z</LastModified><ETag>{_etag(data)}</ETag>'
            f'<Size>{len(data)}</Size></Contents></ListBucketResult>').encode()


def _adapter(media, *, data=b'fictional-media', xml=None, headers=None, status=200, body=None):
    requests, responses = [], []
    base_headers = {'Content-Length': str(len(data)), 'ETag': _etag(data),
                    'X-Goog-Generation': '123456', 'X-Goog-Metageneration': '7',
                    'Last-Modified': format_datetime(STAMP, usegmt=True), 'Content-Type': 'image/png',
                    'X-Goog-Meta-Fixture': 'kept', 'Cache-Control': 'private'}
    if headers:
        for name, value in headers.items():
            if value is None:
                base_headers.pop(name)
            else:
                base_headers[name] = value
    def handler(request):
        requests.append(request)
        if request.url.path == '/fixture-bucket':
            response = httpx.Response(200, stream=httpx.ByteStream(_xml(data) if xml is None else xml))
        else:
            response = httpx.Response(status, headers=base_headers,
                                      stream=httpx.ByteStream(data if body is None else body))
        responses.append(response)
        return response
    adapter = media.GCSOnlineMedia(VALUES, transport=httpx.MockTransport(handler))
    return adapter, requests, responses


def _get(adapter, item):
    return adapter.get_object(Bucket='fixture-bucket', Key=KEY, IfMatch=item['ETag'],
                              Generation=item['generation'], Metageneration=item['metageneration'])


def test_existing_hmac_and_native_generation_conditions_are_used(media):
    adapter, requests, responses = _adapter(media)
    try:
        frozen = adapter.inventory()
        item = frozen[KEY]
        assert item['generation'] == '123456' and item['metageneration'] == '7'
        result = _get(adapter, item)
        raw = b''.join(iter(lambda: result['Body'].read(4), b''))
        assert raw == b'fictional-media'
        assert result['Generation'] == '123456' and result['Metageneration'] == '7'
        assert result['Metadata'] == {'fixture': 'kept'}
        assert responses[-1].is_closed
        assert len(requests) == 2
        assert requests[0].headers['authorization'].startswith('AWS4-HMAC-SHA256 ')
        assert requests[0].url.params['max-keys'] == '1000'
        assert requests[0].extensions['timeout']['read'] <= 0.5
        download = requests[1]
        assert download.url.params['generation'] == '123456'
        assert download.headers['x-amz-if-generation-match'] == '123456'
        assert download.headers['x-amz-if-metageneration-match'] == '7'
        assert download.headers['if-match'] == item['ETag']
        assert download.headers['accept-encoding'] == 'gzip' and 'range' not in download.headers
        assert download.extensions['timeout']['read'] == 30
    finally:
        adapter.close()


def test_frozen_inventory_cannot_be_replaced_by_caller_mutation(media):
    adapter, requests, _ = _adapter(media)
    try:
        frozen = adapter.inventory()
        frozen[KEY]['generation'] = '999999'
        with pytest.raises(media.GCSOnlineMediaError):
            _get(adapter, frozen[KEY])
        assert len(requests) == 1
    finally:
        adapter.close()


def test_negotiation_headers_stay_on_wire_but_version_conditions_are_signed(media):
    adapter, requests, _ = _adapter(media)
    try:
        result = _get(adapter, adapter.inventory()[KEY])
        result['Body'].close()
        for request in requests:
            names = set(request.headers['authorization'].split('SignedHeaders=', 1)[1].split(',', 1)[0].split(';'))
            assert {'host', 'x-amz-date', 'x-amz-content-sha256'} <= names
            assert not {'accept', 'accept-encoding', 'connection', 'user-agent'} & names
            assert 'accept-encoding' in request.headers
        assert requests[0].headers['accept-encoding'] == 'identity'
        assert requests[1].headers['accept-encoding'] == 'gzip'
        download_names = set(requests[1].headers['authorization'].split('SignedHeaders=', 1)[1].split(',', 1)[0].split(';'))
        assert {'if-match', 'x-amz-if-generation-match', 'x-amz-if-metageneration-match'} <= download_names
    finally:
        adapter.close()


def test_aws4_preconditions_use_one_vendor_prefix_without_losing_version_pins(media):
    adapter, requests, _ = _adapter(media)
    try:
        item = adapter.inventory()[KEY]
        result = _get(adapter, item)
        assert result['Body'].read() == b'fictional-media'
        request = requests[-1]
        assert request.headers['authorization'].startswith('AWS4-HMAC-SHA256 ')
        assert not any(name.startswith('x-goog-') for name in request.headers)
        for suffix, expected in (('generation', '123456'), ('metageneration', '7')):
            name = 'x-amz-if-' + suffix + '-match'
            assert request.headers.get_list(name) == [expected]
            assert name in request.headers['authorization'].split('SignedHeaders=', 1)[1].split(',', 1)[0].split(';')
        assert request.url.params['generation'] == item['generation']
        assert request.headers['if-match'] == item['ETag']
        assert result['Generation'] == item['generation']
        assert result['Metageneration'] == item['metageneration']
        assert len(requests) == 2
    finally:
        adapter.close()


@pytest.mark.parametrize('status', [206, 302, 404, 412])
def test_missing_or_changed_generation_never_falls_back_or_redirects(media, status):
    adapter, requests, responses = _adapter(media, status=status)
    try:
        item = adapter.inventory()[KEY]
        with pytest.raises(media.GCSOnlineMediaError):
            _get(adapter, item)
        assert len(requests) == 2 and responses[-1].is_closed
    finally:
        adapter.close()


@pytest.mark.parametrize('headers', [
    {'X-Goog-Generation': '999'}, {'X-Goog-Metageneration': '8'},
    {'X-Goog-Generation': None}, {'X-Goog-Metageneration': None},
    {'Content-Length': None}, {'Content-Length': '999'}, {'ETag': '"different"'},
    {'X-Goog-Stored-Content-Length': '999'},
    {'X-Goog-Stored-Content-Encoding': 'gzip'},
    {'Content-Encoding': 'gzip', 'X-Goog-Stored-Content-Encoding': 'identity'},
])
def test_response_identity_and_stored_byte_headers_must_match(media, headers):
    adapter, _, responses = _adapter(media, headers=headers)
    try:
        item = adapter.inventory()[KEY]
        with pytest.raises(media.GCSOnlineMediaError):
            _get(adapter, item)
        assert responses[-1].is_closed
    finally:
        adapter.close()


@pytest.mark.parametrize('headers', [
    {'X-Goog-Stored-Content-Encoding': 'identity'},
    {'Content-Encoding': 'identity', 'X-Goog-Stored-Content-Encoding': ''},
])
def test_explicit_and_omitted_identity_encoding_preserve_verified_raw_bytes(media, headers):
    adapter, _, responses = _adapter(media, headers=headers)
    try:
        result = _get(adapter, adapter.inventory()[KEY])
        assert result['Body'].read() == b'fictional-media'
        assert result['Body'].read() == b''
        assert responses[-1].is_closed
    finally:
        adapter.close()


def test_gzip_object_is_backed_up_as_raw_stored_bytes(media):
    data = gzip.compress(b'fictional text' * 100)
    adapter, _, _ = _adapter(media, data=data, headers={
        'Content-Encoding': 'gzip', 'X-Goog-Stored-Content-Encoding': 'gzip',
        'X-Goog-Stored-Content-Length': str(len(data)),
    })
    try:
        result = _get(adapter, adapter.inventory()[KEY])
        raw = b''.join(iter(lambda: result['Body'].read(1024), b''))
        assert raw == data and gzip.decompress(raw) == b'fictional text' * 100
        assert result['ContentEncoding'] == 'gzip'
    finally:
        adapter.close()


def test_equal_length_wrong_bytes_fail_checksum_before_final_eof(media):
    adapter, _, responses = _adapter(media, data=b'abc', body=b'bad')
    try:
        result = _get(adapter, adapter.inventory()[KEY])
        with pytest.raises(media.GCSOnlineMediaError):
            b''.join(iter(lambda: result['Body'].read(1024), b''))
        assert responses[-1].is_closed
    finally:
        adapter.close()


@pytest.mark.parametrize('fault', ['truncated', 'continuation', 'duplicate', 'missing_generation',
                                 'missing_metageneration', 'bucket', 'doctype', 'oversized'])
def test_partial_or_unsafe_inventory_cannot_become_a_snapshot(media, fault):
    data = _xml(b'fictional-media')
    if fault == 'truncated':
        data = data.replace(b'<IsTruncated>false', b'<IsTruncated>true')
    elif fault == 'continuation':
        data = data.replace(b'</ListBucketResult>', b'<NextMarker>more</NextMarker></ListBucketResult>')
    elif fault == 'duplicate':
        entry = data[data.index(b'<Contents>'):data.index(b'</Contents>') + len(b'</Contents>')]
        data = data.replace(b'</ListBucketResult>', entry + b'</ListBucketResult>')
    elif fault == 'missing_generation':
        data = data.replace(b'<Generation>123456</Generation>', b'')
    elif fault == 'missing_metageneration':
        data = data.replace(b'<MetaGeneration>7</MetaGeneration>', b'')
    elif fault == 'bucket':
        data = data.replace(b'<Name>fixture-bucket', b'<Name>another-bucket')
    elif fault == 'doctype':
        data = b'<!DOCTYPE doc [<!ENTITY x "dummy-private-payload">]>' + data
    elif fault == 'oversized':
        data = b'x' * (media._MAX_LIST_BYTES + 1)
    adapter, requests, responses = _adapter(media, xml=data)
    try:
        with pytest.raises(media.GCSOnlineMediaError) as captured:
            adapter.inventory()
        assert 'dummy-private-payload' not in str(captured.value)
        assert len(requests) == 1 and responses[-1].is_closed
        assert adapter._frozen is None
    finally:
        adapter.close()


def test_transport_error_is_redacted_and_not_retried(media):
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        raise httpx.ReadTimeout('dummy-secret-and-private-object')
    adapter = media.GCSOnlineMedia(VALUES, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(media.GCSOnlineMediaError) as captured:
            adapter.inventory()
        assert 'dummy-secret' not in str(captured.value) and count == 1
    finally:
        adapter.close()
