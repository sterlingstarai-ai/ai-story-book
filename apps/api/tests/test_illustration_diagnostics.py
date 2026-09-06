"""Quality failure diagnostics preserve enums/counts without private context."""

import json
from types import SimpleNamespace

import pytest

from src.core.errors import ErrorCode
from src.core.logging import redact_log_data
from src.services import illustration_diagnostics as diagnostics

PRIVATE = "private-child-name-provider-explanation-and-secret"


@pytest.fixture
def events(monkeypatch):
    captured = []

    def warning(event, **fields):
        captured.append(redact_log_data(None, "warning", {"event": event, **fields}))

    monkeypatch.setattr(diagnostics, "logger", SimpleNamespace(warning=warning))
    return captured


def test_valid_diagnostics_survive_shared_log_redaction(events):
    diagnostics.record_illustration_diagnostic(
        "review_findings", "findings", error_code=ErrorCode.IMAGE_QUALITY_FAILED,
        page_numbers=[12, 0], issue_counts={"readable_text": 2, "identity_swap": 1},
    )
    assert events == [{
        "event": "Illustration quality diagnostic", "quality_stage": "review_findings",
        "quality_reason": "findings", "quality_error_code": "IMAGE_QUALITY_FAILED",
        "quality_pages": [0, 12], "quality_issue_counts": {"readable_text": 2, "identity_swap": 1},
    }]


@pytest.mark.parametrize("value", [PRIVATE, {PRIVATE: PRIVATE}, [PRIVATE], ValueError(PRIVATE)])
def test_unknown_reason_error_and_unvalidated_findings_never_enter_logs(events, value):
    diagnostics.record_illustration_diagnostic(
        value, value, error_code=value, page_numbers=[value], issue_counts={PRIVATE: 1},
    )
    assert events == [{"event": "Illustration quality diagnostic",
                       "quality_stage": "unknown", "quality_reason": "unknown"}]
    assert PRIVATE not in json.dumps(events)


@pytest.mark.parametrize("pages,counts", [
    ([True], {"readable_text": True}), ([13], {"readable_text": 14}),
    ([0, 0], {"readable_text": -1}), (["0"], {"readable_text": "1"}),
])
def test_invalid_page_numbers_and_issue_counts_are_dropped(events, pages, counts):
    diagnostics.record_illustration_diagnostic("pipeline", "pipeline_exception",
                                              page_numbers=pages, issue_counts=counts)
    assert "quality_pages" not in events[0]
    assert "quality_issue_counts" not in events[0]
