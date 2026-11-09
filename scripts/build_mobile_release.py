"""Validate mobile release inputs; compile after verifying the public policy site.

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

from build_public_support_site import verify_published
from final_external_preflight import assess_bundled_policies, mobile_url_error
from render_legal_documents import render

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {'PROD_API_URL', 'PRIVACY_POLICY_URL', 'TERMS_OF_SERVICE_URL'}
OPTIONAL = {'KAKAO_NATIVE_APP_KEY'}


def release_configuration(values):
    if not isinstance(values, dict) or not REQUIRED <= values.keys() or values.keys() - REQUIRED - OPTIONAL:
        raise ValueError('Only the documented public mobile build fields are accepted; never pass a backend env file.')
    for key in REQUIRED:
        error = mobile_url_error(key, values[key])
        if error:
            raise ValueError(error)
    if 'KAKAO_NATIVE_APP_KEY' in values and (not isinstance(values['KAKAO_NATIVE_APP_KEY'], str)
                                          or not values['KAKAO_NATIVE_APP_KEY'].isalnum()):
        raise ValueError('KAKAO_NATIVE_APP_KEY must be a nonempty public native application key.')
    return {key: values[key] for key in sorted(values)}


def build_command(platform, values):
    options = ['appbundle', '--release'] if platform == 'android' else ['ios', '--release', '--no-codesign']
    return ['flutter', 'build', *options, *(f'--dart-define={key}={value}' for key, value in values.items())]


def bundled_policy_pages(values):
    pages = {}
    for slug, field in [('privacy', 'PRIVACY_POLICY_URL'), ('terms', 'TERMS_OF_SERVICE_URL')]:
        source = ROOT / f'apps/mobile/assets/legal/{slug}.ko.json'
        pages[slug] = (values[field], (render(json.loads(source.read_text())) + '\n').encode('utf-8'))
    return pages


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True, help='JSON containing public mobile defines only')
    parser.add_argument('--platform', choices=['android', 'ios'], required=True)
    parser.add_argument('--support-site-config', type=Path, help='Approved public support site JSON for --execute')
    parser.add_argument('--execute', action='store_true', help='Verify the published support site and build locally')
    args = parser.parse_args(argv)
    try:
        values = release_configuration(json.loads(args.config.read_text()))
        policies = assess_bundled_policies(ROOT)
        if args.execute and not policies['ready']:
            raise ValueError('Bundled privacy and terms documents must be complete, approved and already effective before building.')
        if args.execute and args.support_site_config is None:
            raise ValueError('Pass --support-site-config to verify the published policy site before building.')
        if not shutil.which('flutter'):
            raise ValueError('Flutter is unavailable on PATH.')
        if args.platform == 'android' and not (ROOT / 'apps/mobile/android/key.properties').is_file():
            raise ValueError('Existing private Android upload signing configuration is required.')
        command = build_command(args.platform, values)
        if not args.execute:
            print(json.dumps({'status': 'BUILD_CONFIGURED_NOT_EXECUTED', 'platform': args.platform,
                              'public_define_names': sorted(values), 'remote_calls': 0,
                              'bundled_policy_documents': policies,
                              'requires': ['published support site and bundled policy match', 'production E2E', 'store signing/review']}))
            return 0
        verified_files = verify_published(args.support_site_config, bundled_policies=bundled_policy_pages(values))
        wrapper = ['bash', '-c', 'set -euo pipefail; source "$1"; setup_mobile_toolchain; shift; exec "$@"',
                   'storybook-mobile-release', str(ROOT / 'scripts/mobile-toolchain.sh')]
        result = subprocess.run(wrapper + command, cwd=ROOT / 'apps/mobile', check=False)
        if result.returncode:
            raise ValueError('Mobile build failed; inspect compiler output. No artifact was submitted.')
        build_dir = ROOT / 'apps/mobile/build'
        if args.platform == 'android':
            artifact = build_dir / 'app/outputs/bundle/release/app-release.aab'
            hash_field = 'artifact_sha256'
        else:
            artifact = build_dir / 'ios/iphoneos/Runner.app/Runner'
            hash_field = 'ios_executable_sha256'
        if not artifact.is_file() or artifact.stat().st_size == 0:
            raise ValueError('Flutter completed without the expected mobile release artifact.')
        with artifact.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        evidence = {'status': 'LOCAL_BUILD_NOT_SUBMITTED', 'platform': args.platform,
                    'ios_signing_verified': False, 'store_submission': False, 'production_e2e_verified': False,
                              'published_support_files_verified': verified_files,
                    hash_field: digest}
        print(json.dumps(evidence))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        # JSON decode errors can echo supplied input; never report those details.
        message = str(error) if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError) else 'Public build configuration could not be read.'
        print(json.dumps({'status': 'BLOCKED', 'message': message}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
