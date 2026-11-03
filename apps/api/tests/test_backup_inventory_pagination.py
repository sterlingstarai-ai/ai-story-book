"""An incomplete storage listing must never become a complete backup."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from backup_external import BackupError, inventory  # noqa: E402
import backup_external  # noqa: E402


class Storage:
    def __init__(self, pages):
        self.pages = pages

    def get_paginator(self, name):
        assert name == 'list_objects_v2'
        return self

    def paginate(self, **_kwargs):
        return iter(self.pages)


def test_inventory_reads_all_pages():
    pages = [
        {'IsTruncated': True, 'NextContinuationToken': 'next',
         'Contents': [{'Key': 'a', 'Size': 1}]},
        {'IsTruncated': False, 'Contents': [{'Key': 'b', 'Size': 2}]},
    ]
    assert set(inventory(Storage(pages), 'bucket')) == {'a', 'b'}


def test_inventory_bounds_empty_pages(monkeypatch):
    monkeypatch.setattr(backup_external, '_MAX_INVENTORY_PAGES', 2)
    pages = [{'IsTruncated': True, 'NextContinuationToken': str(i)} for i in range(3)]
    with pytest.raises(BackupError, match='exceeds limit'):
        inventory(Storage(pages), 'bucket')


@pytest.mark.parametrize('pages', [
    [],
    [{'IsTruncated': True}],
    [{'IsTruncated': True, 'NextContinuationToken': 'next'}],
    [{'IsTruncated': False}, {'IsTruncated': False}],
    [{'IsTruncated': 'false'}],
    [{}],
    [{'IsTruncated': False, 'KeyCount': 1}],
    [{'IsTruncated': False, 'KeyCount': True}],
    [{'IsTruncated': False, 'CommonPrefixes': [{'Prefix': 'missing/'}]}],
    [{'IsTruncated': False, 'Name': 'different-bucket'}],
    [{'IsTruncated': False, 'Contents': [None]}],
    [{'IsTruncated': True, 'NextContinuationToken': 'same'},
     {'IsTruncated': True, 'NextContinuationToken': 'same'}],
])
def test_inventory_rejects_incomplete_or_invalid_pagination(pages):
    with pytest.raises(BackupError):
        inventory(Storage(pages), 'bucket')
