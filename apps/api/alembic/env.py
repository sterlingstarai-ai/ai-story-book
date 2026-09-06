from logging.config import fileConfig
from sqlalchemy import create_engine
from sqlalchemy import pool

from alembic import context

import sys
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.database import Base
from src.core.config import settings
from src.core.database_options import database_options

# Import all models to register them with SQLAlchemy metadata for Alembic
from src.models.db import (  # noqa: F401
    AccountIdentity,
    Job,
    StoryDraftDB,
    ImagePromptsDB,
    Book,
    ContentReport,
    Page,
    Character,
    RateLimit,
    UserCredits,
    Subscription,
    CreditTransaction,
    DailyStreak,
    DailyStory,
    ReadingLog,
    IAPReceipt,
    UserConsent,
    UserSettings,
    ChildProfile,
    ScreenTimeLimit,
    AdRewardLog,
    PodOrder,
    VoiceProfile,
    BranchStoryNode,
    BranchStoryEdge,
    PronunciationLog,
)

config = context.config

# Keep percent-encoded credentials out of ConfigParser interpolation. Runtime
# and migrations use the same TLS policy, even with a separate direct endpoint.
database_url, database_connect_args = database_options(
    settings.database_migration_url or settings.database_url,
    asynchronous=False,
    ssl_mode=settings.database_ssl_mode,
    ssl_root_cert=settings.database_ssl_root_cert,
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = create_engine(
        database_url,
        connect_args=database_connect_args,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
