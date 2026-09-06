"""
Celery task idempotency tests (M23).

Celery is configured with acks_late=True + reject_on_worker_lost=True, so a
worker that dies mid-task causes the message to be **redelivered** and the task
to re-run from scratch. The re-run must be idempotent:

- A job that already reached a terminal state (done/failed) must NOT be
  re-executed — otherwise re-inserts collide on the unique job_id constraints
  (story_drafts/image_prompts/books) and a recoverable redelivery is turned
  into a permanent failure.
- A queued job is claimed atomically before any provider call. Once claimed,
  an IntegrityError is a real database failure and must not become fake success.
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
    @pytest.fixture(autouse=True)
    def claim_queued_job(self, monkeypatch):
        monkeypatch.setattr("src.services.tasks._claim_job_async", AsyncMock(return_value=True))

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

    def test_runs_claimed_queued_job(self, valid_book_spec):
        """The delivery that wins the queued claim executes normally."""
        with patch(
            "src.services.tasks._get_job_status_async",
            new=AsyncMock(return_value="queued"),
        ):
            with patch(
                "src.services.orchestrator.start_book_generation",
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_start:
                result = _run_task("job-running", valid_book_spec)

        mock_start.assert_called_once()
        assert result["status"] == "success"

    def test_integrity_error_after_claim_is_reported(self, valid_book_spec):
        """A failed DB write after the unique claim cannot be reported as success."""
        with patch(
            "src.services.tasks._get_job_status_async",
            new=AsyncMock(return_value="queued"),
        ):
            with patch(
                "src.services.orchestrator.start_book_generation",
                new=AsyncMock(side_effect=_make_integrity_error()),
            ):
                with patch(
                    "src.services.tasks._mark_job_failed_async",
                    new_callable=AsyncMock,
                ) as mock_fail:
                    with pytest.raises(IntegrityError):
                        _run_task("job-dup", valid_book_spec)

        mock_fail.assert_called_once()

    def test_non_integrity_error_still_fails_loudly(self, valid_book_spec):
        """Genuine errors are still marked failed and re-raised (no silent swallow)."""
        with patch(
            "src.services.tasks._get_job_status_async",
            new=AsyncMock(return_value="queued"),
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
