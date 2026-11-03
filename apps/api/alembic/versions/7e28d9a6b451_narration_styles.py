"""Keep legacy recordings while separating narration style variants.

Revision ID: 7e28d9a6b451
Revises: 9c1e3a7f620d
"""
from alembic import op
import sqlalchemy as sa

revision = '7e28d9a6b451'
down_revision = '9c1e3a7f620d'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('narration_variants') as batch:
        batch.add_column(sa.Column('style', sa.String(16), nullable=False, server_default='legacy'))
        batch.add_column(sa.Column('provider', sa.String(24), nullable=False, server_default='openai'))
        batch.drop_constraint('uq_narration_variant', type_='unique')
        batch.drop_constraint('ck_narration_variant_voice', type_='check')
        batch.create_unique_constraint('uq_narration_variant', ['page_id', 'language', 'voice', 'style', 'provider'])
        batch.create_check_constraint('ck_narration_variant_voice', "voice IN ('default','warm','deep')")
        batch.create_check_constraint('ck_narration_variant_style', "style IN ('legacy','natural','animated','bedtime')")


def downgrade():
    # Do not discard newly created recordings during an automatic rollback.
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT COUNT(*) FROM narration_variants WHERE style != 'legacy' OR voice = 'default' OR provider != 'openai'")).scalar():
        raise RuntimeError('Cannot downgrade while style recordings exist')
    with op.batch_alter_table('narration_variants') as batch:
        batch.drop_constraint('ck_narration_variant_style', type_='check')
        batch.drop_constraint('ck_narration_variant_voice', type_='check')
        batch.drop_constraint('uq_narration_variant', type_='unique')
        batch.create_unique_constraint('uq_narration_variant', ['page_id', 'language', 'voice'])
        batch.create_check_constraint('ck_narration_variant_voice', "voice IN ('warm','deep')")
        batch.drop_column('provider')
        batch.drop_column('style')
