"""Bounded candidate-only live-provider probe; no execution entry point yet.

Designed to be sent to a pinned candidate via `docker exec -i ... python -`.
The surrounding cutover adapter must first prove candidate identity, isolate
new ingress, and handle an indeterminate timed-out daemon exec without retrying.
This module by itself cannot authorize or perform a production cutover.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import io
import json
import uuid


@contextmanager
def _provider_request_budget():
    """Enforce a single request for each pinned model, including retries."""
    import httpx
    original = httpx.AsyncClient.send
    counts = {'text': 0, 'image': 0}

    async def bounded(client, request, *args, **kwargs):
        endpoint = str(request.url)
        if request.method != 'POST':
            raise RuntimeError('Unexpected provider request')
        if endpoint == 'https://api.openai.com/v1/responses':
            kind, model = 'text', 'gpt-5.6-sol'
        elif endpoint == 'https://api.openai.com/v1/images/generations':
            kind, model = 'image', 'gpt-image-2'
        else:
            raise RuntimeError('Unexpected provider endpoint')
        body = json.loads(request.content)
        if (not isinstance(body, dict) or body.get('model') != model or counts[kind]
                or (kind == 'image' and (type(body.get('n')) is not int or body['n'] != 1))
                or (kind == 'text' and (type(body.get('max_output_tokens')) is not int
                                         or not 1 <= body['max_output_tokens'] <= 4160))):
            raise RuntimeError('Provider request budget exceeded')
        counts[kind] += 1
        return await original(client, request, *args, **kwargs)

    httpx.AsyncClient.send = bounded
    try:
        yield counts
    finally:
        httpx.AsyncClient.send = original


async def probe_inside():
    from PIL import Image
    from src.core.config import settings
    from src.models.dto import ImagePrompt
    from src.services.image import generate_image, image_storage_scope
    from src.services.llm import call_llm
    from src.services.provider_runtime import provider_runtime_status
    from src.services.storage import _delete_prefix_keys, get_object_bytes, get_s3_client, key_from_public_url

    # Fixed provider/model selection bounds this probe's possible cost. It must
    # not silently succeed against a mock or another more expensive model.
    if (settings.llm_provider != 'openai' or settings.llm_model != 'gpt-5.6-sol'
            or settings.image_provider != 'openai' or settings.image_model != 'gpt-image-2'):
        return False
    prefix = f'provider-cutover-check/{uuid.uuid4().hex}/'
    image_attempted = False
    success = False
    cleanup_ok = True
    try:
        with _provider_request_budget() as counts:
            text = await call_llm('Return a JSON object only.', 'Return exactly {"ok": true}.', max_tokens=64)
            parsed = json.loads(text)
            if counts['text'] != 1 or type(parsed) is not dict or parsed != {'ok': True}:
                return False
            prompt = ImagePrompt(page=0, positive_prompt='A single yellow paper star on a plain blue background.',
                                 negative_prompt='letters, words, text, people', seed=1, aspect_ratio='1:1')
            image_attempted = True
            with image_storage_scope(prefix):
                url = await generate_image(prompt)
            if counts['image'] != 1:
                return False
        key = key_from_public_url(url)
        if not isinstance(key, str) or not key.startswith(prefix):
            return False
        data, mime = await get_object_bytes(key)
        if (not isinstance(data, bytes) or not 1 <= len(data) <= 25_000_000
                or mime not in {'image/png', 'image/jpeg', 'image/webp'}):
            return False
        with Image.open(io.BytesIO(data)) as picture:
            if picture.format not in {'PNG', 'JPEG', 'WEBP'} or not all(1 <= n <= 8192 for n in picture.size):
                return False
            picture.verify()
        state = await provider_runtime_status(include_photo=False)
        success = isinstance(state, dict) and state.get('status') == 'healthy'
    except Exception:
        success = False
    finally:
        if image_attempted:
            try:
                cleanup_ok = await _delete_prefix_keys(prefix) == []
                if cleanup_ok:
                    client = get_s3_client()
                    listing = await asyncio.to_thread(client.list_objects_v2, Bucket=settings.s3_bucket,
                                                      Prefix=prefix, MaxKeys=1)
                    cleanup_ok = (isinstance(listing, dict) and listing.get('Contents', []) == []
                                  and listing.get('IsTruncated') is False)
            except Exception:
                cleanup_ok = False
    return success and cleanup_ok


async def _entry():
    try:
        return await probe_inside()
    except Exception:
        return False


if __name__ == '__main__':
    # Existing application logs may contain provider details. Send them to a
    # private in-memory sink and emit exactly one non-sensitive status line.
    import contextlib
    import sys
    if sys.argv != ['-', '--inside-pinned-candidate']:
        raise SystemExit('This probe is callable only by the candidate adapter')
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        ok = asyncio.run(_entry())
    sys.stdout.write('PROVIDER_PROBE_OK\n' if ok else 'PROVIDER_PROBE_FAILED\n')
    raise SystemExit(0 if ok else 1)
