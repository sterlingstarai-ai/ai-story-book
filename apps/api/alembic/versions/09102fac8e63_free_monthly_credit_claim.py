"""One free allowance claim per account and Korea calendar month."""
from alembic import op
import sqlalchemy as sa
revision = "09102fac8e63"
down_revision = 'e6f7a8b9c0d1'
branch_labels = None
depends_on = None

def upgrade():
    op.create_index("uq_credit_transactions_free_monthly", "credit_transactions",
                    ["user_key", "reference_id"], unique=True,
                    sqlite_where=sa.text("transaction_type = 'free_monthly'"),
                    postgresql_where=sa.text("transaction_type = 'free_monthly'"))

def downgrade():
    op.drop_index("uq_credit_transactions_free_monthly", table_name="credit_transactions")
