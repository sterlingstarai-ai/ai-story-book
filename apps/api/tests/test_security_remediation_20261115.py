"""Credential privacy at real SQLAlchemy and stdlib logging boundaries."""
import io
import logging
import traceback

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from src.core import database
from src.core.logging import configure_logging

SECRET = "12345678-1234-4234-8234-123456789abc"


def test_sync_engine_hides_bound_credentials_and_preserves_queries():
    with database.engine.connect() as conn:
        assert conn.execute(text("select :credential"), {"credential": SECRET}).scalar() == SECRET
        with pytest.raises(DBAPIError) as error:
            conn.execute(text("select :credential from absent_security_fixture"), {"credential": SECRET})
    assert SECRET not in str(error.value)
    assert "parameters hidden" in str(error.value)


@pytest.mark.asyncio
async def test_async_engine_hides_credentials_in_exception_traceback():
    async with database.async_engine.connect() as conn:
        assert (await conn.execute(text("select :credential"), {"credential": SECRET})).scalar() == SECRET
        with pytest.raises(DBAPIError) as error:
            await conn.execute(text("select :credential from absent_security_fixture"), {"credential": SECRET})
    rendered = "".join(traceback.format_exception(error.value))
    assert SECRET not in rendered
    assert database._ASYNC_ENGINE_KWARGS["hide_parameters"] is True


@pytest.mark.parametrize("logger_name", ["uvicorn.error", "celery.app.trace", "sqlalchemy.engine.Engine"])
def test_stdlib_handlers_cannot_render_driver_detail_credentials(logger_name, monkeypatch, caplog):
    configure_logging()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger(logger_name)
    # Alembic's fileConfig disables existing loggers in earlier migration tests.
    monkeypatch.setattr(logger, "disabled", False)
    caplog.set_level(logging.ERROR, logger=logger_name)
    logger.addHandler(handler)
    try:
        try:
            # PostgreSQL driver DETAIL can contain a key even with hide_parameters.
            raise RuntimeError("constraint DETAIL: user_key=" + SECRET)
        except RuntimeError:
            logger.error("database operation failed for %s", SECRET, exc_info=True)
    finally:
        logger.removeHandler(handler)
    output = stream.getvalue()
    assert SECRET not in output
    assert "RuntimeError" in output
    assert "database operation failed" in output


def test_logging_configuration_is_idempotent_and_keeps_correlation():
    configure_logging()
    factory = logging.getLogRecordFactory()
    configure_logging()
    assert logging.getLogRecordFactory() is factory
    record = factory("src.operation", logging.INFO, __file__, 1,
                     '{"request_id": "' + SECRET + '", "event": "ready"}', (), None)
    assert SECRET in record.getMessage()
