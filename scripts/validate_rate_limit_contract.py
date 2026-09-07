"""Keep deployed read/write rate defaults aligned; no app imports or credentials."""
import ast
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def validate() -> list[str]:
    names = ('RATE_LIMIT_REQUESTS', 'RATE_LIMIT_READ_REQUESTS', 'RATE_LIMIT_WINDOW')
    tree = ast.parse((ROOT / 'apps/api/src/core/config.py').read_text())
    defaults = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            key = node.target.id.upper()
            if key not in names:
                continue
            value = node.value
            if isinstance(value, ast.Call):
                value = next(item.value for item in value.keywords if item.arg == 'default')
            defaults[key] = ast.literal_eval(value)
    errors = []
    schema = json.loads((ROOT / 'env.schema.json').read_text())['properties']
    for name in names:
        expected = defaults[name]
        if not isinstance(expected, int) or expected < 1:
            errors.append(f'{name}: runtime default must be a positive integer')
        if schema.get(name, {}).get('default') != expected:
            errors.append(f'{name}: env schema default differs from runtime')
        for relative in ['apps/api/.env.example', 'infra/.env.example']:
            text = (ROOT / relative).read_text()
            match = re.search(rf'^{name}=(\d+)(?:\s|$)', text, re.M)
            if not match or int(match[1]) != expected:
                errors.append(f'{relative}: {name} default missing or different')
        for relative in ['infra/docker-compose.yml', 'infra/docker-compose.prod.yml', 'infra/docker-compose.external.yml']:
            if '${' + name + ':-' + str(expected) + '}' not in (ROOT / relative).read_text():
                errors.append(f'{relative}: {name} forwarding missing or different')
        render = (ROOT / 'infra/render.yaml.template').read_text()
        if not re.search(rf'key: {name}\s+value: [\'\"]?{expected}[\'\"]?\s', render):
            errors.append(f'render template: {name} default missing or different')
        ci = (ROOT / '.github/workflows/ci.yml').read_text()
        if not re.search(rf'^  {name}: [\'\"]?{expected}[\'\"]?$', ci, re.M):
            errors.append(f'CI: {name} fixture differs from deployed default')
    if defaults['RATE_LIMIT_READ_REQUESTS'] < 60:
        errors.append('Read bucket cannot sustain normal 2-second progress polling plus navigation')
    return errors


if __name__ == '__main__':
    errors = validate()
    print('\n'.join(errors) if errors else 'Rate-limit contracts aligned across runtime, CI, schema and deployment.')
    raise SystemExit(bool(errors))
