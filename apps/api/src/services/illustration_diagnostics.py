"""Allowlisted quality decisions, never provider prose or private image context."""

import structlog

from src.core.errors import ErrorCode

logger = structlog.get_logger()

_STAGES = {"provider_response", "review_schema", "review_findings", "avatar_findings", "pipeline"}
_REASONS = {
    "provider_refusal", "provider_response_invalid", "provider_timeout", "provider_error",
    "schema_invalid", "response_size_invalid", "page_coverage_invalid", "findings",
    "quality_disabled", "deadline_exhausted", "correction_invalid", "asset_invalid",
    "unknown_issue", "repair_limit_exceeded", "blocking_issue", "repair_scope_invalid",
    "repair_deadline_insufficient", "recheck_failed", "pipeline_exception",
}
_ISSUES = {
    "printed_instructions", "readable_text", "duplicate_character", "identity_swap",
    "action_mismatch", "unsafe_depiction", "uncertain",
    "multiple_characters", "malformed_character", "photographic_rendering",
}


def record_illustration_diagnostic(
    stage, reason, *, error_code=None, page_numbers=None, issue_counts=None,
):
    """Only pass findings after model validation; independently bound every field."""
    fields = {
        "quality_stage": stage if type(stage) is str and stage in _STAGES else "unknown",
        "quality_reason": reason if type(reason) is str and reason in _REASONS else "unknown",
    }
    if isinstance(error_code, ErrorCode):
        fields["quality_error_code"] = error_code.value
    if (type(page_numbers) is list and len(page_numbers) <= 13
            and all(type(page) is int and 0 <= page <= 12 for page in page_numbers)
            and len(set(page_numbers)) == len(page_numbers)):
        fields["quality_pages"] = sorted(page_numbers)
    if (type(issue_counts) is dict and len(issue_counts) <= len(_ISSUES)
            and all(type(issue) is str and issue in _ISSUES
                    and type(count) is int and 0 <= count <= 13
                    for issue, count in issue_counts.items())):
        fields["quality_issue_counts"] = dict(issue_counts)
    # Celery may suppress INFO logs. Rejection diagnostics must remain visible
    # at its normal WARNING level without changing global logging verbosity.
    logger.warning("Illustration quality diagnostic", **fields)
