"""Growth Router: 읽기 성장 리포트 + 학습 응답 기록."""

from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_profile_id, get_user_key
from src.services.growth import growth_service

router = APIRouter()


class AnswerRequest(BaseModel):
    book_id: str = Field(max_length=60)
    quiz_type: Literal["vocab", "comprehension", "quiz"]
    correct: bool
    page_number: Optional[int] = None
    question_index: Optional[int] = None
    term: Optional[str] = Field(default=None, max_length=120)
    user_answer: Optional[str] = Field(default=None, max_length=500)


@router.get("")
async def get_growth(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """아이의 읽기 성장 리포트 — 읽은 책·스트릭·학습 어휘·퀴즈 정확도·추정 읽기레벨."""
    return await growth_service.get_growth_report(db, user_key, profile_id=profile_id)


@router.post("/answers")
async def record_answer(
    payload: AnswerRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """학습 퀴즈/어휘 응답 기록 — 성장 측정의 근거 데이터."""
    answer = await growth_service.record_answer(
        db,
        user_key,
        book_id=payload.book_id,
        quiz_type=payload.quiz_type,
        correct=payload.correct,
        page_number=payload.page_number,
        question_index=payload.question_index,
        term=payload.term,
        user_answer=payload.user_answer,
        profile_id=profile_id,
    )
    return {"id": answer.id, "recorded": True}
