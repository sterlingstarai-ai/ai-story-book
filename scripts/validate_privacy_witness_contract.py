"""Check witness configuration forwarding without reading credentials."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = tuple('PRIVACY_JOURNAL_WITNESS_S3_' + suffix for suffix in
              ('ENDPOINT', 'BUCKET', 'REGION', 'ACCESS_KEY', 'SECRET_KEY'))


def validate():
    errors = []
    tree = ast.parse((ROOT / 'apps/api/src/core/config.py').read_text())
    defaults = {node.target.id.upper(): ast.literal_eval(node.value) for node in ast.walk(tree)
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                and node.target.id.upper() in NAMES}
    schema = json.loads((ROOT / 'env.schema.json').read_text())['properties']
    for name in NAMES:
        if defaults.get(name) != '' or schema.get(name, {}).get('default') != '':
            errors.append(f'{name}: runtime/schema default must be empty')
        for file in ('apps/api/.env.example', 'infra/.env.example', 'infra/.env.external.example'):
            if (ROOT / file).read_text().splitlines().count(name + '=') != 1:
                errors.append(f'{file}: {name} example missing or duplicated')
        for file in ('infra/docker-compose.yml', 'infra/docker-compose.prod.yml'):
            if (ROOT / file).read_text().count('${' + name + ':-}') != 2:
                errors.append(f'{file}: {name} must be forwarded to API and worker')
        external = (ROOT / 'infra/docker-compose.external.yml').read_text()
        if external.count('${' + name + ':-}') != 1 or 'environment: *id001' not in external:
            errors.append(f'external compose: {name} shared forwarding missing')
        render = (ROOT / 'infra/render.yaml.template').read_text()
        if render.count(f'key: {name}\n') != 2 or f'envVarKey: {name}\n' not in render:
            errors.append(f'render: {name} API/worker forwarding missing')
    return errors


if __name__ == '__main__':
    errors = validate()
    print('\n'.join(errors) if errors else 'Privacy witness configuration contracts aligned.')
    raise SystemExit(bool(errors))
