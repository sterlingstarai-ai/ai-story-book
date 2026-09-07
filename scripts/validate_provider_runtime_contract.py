"""Check provider observation/usage configuration forwarding without credentials."""
import ast
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('PROVIDER_OBSERVATION_TTL_SECONDS', 'PROVIDER_USAGE_PRICES_JSON')


def validate():
    defaults = {}
    tree = ast.parse((ROOT / 'apps/api/src/core/config.py').read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id.upper() in NAMES:
            value = node.value
            if isinstance(value, ast.Call):
                value = next(item.value for item in value.keywords if item.arg == 'default')
            defaults[node.target.id.upper()] = ast.literal_eval(value)
    errors = []
    schema = json.loads((ROOT / 'env.schema.json').read_text())['properties']
    for name in NAMES:
        expected = defaults[name]
        if schema.get(name, {}).get('default') != expected:
            errors.append(f'{name}: schema differs from runtime')
        for file in ['apps/api/.env.example', 'infra/.env.example']:
            match = re.search(rf'^{name}=(.+)$', (ROOT / file).read_text(), re.M)
            if not match or match[1].strip("'\"") != str(expected):
                errors.append(f'{file}: {name} example differs from runtime')
        for file in ['infra/docker-compose.yml', 'infra/docker-compose.prod.yml', 'infra/docker-compose.external.yml']:
            default = '' if name.endswith('_JSON') else str(expected)
            if '${' + name + ':-' + default + '}' not in (ROOT / file).read_text():
                errors.append(f'{file}: {name} forwarding missing')
        render = (ROOT / 'infra/render.yaml.template').read_text()
        if f'key: {name}' not in render or f'envVarKey: {name}' not in render:
            errors.append(f'render: {name} API/worker forwarding missing')
        if f"  {name}: '{expected}'" not in (ROOT / '.github/workflows/ci.yml').read_text():
            errors.append(f'CI: {name} fixture differs from runtime')
    return errors


if __name__ == '__main__':
    errors = validate()
    print('\n'.join(errors) if errors else 'Provider runtime configuration contracts aligned.')
    raise SystemExit(bool(errors))
