"""Run the bounded provider refresh against the pinned running pilot API."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from backup_service_guard import BackupServiceGuard, assert_no_narration_recovery
from provider_cutover_probe_runner import _source
from provider_probe_budget import ProbeFollowupUnavailable, claim


_CHECK = b"""
import asyncio, os
from contextlib import redirect_stdout, redirect_stderr
async def check():
    from src.core.config import settings
    from src.core.rate_limit import rate_limiter
    from src.services.provider_runtime import provider_runtime_status
    if settings.testing or settings.provider_observation_ttl_seconds != 86400 or (
        settings.llm_provider, settings.llm_model, settings.image_provider, settings.image_model
    ) != ('openai', 'gpt-5.6-sol', 'openai', 'gpt-image-2'):
        return 'UNSUPPORTED'
    import time
    audio = settings.audio_feature_enabled
    tts = settings.tts_provider if audio else None
    if audio and (tts not in {'google_gemini', 'openai_realtime'} or not settings.audio_narration_only_enabled):
        return 'UNSUPPORTED'
    try:
        state = await provider_runtime_status(include_photo=False, include_audio=audio)
    finally:
        await rate_limiter.close()
    # OpenAI uses static keys. Gemini uses refreshed workload tokens and may
    # recover without a configuration change, under the same bounded budget.
    static_key_kinds = {'llm', 'image', 'tts'} if tts == 'openai_realtime' else {'llm', 'image'}
    if any(item['kind'] in static_key_kinds and item.get('reason') == 'credentials_rejected'
           for item in state['observations']):
        return 'UNAVAILABLE'
    kinds = {item['kind'] for item in state['observations']}
    if kinds != ({'llm', 'image', 'tts'} if audio else {'llm', 'image'}):
        return 'UNSUPPORTED'
    unhealthy = {item['kind'] for item in state['observations'] if item['status'] != 'healthy'}
    now = time.time()
    if unhealthy == {'tts'}:
        # The 18-hour claim interval leaves an hour for the timer and delays.
        openai_has_runway = all(
            settings.provider_observation_ttl_seconds - (now - item['observed_at']) >= 19 * 3600
            for item in state['observations'] if item['kind'] != 'tts'
        )
        return 'REQUIRED_TTS' if openai_has_runway else 'REQUIRED_TTS_WITH_OPENAI'
    if unhealthy:
        return 'REQUIRED_ALL' if audio else 'REQUIRED'
    due = any(now - item['observed_at'] >= 20 * 3600 for item in state['observations'])
    # A shared claim covers one refresh window. Refresh the active providers
    # together so a later-expiring observation cannot outlive the next claim.
    return ('DUE_ALL' if audio else 'DUE') if due else ('FRESH_AUDIO' if audio else 'FRESH')
with open(os.devnull, 'w') as sink, redirect_stdout(sink), redirect_stderr(sink):
    result = asyncio.run(check())
print(result)
"""
_TTS_PROBE = """
import asyncio, os
from contextlib import redirect_stdout, redirect_stderr
async def run():
    from src.core.config import settings
    from src.core.rate_limit import rate_limiter
    from src.services.tts import tts_service
    from src.services.provider_runtime import provider_runtime_status
    if (not settings.audio_feature_enabled or not settings.audio_narration_only_enabled
            or settings.tts_provider not in {'google_gemini', 'openai_realtime'}):
        return False
    try:
        await tts_service.provider.synthesize('작은 별이 반짝였어요.', language='ko', style='natural')
        state = await provider_runtime_status(include_photo=False, include_audio=True)
        return any(item['kind'] == 'tts' and item['status'] == 'healthy' for item in state['observations'])
    finally:
        await rate_limiter.close()
with open(os.devnull, 'w') as sink, redirect_stdout(sink), redirect_stderr(sink):
    ok = asyncio.run(asyncio.wait_for(run(), 95))
print('TTS_VERIFIED' if ok else 'TTS_FAILED')
""".encode()
_DOCKER = ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock']
_ENV = {'PATH': '/usr/bin:/bin', 'HOME': '/root'}
_API = 'asb-pilot-api'
_TTS_REQUIRED = {b'REQUIRED_TTS\n', b'REQUIRED_TTS_WITH_OPENAI\n'}


def docker(*args, data=None, timeout=20):
    return subprocess.run(
        [*_DOCKER, *args], input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        check=True, timeout=timeout, env=_ENV,
    ).stdout


def refresh(image_id, ledger, state_dir, *, execute, refresh_now=False):
    guard = BackupServiceGuard(state_dir, None)
    fd = guard._locked()
    try:
        assert_no_narration_recovery()
        if os.path.lexists(state_dir / 'restart-required.json'):
            raise RuntimeError('backup recovery pending')
        item = json.loads(docker('inspect', '--format',
                                 '{"Id":{{json .Id}},"Image":{{json .Image}},'
                                 '"Name":{{json .Name}},"Running":{{json .State.Running}}}', _API))
        identifier = item['Id']
        if (
            item['Image'] != image_id or item['Name'] != '/' + _API
            or item['Running'] is not True
            or not re.fullmatch(r'[0-9a-f]{64}', identifier)
        ):
            raise RuntimeError('unexpected API identity')
        status = docker('exec', '-i', identifier, 'python', '-', data=_CHECK)
        if status in {b'FRESH\n', b'FRESH_AUDIO\n'}:
            if not refresh_now:
                return 'OBSERVATIONS_FRESH'
            status = b'DUE_ALL\n' if status == b'FRESH_AUDIO\n' else b'DUE\n'
        tts_only = status == b'REQUIRED_TTS\n' and not refresh_now
        required = status in {b'REQUIRED\n', b'REQUIRED_ALL\n'} or status in _TTS_REQUIRED
        if status not in {b'DUE\n', b'DUE_ALL\n'} and not required:
            raise RuntimeError('provider refresh is not eligible')
        source = None if tts_only else _source()
        if not execute:
            return 'OBSERVATIONS_DUE'
        try:
            claimed = claim(ledger, require_next_interval=True) if tts_only else claim(ledger)
        except ProbeFollowupUnavailable:
            source = _source()
            tts_only = False
            claimed = claim(ledger)
        if not claimed:
            return 'PROBE_REQUIRED_BUDGET_DEFERRED' if required else 'PROBE_BUDGET_DEFERRED'
        audio = status in {b'DUE_ALL\n', b'REQUIRED_ALL\n'} or status in _TTS_REQUIRED
        text_and_image_ok = tts_only
        try:
            if source is not None:
                text_and_image_ok = docker(
                    'exec', '-i', identifier, 'python', '-', '--inside-pinned-candidate',
                    data=source, timeout=300) == b'PROVIDER_PROBE_OK\n'
        finally:
            # Refresh narration independently even if the OpenAI probe fails.
            if audio and docker('exec', '-i', identifier, 'python', '-',
                                data=_TTS_PROBE, timeout=105) != b'TTS_VERIFIED\n':
                raise RuntimeError('narration refresh failed')
        if not text_and_image_ok:
            raise RuntimeError('text or image refresh failed')
        expected = b'FRESH_AUDIO\n' if audio else b'FRESH\n'
        if docker('exec', '-i', identifier, 'python', '-', data=_CHECK) != expected:
            raise RuntimeError('provider observations did not become fresh after refresh')
        return 'PROBE_VERIFIED'
    finally:
        os.close(fd)


def bootstrap_isolated_narration(identifier, image_id, ledger):
    """Observe TTS on an isolated candidate under the release's backup lock."""
    if not re.fullmatch(r'[0-9a-f]{64}', identifier):
        raise RuntimeError('candidate identity is invalid')
    item = json.loads(docker('inspect', '--format',
        '{"Id":{{json .Id}},"Image":{{json .Image}},"Name":{{json .Name}},'
        '"Running":{{json .State.Running}},"Restart":{{json .HostConfig.RestartPolicy.Name}}}', identifier))
    if item != {'Id': identifier, 'Image': image_id, 'Name': '/asb-narration-next-api',
                'Running': True, 'Restart': 'no'}:
        raise RuntimeError('candidate identity does not match')
    status = docker('exec', '-i', identifier, 'python', '-', data=_CHECK)
    if status in {b'FRESH_AUDIO\n', b'DUE_ALL\n'}:
        return
    if status not in _TTS_REQUIRED or not claim(ledger):
        raise RuntimeError('candidate narration probe is not eligible')
    if docker('exec', '-i', identifier, 'python', '-', data=_TTS_PROBE, timeout=105) != b'TTS_VERIFIED\n':
        raise RuntimeError('candidate narration probe failed')
    if docker('exec', '-i', identifier, 'python', '-', data=_CHECK) not in {b'FRESH_AUDIO\n', b'DUE_ALL\n'}:
        raise RuntimeError('candidate narration observation is not verified')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image-id', required=True)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--refresh-now', action='store_true',
                        help='manual verification within the same persistent request budget')
    args = parser.parse_args()
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', args.image_id):
        parser.error('expected a pinned image ID')
    if args.refresh_now and not args.execute:
        parser.error('--refresh-now requires --execute')
    try:
        result = refresh(args.image_id, args.ledger, args.state_dir, execute=args.execute,
                         refresh_now=args.refresh_now)
    except Exception:
        result = 'PROBE_FAILED'
    print(result)
    return 0 if result in {'OBSERVATIONS_FRESH', 'OBSERVATIONS_DUE', 'PROBE_VERIFIED', 'PROBE_BUDGET_DEFERRED'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
