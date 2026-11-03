"""Check a new key against the pilot models without touching production.

The default is a no-network dry run. An explicit --allow-billable-requests
prompts once in an interactive terminal using hidden input, then submits one
generic text request and (only after text succeeds) one generic image request.
The key, response bodies and image bytes are never written or printed. This
does not configure an application, touch Redis, or establish live readiness.
"""
import argparse
import base64
import binascii
import getpass
import io
import json
import logging
import re
import sys
import warnings

import httpx
from PIL import Image

TEXT_URL = 'https://api.openai.com/v1/responses'
IMAGE_URL = 'https://api.openai.com/v1/images/generations'
TEXT_MODEL = 'gpt-5.6-sol'
IMAGE_MODEL = 'gpt-image-2'
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class ProbeFailure(RuntimeError):
    pass


def _post_json(client, url, key, payload):
    data = bytearray()
    try:
        with client.stream('POST', url, headers={'Authorization': 'Bearer ' + key}, json=payload) as response:
            if response.status_code != 200:
                return None, response.status_code
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > MAX_JSON_BYTES:
                    raise ProbeFailure('response too large')
        parsed = json.loads(data)
        if not isinstance(parsed, dict) or parsed.get('error'):
            raise ProbeFailure('invalid response')
        return parsed, 200
    except ProbeFailure:
        raise
    except Exception:
        raise ProbeFailure('provider request failed') from None


def _check_text(data):
    if data.get('status') != 'completed' or data.get('incomplete_details') is not None:
        raise ProbeFailure('text response incomplete')
    output = data.get('output')
    if not isinstance(output, list):
        raise ProbeFailure('text response invalid')
    texts = []
    for item in output:
        if not isinstance(item, dict):
            raise ProbeFailure('text response invalid')
        if item.get('type') == 'reasoning':
            continue
        if item.get('type') != 'message' or item.get('role') != 'assistant' or item.get('status') != 'completed':
            raise ProbeFailure('text response invalid')
        blocks = item.get('content')
        if not isinstance(blocks, list):
            raise ProbeFailure('text response invalid')
        for block in blocks:
            if not isinstance(block, dict) or block.get('type') != 'output_text' or not isinstance(block.get('text'), str):
                raise ProbeFailure('text response invalid')
            texts.append(block['text'])
    try:
        parsed = json.loads(''.join(texts))
        if not isinstance(parsed, dict) or set(parsed) != {'ok'} or parsed['ok'] is not True:
            raise ValueError('unexpected synthetic result')
    except Exception:
        raise ProbeFailure('text response invalid') from None


def _check_image(data):
    entries = data.get('data')
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        raise ProbeFailure('image response invalid')
    encoded = entries[0].get('b64_json')
    if not isinstance(encoded, str) or not encoded or len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
        raise ProbeFailure('image response invalid')
    try:
        image = base64.b64decode(encoded, validate=True)
        if not 0 < len(image) <= MAX_IMAGE_BYTES:
            raise ValueError('invalid image size')
        with Image.open(io.BytesIO(image)) as picture:
            if picture.format not in {'PNG', 'JPEG', 'WEBP'} or picture.width * picture.height > 16_777_216:
                raise ValueError('invalid image format')
            picture.verify()
    except (ValueError, binascii.Error, OSError, Image.DecompressionBombError):
        raise ProbeFailure('image response invalid') from None


def probe(client, key):
    if not isinstance(key, str) or not re.fullmatch(r'sk-[A-Za-z0-9_-]{16,512}', key):
        raise ProbeFailure('key format invalid')
    text, status = _post_json(client, TEXT_URL, key, {
        'model': TEXT_MODEL,
        'input': [{'role': 'user', 'content': 'Return only the JSON object {"ok":true}.'}],
        'max_output_tokens': 4128, 'reasoning': {'effort': 'low'},
        'text': {'format': {'type': 'json_object'}}, 'store': False,
    })
    if status != 200:
        return {'status': 'TEXT_FAILED', 'http_status': status, 'production_changed': False}
    _check_text(text)
    image, status = _post_json(client, IMAGE_URL, key, {
        'model': IMAGE_MODEL, 'prompt': 'A single blue circle on plain white paper, flat illustration.',
        'n': 1, 'size': '1024x1024', 'quality': 'medium',
    })
    if status != 200:
        return {'status': 'IMAGE_FAILED', 'http_status': status, 'production_changed': False}
    _check_image(image)
    return {'status': 'BOTH_MODELS_VERIFIED_IN_ISOLATION', 'production_changed': False,
            'production_readiness_verified': False, 'credential_freshness_verified': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-billable-requests', action='store_true')
    args = parser.parse_args(argv)
    if not args.allow_billable_requests:
        print(json.dumps({'status': 'DRY_RUN', 'production_changed': False}))
        return 0
    if not sys.stdin.isatty():
        print(json.dumps({'status': 'INTERACTIVE_TERMINAL_REQUIRED', 'production_changed': False}))
        return 1
    logging.disable(logging.CRITICAL)
    try:
        # getpass can otherwise fall back to visible terminal input. Refuse
        # before reading if the platform cannot disable echo.
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            key = getpass.getpass('새 OpenAI API 키 (입력 내용은 표시되지 않습니다): ')
        with httpx.Client(trust_env=False, follow_redirects=False,
                          timeout=httpx.Timeout(120, connect=15)) as client:
            result = probe(client, key)
        print(json.dumps(result))
        return 0 if result['status'] == 'BOTH_MODELS_VERIFIED_IN_ISOLATION' else 1
    except (Exception, KeyboardInterrupt):
        print(json.dumps({'status': 'PROBE_FAILED', 'production_changed': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
