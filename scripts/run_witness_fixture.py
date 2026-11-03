"""Exercise a checkpoint against disposable Postgres and local MinIO only.

The GCS JSON API is emulated in-process and backed by local MinIO. This does
not test Google Cloud or establish independent account administration.
"""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import unquote

import httpx

from run_restore_replay_fixture import require_local_fixture


async def main():
    require_local_fixture()
    from fixture_journal_store import load_fixture_journal
    from run_backup_restore_rehearsal import storage
    from src.core.database import AsyncSessionLocal, async_engine
    from src.services.privacy_checkpoint_gcs import GCSCheckpointStore
    from src.services.privacy_checkpoint_head import append_checkpoint_head, verify_anchored_checkpoint
    from src.services.privacy_checkpoint_keys import issue_checkpoint_key, recover_checkpoint_key
    from src.services.privacy_journal import JournalError, JournalScan
    from src.services.privacy_journal_checkpoint import capture_fenced_checkpoint, verify_checkpoint_extension
    from src.services.privacy_witness_watch import assess_witness

    endpoint = os.environ.get('ASB_FIXTURE_WITNESS_ENDPOINT')
    if endpoint != 'http://127.0.0.1:19010':
        raise RuntimeError('Disposable local witness required')
    client = storage(endpoint)
    bucket, head_bucket = 'synthetic-checkpoint-witness', 'synthetic-checkpoint-head'

    def handler(request):
        if request.url.host != 'storage.googleapis.com':
            raise RuntimeError('Unexpected witness host')
        request_bucket = request.url.path.split('/b/', 1)[1].split('/', 1)[0]
        if request_bucket not in {bucket, head_bucket}:
            raise RuntimeError('Unexpected synthetic bucket')
        if request.method == 'POST':
            if request.url.params.get('ifGenerationMatch') != '0':
                raise RuntimeError('Create-only precondition missing')
            try:
                client.put_object(Bucket=request_bucket, Key=request.url.params['name'], Body=request.content,
                                  IfNoneMatch='*')
            except Exception:
                return httpx.Response(412)
            return httpx.Response(200)
        name = unquote(request.url.raw_path.decode().split('/o/', 1)[1].split('?', 1)[0])
        try:
            response = client.get_object(Bucket=request_bucket, Key=name)
            try:
                value = response['Body'].read()
            finally:
                response['Body'].close()
            return httpx.Response(200, content=value)
        except Exception:
            return httpx.Response(404)

    journal = load_fixture_journal()
    ref_path = Path(os.environ['ASB_FIXTURE_JOURNAL_DIR']).parent / 'witness-reference.json'
    namespace = '1' * 32
    recovery_key = b'\x42' * 32  # Synthetic only; never a production recovery key.
    head_key = b'\x43' * 32  # Synthetic only; held separately from checkpoint key.
    try:
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            witness = GCSCheckpointStore(bucket, token_provider=lambda: 'fixture-token', client=http)
            head_store = GCSCheckpointStore(head_bucket, token_provider=lambda: 'fixture-token', client=http)
            mode = os.environ.get('ASB_FIXTURE_WITNESS_MODE')
            if mode == 'capture':
                client.create_bucket(Bucket=bucket)
                client.create_bucket(Bucket=head_bucket)
                key, key_ref = issue_checkpoint_key(witness, namespace=namespace, recovery_key=recovery_key)
                async with AsyncSessionLocal() as db:
                    ref = await capture_fenced_checkpoint(db, journal, witness, namespace=namespace,
                        generation=1, key=key, now=1000)
                head = append_checkpoint_head(head_store, namespace=namespace, key=head_key, checkpoint=ref)
                ref_path.write_text(json.dumps({'checkpoint': ref, 'key': key_ref, 'head': head}))
            elif mode == 'verify':
                refs = json.loads(ref_path.read_text())
                ref, key_ref = refs['checkpoint'], refs['key']
                key = recover_checkpoint_key(witness, namespace=namespace, key_id=key_ref['key_id'],
                    expected_sha256=key_ref['sha256'], recovery_key=recovery_key)
                scan = journal.scan()
                result = verify_checkpoint_extension(witness, scan, namespace=namespace, generation=1,
                    expected_sha256=ref['sha256'], key=key, now=1001, max_age=10)
                if (result['checkpoint_count'] != ref['event_count'] or ref['event_count'] < 1
                        or result['journal_count'] <= ref['event_count']):
                    raise RuntimeError('Synthetic checkpoint extension mismatch')
                async with AsyncSessionLocal() as db:
                    prior_status = await assess_witness(db, journal, head_store, witness, namespace=namespace,
                        head_key=head_key, checkpoint_key=key, trusted_head=refs['head'], now=1001, max_age=10)
                if prior_status != {'status': 'ALERT', 'restore_authorized': False}:
                    raise RuntimeError('Unanchored source events did not trigger alert')
                async with AsyncSessionLocal() as db:
                    next_checkpoint = await capture_fenced_checkpoint(db, journal, witness, namespace=namespace,
                        generation=2, key=key, now=1001)
                next_head = append_checkpoint_head(head_store, namespace=namespace, key=head_key,
                    checkpoint=next_checkpoint, previous=refs['head'])
                head_args = {'namespace': namespace, 'head_key': head_key, 'checkpoint_key': key,
                             'trusted_head': next_head, 'now': 1002, 'max_age': 10}
                if verify_anchored_checkpoint(head_store, witness, scan, candidate_head=next_head,
                                              **head_args)['restore_authorized'] is not False:
                    raise RuntimeError('Synthetic head improperly authorized restore')
                async with AsyncSessionLocal() as db:
                    current_status = await assess_witness(db, journal, head_store, witness, namespace=namespace,
                        head_key=head_key, checkpoint_key=key, trusted_head=next_head, now=1002, max_age=10)
                if current_status != {'status': 'SNAPSHOT_MATCHES', 'restore_authorized': False}:
                    raise RuntimeError('Fenced current witness snapshot failed')
                try:
                    verify_anchored_checkpoint(head_store, witness, scan, candidate_head=refs['head'], **head_args)
                except JournalError:
                    pass
                else:
                    raise RuntimeError('Synthetic stale head was accepted')
                altered = JournalScan(committed=tuple(e for e in scan.committed if not (
                    e.subject == '00000000-0000-4000-8000-000000000003' and e.revision == 1)),
                    pending_count=0, restore_authorized=False)
                try:
                    verify_checkpoint_extension(witness, altered, namespace=namespace, generation=1,
                        expected_sha256=ref['sha256'], key=key, now=1001, max_age=10)
                except JournalError:
                    pass
                else:
                    raise RuntimeError('Missing witnessed event was accepted')
            else:
                raise RuntimeError('Unknown synthetic witness operation')
    finally:
        await async_engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
