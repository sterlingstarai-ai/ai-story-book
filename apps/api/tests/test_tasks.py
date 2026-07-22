"""
Celery task idempotency tests (M23).

Celery is configured with acks_late=True + reject_on_worker_lost=True, so a
worker that dies mid-task causes the message to be **redelivered** and the task
to re-run from scratch. The re-run must be idempotent:

- A job that already reached a terminal state (done/failed) must NOT be
  re-executed — otherwise re-inserts collide on the unique job_id constraints
  (story_drafts/image_prompts/books) and a recoverable redelivery is turned
  into a permanent failure.
- A duplicate-insert IntegrityError raised by a concurrent redelivery race must
  be absorbed (treated as already-claimed no-op), not marked as a hard UNKNOWN
  failure and re-raised (which Celery would redeliver again → failure loop).
"""

import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy.exc import IntegrityError


def _make_integrity_error() -> IntegrityError:
    """Simulate a job_id unique collision from a redelivered second execution."""
    return IntegrityError(
        "INSERT INTO story_drafts ...",
        {},
        Exception("UNIQUE constraint failed: story_drafts.job_id"),
    )


# ==================== Pure helper ====================


class TestRedeliveryNoopHelper:
    """is_redelivery_noop: pure decision — terminal states short-circuit re-run."""

    def test_terminal_statuses_are_noop(self):
        from src.services.tasks import is_redelivery_noop

        assert is_redelivery_noop("done") is True
        assert is_redelivery_noop("failed") is True

    def test_non_terminal_statuses_proceed(self):
        from src.services.tasks import is_redelivery_noop

        assert is_redelivery_noop("queued") is False
        assert is_redelivery_noop("running") is False
        assert is_redelivery_noop(None) is False
        assert is_redelivery_noop("") is False


# ==================== Task-level idempotency guard ====================


class TestGenerateBookTaskIdempotency:
    def test_skips_done_job(self, valid_book_spec):
        """A redelivered task for an already-done job is a clean no-op."""
        with patch(
            "src.services.tasks._get_job_status_async",
            new=AsyncMock(return_value="done"),
        ):
            with patch(
                "src.services.orchestrator.start_book_generation",
                new_callable=AsyncMock,
            ) as mock_start:
                result = _run_task("job-done", valid_book_spec)

        # No work performed on a terminal job.
        mock_start.assert_not_called()
        assert result["status"] == "skipped"

    def test_skips_failed_job(self, valid_book_spec):
        """A redelivered task for an already-failed job is a clean no-op."""
        with patch(
            "src.services.tasks._get_job_status_async",
            new=AsyncMock(return_value="failed"),
        ):
            with patch(
                "src.services.orchestrator.start_book_generation",
                new_callable=AsyncMock,
            ) as mock_start:
                result = _run_task("job-failed", valid_book_spec)

        mock_start.assert_not_called()
        assert result["status"] == "skipped"

    def test_runs_non_terminal_job(self, valid_book_spec):
        """A running/queued job still executes normally (no false skip)."""
        with patch(
            "src.services.tasks._get_job_status_async",
            new=AsyncMock(return_value="running"),
        ):
            with patch(
                "src.services.orchestrator.start_book_generation",
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_start:
                result = _run_task("job-running", valid_book_spec)

        mock_start.assert_called_once()
        assert result["status"] == "success"

    def test_absorbs_integrity_error_from_redelivery(self, valid_book_spec):
        """A duplicate-insert IntegrityError is absorbed as a no-op, not a failure."""
        with patch(
            "src.services.tasks._get_job_status_async",
            new=AsyncMock(return_value="running"),
        ):
            with patch(
                "src.services.orchestrator.start_book_generation",
                new=AsyncMock(side_effect=_make_integrity_error()),
            ):
                with patch(
                    "src.services.tasks._mark_job_failed_async",
                    new_callable=AsyncMock,
                ) as mock_fail:
                    # Must NOT re-raise (Celery would redeliver again otherwise).
                    result = _run_task("job-dup", valid_book_spec)

        # Not marked failed — the collision means another execution already
        # claimed/created the rows.
        mock_fail.assert_not_called()
        assert result["status"] == "skipped"

    def test_non_integrity_error_still_fails_loudly(self, valid_book_spec):
        """Genuine errors are still marked failed and re-raised (no silent swallow)."""
        with patch(
            "src.services.tasks._get_job_status_async",
            new=AsyncMock(return_value="running"),
        ):
            with patch(
                "src.services.orchestrator.start_book_generation",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ):
                with patch(
                    "src.services.tasks._mark_job_failed_async",
                    new_callable=AsyncMock,
                ) as mock_fail:
                    with pytest.raises(RuntimeError):
                        _run_task("job-boom", valid_book_spec)

        mock_fail.assert_called_once()


def _run_task(job_id: str, spec_dict: dict):
    """Invoke the bound Celery task synchronously in-process."""
    from src.services.tasks import generate_book_task

    return generate_book_task(job_id, spec_dict, "user-key-1")
