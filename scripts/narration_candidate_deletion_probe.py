"""Inject synthetic S3 deletion failures into a network-isolated candidate."""
import asyncio
import json
import os
from types import SimpleNamespace

if os.environ.get('ASB_NARRATION_ISOLATED_PROBE') != '1':
    raise RuntimeError('An explicitly isolated fixture is required')

from src.models.db import StoragePurgeTask  # noqa: E402
from src.services import purge_queue, storage  # noqa: E402


class Session:
    async def commit(self):
        return None


async def main():
    client = SimpleNamespace(list_objects_v2=object(), delete_objects=object())
    storage.get_s3_client = lambda: client

    async def partial(_method, **_kwargs):
        return {'Deleted': [{'Key': 'test/a'}]}

    storage._call_s3 = partial
    assert await storage.delete_keys(['test/a', 'test/b']) == ['test/a', 'test/b']

    async def mixed(_method, **_kwargs):
        return {'Deleted': [{'Key': 'test/a'}], 'Errors': [{'Key': 'test/b'}]}

    storage._call_s3 = mixed
    assert await storage.delete_keys(['test/a', 'test/b']) == ['test/b']

    pages = iter([{'Contents': [], 'IsTruncated': True, 'NextContinuationToken': 'same'},
                  {'Contents': [], 'IsTruncated': True, 'NextContinuationToken': 'same'}])

    async def repeated(_method, **_kwargs):
        return next(pages)

    storage._call_s3 = repeated
    assert await storage._delete_prefix_keys('test/') == ['test/*']

    async def failed(_task):
        raise RuntimeError('synthetic private diagnostic')

    purge_queue._execute_task = failed
    task = StoragePurgeTask(id=1, user_key='fixture', reason='consent_revoke',
                            kind='prefix', target='test/', status='pending')
    assert await purge_queue.run_purge_tasks(Session(), [task]) == ['test/']
    assert task.status == 'pending' and task.last_error == 'storage_operation_failed'
    print(json.dumps({'status': 'DELETION_FAILURE_FIXTURE_PASSED', 'synthetic_data_only': True,
                      'real_storage_verified': False, 'production_authorized': False}))


asyncio.run(main())
