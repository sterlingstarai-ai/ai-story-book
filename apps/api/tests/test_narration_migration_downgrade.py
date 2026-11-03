"""Protect generated narration from destructive downgrade."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_narration_downgrade_preserves_nonempty_table(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/9c1e3a7f620d_narration_variants.py'
    spec = importlib.util.spec_from_file_location('narration_variants_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE narration_variants (id TEXT PRIMARY KEY, page_id INTEGER NOT NULL)'))
        connection.execute(sa.text('CREATE INDEX ix_narration_variants_page_id ON narration_variants (page_id)'))
        connection.execute(sa.text("INSERT INTO narration_variants (id, page_id) VALUES ('synthetic', 1)"))
        monkeypatch.setattr(migration, 'op', Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match='Cannot downgrade while narration variants exist'):
            migration.downgrade()
        assert connection.execute(sa.text('SELECT count(*) FROM narration_variants')).scalar_one() == 1
        connection.execute(sa.text('DELETE FROM narration_variants'))
        migration.downgrade()
        assert not sa.inspect(connection).has_table('narration_variants')
    engine.dispose()
