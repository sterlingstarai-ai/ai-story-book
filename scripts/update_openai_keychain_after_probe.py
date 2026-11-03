#!/usr/bin/env python3
"""Validate one pasted OpenAI key before replacing the existing keychain item.

The default is a no-network dry run. --execute requires a terminal, takes one
hidden input, and uses no secret-bearing command arguments, environment values,
logs, or files. It performs one free model retrieval. Only when that request
returns 403, it performs at most one small paid fictional Responses request.
Neither check proves image access, available credits for later work, or production
readiness. The keychain item is updated only after an affirmative response.
"""

from __future__ import annotations

import argparse
import ctypes
import getpass
import json
import logging
import re
import sys
import warnings

import httpx

ACCOUNT = 'ai-story-book'
SERVICE = 'ai-story-book-openai-production-2026-11-03'
MODEL = 'gpt-5.6-sol'
MODEL_URL = f'https://api.openai.com/v1/models/{MODEL}'
RESPONSE_URL = 'https://api.openai.com/v1/responses'
BODY_LIMIT = 128 * 1024


class KeychainFailure(RuntimeError):
    pass


class ProbeFailure(RuntimeError):
    pass


def read_response(client, method, url, *, key, payload=None):
    """Return a bounded response; never propagate a body or request in errors."""
    body = bytearray()
    try:
        with client.stream(method, url, headers={'Authorization': 'Bearer ' + key},
                           json=payload) as response:
            status = response.status_code
            # No failure body is consumed or logged, including error messages
            # that may include portions of credentials.
            if status != 200:
                return status, None
            if response.headers.get('content-encoding', '').strip().lower() not in ('', 'identity'):
                raise ProbeFailure('Invalid response encoding')
            chunks = ([response.content] if response.is_stream_consumed else response.iter_raw(chunk_size=65536))
            for chunk in chunks:
                body.extend(chunk)
                if len(body) > BODY_LIMIT:
                    raise ProbeFailure('Response exceeds size limit')
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise ProbeFailure('Invalid response')
        return status, parsed
    except ProbeFailure:
        raise
    except Exception:
        raise ProbeFailure('Provider request failed') from None


def valid_paid_response(body):
    if not isinstance(body, dict) or body.get('status') != 'completed' or body.get('incomplete_details') is not None:
        return False
    items = body.get('output')
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, dict) or item.get('type') != 'message' or item.get('role') != 'assistant':
            continue
        if item.get('status') != 'completed' or not isinstance(item.get('content'), list):
            continue
        if any(isinstance(c, dict) and c.get('type') == 'output_text'
               and isinstance(c.get('text'), str) and bool(c['text'].strip()) for c in item['content']):
            return True
    return False


def verify_key(client, key):
    if not isinstance(key, str) or not re.fullmatch(r'sk-[A-Za-z0-9_-]{16,512}', key):
        return {'status': 'INVALID_KEY_FORMAT', 'paid_requests': 0}
    status, body = read_response(client, 'GET', MODEL_URL, key=key)
    if status == 200 and body.get('id') == MODEL and body.get('object') == 'model':
        return {'status': 'VERIFIED', 'method': 'model_retrieval', 'paid_requests': 0}
    if status != 403:
        return {'status': 'AUTH_NOT_VERIFIED', 'http_status': status, 'paid_requests': 0}
    payload = {'model': MODEL, 'input': 'Return the word OK.', 'max_output_tokens': 128,
               'reasoning': {'effort': 'low'}, 'store': False}
    try:
        fallback_status, fallback_body = read_response(client, 'POST', RESPONSE_URL, key=key, payload=payload)
    except ProbeFailure:
        # The provider may have processed the one request before a timeout.
        return {'status': 'AUTH_NOT_VERIFIED', 'reason': 'paid_result_unavailable', 'paid_requests': 1}
    if fallback_status == 200 and valid_paid_response(fallback_body):
        return {'status': 'VERIFIED', 'method': 'small_paid_text', 'paid_requests': 1}
    return {'status': 'AUTH_NOT_VERIFIED', 'http_status': fallback_status, 'paid_requests': 1}


class MacKeychain:
    """Update exactly one existing default-keychain item via Security.framework."""

    def __init__(self):
        if sys.platform != 'darwin':
            raise KeychainFailure('macOS required')
        try:
            self.cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
            self.sec = ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
            p = ctypes.c_void_p
            self.cf.CFStringCreateWithCString.argtypes = [p, ctypes.c_char_p, ctypes.c_uint32]
            self.cf.CFStringCreateWithCString.restype = p
            self.cf.CFDataCreate.argtypes = [p, p, ctypes.c_long]
            self.cf.CFDataCreate.restype = p
            self.cf.CFArrayCreate.argtypes = [p, ctypes.POINTER(p), ctypes.c_long, p]
            self.cf.CFArrayCreate.restype = p
            self.cf.CFDictionaryCreateMutable.argtypes = [p, ctypes.c_long, p, p]
            self.cf.CFDictionaryCreateMutable.restype = p
            self.cf.CFDictionarySetValue.argtypes = [p, p, p]
            self.cf.CFRelease.argtypes = [p]
            self.cf.CFGetTypeID.argtypes = [p]
            self.cf.CFGetTypeID.restype = ctypes.c_ulong
            self.cf.CFDataGetTypeID.restype = ctypes.c_ulong
            self.sec.SecKeychainCopyDefault.argtypes = [ctypes.POINTER(p)]
            self.sec.SecKeychainCopyDefault.restype = ctypes.c_int32
            self.sec.SecItemCopyMatching.argtypes = [p, ctypes.POINTER(p)]
            self.sec.SecItemCopyMatching.restype = ctypes.c_int32
            self.sec.SecItemUpdate.argtypes = [p, p]
            self.sec.SecItemUpdate.restype = ctypes.c_int32
        except Exception:
            raise KeychainFailure('Security framework unavailable') from None

    def _constant(self, name):
        return ctypes.c_void_p.in_dll(self.sec, name).value

    def _boolean_true(self):
        return ctypes.c_void_p.in_dll(self.cf, 'kCFBooleanTrue').value

    def update_existing(self, key):
        """Retain/release native objects; do not create, delete, or change ACLs."""
        owned = []
        p = ctypes.c_void_p

        def take(value):
            if not value:
                raise KeychainFailure('Keychain operation unavailable')
            owned.append(value)
            return value

        def string(value):
            return take(self.cf.CFStringCreateWithCString(None, value.encode('utf-8'), 0x08000100))

        def array(value):
            ptrs = (p * 1)(value)
            return take(self.cf.CFArrayCreate(None, ptrs, 1, None))

        def dictionary(pairs):
            result = take(self.cf.CFDictionaryCreateMutable(None, 0, None, None))
            for name, value in pairs:
                self.cf.CFDictionarySetValue(result, self._constant(name), value)
            return result

        try:
            keychain = p()
            if self.sec.SecKeychainCopyDefault(ctypes.byref(keychain)) != 0:
                raise KeychainFailure('Default keychain unavailable')
            keychain_ref = take(keychain.value)
            account, service = string(ACCOUNT), string(SERVICE)
            query = dictionary([
                ('kSecClass', self._constant('kSecClassGenericPassword')),
                ('kSecAttrAccount', account), ('kSecAttrService', service),
                ('kSecMatchSearchList', array(keychain_ref)),
                ('kSecMatchLimit', self._constant('kSecMatchLimitOne')),
                ('kSecReturnPersistentRef', self._boolean_true()),
            ])
            item = p()
            if self.sec.SecItemCopyMatching(query, ctypes.byref(item)) != 0 or not item.value:
                raise KeychainFailure('Existing keychain item unavailable')
            item_ref = take(item.value)
            if self.cf.CFGetTypeID(item_ref) != self.cf.CFDataGetTypeID():
                raise KeychainFailure('Unexpected keychain item reference')
            # MatchItemList constrains SecItemUpdate to this persistent ref;
            # do not update every similar item in the keychain search list.
            update_query = dictionary([
                ('kSecClass', self._constant('kSecClassGenericPassword')),
                ('kSecMatchItemList', array(item_ref)),
            ])
            raw = key.encode('ascii')
            buffer = ctypes.create_string_buffer(raw, len(raw))
            data = take(self.cf.CFDataCreate(None, ctypes.cast(buffer, p), len(raw)))
            update = dictionary([('kSecValueData', data)])
            if self.sec.SecItemUpdate(update_query, update) != 0:
                raise KeychainFailure('Keychain update not confirmed')
        except KeychainFailure:
            raise
        except Exception:
            raise KeychainFailure('Keychain update not confirmed') from None
        finally:
            for value in reversed(owned):
                self.cf.CFRelease(value)


def execute(key, client, store_factory=MacKeychain):
    """Only invoke the keychain after an affirmative, independently bounded probe."""
    try:
        result = verify_key(client, key)
        if result['status'] != 'VERIFIED':
            return {**result, 'keychain_updated': False}
        store_factory().update_existing(key)
        return {**result, 'keychain_updated': True, 'production_changed': False}
    except ProbeFailure:
        return {'status': 'PROBE_FAILED', 'keychain_updated': False}
    except KeychainFailure:
        # A native interruption/error cannot prove the final persistent state.
        return {'status': 'KEYCHAIN_UPDATE_UNCONFIRMED', 'keychain_updated': None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({'status': 'DRY_RUN', 'keychain_updated': False}))
        return 0
    if not sys.stdin.isatty():
        print(json.dumps({'status': 'INTERACTIVE_TERMINAL_REQUIRED', 'keychain_updated': False}))
        return 1
    logging.disable(logging.CRITICAL)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            key = getpass.getpass('새 OpenAI API 키 (입력 내용은 표시되지 않습니다): ')
        with httpx.Client(trust_env=False, follow_redirects=False,
                          headers={'Accept-Encoding': 'identity'},
                          timeout=httpx.Timeout(45, connect=15)) as client:
            result = execute(key, client)
        print(json.dumps(result))
        return 0 if result.get('keychain_updated') is True else 1
    except (Exception, KeyboardInterrupt):
        print(json.dumps({'status': 'UNCONFIRMED', 'keychain_updated': None}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
