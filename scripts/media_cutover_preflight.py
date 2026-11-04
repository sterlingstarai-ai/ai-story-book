"""Check the empty-source path for a media migration while writers are fenced.

Callers must close admission, drain app writers and independently restrict
direct storage writers before using this check. Its result does not grant
permission to start an application or discard the source.
"""

from contextlib import ExitStack, closing
from uuid import uuid4

from botocore.exceptions import ClientError

from backup_external import inventory, storage_client


class MediaCutoverError(RuntimeError):
    pass


def verify_empty_media_detach(fence, source_values, target_values, *, expected_revision):
    """Verify the empty-storage switch while the old source is still available.

    The caller holds the DB fence and keeps the original bucket available.
    This checks references and inventory, not retirement of source writers.
    """
    if source_values['S3_ENDPOINT'] == target_values['S3_ENDPOINT']:
        raise MediaCutoverError('Media detach requires distinct storage endpoints')
    _require_distinct_credentials(source_values, target_values)
    fence.verify_revision(expected_revision)
    with closing(storage_client(source_values)) as source, closing(storage_client(target_values)) as target:
        _probe_source_reader(source, source_values['S3_BUCKET'])
        verify_empty_cutover(fence, source, source_values['S3_BUCKET'], target, target_values['S3_BUCKET'])


def _require_distinct_credentials(*clients_values):
    for field in ('S3_ACCESS_KEY', 'S3_SECRET_KEY'):
        credentials = {values.get(field) for values in clients_values}
        if not all(credentials) or len(credentials) != len(clients_values):
            raise MediaCutoverError('Cutover storage credentials must be distinct')


def verify_staged_media_cutover(fence, source_values, retired_values, target_values):
    """Recheck exact configured clients while the caller holds the DB fence."""
    source_bucket = source_values['S3_BUCKET']
    if (retired_values['S3_BUCKET'] != source_bucket
            or retired_values['S3_ENDPOINT'] != source_values['S3_ENDPOINT']
            or retired_values['S3_REGION'] != source_values['S3_REGION']):
        raise MediaCutoverError('Retired credential is bound to a different source')
    clients_values = (source_values, retired_values, target_values)
    _require_distinct_credentials(*clients_values)
    with ExitStack() as clients:
        source, retired, target = (
            clients.enter_context(closing(storage_client(values)))
            for values in clients_values
        )
        verify_source_storage_permissions(source, retired, source_bucket)
        verify_empty_cutover(fence, source, source_bucket, target, target_values['S3_BUCKET'])


def verify_source_storage_permissions(read_client, retired_client, bucket):
    """Verify read access and direct write denial for both tested credentials."""
    if read_client is retired_client:
        raise MediaCutoverError('Read and retired storage clients must be distinct')
    try:
        if read_client.meta.endpoint_url != retired_client.meta.endpoint_url:
            raise MediaCutoverError('Source storage clients point to different endpoints')
        before, key = _probe_source_reader(read_client, bucket)
        _require_denied(lambda: retired_client.list_objects_v2(Bucket=bucket, MaxKeys=1), {401, 403})
        _require_denied(lambda: retired_client.delete_object(Bucket=bucket, Key=key), {401, 403})
        if inventory(read_client, bucket) != before:
            raise MediaCutoverError('Source media changed during permission verification')
    except MediaCutoverError:
        raise
    except Exception:
        raise MediaCutoverError('Source storage permissions could not be verified') from None


def verify_staged_target_writer(values):
    """Prove the exact destination credential can write, read and remove a canary."""
    key = 'asb-cutover-target-probe-' + uuid4().hex
    payload = b'AI Story Book cutover write probe'
    args = {'Bucket': values['S3_BUCKET'], 'Key': key}
    try:
        with closing(storage_client(values)) as target:
            _require_denied(lambda: target.head_object(**args), {404})
            put_confirmed = False
            try:
                target.put_object(**args, Body=payload, IfNoneMatch='*')
                put_confirmed = True
            finally:
                # PUT can time out after committing. Read once both to prove
                # the upload and to verify ownership before deleting.
                try:
                    result = target.get_object(**args)
                except ClientError as exc:
                    if put_confirmed or exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode') != 404:
                        raise
                else:
                    with closing(result['Body']) as body:
                        if body.read(len(payload) + 1) != payload:
                            raise MediaCutoverError('Destination canary ownership is unverified')
                    target.delete_object(**args)
                    _require_denied(lambda: target.head_object(**args), {404})
    except MediaCutoverError:
        raise
    except Exception:
        raise MediaCutoverError('Destination write, read or cleanup could not be verified') from None


def _probe_source_reader(read_client, bucket):
    before = inventory(read_client, bucket)
    # Neon uses the same storage:write scope for upload and deletion.
    # Probe deletion only on a randomly generated absent key.
    key = 'asb-cutover-permission-probe-' + uuid4().hex
    if key in before:
        raise MediaCutoverError('Storage permission probe key already exists')
    _require_denied(lambda: read_client.delete_object(Bucket=bucket, Key=key), {403})
    return before, key


def _require_denied(action, expected_http):
    try:
        action()
    except ClientError as exc:
        if exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode') in expected_http:
            return
    raise MediaCutoverError('Source storage permission did not return an authorization denial')


def verify_empty_cutover(fence, source_client, source_bucket, target_client, target_bucket):
    """Reject any visible source or target objects or persisted media references."""
    if source_bucket == target_bucket:
        raise MediaCutoverError('Media cutover requires distinct bucket names')
    try:
        fence.verify()
        if inventory(source_client, source_bucket) or inventory(target_client, target_bucket):
            raise MediaCutoverError('Media cutover requires both buckets to be empty')
        fence.verify_no_media_references()
        _verify_empty_source_history(source_client, source_bucket)
        if inventory(source_client, source_bucket) or inventory(target_client, target_bucket):
            raise MediaCutoverError('Media appeared during cutover verification')
        fence.verify()
    except MediaCutoverError:
        raise
    except Exception:
        raise MediaCutoverError('Empty media cutover could not be verified') from None


def _verify_empty_source_history(client, bucket):
    uploads = client.list_multipart_uploads(Bucket=bucket)
    versions = client.list_object_versions(Bucket=bucket)
    if (uploads.get('IsTruncated') is not False or uploads.get('Uploads', []) != []
            or uploads.get('CommonPrefixes', []) != []
            or versions.get('IsTruncated') is not False or versions.get('Versions', []) != []
            or versions.get('DeleteMarkers', []) != [] or versions.get('CommonPrefixes', []) != []):
        raise MediaCutoverError('Source storage contains multipart uploads or retained versions')
