"""Render-only launcher; keep its dynamic private Redis URL in DBs 0/1/2.

No secrets are printed or placed in process arguments. The original server or
worker replaces this process so SIGTERM is delivered to it directly.
"""

import os
from pathlib import Path
import sys
from urllib.parse import urlsplit, urlunsplit


COMMANDS = {
    'api': ['uvicorn', 'src.main:app', '--host', '0.0.0.0', '--port', '8000', '--no-access-log'],
    'worker': ['celery', '-A', 'src.worker', 'worker', '--loglevel=info', '--concurrency=2'],
    'migrate': ['alembic', 'upgrade', 'head'],
}


def redis_databases(base_url: str) -> dict[str, str]:
    try:
        parsed = urlsplit(base_url)
        parsed.port
        if (parsed.scheme not in {'redis', 'rediss'} or not parsed.hostname
                or parsed.path not in {'', '/', '/0'} or parsed.query or parsed.fragment):
            raise ValueError
    except ValueError:
        raise ValueError('Render REDIS_URL must be a private Key Value connection string') from None
    return {name: urlunsplit(parsed._replace(path=f'/{index}'))
            for index, name in enumerate(['REDIS_URL', 'CELERY_BROKER_URL', 'CELERY_RESULT_BACKEND'])}


def launch_environment(config, inherited: dict[str, str]) -> dict[str, str]:
    from src.core.database_options import database_options
    if config.database_ssl_mode != 'verify-full':
        raise ValueError('Render database connections require verify-full')
    if config.database_ssl_root_cert != '/etc/secrets/supabase-ca.crt':
        raise ValueError('Render requires the configured database CA Secret File')
    if not Path(config.database_ssl_root_cert).is_file():
        raise ValueError('Render database CA Secret File is missing')
    if config.s3_addressing_style != 'path' or config.s3_auto_create_bucket:
        raise ValueError('Render requires a pre-created private S3 bucket with path addressing')
    if (config.debug or config.testing or config.enable_test_hooks
            or not config.require_parental_consent_enabled or not config.use_celery):
        raise ValueError('Render requires production API/Celery settings')
    # Validate TLS/CA with the same runtime adapter before any process starts.
    database_options(config.database_url, asynchronous=True,
                     ssl_mode=config.database_ssl_mode, ssl_root_cert=config.database_ssl_root_cert)
    return {**inherited, **redis_databases(config.redis_url)}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in COMMANDS:
        print('usage: python -m src.ops.render_entrypoint api|worker|migrate', file=sys.stderr)
        return 2
    from src.core.config import settings
    try:
        environment = launch_environment(settings, dict(os.environ))
    except (ValueError, OSError):
        print('Render startup blocked: verify production safety and parental consent, database CA/TLS, private S3 and Redis/Celery settings.', file=sys.stderr)
        return 1
    command = COMMANDS[args[0]]
    os.execvpe(command[0], command, environment)
    return 0  # Only reached by an inert test replacement for exec.


if __name__ == '__main__':
    raise SystemExit(main())
