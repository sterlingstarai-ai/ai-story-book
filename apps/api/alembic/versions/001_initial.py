"""Initial migration

Revision ID: 001
Revises:
Create Date: 2026-01-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Jobs table
    op.create_table(
        'jobs',
        sa.Column('id', sa.String(60), primary_key=True),
        sa.Column('status', sa.String(20), nullable=False, default='queued'),
        sa.Column('progress', sa.Integer(), default=0),
        sa.Column('current_step', sa.String(120), default='대기 중'),
        sa.Column('error_code', sa.String(60), nullable=True),
        sa.Column('error_message', sa.String(300), nullable=True),
        sa.Column('moderation_input', sa.JSON(), nullable=True),
        sa.Column('moderation_output', sa.JSON(), nullable=True),
        sa.Column('user_key', sa.String(80), nullable=False),
        sa.Column('idempotency_key', sa.String(80), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_jobs_user_key', 'jobs', ['user_key'])
    op.create_index('ix_jobs_idempotency_key', 'jobs', ['idempotency_key'])

    # Characters table
    op.create_table(
        'characters',
        sa.Column('id', sa.String(60), primary_key=True),
        sa.Column('name', sa.String(40), nullable=False),
        sa.Column('master_description', sa.Text(), nullable=False),
        sa.Column('appearance', sa.JSON(), nullable=False),
        sa.Column('clothing', sa.JSON(), nullable=False),
        sa.Column('personality_traits', sa.JSON(), nullable=False),
        sa.Column('visual_style_notes', sa.String(200), nullable=True),
        sa.Column('user_key', sa.String(80), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_characters_user_key', 'characters', ['user_key'])

    # Story drafts table
    op.create_table(
        'story_drafts',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('job_id', sa.String(60), sa.ForeignKey('jobs.id'), nullable=False, unique=True),
        sa.Column('draft', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # Image prompts table
    op.create_table(
        'image_prompts',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('job_id', sa.String(60), sa.ForeignKey('jobs.id'), nullable=False, unique=True),
        sa.Column('prompts', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # Books table
    op.create_table(
        'books',
        sa.Column('id', sa.String(60), primary_key=True),
        sa.Column('job_id', sa.String(60), sa.ForeignKey('jobs.id'), nullable=False, unique=True),
        sa.Column('title', sa.String(80), nullable=False),
        sa.Column('language', sa.String(10), nullable=False),
        sa.Column('target_age', sa.String(10), nullable=False),
        sa.Column('style', sa.String(30), nullable=False),
        sa.Column('theme', sa.String(20), nullable=True),
        sa.Column('character_id', sa.String(60), sa.ForeignKey('characters.id'), nullable=True),
        sa.Column('cover_image_url', sa.String(500), nullable=True),
        sa.Column('pdf_url', sa.String(500), nullable=True),
        sa.Column('audio_url', sa.String(500), nullable=True),
        sa.Column('user_key', sa.String(80), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_books_user_key', 'books', ['user_key'])

    # Pages table
    op.create_table(
        'pages',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('book_id', sa.String(60), sa.ForeignKey('books.id'), nullable=False),
        sa.Column('page_number', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('image_url', sa.String(500), nullable=True),
        sa.Column('image_prompt', sa.Text(), nullable=True),
        sa.Column('audio_url', sa.String(500), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # Rate limits table
    op.create_table(
        'rate_limits',
        sa.Column('user_key', sa.String(80), primary_key=True),
        sa.Column('request_count', sa.Integer(), default=0),
        sa.Column('window_start', sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('rate_limits')
    op.drop_table('pages')
    op.drop_table('books')
    op.drop_table('image_prompts')
    op.drop_table('story_drafts')
    op.drop_table('characters')
    op.drop_table('jobs')
