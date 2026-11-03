"""Fake GCE/IAP/sender checks: never touch a network, Keychain, or real key."""
import base64
from contextlib import contextmanager
import copy
import datetime as dt
import email.utils
import hashlib
import io
import os
from pathlib import Path
import signal
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error

from scripts import provider_iap_sender_session as session
from scripts.gcp_instance_ssh_guard import Conflict, UncertainUpdate

WIRE = b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20' + bytes(range(32))
PUBLIC = 'ssh-ed25519 ' + base64.b64encode(WIRE).decode('ascii')
RECEIVER = b'synthetic-only'
RECEIVER_SHA = hashlib.sha256(RECEIVER).hexdigest()


class FakeMetadata:
    def __init__(self, events, mode):
        self.events, self.mode, self.calls = events, mode, 0
        self.data = {'fingerprint': '0', 'items': [{'key': 'unrelated', 'value': 'preserved'}]}
        self.ledger, self.session_id, self.entry = None, None, None

    def verify_target(self):
        self.events.append('target_verified')

    def read(self):
        return copy.deepcopy(self.data)

    def compare_and_set(self, value):
        self.calls += 1
        self.events.append('metadata_insert' if self.calls == 1 else 'metadata_remove')
        operation, _ = self.ledger.begin_operation(self.session_id, self.entry,
                                                   metadata_fingerprint=value['fingerprint'],
                                                   action='insert' if self.calls == 1 else 'remove')
        self.data = copy.deepcopy(value)
        self.data['fingerprint'] = str(self.calls)
        if ((self.mode == 'insert_uncertain' and self.calls == 1)
                or (self.mode == 'remove_uncertain' and self.calls == 2)):
            raise UncertainUpdate('synthetic response lost')
        self.ledger.record_operation(operation, self.session_id, 'operation-' + str(self.calls))
        self.ledger.finish_operation(operation, self.session_id, 'applied')


class FakeInfra:
    def __init__(self, mode='success'):
        self.events, self.mode = [], mode
        self.metadata = FakeMetadata(self.events, mode)
        self.identity_path = None

    def identity(self, directory):
        path = Path(directory) / 'identity'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, b'synthetic-fixture-only')
            info = os.fstat(fd)
        finally:
            os.close(fd)
        self.identity_path = path
        self.events.append('identity_created')
        return path, (info.st_dev, info.st_ino), PUBLIC

    def transport(self, ledger, session_id, entry):
        self.metadata.ledger, self.metadata.session_id, self.metadata.entry = ledger, session_id, entry
        return self.metadata

    @contextmanager
    def tunnel(self):
        self.events.append('tunnel_open')
        try:
            yield 22222
        finally:
            self.events.append('tunnel_closed')
            if self.mode == 'tunnel_cleanup_failure':
                raise session.TunnelCleanupError('synthetic tunnel cleanup failure')

    def transfer(self, **kwargs):
        if self.mode == 'master_failure':
            raise session.SessionError('synthetic master failure')
        if not self.identity_path.exists():
            raise AssertionError('identity vanished before authentication')
        self.events.append('master_authenticated')
        if kwargs['on_master_ready']() is not True:
            raise session.SessionError('synthetic cleanup rejected')
        if self.identity_path.exists():
            raise AssertionError('identity remained when synthetic keychain was read')
        if any(item.get('key') == 'ssh-keys' for item in self.metadata.read()['items']):
            raise AssertionError('metadata remained when synthetic keychain was read')
        self.events.append('synthetic_keychain_read')
        return {'status': 'KEY_FILE_INSTALLED', 'recovery_required': False}


class IapSenderSessionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='asb-session-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.known = self.base / 'known_hosts'
        self.known.write_text('synthetic-known-host-only\n')
        os.chmod(self.known, 0o600)
        self.journal = self.base / 'journal'
        self.journal.mkdir(mode=0o700)

    def args(self, infra):
        return {'transaction_id': 'a' * 32, 'receiver_source': RECEIVER, 'receiver_sha256': RECEIVER_SHA,
                'known_hosts_file': str(self.known), 'journal_dir': str(self.journal),
                '_infrastructure': infra, '_sender': infra.transfer}

    def test_explicit_opt_in_required_before_any_side_effect(self):
        infra = FakeInfra()
        with self.assertRaises(session.SessionError):
            session.transfer_via_iap(**self.args(infra))
        self.assertEqual(infra.events, [])

    def test_real_gce_infrastructure_rejects_injected_sender_and_journal(self):
        kwargs = self.args(FakeInfra())
        kwargs['_infrastructure'] = session.GceInfrastructure()
        with self.assertRaisesRegex(session.SessionError, 'Live IAP session configuration is invalid'):
            session.transfer_via_iap(execute=True, **kwargs)

    def test_live_legacy_audit_failure_precedes_session_and_identity(self):
        infra = session.GceInfrastructure()
        kwargs = self.args(FakeInfra())
        kwargs.update(_infrastructure=infra, _sender=None)
        with (patch.object(session, 'PRODUCTION_JOURNAL_DIR', str(self.journal)),
              patch.object(session.sender, '_known_hosts'),
              patch.object(session, '_audit_legacy_sessions', side_effect=RuntimeError('unconfirmed')) as audit,
              patch.object(infra, 'identity') as identity):
            with self.assertRaises(Exception):
                session.transfer_via_iap(execute=True, **kwargs)
        audit.assert_called_once_with(infra)
        identity.assert_not_called()
        self.assertEqual(list(self.journal.glob('session-*.json')), [])

    def test_live_legacy_audit_success_precedes_identity(self):
        infra = session.GceInfrastructure()
        kwargs = self.args(FakeInfra())
        kwargs.update(_infrastructure=infra, _sender=None)
        order = []

        def stop_at_identity(_):
            order.append('identity')
            raise RuntimeError('synthetic stop')

        with (patch.object(session, 'PRODUCTION_JOURNAL_DIR', str(self.journal)),
              patch.object(session.sender, '_known_hosts'),
              patch.object(session, '_audit_legacy_sessions', side_effect=lambda _: order.append('audit')),
              patch.object(infra, 'identity', side_effect=stop_at_identity)):
            with self.assertRaises(session.SessionError):
                session.transfer_via_iap(execute=True, **kwargs)
        self.assertEqual(order, ['audit', 'identity'])

    def test_success_cleans_metadata_and_identity_before_synthetic_keychain(self):
        infra = FakeInfra()
        result = session.transfer_via_iap(execute=True, **self.args(infra))
        self.assertEqual(result, {'status': 'KEY_FILE_INSTALLED', 'recovery_required': False})
        self.assertEqual(infra.events, ['identity_created', 'target_verified', 'tunnel_open', 'metadata_insert',
                                        'master_authenticated', 'metadata_remove', 'synthetic_keychain_read',
                                        'tunnel_closed'])
        self.assertEqual(infra.metadata.data['items'], [{'key': 'unrelated', 'value': 'preserved'}])

    def test_uncertain_insert_or_remove_never_reaches_keychain(self):
        for mode in ('insert_uncertain', 'remove_uncertain'):
            infra = FakeInfra(mode)
            journal = self.base / mode
            journal.mkdir(mode=0o700)
            kwargs = self.args(infra)
            kwargs['journal_dir'] = str(journal)
            with self.subTest(mode=mode), self.assertRaisesRegex(session.SessionError, 'metadata cleanup is unconfirmed'):
                session.transfer_via_iap(execute=True, **kwargs)
            self.assertNotIn('synthetic_keychain_read', infra.events)
            self.assertIn('tunnel_closed', infra.events)
            self.assertEqual(infra.metadata.data['items'], [{'key': 'unrelated', 'value': 'preserved'}])
            retry = FakeInfra()
            retry_kwargs = self.args(retry)
            retry_kwargs['journal_dir'] = str(journal)
            with self.assertRaises(session.SessionError):
                session.transfer_via_iap(execute=True, **retry_kwargs)
            self.assertEqual(retry.events, [])

    def test_master_failure_removes_owned_access_before_return(self):
        infra = FakeInfra('master_failure')
        with self.assertRaises(session.SessionError):
            session.transfer_via_iap(execute=True, **self.args(infra))
        self.assertNotIn('synthetic_keychain_read', infra.events)
        self.assertIn('metadata_remove', infra.events)
        self.assertFalse(infra.identity_path.exists())

    def test_identity_cleanup_failure_blocks_keychain(self):
        infra = FakeInfra()
        with patch.object(session, '_remove_identity', side_effect=session.SessionError('synthetic')):
            with self.assertRaises(session.SessionError):
                session.transfer_via_iap(execute=True, **self.args(infra))
        self.assertNotIn('synthetic_keychain_read', infra.events)
        self.assertIn('metadata_remove', infra.events)

    def test_tunnel_cleanup_failure_is_not_success(self):
        infra = FakeInfra('tunnel_cleanup_failure')
        with self.assertRaises(session.TunnelCleanupError) as error:
            session.transfer_via_iap(execute=True, **self.args(infra))
        self.assertTrue(error.exception.tunnel_cleanup_uncertain)
        self.assertIn('synthetic_keychain_read', infra.events)
        self.assertIn('tunnel_closed', infra.events)

    def test_invalid_receiver_digest_precedes_infrastructure(self):
        infra = FakeInfra()
        kwargs = self.args(infra)
        kwargs['receiver_sha256'] = '0' * 64
        with self.assertRaises(session.SessionError):
            session.transfer_via_iap(execute=True, **kwargs)
        self.assertEqual(infra.events, [])

    def test_sigterm_unwinds_and_removes_owned_metadata_and_identity(self):
        infra = FakeInfra()

        def interrupt(**_kwargs):
            os.kill(os.getpid(), signal.SIGTERM)
            raise AssertionError('signal should interrupt')

        kwargs = self.args(infra)
        kwargs['_sender'] = interrupt
        with self.assertRaises(session.SessionError):
            session.transfer_via_iap(execute=True, **kwargs)
        self.assertIn('metadata_remove', infra.events)
        self.assertIn('tunnel_closed', infra.events)
        self.assertNotIn('synthetic_keychain_read', infra.events)
        self.assertFalse(infra.identity_path.exists())

    def test_non_main_thread_is_rejected_before_identity_or_metadata(self):
        infra = FakeInfra()
        failures = []

        def work():
            try:
                session.transfer_via_iap(execute=True, **self.args(infra))
            except session.SessionError:
                failures.append(True)

        thread = threading.Thread(target=work)
        thread.start()
        thread.join(timeout=3)
        self.assertEqual(failures, [True])
        self.assertEqual(infra.events, [])


class GceTransportTest(unittest.TestCase):
    def test_plain_get_and_post_return_parsed_json_without_clock_mode(self):
        transport = session.GceInstanceTransport(env={}, ledger=None, session_id='', entry='synthetic')

        class Response:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def read(self, _limit):
                return b'{"synthetic":true}'

        class Opener:
            def __init__(self):
                self.methods = []

            def open(self, request, timeout):
                self.methods.append(request.get_method())
                return Response()

        opener = Opener()
        token = subprocess.CompletedProcess([], 0, b'synthetic-access-token', b'')
        with patch.object(session.subprocess, 'run', return_value=token), \
                patch.object(session.urllib.request, 'build_opener', return_value=opener):
            self.assertEqual(transport._request('https://example.invalid'), {'synthetic': True})
            self.assertEqual(transport._request('https://example.invalid', method='POST', payload={'x': 1}),
                             {'synthetic': True})
        self.assertEqual(opener.methods, ['GET', 'POST'])

    def test_authenticated_server_clock_is_bounded_conservatively(self):
        header = email.utils.format_datetime(dt.datetime.fromtimestamp(1000, dt.timezone.utc), usegmt=True)
        session._verify_server_clock([header], wall_before=1000.2, wall_after=1001.2,
                                     monotonic_before=50, monotonic_after=51)
        cases = [
            ([], 1000.2, 1001.2, 50, 51),
            ([header, header], 1000.2, 1001.2, 50, 51),
            (['not-a-date'], 1000.2, 1001.2, 50, 51),
            ([header], 1030, 1031, 50, 51),
            ([header], 970, 971, 50, 51),
            ([header], 1000, 1011, 50, 61),
            ([header], 1000, 1003, 50, 51),
            ([header], 1000, 1001, 51, 50),
            ([header], float('nan'), 1001, 50, 51),
        ]
        for values in cases:
            with self.subTest(headers=values[0], wall_before=values[1]), self.assertRaises(session.SessionError):
                session._verify_server_clock(values[0], wall_before=values[1], wall_after=values[2],
                                             monotonic_before=values[3], monotonic_after=values[4])

    def test_unverified_clock_blocks_before_ledger_or_metadata_post(self):
        class Ledger:
            def begin_operation(self, *_args, **_kwargs):
                raise AssertionError('ledger must not be reached')

        transport = session.GceInstanceTransport(env={}, ledger=Ledger(), session_id='2' * 32, entry='synthetic')
        with patch.object(transport, 'verify_target', side_effect=session.SessionError('clock unavailable')):
            with self.assertRaises(session.SessionError):
                transport.compare_and_set({'fingerprint': 'synthetic'})

    @unittest.skipUnless(shutil.which('ssh-keygen'), 'ssh-keygen unavailable')
    def test_local_synthetic_identity_is_private_and_deleted_by_inode(self):
        with tempfile.TemporaryDirectory(prefix='asb-iap-identity-test-') as directory:
            path, identity, public = session.GceInfrastructure().identity(directory)
            self.assertTrue(public.startswith('ssh-ed25519 '))
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            session._remove_identity(path, identity)
            self.assertFalse(path.exists())

    def test_symlinked_public_key_is_rejected_without_following_it(self):
        with tempfile.TemporaryDirectory(prefix='asb-iap-identity-test-') as directory:
            def fake_keygen(args, **_kwargs):
                path = Path(args[-1])
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
                path.with_suffix('.pub').symlink_to('/synthetic/missing')
                return subprocess.CompletedProcess(args, 0, b'', b'')

            with patch.object(session.subprocess, 'run', side_effect=fake_keygen):
                with self.assertRaises(session.SessionError):
                    session.GceInfrastructure().identity(directory)

    def test_request_rejects_compression_and_oversize_before_json_parsing(self):
        transport = session.GceInstanceTransport(env={}, ledger=None, session_id='', entry='synthetic')

        class Response:
            def __init__(self, encoding, payload):
                self.headers = {'content-encoding': encoding}
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def read(self, _limit):
                return self.payload

        class Opener:
            def __init__(self, response):
                self.response = response

            def open(self, request, timeout):
                self.assert_identity = request.get_header('Accept-encoding') == 'identity'
                return self.response

        token = subprocess.CompletedProcess([], 0, b'synthetic-access-token', b'')
        for response in (Response('gzip', b'{}'), Response('', b'x' * (1024 * 1024 + 1))):
            with self.subTest(encoding=response.headers['content-encoding']):
                with patch.object(session.subprocess, 'run', return_value=token), \
                        patch.object(session.urllib.request, 'build_opener', return_value=Opener(response)):
                    with self.assertRaises(session.SessionError):
                        transport._request('https://example.invalid')

    def test_metadata_request_journal_is_written_before_post_and_completed(self):
        events = []

        class Journal:
            def begin_operation(self, _session_id, _entry, **_kwargs):
                events.append('intent')
                return '1' * 32, '12345678-1234-4123-8123-123456789abc'

            def record_operation(self, _identifier, _session_id, _name):
                events.append('operation')

            def finish_operation(self, _identifier, _session_id, _outcome):
                events.append('done')

        transport = session.GceInstanceTransport(env={}, ledger=Journal(), session_id='2' * 32, entry='synthetic')

        def request(url, *, method='GET', payload=None, require_clock=False):
            if require_clock:
                events.append('clock_and_target')
                return {'id': session.INSTANCE_ID, 'name': session.INSTANCE, 'status': 'RUNNING'}
            events.append('post' if method == 'POST' else 'poll')
            return {'name': 'operation-1'} if method == 'POST' else {'name': 'operation-1', 'status': 'DONE'}

        with patch.object(transport, '_request', side_effect=request):
            transport.compare_and_set({'fingerprint': 'synthetic'})
        self.assertEqual(events, ['clock_and_target', 'intent', 'post', 'operation', 'poll', 'done'])

    def test_fingerprint_conflict_is_distinct_from_uncertain_submit(self):
        class Journal:
            def begin_operation(self, _session_id, _entry, **_kwargs):
                return '1' * 32, '12345678-1234-4123-8123-123456789abc'

            def finish_operation(self, _identifier, _session_id, _outcome):
                pass

        transport = session.GceInstanceTransport(env={}, ledger=Journal(), session_id='2' * 32, entry='synthetic')
        conflict = urllib.error.HTTPError('https://example.invalid', 412, 'precondition', {}, io.BytesIO())
        def fail_after_clock(_url, *, method='GET', payload=None, require_clock=False):
            if require_clock:
                return {'id': session.INSTANCE_ID, 'name': session.INSTANCE, 'status': 'RUNNING'}
            raise conflict
        try:
            with patch.object(transport, '_request', side_effect=fail_after_clock), self.assertRaises(Conflict):
                transport.compare_and_set({'fingerprint': 'synthetic'})
        finally:
            conflict.close()
        def timeout_after_clock(_url, *, method='GET', payload=None, require_clock=False):
            if require_clock:
                return {'id': session.INSTANCE_ID, 'name': session.INSTANCE, 'status': 'RUNNING'}
            raise TimeoutError()
        with patch.object(transport, '_request', side_effect=timeout_after_clock), self.assertRaises(UncertainUpdate):
            transport.compare_and_set({'fingerprint': 'synthetic'})


if __name__ == '__main__':
    unittest.main()
