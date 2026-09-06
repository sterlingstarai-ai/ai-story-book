"""Prepare, but never deploy, the paid Render API/worker/Key Value Blueprint.

The explicit release manifest must identify the successful CI run and matching
immutable images. This offline tool validates supplied evidence shapes; it does
not authenticate the CI result, registry access, account plan, or secret files.
"""

import argparse
import json
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'sterlingstarai-ai/ai-story-book'
MANIFEST_KEYS = {'commit_sha', 'api_image', 'worker_image', 'ci_status', 'ci_run_url'}


def validate_release(release):
    if not isinstance(release, dict) or set(release) != MANIFEST_KEYS:
        raise ValueError('Release manifest must contain only the documented evidence fields')
    sha = release['commit_sha']
    if not isinstance(sha, str) or not re.fullmatch('[a-f0-9]{40}', sha) or len(set(sha)) == 1:
        raise ValueError('A complete verified commit SHA is required')
    if release['ci_status'] != 'success':
        raise ValueError('Successful CI evidence is required before preparing a deployable Blueprint')
    if not re.fullmatch(rf'https://github\.com/{re.escape(REPOSITORY)}/actions/runs/[1-9][0-9]*', release['ci_run_url']):
        raise ValueError('CI evidence must identify this repository workflow run')
    for kind in ['api', 'worker']:
        expected = f'ghcr.io/{REPOSITORY}/{kind}'
        image = release[kind + '_image']
        if not isinstance(image, str) or not (image == f'{expected}:{sha}' or re.fullmatch(re.escape(expected) + r'@sha256:[a-f0-9]{64}', image)):
            raise ValueError(f'{kind} image must use the verified commit tag or an explicitly verified digest')


def prepare(release, *, registry_credential, prefix='ai-story-book-prod', region='singapore'):
    validate_release(release)
    if not re.fullmatch(r'[a-z][a-z0-9-]{2,40}', prefix):
        raise ValueError('Service prefix must be a new lowercase Render service name')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{2,63}', registry_credential) or any(
        marker in registry_credential.lower() for marker in ['change_me', 'placeholder', 'your-']
    ):
        raise ValueError('Provide the name of the registry credential configured in Render')
    if region not in {'oregon', 'ohio', 'virginia', 'frankfurt', 'singapore'}:
        raise ValueError('Choose a supported Render region')
    text = (ROOT / 'infra/render.yaml.template').read_text()
    for token, value in {'__API_IMAGE__': release['api_image'], '__WORKER_IMAGE__': release['worker_image'],
                         '__REGISTRY_CREDENTIAL__': registry_credential, '__PREFIX__': prefix, '__REGION__': region}.items():
        text = text.replace(token, value)
    if re.search(r'__[A-Z_]+__|\$\{', text):
        raise ValueError('Unresolved template values remain')
    blueprint = yaml.safe_load(text)
    # This is a package for newly created services. Never infer account ownership
    # or overwrite an existing unrelated service from its name alone.
    for service in blueprint['services'][:2]:
        if service['runtime'] != 'image' or service['numInstances'] != 1 or 'scaling' in service:
            raise ValueError('Unexpected runtime/scaling template drift')
    return text.replace('# TEMPLATE ONLY: generate with scripts/prepare_render_blueprint.py after verified CI images exist.',
                        f"# Prepared from supplied CI evidence: {release['ci_run_url']}\n# Commit: {release['commit_sha']}; configuration-only validation, not deployed.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-manifest', type=Path, required=True)
    parser.add_argument('--registry-credential-name', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--service-prefix', default='ai-story-book-prod')
    parser.add_argument('--region', default='singapore')
    parser.add_argument('--schema-file', type=Path, help='Optional locally downloaded official Render JSON Schema')
    args = parser.parse_args(argv)
    try:
        text = prepare(json.loads(args.release_manifest.read_text()), registry_credential=args.registry_credential_name,
                       prefix=args.service_prefix, region=args.region)
        if args.schema_file:
            import jsonschema
            jsonschema.validate(yaml.safe_load(text), json.loads(args.schema_file.read_text()))
        # No overwrite, commit, push, CLI authentication, account write or deploy.
        with args.output.open('x') as stream:
            stream.write(text)
        print(json.dumps({'status': 'BLUEPRINT_PREPARED_NOT_DEPLOYED', 'configuration_only': True,
                          'render_base_monthly_usd': 42, 'supabase_base_monthly_usd': 25,
                          'initial_base_monthly_estimate_usd': 67, 'services': 3,
                          'requires_account_validation': True, 'ca_secret_files_required': 2}))
        return 0
    except Exception:
        # A supplied manifest can contain arbitrary content. Do not echo its values.
        print(json.dumps({'status': 'BLOCKED', 'message': 'Check release evidence, image SHA/digest, registry credential name, template/schema and a new output path.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
