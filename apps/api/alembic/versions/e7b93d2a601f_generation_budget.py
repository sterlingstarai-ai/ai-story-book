"""Add opt-in durable global generation admission counts.

Revision ID: e7b93d2a601f
Revises: 4c2d8f71b906
"""
from alembic import op
import sqlalchemy as sa

revision = "e7b93d2a601f"
down_revision = "4c2d8f71b906"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "generation_budget_activation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("blocked_through_day", sa.String(8), nullable=False),
        sa.Column("current_day", sa.String(8), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_generation_budget_singleton"),
        sa.CheckConstraint("requests >= 0", name="ck_generation_budget_nonnegative"),
        sa.CheckConstraint("length(blocked_through_day) = 8 AND length(current_day) = 8", name="ck_generation_budget_days"),
        sa.CheckConstraint("current_day >= blocked_through_day", name="ck_generation_budget_day_order"),
    )


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT COUNT(*) FROM generation_budget_activation")).scalar():
        raise RuntimeError("Cannot discard durable generation budget history")
    op.drop_table("generation_budget_activation")
