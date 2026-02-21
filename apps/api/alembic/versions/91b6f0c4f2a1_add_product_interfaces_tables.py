"""add_product_interfaces_tables

Revision ID: 91b6f0c4f2a1
Revises: 7f3d2c4b6a10
Create Date: 2026-02-20

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "91b6f0c4f2a1"
down_revision: Union[str, None] = "7f3d2c4b6a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "iap_receipts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_key", sa.String(length=80), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("product_id", sa.String(length=120), nullable=False),
        sa.Column("transaction_id", sa.String(length=200), nullable=False),
        sa.Column("purchase_token", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform",
            "transaction_id",
            name="uq_iap_receipts_platform_transaction_id",
        ),
    )
    op.create_index("ix_iap_receipts_user_key", "iap_receipts", ["user_key"], unique=False)

    op.create_table(
        "user_consents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_key", sa.String(length=80), nullable=False),
        sa.Column("consent_version", sa.String(length=20), nullable=False),
        sa.Column("privacy", sa.Boolean(), nullable=False),
        sa.Column("photos", sa.Boolean(), nullable=False),
        sa.Column("data_processing", sa.Boolean(), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_consents_user_key", "user_consents", ["user_key"], unique=False)

    op.create_table(
        "user_settings",
        sa.Column("user_key", sa.String(length=80), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("dark_mode", sa.Boolean(), nullable=False),
        sa.Column("bedtime_notification_enabled", sa.Boolean(), nullable=False),
        sa.Column("bedtime_notification_hour", sa.Integer(), nullable=True),
        sa.Column("bedtime_notification_minute", sa.Integer(), nullable=True),
        sa.Column("sleep_mode_default_minutes", sa.Integer(), nullable=False),
        sa.Column("allow_kakao_share", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("user_key"),
    )

    op.create_table(
        "child_profiles",
        sa.Column("id", sa.String(length=60), nullable=False),
        sa.Column("user_key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("age_band", sa.String(length=10), nullable=False),
        sa.Column("preferred_theme", sa.String(length=30), nullable=True),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_key", "name", name="uq_child_profiles_user_name"),
    )
    op.create_index("ix_child_profiles_user_key", "child_profiles", ["user_key"], unique=False)

    op.create_table(
        "screen_time_limits",
        sa.Column("user_key", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("daily_limit_minutes", sa.Integer(), nullable=False),
        sa.Column("used_minutes_today", sa.Integer(), nullable=False),
        sa.Column("usage_date", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("user_key"),
    )

    op.create_table(
        "ad_reward_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_key", sa.String(length=80), nullable=False),
        sa.Column("reward_type", sa.String(length=40), nullable=False),
        sa.Column("reward_amount", sa.Integer(), nullable=False),
        sa.Column("ad_network", sa.String(length=40), nullable=True),
        sa.Column("ad_unit_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ad_reward_logs_user_key_created",
        "ad_reward_logs",
        ["user_key", "created_at"],
        unique=False,
    )

    op.create_table(
        "pod_orders",
        sa.Column("id", sa.String(length=60), nullable=False),
        sa.Column("user_key", sa.String(length=80), nullable=False),
        sa.Column("book_id", sa.String(length=60), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Integer(), nullable=False),
        sa.Column("shipping_fee", sa.Integer(), nullable=False),
        sa.Column("total_price", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("shipping_address", sa.JSON(), nullable=False),
        sa.Column("provider_order_id", sa.String(length=120), nullable=True),
        sa.Column("tracking_number", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pod_orders_user_key", "pod_orders", ["user_key"], unique=False)

    op.create_table(
        "voice_profiles",
        sa.Column("id", sa.String(length=60), nullable=False),
        sa.Column("user_key", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=40), nullable=False),
        sa.Column("relationship", sa.String(length=30), nullable=True),
        sa.Column("sample_audio_url", sa.String(length=500), nullable=False),
        sa.Column("provider_voice_id", sa.String(length=120), nullable=True),
        sa.Column("consented", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_profiles_user_key", "voice_profiles", ["user_key"], unique=False)

    op.create_table(
        "branch_story_nodes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("book_id", sa.String(length=60), nullable=False),
        sa.Column("node_key", sa.String(length=80), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("book_id", "node_key", name="uq_branch_story_nodes_book_node"),
    )
    op.create_index("ix_branch_story_nodes_book_id", "branch_story_nodes", ["book_id"], unique=False)

    op.create_table(
        "branch_story_edges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("book_id", sa.String(length=60), nullable=False),
        sa.Column("from_node_key", sa.String(length=80), nullable=False),
        sa.Column("to_node_key", sa.String(length=80), nullable=False),
        sa.Column("option_text", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_branch_story_edges_book_id", "branch_story_edges", ["book_id"], unique=False)

    op.create_table(
        "pronunciation_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_key", sa.String(length=80), nullable=False),
        sa.Column("book_id", sa.String(length=60), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("expected_text", sa.Text(), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("audio_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pronunciation_logs_user_key_created",
        "pronunciation_logs",
        ["user_key", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_pronunciation_logs_user_key_created", table_name="pronunciation_logs")
    op.drop_table("pronunciation_logs")

    op.drop_index("ix_branch_story_edges_book_id", table_name="branch_story_edges")
    op.drop_table("branch_story_edges")

    op.drop_index("ix_branch_story_nodes_book_id", table_name="branch_story_nodes")
    op.drop_table("branch_story_nodes")

    op.drop_index("ix_voice_profiles_user_key", table_name="voice_profiles")
    op.drop_table("voice_profiles")

    op.drop_index("ix_pod_orders_user_key", table_name="pod_orders")
    op.drop_table("pod_orders")

    op.drop_index("ix_ad_reward_logs_user_key_created", table_name="ad_reward_logs")
    op.drop_table("ad_reward_logs")

    op.drop_table("screen_time_limits")

    op.drop_index("ix_child_profiles_user_key", table_name="child_profiles")
    op.drop_table("child_profiles")

    op.drop_table("user_settings")

    op.drop_index("ix_user_consents_user_key", table_name="user_consents")
    op.drop_table("user_consents")

    op.drop_index("ix_iap_receipts_user_key", table_name="iap_receipts")
    op.drop_table("iap_receipts")
