"""#11 [M23]: Celery 재전달이 '복구'되어야 한다 — mock 없는 실경로 검증.

M23은 태스크 레벨에서 IntegrityError를 흡수했지만, 산출물 저장(save_story_draft/
save_image_prompts)이 plain INSERT라 재전달 시 충돌이 먼저 start_book_generation의 전역
except에 잡혀 UNKNOWN 실패 + 환불로 확정됐다(태스크 레벨 흡수는 사후 도달). 기존
test_tasks.py는 start_book_generation을 mock해 이 실경로를 한 번도 검증하지 못했다.
"""

import pytest
from sqlalchemy import func, select

from src.models.db import ImagePromptsDB, StoryDraftDB


@pytest.mark.asyncio
async def test_save_story_draft_is_idempotent_across_redelivery(db_session):
    """같은 job_id로 두 번 저장해도 충돌하지 않고 최신 값으로 갱신된다."""
    from src.models.dto import (
        Language,
        StoryCharacter,
        StoryContinuity,
        StoryCover,
        StoryDraft,
        StoryPage,
        TargetAge,
    )
    from src.services.orchestrator import save_story_draft

    job_id = "job_redelivery_draft"

    def _draft(title: str) -> StoryDraft:
        return StoryDraft(
            title=title,
            language=Language.ko,
            target_age=TargetAge.a5_7,
            theme="friendship",
            moral="Be kind",
            characters=[
                StoryCharacter(id="char1", name="Tori", role="main", brief="A bunny")
            ],
            cover=StoryCover(
                cover_text=title, scene="Meadow", mood="happy", camera="wide shot"
            ),
            pages=[
                StoryPage(
                    page=i + 1,
                    text=f"본문 {i + 1}",
                    scene="Scene",
                    mood="happy",
                    camera="medium shot",
                    characters_present=["Tori"],
                )
                for i in range(4)
            ],
            continuity=StoryContinuity(
                character_consistency_notes="Notes", style_notes_for_images="Style"
            ),
        )

    await save_story_draft(job_id, _draft("첫 실행"))
    # 재전달로 파이프라인이 같은 단계를 다시 수행 — 여기서 터지면 잡이 UNKNOWN으로 확정된다.
    await save_story_draft(job_id, _draft("재전달 실행"))

    rows = (
        await db_session.execute(
            select(func.count()).select_from(StoryDraftDB).where(
                StoryDraftDB.job_id == job_id
            )
        )
    ).scalar_one()
    assert rows == 1, "job_id당 1행이어야 함(중복 INSERT 없음)"

    saved = (
        await db_session.execute(
            select(StoryDraftDB).where(StoryDraftDB.job_id == job_id)
        )
    ).scalar_one()
    assert saved.draft["title"] == "재전달 실행", "재실행 결과로 갱신돼야 함"


@pytest.mark.asyncio
async def test_save_image_prompts_is_idempotent_across_redelivery(db_session):
    from src.models.dto import ImagePrompt, ImagePrompts
    from src.services.orchestrator import save_image_prompts

    job_id = "job_redelivery_prompts"

    def _prompts(seed: int) -> ImagePrompts:
        return ImagePrompts(
            style="watercolor",
            cover=ImagePrompt(
                page=0,
                positive_prompt="a cover illustration",
                negative_prompt="text, watermark",
                seed=seed,
            ),
            pages=[
                ImagePrompt(
                    page=i + 1,
                    positive_prompt="a page illustration",
                    negative_prompt="text, watermark",
                    seed=seed,
                )
                for i in range(4)
            ],
        )

    await save_image_prompts(job_id, _prompts(1))
    await save_image_prompts(job_id, _prompts(2))

    rows = (
        await db_session.execute(
            select(func.count()).select_from(ImagePromptsDB).where(
                ImagePromptsDB.job_id == job_id
            )
        )
    ).scalar_one()
    assert rows == 1
    saved = (
        await db_session.execute(
            select(ImagePromptsDB).where(ImagePromptsDB.job_id == job_id)
        )
    ).scalar_one()
    assert saved.prompts["cover"]["seed"] == 2
