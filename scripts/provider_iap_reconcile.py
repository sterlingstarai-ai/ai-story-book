"""Read-only GCE observation of a locally owned sender operation.

Only a verified successful operation may receive a local terminal record. This
module never updates GCE metadata, never reads a provider key, and never closes
the enclosing sender session. Missing or ambiguous evidence stays unresolved.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import urllib.parse
import uuid

try:
    from scripts.gcp_instance_ssh_guard import _valid_public_key
    from scripts.provider_iap_sender_session import GceInstanceTransport, INSTANCE, INSTANCE_ID, PROJECT, ZONE
except ModuleNotFoundError:
    from gcp_instance_ssh_guard import _valid_public_key
    from provider_iap_sender_session import GceInstanceTransport, INSTANCE, INSTANCE_ID, PROJECT, ZONE


class ReconcileError(RuntimeError):
    pass


_ID = re.compile(r'[0-9a-f]{32}\Z')
_OPERATION = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
_FINGERPRINT = re.compile(r'[A-Za-z0-9_+/=-]{1,256}\Z')
_BASE = f'https://compute.googleapis.com/compute/v1/projects/{PROJECT}/zones/{ZONE}'
_INSTANCE_URL = f'{_BASE}/instances/{INSTANCE}'
_EXPECTED_TARGET = {'project': PROJECT, 'zone': ZONE, 'instance': INSTANCE, 'instance_id': INSTANCE_ID}


class GceReadOnly:
    """GET-only access to the fixed instance and its zonal operations."""

    def __init__(self, *, env):
        self._transport = GceInstanceTransport(env=env, ledger=None, session_id='', entry='')

    def metadata(self):
        return self._transport._request(_INSTANCE_URL)

    def operation(self, name):
        if not isinstance(name, str) or not _OPERATION.fullmatch(name):
            raise ReconcileError('Operation identity is invalid')
        return self._transport._request(f'{_BASE}/operations/{name}')

    def find_operation(self, request_id):
        """Bounded listing; empty/multiple results remain unconfirmed."""
        if not _valid_request_id(request_id):
            raise ReconcileError('Request identity is invalid')
        matches = []
        page = None
        seen = set()
        for _ in range(5):
            params = {'maxResults': '100', 'filter': 'clientOperationId = "' + request_id + '"',
                      'fields': 'nextPageToken,items(name,clientOperationId,operationType,targetId,targetLink,zone,status,error)'}
            if page is not None:
                params['pageToken'] = page
            response = self._transport._request(f'{_BASE}/operations?' + urllib.parse.urlencode(params))
            if not isinstance(response, dict) or not isinstance(response.get('items', []), list):
                raise ReconcileError('Operation listing is invalid')
            for item in response.get('items', []):
                if not isinstance(item, dict) or item.get('clientOperationId') != request_id:
                    raise ReconcileError('Operation listing is inconsistent')
                matches.append(item)
                if len(matches) > 1:
                    return matches
            page = response.get('nextPageToken')
            if page is None:
                return matches
            if not isinstance(page, str) or not page or len(page) > 1024 or page in seen:
                raise ReconcileError('Operation pagination is invalid')
            seen.add(page)
        raise ReconcileError('Operation listing is incomplete')


def _valid_request_id(value):
    try:
        parsed = uuid.UUID(value)
        return str(parsed) == value and parsed.int != 0
    except (ValueError, TypeError, AttributeError):
        return False


def _valid_entry(entry):
    if not isinstance(entry, str) or len(entry) > 4096:
        return False
    match = re.fullmatch(r'jmac:(ssh-ed25519 [A-Za-z0-9+/=]+) google-ssh (\{[^\r\n]+\})', entry)
    if not match or not _valid_public_key(match.group(1)):
        return False
    try:
        obj = json.loads(match.group(2))
        expiry = dt.datetime.fromisoformat(obj['expireOn'].replace('Z', '+00:00'))
        return (set(obj) == {'userName', 'expireOn'} and obj['userName'] == 'jmac'
                and expiry.tzinfo is not None and expiry.utcoffset() is not None)
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def _trusted_link(value, path):
    if not isinstance(value, str):
        return False
    parsed = urllib.parse.urlparse(value)
    return (parsed.scheme == 'https' and parsed.netloc in {'compute.googleapis.com', 'www.googleapis.com'}
            and parsed.path == path and not parsed.params and not parsed.query and not parsed.fragment)


def _valid_operation(value, request_id, recorded_name):
    target_path = f'/compute/v1/projects/{PROJECT}/zones/{ZONE}/instances/{INSTANCE}'
    zone_path = f'/compute/v1/projects/{PROJECT}/zones/{ZONE}'
    return (isinstance(value, dict) and isinstance(value.get('name'), str)
            and bool(_OPERATION.fullmatch(value['name']))
            and (recorded_name is None or value['name'] == recorded_name)
            and value.get('clientOperationId') == request_id
            and value.get('operationType') == 'setMetadata' and str(value.get('targetId')) == INSTANCE_ID
            and _trusted_link(value.get('targetLink'), target_path) and _trusted_link(value.get('zone'), zone_path)
            and value.get('status') in {'PENDING', 'RUNNING', 'DONE'})


def _metadata_view(instance, owned_entry, submitted_fingerprint):
    if (not isinstance(instance, dict) or str(instance.get('id')) != INSTANCE_ID
            or instance.get('name') != INSTANCE or not isinstance(instance.get('metadata'), dict)):
        raise ReconcileError('GCE instance identity is unconfirmed')
    metadata = instance['metadata']
    fingerprint = metadata.get('fingerprint')
    items = metadata.get('items', [])
    if (not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint)
            or not isinstance(items, list) or any(not isinstance(x, dict) for x in items)):
        raise ReconcileError('GCE metadata is invalid')
    ssh_items = [x for x in items if x.get('key') == 'ssh-keys']
    if len(ssh_items) > 1 or (ssh_items and not isinstance(ssh_items[0].get('value'), str)):
        raise ReconcileError('GCE SSH metadata is ambiguous')
    lines = ssh_items[0]['value'].splitlines() if ssh_items else []
    count = sum(line == owned_entry for line in lines)
    if count > 1:
        raise ReconcileError('Owned SSH entry is ambiguous')
    return {'owned_entry_count': count, 'fingerprint_matches_submitted': fingerprint == submitted_fingerprint}


def reconcile_operation(*, ledger, operation_id, client):
    """Observe one exact owned operation, recording only confirmed success.

    The enclosing session remains open even after success; private-identity,
    tunnel and any other pending operation recovery still need their own proof.
    """
    if not isinstance(operation_id, str) or not _ID.fullmatch(operation_id):
        raise ReconcileError('Operation identity is invalid')
    try:
        records = ledger._records()
        started = records.get((operation_id, 'op-start'))
        if (not isinstance(started, dict)
                or set(started) != {'version', 'id', 'kind', 'session', 'request_id', 'owned_entry',
                                    'metadata_fingerprint', 'action'}):
            raise ReconcileError('Owned operation journal was not found')
        sid = started.get('session')
        opened = records.get((sid, 'session-open'))
        if (not isinstance(sid, str) or not _ID.fullmatch(sid) or not isinstance(opened, dict)
                or set(opened) != {'version', 'id', 'kind', 'temporary_directory', 'target'}
                or opened.get('target') != _EXPECTED_TARGET or records.get((sid, 'session-closed')) is not None
                or not _valid_request_id(started.get('request_id')) or not _valid_entry(started.get('owned_entry'))
                or not isinstance(started.get('metadata_fingerprint'), str)
                or not _FINGERPRINT.fullmatch(started['metadata_fingerprint'])
                or started.get('action') not in {'insert', 'remove'}):
            raise ReconcileError('Owned operation journal is invalid')
        done = records.get((operation_id, 'op-done'))
        if done is not None:
            if (set(done) != {'version', 'id', 'kind', 'session', 'outcome'} or done.get('session') != sid
                    or done.get('outcome') not in {'applied', 'rejected'}):
                raise ReconcileError('Recorded operation outcome is invalid')
            return {'status': 'ALREADY_RECORDED', 'session_closed': False}
        recorded = records.get((operation_id, 'op-operation'))
        name = None
        if recorded is not None:
            if (set(recorded) != {'version', 'id', 'kind', 'session', 'operation'} or recorded.get('session') != sid
                    or not isinstance(recorded.get('operation'), str) or not _OPERATION.fullmatch(recorded['operation'])):
                raise ReconcileError('Recorded operation identity is invalid')
            name = recorded['operation']
            operation = client.operation(name)
        else:
            matches = client.find_operation(started['request_id'])
            if not isinstance(matches, list) or len(matches) != 1:
                return {'status': 'UNCONFIRMED', 'session_closed': False}
            operation = matches[0]
        if not _valid_operation(operation, started['request_id'], name):
            return {'status': 'UNCONFIRMED', 'session_closed': False}
        view = _metadata_view(client.metadata(), started['owned_entry'], started['metadata_fingerprint'])
        common = {'session_closed': False, **view}
        if operation['status'] != 'DONE':
            return {'status': 'PENDING', **common}
        if 'error' in operation:
            return {'status': 'FAILED', **common}
        expected = 1 if started['action'] == 'insert' else 0
        if view['owned_entry_count'] != expected:
            return {'status': 'UNCONFIRMED', **common}
        if name is None:
            ledger.record_operation(operation_id, sid, operation['name'])
        ledger.finish_operation(operation_id, sid, 'applied')
        return {'status': 'CONFIRMED_APPLIED', **common}
    except ReconcileError:
        raise
    except Exception:
        raise ReconcileError('Read-only operation reconciliation is unconfirmed') from None
