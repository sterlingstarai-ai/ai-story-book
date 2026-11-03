"""All provider and keychain interactions are fakes; no actual secrets are used."""
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('keychain_probe', ROOT / 'scripts/update_openai_keychain_after_probe.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
KEY = 'sk-' + 'z' * 32


class Response:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self.body = json.dumps(body).encode() if body is not None else b''
        self.headers = headers or {}
        self.is_stream_consumed = False

    def iter_raw(self, **_):
        yield self.body


class Client:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    @contextmanager
    def stream(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        yield self.responses.pop(0)


class Store:
    def __init__(self):
        self.updates = []

    def update_existing(self, key):
        self.updates.append(key)


def completed():
    return {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
            'status': 'completed', 'content': [{'type': 'output_text', 'text': 'OK'}]}]}


class ProbeTests(unittest.TestCase):
    def test_free_probe_success_updates_exactly_once(self):
        client = Client(Response(200, {'id': module.MODEL, 'object': 'model'}))
        store = Store()
        result = module.execute(KEY, client, lambda: store)
        self.assertEqual(result['method'], 'model_retrieval')
        self.assertEqual(result['paid_requests'], 0)
        self.assertEqual(store.updates, [KEY])
        self.assertEqual([x[0] for x in client.requests], ['GET'])
        self.assertNotIn(KEY, json.dumps(result))

    def test_401_and_unexpected_body_never_update(self):
        for response in (Response(401), Response(200, {'id': 'other', 'object': 'model'})):
            with self.subTest(status=response.status_code):
                store = Store()
                client = Client(response)
                self.assertFalse(module.execute(KEY, client, lambda: store)['keychain_updated'])
                self.assertEqual(store.updates, [])
                self.assertEqual(len(client.requests), 1)

    def test_only_403_triggers_one_bounded_paid_text_fallback(self):
        client = Client(Response(403), Response(200, completed()))
        store = Store()
        result = module.execute(KEY, client, lambda: store)
        self.assertTrue(result['keychain_updated'])
        self.assertEqual(result['paid_requests'], 1)
        self.assertEqual([r[0] for r in client.requests], ['GET', 'POST'])
        payload = client.requests[1][2]['json']
        self.assertEqual(payload['max_output_tokens'], 128)
        self.assertIs(payload['store'], False)
        self.assertEqual(store.updates, [KEY])

    def test_failed_incomplete_and_compressed_fallback_never_update(self):
        for second in (Response(401), Response(200, {'status': 'incomplete'}),
                       Response(200, completed(), {'content-encoding': 'gzip'})):
            store = Store()
            result = module.execute(KEY, Client(Response(403), second), lambda: store)
            self.assertFalse(result['keychain_updated'])
            self.assertEqual(store.updates, [])
            if second.headers:
                self.assertEqual(result['paid_requests'], 1)

    def test_invalid_input_and_untrusted_errors_never_update(self):
        store = Store()
        self.assertEqual(module.execute('invalid', Client(), lambda: store)['status'], 'INVALID_KEY_FORMAT')
        self.assertEqual(store.updates, [])
        client = Client(Response(200, {'id': module.MODEL, 'object': 'model'}))
        def fail_store():
            raise module.KeychainFailure(KEY)
        result = module.execute(KEY, client, fail_store)
        self.assertIsNone(result['keychain_updated'])
        self.assertNotIn(KEY, json.dumps(result))

    def test_dry_run_has_no_keychain_or_network_side_effect(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/update_openai_keychain_after_probe.py')],
                                capture_output=True, text=True, timeout=10, check=True)
        self.assertEqual(json.loads(result.stdout)['status'], 'DRY_RUN')


class FakeCF:
    def __init__(self):
        self.next = 200
        self.objects = {}
        self.released = []

    def _new(self, value):
        self.next += 1
        self.objects[self.next] = value
        return self.next

    def CFStringCreateWithCString(self, _, value, __):
        return self._new(value.decode())

    def CFDataCreate(self, _, value, length):
        import ctypes
        return self._new(ctypes.string_at(value, length))

    def CFArrayCreate(self, _, values, length, __):
        return self._new([values[i] for i in range(length)])

    def CFDictionaryCreateMutable(self, *_):
        return self._new({})

    def CFDictionarySetValue(self, dictionary, key, value):
        self.objects[dictionary][key] = value

    def CFGetTypeID(self, _):
        return 9

    def CFDataGetTypeID(self):
        return 9

    def CFRelease(self, value):
        self.released.append(value)


class FakeSec:
    def __init__(self, cf):
        self.cf = cf
        self.update_calls = []
        self.match_status = 0
        self.update_status = 0

    def SecKeychainCopyDefault(self, pointer):
        pointer._obj.value = 100
        return 0

    def SecItemCopyMatching(self, query, pointer):
        self.search = self.cf.objects[query].copy()
        pointer._obj.value = 101
        return self.match_status

    def SecItemUpdate(self, query, update):
        self.update_calls.append((self.cf.objects[query].copy(), self.cf.objects[update].copy()))
        return self.update_status


class FakeMacKeychain(module.MacKeychain):
    names = ('kSecClass', 'kSecClassGenericPassword', 'kSecAttrAccount', 'kSecAttrService',
             'kSecMatchSearchList', 'kSecMatchLimit', 'kSecMatchLimitOne', 'kSecReturnPersistentRef',
             'kSecMatchItemList', 'kSecValueData')
    constants = {name: i + 500 for i, name in enumerate(names)}

    def __init__(self):
        self.cf = FakeCF()
        self.sec = FakeSec(self.cf)

    def _constant(self, name):
        return self.constants[name]

    def _boolean_true(self):
        return 900


class NativeBindingTests(unittest.TestCase):
    def test_native_query_targets_default_keychain_and_single_persistent_ref(self):
        store = FakeMacKeychain()
        store.update_existing(KEY)
        names, objects = store.constants, store.cf.objects
        query = store.sec.search
        self.assertEqual(objects[query[names['kSecAttrAccount']]], module.ACCOUNT)
        self.assertEqual(objects[query[names['kSecAttrService']]], module.SERVICE)
        self.assertEqual(objects[query[names['kSecMatchSearchList']]], [100])
        update_query, update = store.sec.update_calls[0]
        self.assertEqual(objects[update_query[names['kSecMatchItemList']]], [101])
        self.assertEqual(objects[update[names['kSecValueData']]], KEY.encode())
        self.assertEqual(len(update), 1)
        self.assertIn(100, store.cf.released)
        self.assertIn(101, store.cf.released)

    def test_missing_item_never_invokes_update(self):
        store = FakeMacKeychain()
        store.sec.match_status = -1
        with self.assertRaises(module.KeychainFailure):
            store.update_existing(KEY)
        self.assertEqual(store.sec.update_calls, [])


if __name__ == '__main__':
    unittest.main()
