"""Inspect a pilot's provider bindings without permitting a credential change.

Explicitly pinned image IDs are required. Docker environment values are read
only into memory and never returned, logged, or included in error messages.
Passing this inspection does not authorize deployment or prove credentials.
"""
import argparse
import hmac
import json
import re
import subprocess

_IMAGE = re.compile(r'^sha256:[0-9a-f]{64}$')
_FIELDS = {
    'LLM_PROVIDER', 'LLM_MODEL', 'LLM_API_KEY', 'IMAGE_PROVIDER', 'IMAGE_MODEL',
    'IMAGE_API_KEY', 'PHOTO_PROCESSING_ENABLED', 'PHOTO_ANALYSIS_PROVIDER',
    'PHOTO_ANALYSIS_MODEL', 'PHOTO_ANALYSIS_API_KEY', 'AUDIO_FEATURE_ENABLED',
    'TTS_PROVIDER', 'OPENAI_TTS_API_KEY', 'STT_PROVIDER', 'STT_API_KEY',
}
_REQUIRED = {'LLM_PROVIDER', 'LLM_MODEL', 'LLM_API_KEY', 'IMAGE_PROVIDER',
             'IMAGE_MODEL', 'IMAGE_API_KEY'}


class InspectionError(RuntimeError):
    pass


def _selected_environment(items):
    if not isinstance(items, list):
        raise InspectionError('Invalid runtime environment')
    result = {}
    for item in items:
        if not isinstance(item, str) or '=' not in item:
            raise InspectionError('Invalid runtime environment')
        name, value = item.split('=', 1)
        if name in _FIELDS:
            if name in result:
                raise InspectionError('Duplicate runtime setting')
            result[name] = value
    if any(not result.get(name) for name in _REQUIRED):
        raise InspectionError('Required provider settings are missing')
    for name in ('PHOTO_PROCESSING_ENABLED', 'AUDIO_FEATURE_ENABLED'):
        value = result.get(name, 'false').lower()
        if value not in ('true', 'false'):
            raise InspectionError('Invalid feature setting')
        result[name] = value
    return result


def _docker_inspect(name):
    if name not in ('asb-pilot-api', 'asb-pilot-worker'):
        raise InspectionError('Unexpected container')
    try:
        proc = subprocess.run(
            ['docker', 'inspect', '--format',
             '{{json .Name}}\n{{json .Image}}\n{{json .State.Running}}\n{{json .Config.Env}}', name], check=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15,
        )
        if len(proc.stdout) > 4 * 1024 * 1024:
            raise ValueError('oversized inspect output')
        lines = proc.stdout.splitlines()
        if len(lines) != 4:
            raise ValueError('invalid inspect output')
        container_name, image, running, environment = map(json.loads, lines)
        return {'Name': container_name, 'Image': image,
                'State': {'Running': running}, 'Config': {'Env': environment}}
    except Exception:
        raise InspectionError('Container inspection failed') from None


def inspect_bindings(api_image, worker_image, *, inspect=_docker_inspect):
    if not _IMAGE.fullmatch(api_image or '') or not _IMAGE.fullmatch(worker_image or ''):
        raise InspectionError('Explicit image IDs are required')
    environments = []
    for name, expected in (('asb-pilot-api', api_image), ('asb-pilot-worker', worker_image)):
        item = inspect(name)
        if (not isinstance(item, dict) or item.get('Image') != expected
                or item.get('Name') != '/' + name
                or item.get('State', {}).get('Running') is not True):
            raise InspectionError('Container image or running state differs')
        environments.append(_selected_environment(item.get('Config', {}).get('Env')))
    api, worker = environments
    if api.keys() != worker.keys() or any(
        not hmac.compare_digest(api[name].encode(), worker[name].encode()) for name in api
    ):
        raise InspectionError('Provider configuration differs between containers')
    photo_enabled = api['PHOTO_PROCESSING_ENABLED'] == 'true'
    photo_key = api.get('PHOTO_ANALYSIS_API_KEY', '')
    return {
        'status': 'PROVIDER_BINDINGS_INSPECTED',
        'api_worker_bindings_match': True,
        'llm_and_image_use_same_key': hmac.compare_digest(
            api['LLM_API_KEY'].encode(), api['IMAGE_API_KEY'].encode()),
        'photo_enabled': photo_enabled,
        'photo_key_configured': bool(photo_key) if photo_enabled else None,
        'photo_uses_llm_key': bool(photo_key and hmac.compare_digest(photo_key, api['LLM_API_KEY']))
            if photo_enabled and photo_key else None,
        'tts_enabled': api['AUDIO_FEATURE_ENABLED'] == 'true',
        'credential_validity_verified': False,
        'apply_authorized': False,
        'rollback_verified': False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inspect', action='store_true', help='Perform read-only Docker inspection')
    parser.add_argument('--api-image')
    parser.add_argument('--worker-image')
    args = parser.parse_args(argv)
    if not args.inspect:
        print(json.dumps({'status': 'DRY_RUN', 'apply_authorized': False}))
        return 0
    try:
        print(json.dumps(inspect_bindings(args.api_image, args.worker_image)))
        return 0
    except Exception:
        print(json.dumps({'status': 'INSPECTION_FAILED', 'apply_authorized': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
