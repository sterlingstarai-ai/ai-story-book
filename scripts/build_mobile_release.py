"""Validate public-only mobile release configuration; build only with --execute.

Never load backend .env or include server/provider keys. Android builds the signed
AAB with the existing private upload key; iOS compiles without signing or upload.
Neither command publishes, registers an app, or changes store/account settings.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit

from final_external_preflight import present, public_https_endpoint

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {'PROD_API_URL', 'PRIVACY_POLICY_URL', 'TERMS_OF_SERVICE_URL'}
OPTIONAL = {'KAKAO_NATIVE_APP_KEY'}


def release_configuration(values):
    if not isinstance(values, dict) or not REQUIRED <= values.keys() or values.keys() - REQUIRED - OPTIONAL:
        raise ValueError('Only the documented public mobile build fields are accepted; never pass a backend env file.')
    for key in REQUIRED:
        value = values[key]
        if not isinstance(value, str) or 'replace-me' in value or not present(value) or not public_https_endpoint(value):
            raise ValueError(f'{key} requires a non-placeholder public HTTPS URL.')
        host = urlsplit(value).hostname or ''
        if host.endswith(('.invalid', '.test', '.example')) or host in {'example.com', 'example.net', 'example.org'}:
            raise ValueError(f'{key} cannot use a documentation or test hostname.')
        if urlsplit(value).fragment:
            raise ValueError(f'{key} cannot contain a fragment.')
    api = urlsplit(values['PROD_API_URL'])
    if api.path not in {'', '/'} or api.query:
        raise ValueError('PROD_API_URL must be an origin without a path or query.')
    if 'KAKAO_NATIVE_APP_KEY' in values and (not isinstance(values['KAKAO_NATIVE_APP_KEY'], str)
                                          or not values['KAKAO_NATIVE_APP_KEY'].isalnum()):
        raise ValueError('KAKAO_NATIVE_APP_KEY must be a nonempty public native application key.')
    return {key: values[key] for key in sorted(values)}


def build_command(platform, values):
    options = ['appbundle', '--release'] if platform == 'android' else ['ios', '--release', '--no-codesign']
    return ['flutter', 'build', *options, *(f'--dart-define={key}={value}' for key, value in values.items())]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True, help='JSON containing public mobile defines only')
    parser.add_argument('--platform', choices=['android', 'ios'], required=True)
    parser.add_argument('--execute', action='store_true', help='Build locally after configuration validation')
    args = parser.parse_args(argv)
    try:
        values = release_configuration(json.loads(args.config.read_text()))
        if not shutil.which('flutter'):
            raise ValueError('Flutter is unavailable on PATH.')
        if args.platform == 'android' and not (ROOT / 'apps/mobile/android/key.properties').is_file():
            raise ValueError('Existing private Android upload signing configuration is required.')
        command = build_command(args.platform, values)
        if not args.execute:
            print(json.dumps({'status': 'BUILD_CONFIGURED_NOT_EXECUTED', 'platform': args.platform,
                              'public_define_names': sorted(values), 'remote_calls': 0,
                              'requires': ['public document content/ownership verification', 'production E2E', 'store signing/review']}))
            return 0
        wrapper = ['bash', '-c', 'set -euo pipefail; source "$1"; setup_mobile_toolchain; shift; exec "$@"',
                   'storybook-mobile-release', str(ROOT / 'scripts/mobile-toolchain.sh')]
        result = subprocess.run(wrapper + command, cwd=ROOT / 'apps/mobile', check=False)
        if result.returncode:
            raise ValueError('Mobile build failed; inspect compiler output. No artifact was submitted.')
        artifact = ROOT / 'apps/mobile/build/app/outputs/bundle/release/app-release.aab'
        evidence = {'status': 'LOCAL_BUILD_NOT_SUBMITTED', 'platform': args.platform,
                    'ios_signing_verified': False, 'store_submission': False, 'production_e2e_verified': False}
        if args.platform == 'android' and artifact.is_file():
            evidence['artifact_sha256'] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        print(json.dumps(evidence))
        return 0
    except (OSError, ValueError) as error:
        # JSON decode errors can echo supplied input; never report those details.
        message = str(error) if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError) else 'Public build configuration could not be read.'
        print(json.dumps({'status': 'BLOCKED', 'message': message}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
