"""Minimal reporting contract: no contact details or copied child content."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReportReason = Literal[
    "harmful_content",
    "sexual_content",
    "hate_or_bullying",
    "personal_information",
    "image_problem",
    "other",
]
ReportStatus = Literal["pending", "in_review", "resolved", "dismissed"]


class CreateContentReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    page_number: int = Field(ge=0, le=64, description="0 is the cover; body pages are one-based")
    reason: ReportReason


class ContentReportResponse(BaseModel):
    report_id: str
    status: ReportStatus
    created_at: datetime
