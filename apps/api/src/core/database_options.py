"""Driver-compatible TLS options shared by API, Celery and Alembic.

Configuration errors never include the database URL or its credentials.
"""

import ssl

from sqlalchemy.engine import make_url

SSL_MODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}


def database_options(
    raw_url: str, *, asynchronous: bool, ssl_mode: str = "", ssl_root_cert: str = ""
) -> tuple[str, dict]:
    # Supabase also displays the libpq postgres:// spelling.
    if raw_url.startswith("postgres://"):
        raw_url = "postgresql://" + raw_url[len("postgres://"):]
    try:
        url = make_url(raw_url)
    except Exception:
        raise ValueError("DATABASE_URL is not a valid SQLAlchemy connection URL") from None
    backend = url.get_backend_name()
    if backend == "sqlite":
        driver = "sqlite+aiosqlite" if asynchronous else "sqlite"
        return url.set(drivername=driver).render_as_string(hide_password=False), {}
    if backend != "postgresql":
        raise ValueError("DATABASE_URL must use PostgreSQL or SQLite")
    if (url.host or "").endswith((".supabase.com", ".supabase.co")) and url.port == 6543:
        raise ValueError("Use the Supabase direct or session endpoint on port 5432; transaction pooling is unsupported")

    query = dict(url.query)
    for name in ("sslmode", "sslrootcert", "channel_binding"):
        if name in query and not isinstance(query[name], str):
            raise ValueError(f"Duplicate database {name} settings are not supported")
    for name, explicit in (("sslmode", ssl_mode), ("sslrootcert", ssl_root_cert)):
        if explicit and name in query and query[name] != explicit:
            raise ValueError(f"Conflicting database {name} settings")
        if explicit:
            query[name] = explicit
    mode = query.get("sslmode", "")
    if mode and mode not in SSL_MODES:
        raise ValueError("DATABASE_SSL_MODE is not supported")
    root_cert = query.get("sslrootcert", "")
    if root_cert and mode not in {"verify-ca", "verify-full"}:
        raise ValueError("DATABASE_SSL_ROOT_CERT requires verify-ca or verify-full")

    # Explicit opt-in for providers whose connection policy requires SCRAM
    # channel binding. psycopg3 uses libpq for both sync and async engines;
    # asyncpg cannot enforce channel_binding=require. Never silently discard it.
    if url.drivername == "postgresql+psycopg":
        if mode != "verify-full" or query.get("channel_binding") != "require":
            raise ValueError("psycopg requires verify-full and channel_binding=require")
        if not root_cert:
            query["sslrootcert"] = "system"
        elif root_cert != "system":
            try:
                ssl.create_default_context(cafile=root_cert)
            except (OSError, ssl.SSLError):
                raise ValueError("Database CA certificate cannot be loaded") from None
        return url.set(drivername="postgresql+psycopg", query=query).render_as_string(hide_password=False), {}

    if asynchronous and "channel_binding" in query:
        raise ValueError("asyncpg does not support channel_binding; use verified psycopg")
    connect_args = {}
    if asynchronous:
        # SQLAlchemy forwards query keys as asyncpg kwargs, but asyncpg only
        # accepts sslmode/sslrootcert inside a DSN, not as keyword arguments.
        query.pop("sslmode", None)
        query.pop("sslrootcert", None)
        if mode in {"verify-ca", "verify-full"}:
            try:
                context = ssl.create_default_context(cafile=root_cert or None)
            except (OSError, ssl.SSLError):
                raise ValueError("Database CA certificate cannot be loaded") from None
            context.check_hostname = mode == "verify-full"
            connect_args["ssl"] = context
        elif mode:
            connect_args["ssl"] = mode
    driver = "postgresql+asyncpg" if asynchronous else "postgresql"
    return url.set(drivername=driver, query=query).render_as_string(hide_password=False), connect_args
