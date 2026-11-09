from pydantic import BaseModel, Field

from src.models.dto import Style


class GenerationOptionsResponse(BaseModel):
    allowed_styles: list[Style] = Field(min_length=1, max_length=7)
    first_book_trial_available: bool = False
    generation_access_allowed: bool = True
