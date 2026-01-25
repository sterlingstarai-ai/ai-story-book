from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional, Literal, Dict

from pydantic import BaseModel, Field, ConfigDict, field_validator, AliasChoices

# Import ErrorCode from canonical source to avoid duplication
from src.core.errors import ErrorCode  # noqa: E402


class Language(str, Enum):
    ko = "ko"
    en = "en"
    ja = "ja"


class TargetAge(str, Enum):
    a3_5 = "3-5"
    a5_7 = "5-7"
    a7_9 = "7-9"
    adult = "adult"


class Style(str, Enum):
    watercolor = "watercolor"
    cartoon = "cartoon"
    three_d = "3d"
    pixel = "pixel"
    oil_painting = "oil_painting"
    claymation = "claymation"
    realistic = "realistic"  # 실사


class Theme(str, Enum):
    lifestyle = "생활습관"
    emotion = "감정코칭"
    social = "사회성"
    friendship = "우정"
    family = "가족"
    adventure = "모험"
    nature = "자연"
    science = "과학"
    time_travel = "시간여행"  # 미래나 역사 속으로
    animal = "동물"
    dinosaur = "공룡"
    occupation = "직업"  # 직업 체험
    fiction_world = "작품속으로"  # 유명 작품 세계관 (저작권 회피)


class JobState(str, Enum):
    queued = "queued"
    running = "running"
    failed = "failed"
    done = "done"


# ErrorCode is imported at the top of the file from src.core.errors
# to avoid duplication with the canonical definition


# ==================== Input Models ====================


class CharacterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    gender: Optional[Literal["male", "female", "neutral"]] = None
    appearance: Optional[str] = Field(default=None, max_length=200)
    personality: Optional[List[str]] = Field(default=None, max_length=8)


class BookSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=200)
    language: Language = Language.ko
    target_age: TargetAge
    style: Style
    page_count: int = Field(ge=4, le=12, default=8)
    theme: Optional[Theme] = None
    character: Optional[CharacterSpec] = None
    character_id: Optional[str] = Field(
        default=None, max_length=60, description="기존 캐릭터 ID (단일)"
    )
    character_ids: Optional[List[str]] = Field(
        default=None, max_length=10, description="기존 캐릭터 ID 목록 (다중 선택)"
    )
    forbidden_elements: Optional[List[str]] = Field(default=None, max_length=20)
    reference_image_base64: Optional[str] = Field(default=None, max_length=5_000_000)
    series_context: Optional[str] = Field(
        default=None, max_length=500, description="시리즈 컨텍스트"
    )


# ==================== Story Models ====================


class ModerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_safe: bool
    reasons: List[str] = Field(default_factory=list, max_length=3)
    suggestions: List[str] = Field(default_factory=list, max_length=3)


class StoryCharacter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=40)
    role: Literal["main", "support"]
    brief: str = Field(min_length=1, max_length=120)


class StoryCover(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cover_text: str = Field(min_length=1, max_length=80)
    scene: str = Field(min_length=1, max_length=200)
    mood: str = Field(min_length=1, max_length=40)
    camera: str = Field(min_length=1, max_length=60)


class StoryPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1, le=12)
    text: str = Field(min_length=1, max_length=600)
    scene: str = Field(min_length=1, max_length=260)
    mood: str = Field(min_length=1, max_length=40)
    camera: str = Field(min_length=1, max_length=60)
    characters_present: List[str] = Field(min_length=1, max_length=6)
    learning_point: Optional[str] = Field(default=None, max_length=120)
    series_hook: Optional[str] = Field(default=None, max_length=120)


class StoryContinuity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_consistency_notes: str = Field(min_length=1, max_length=300)
    style_notes_for_images: str = Field(min_length=1, max_length=300)


class StoryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=80)
    language: Language
    target_age: TargetAge
    theme: Optional[str] = Field(default=None, max_length=20)
    moral: str = Field(min_length=1, max_length=120)
    characters: List[StoryCharacter] = Field(min_length=1, max_length=6)
    cover: StoryCover
    pages: List[StoryPage] = Field(min_length=4, max_length=12)
    continuity: StoryContinuity

    @field_validator("pages")
    @classmethod
    def _pages_unique_and_sorted(cls, v: List[StoryPage]) -> List[StoryPage]:
        nums = [p.page for p in v]
        if len(set(nums)) != len(nums):
            raise ValueError("pages.page must be unique")
        return sorted(v, key=lambda p: p.page)


# ==================== Character Sheet Models ====================


class CharacterAppearance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    age_visual: str = Field(min_length=1, max_length=40)
    face: str = Field(min_length=1, max_length=120)
    hair: str = Field(min_length=1, max_length=120)
    skin: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=80)


class CharacterClothing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top: str = Field(default="알 수 없음", max_length=80)
    bottom: str = Field(default="알 수 없음", max_length=80)
    shoes: str = Field(default="알 수 없음", max_length=80)
    accessories: str = Field(default="없음", max_length=80)


class CharacterSheet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=40)
    master_description: str = Field(min_length=10, max_length=400)
    appearance: CharacterAppearance
    clothing: CharacterClothing
    personality_traits: List[str] = Field(min_length=1, max_length=10)
    visual_style_notes: str = Field(min_length=1, max_length=200)


# ==================== Image Prompt Models ====================


class ImagePrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=0, le=12)  # 0 = cover
    positive_prompt: str = Field(min_length=10, max_length=1200)
    negative_prompt: str = Field(min_length=10, max_length=600)
    seed: int = Field(ge=1, le=2_147_483_647)
    aspect_ratio: Literal["1:1", "3:4", "4:3", "9:16"] = "3:4"
    guidance_notes: Optional[str] = Field(default=None, max_length=200)


class ImagePrompts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    style: str
    cover: ImagePrompt  # Cover prompt (page=0)
    pages: List[ImagePrompt] = Field(min_length=4, max_length=12)


# ==================== Result Models ====================


class PageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1, le=12)
    text: str = Field(min_length=1, max_length=800)
    image_url: str = Field(min_length=8, max_length=500)
    image_prompt: str = Field(min_length=10, max_length=1400)
    audio_url: Optional[str] = Field(default=None, max_length=500)

    # 다국어 지원 (v0.3)
    text_ko: Optional[str] = Field(default=None, max_length=800)
    text_en: Optional[str] = Field(default=None, max_length=800)
    audio_url_ko: Optional[str] = Field(default=None, max_length=500)
    audio_url_en: Optional[str] = Field(default=None, max_length=500)

    # 학습 자산 (v0.3)
    vocab: Optional[List[Dict[str, Any]]] = None
    comprehension_questions: Optional[List[Dict[str, Any]]] = None
    quiz: Optional[List[Dict[str, Any]]] = None


class BookResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    book_id: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=80)
    language: Language
    target_age: TargetAge
    style: str
    cover_image_url: str = Field(min_length=8, max_length=500)
    pages: List[PageResult] = Field(min_length=4, max_length=12)
    character_sheet: Optional[CharacterSheet] = (
        None  # Made optional for API responses without full sheet
    )
    pdf_url: Optional[str] = Field(default=None, max_length=500)
    audio_url: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime

    # 시리즈 관련 (v0.3)
    series_id: Optional[str] = Field(default=None, max_length=60)
    series_index: Optional[int] = Field(default=None, ge=1)

    # 다국어 지원 (v0.3)
    title_ko: Optional[str] = Field(default=None, max_length=100)
    title_en: Optional[str] = Field(default=None, max_length=100)

    # 학습 자산 (v0.3)
    learning_assets: Optional[Dict[str, Any]] = None


# ==================== Job/API Response Models ====================


class ErrorInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str = Field(max_length=300)


class JobStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1, max_length=60)
    status: JobState
    progress: int = Field(ge=0, le=100)
    current_step: str = Field(min_length=1, max_length=120)
    error: Optional[ErrorInfo] = None
    result: Optional[Dict[str, Any]] = None


class CreateBookResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1, max_length=60)
    status: JobState
    estimated_time_seconds: Optional[int] = Field(default=None, ge=1, le=3600)


class RegeneratePageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    mode: Literal["text", "image", "both"] = Field(
        validation_alias=AliasChoices("mode", "regenerate_target")
    )
    feedback: Optional[str] = Field(default=None, max_length=200)


class RegeneratePageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1, max_length=60)
    status: JobState


# ==================== Learning Asset Models (v0.3) ====================


class VocabItem(BaseModel):
    """단어 학습 아이템"""
    model_config = ConfigDict(extra="forbid")

    word: str = Field(min_length=1, max_length=50)
    meaning: str = Field(min_length=1, max_length=200)
    example: Optional[str] = Field(default=None, max_length=300)


class ComprehensionQuestion(BaseModel):
    """이해 질문"""
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=300)
    answer: Optional[str] = Field(default=None, max_length=500)


class QuizItem(BaseModel):
    """퀴즈 아이템 (객관식)"""
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=300)
    options: List[str] = Field(min_length=2, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    explanation: Optional[str] = Field(default=None, max_length=300)


class LearningPageAssets(BaseModel):
    """페이지별 학습 자산"""
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1, le=12)
    translated_text: str = Field(min_length=1, max_length=800)
    vocab: List[VocabItem] = Field(default_factory=list, max_length=10)
    comprehension_questions: List[ComprehensionQuestion] = Field(default_factory=list, max_length=3)
    quiz: List[QuizItem] = Field(default_factory=list, max_length=2)


class ParentGuide(BaseModel):
    """부모 가이드"""
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=500)
    discussion_prompts: List[str] = Field(default_factory=list, max_length=5)
    activities: List[str] = Field(default_factory=list, max_length=5)


class LearningAssets(BaseModel):
    """전체 학습 자산"""
    model_config = ConfigDict(extra="forbid")

    source_language: Language
    target_language: Language
    title_translation: str = Field(min_length=1, max_length=100)
    pages: List[LearningPageAssets] = Field(min_length=4, max_length=12)
    parent_guide: ParentGuide


# ==================== Series Models ====================


class SeriesNextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(min_length=1, max_length=60)
    topic: str = Field(min_length=1, max_length=200)  # 필수로 변경

    # 시리즈 식별 (없으면 새 시리즈 생성)
    series_id: Optional[str] = Field(default=None, max_length=60)
    series_title: Optional[str] = Field(default=None, max_length=100)

    # 기본 설정
    theme: Optional[Theme] = None
    language: Language = Language.ko
    target_age: TargetAge = TargetAge.a5_7
    style: Style = Style.watercolor
    page_count: int = Field(ge=4, le=12, default=8)
    forbidden_elements: Optional[List[str]] = Field(default=None, max_length=20)

    # 기존 설계 확장 호환
    previous_book_id: Optional[str] = Field(default=None, max_length=60)
    new_topic_hint: Optional[str] = Field(default=None, max_length=200)


# ==================== Character API Models ====================


class CreateCharacterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    master_description: str = Field(min_length=10, max_length=400)
    appearance: CharacterAppearance
    clothing: CharacterClothing
    personality_traits: List[str] = Field(min_length=1, max_length=10)
    visual_style_notes: str = Field(min_length=1, max_length=200)


class CharacterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str
    name: str
    master_description: str
    appearance: CharacterAppearance
    clothing: CharacterClothing
    personality_traits: List[str]
    visual_style_notes: str
    created_at: datetime


class CharacterListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    characters: List[CharacterResponse]
    total: int


# ==================== Library Models ====================


class BookSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    book_id: str
    title: str
    cover_image_url: str
    target_age: TargetAge
    style: str
    created_at: datetime


class LibraryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    books: List[BookSummary]
    total: int
