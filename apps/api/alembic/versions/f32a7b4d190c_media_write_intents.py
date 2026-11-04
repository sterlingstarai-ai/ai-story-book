"""Keep unresolved media writes visible to the backup fence."""

import sqlalchemy as sa
from alembic import op

revision = "f32a7b4d190c"
down_revision = "e7b93d2a601f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "media_write_intents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM media_write_intents)")).scalar():
        raise RuntimeError("Cannot discard unresolved media writes")
    op.drop_table("media_write_intents")
