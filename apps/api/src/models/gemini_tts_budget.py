"""Persistent per-period admission counts for paid Gemini TTS requests."""
from sqlalchemy import CheckConstraint, Column, Integer, String

from src.core.database import Base


class GeminiTTSRequestBudget(Base):
    __tablename__ = 'gemini_tts_request_budget'
    __table_args__ = (CheckConstraint('requests >= 0', name='ck_gemini_tts_budget_nonnegative'),)

    bucket = Column(String(20), primary_key=True)
    requests = Column(Integer, nullable=False)
