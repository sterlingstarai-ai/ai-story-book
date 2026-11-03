"""Durable global generation admissions; these are counts, not charges."""
from sqlalchemy import CheckConstraint, Column, Integer, String

from src.core.database import Base


class GenerationBudgetActivation(Base):
    __tablename__ = "generation_budget_activation"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_generation_budget_singleton"),
        CheckConstraint("requests >= 0", name="ck_generation_budget_nonnegative"),
        CheckConstraint("length(blocked_through_day) = 8 AND length(current_day) = 8", name="ck_generation_budget_days"),
        CheckConstraint("current_day >= blocked_through_day", name="ck_generation_budget_day_order"),
    )
    id = Column(Integer, primary_key=True)
    blocked_through_day = Column(String(8), nullable=False)
    current_day = Column(String(8), nullable=False)
    requests = Column(Integer, nullable=False)
