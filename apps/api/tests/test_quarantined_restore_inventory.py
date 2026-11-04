"""Isolated restore must reject incomplete storage listings."""
import hashlib
import io
from pathlib import Path
import sys
import unittest

import boto3
from botocore.stub import Stubber

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from quarantined_restore_runtime import RestoreRuntimeError, _read_media  # noqa: E402


class FakeStorage:
    def __init__(self, pages, data=None):
        self.pages = pages
        self.data = data or {}

    def get_bucket_versioning(self, **kwargs):
        return {}

    def get_paginator(self, name):
        assert name == 'list_objects_v2'
        return self

    def paginate(self, **kwargs):
        return iter(self.pages)

    def get_object(self, *, Bucket, Key):
        return {'Body': io.BytesIO(self.data[Key])}


class QuarantinedInventoryTests(unittest.TestCase):
    def test_empty_inventory_requires_one_explicit_final_page(self):
        _read_media(FakeStorage([{'IsTruncated': False}]), 'synthetic', [])
        for pages in ([], [{}], [{'IsTruncated': True, 'NextContinuationToken': 'next'}],
                      [{'IsTruncated': True}], [{'IsTruncated': 'false'}]):
            with self.subTest(pages=pages), self.assertRaises(RestoreRuntimeError):
                _read_media(FakeStorage(pages), 'synthetic', [])

    def test_multiple_pages_complete_and_each_object_matches(self):
        payloads = {'a': b'one', 'b': b'two'}
        objects = [{'key': key, 'size': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
                   for key, value in payloads.items()]
        pages = [{'IsTruncated': True, 'NextContinuationToken': 'first', 'Contents': [{'Key': 'a'}]},
                 {'IsTruncated': False, 'Contents': [{'Key': 'b'}]}]
        _read_media(FakeStorage(pages, payloads), 'synthetic', objects)
        with self.assertRaises(RestoreRuntimeError):
            _read_media(FakeStorage(pages[:1], payloads), 'synthetic', objects)

    def test_repeated_token_or_page_after_final_is_rejected(self):
        for pages in ([{'IsTruncated': True, 'NextContinuationToken': 'same'},
                       {'IsTruncated': True, 'NextContinuationToken': 'same'}],
                      [{'IsTruncated': False}, {'IsTruncated': False}]):
            with self.subTest(pages=pages), self.assertRaises(RestoreRuntimeError):
                _read_media(FakeStorage(pages), 'synthetic', [])

    def test_unexpected_header_rejects_object_and_closes_response(self):
        body = io.BytesIO(b'one')

        class StorageWithUnexpectedHeader(FakeStorage):
            def get_object(self, *, Bucket, Key):
                return {'Body': body, 'ContentEncoding': 'gzip'}

        pages = [{'IsTruncated': False, 'Contents': [{'Key': 'a'}]}]
        objects = [{'key': 'a', 'size': 3, 'sha256': hashlib.sha256(b'one').hexdigest(),
                    'content_encoding': None}]
        with self.assertRaisesRegex(RestoreRuntimeError, 'metadata differs'):
            _read_media(StorageWithUnexpectedHeader(pages), 'synthetic', objects)
        self.assertTrue(body.closed)

    def test_botocore_paginator_stopping_on_truncated_page_is_rejected(self):
        client = boto3.client('s3', endpoint_url='http://127.0.0.1:9',
                              aws_access_key_id='fixture', aws_secret_access_key='fixture',
                              region_name='us-east-1')
        with Stubber(client) as stub:
            stub.add_response('get_bucket_versioning', {}, {'Bucket': 'synthetic'})
            stub.add_response('list_objects_v2', {'IsTruncated': True}, {'Bucket': 'synthetic'})
            with self.assertRaises(RestoreRuntimeError):
                _read_media(client, 'synthetic', [])


if __name__ == '__main__':
    unittest.main()
