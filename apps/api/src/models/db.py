from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Integer,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from src.core.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(60), primary_key=True)
    status = Column(
        String(20), nullable=False, default="queued"
    )  # queued, running, failed, done
    progress = Column(Integer, default=0)
    current_step = Column(String(120), default="대기 중")
    error_code = Column(String(60), nullable=True)
    error_message = Column(String(300), nullable=True)
    moderation_input = Column(JSON, nullable=True)
    moderation_output = Column(JSON, nullable=True)
    user_key = Column(String(80), nullable=False, index=True)
    idempotency_key = Column(String(80), nullable=True, index=True)
    retry_count = Column(Integer, default=0)  # Number of retry attempts
    last_retry_at = Column(DateTime, nullable=True)  # Last retry timestamp
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    story_draft = relationship("StoryDraftDB", back_populates="job", uselist=False)
    image_prompts = relationship("ImagePromptsDB", back_populates="job", uselist=False)
    book = relationship("Book", back_populates="job", uselist=False)


class StoryDraftDB(Base):
    __tablename__ = "story_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(60), ForeignKey("jobs.id"), nullable=False, unique=True)
    draft = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    job = relationship("Job", back_populates="story_draft")


class ImagePromptsDB(Base):
    __tablename__ = "image_prompts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(60), ForeignKey("jobs.id"), nullable=False, unique=True)
    prompts = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    job = relationship("Job", back_populates="image_prompts")


class Series(Base):
    """시리즈 (동일 캐릭터 연작)"""

    __tablename__ = "series"

    id = Column(String(60), primary_key=True)
    title = Column(String(100), nullable=False)
    language = Column(String(10), nullable=False)
    target_age = Column(String(10), nullable=False)
    style = Column(String(30), nullable=False)
    theme = Column(String(20), nullable=True)
    character_id = Column(String(60), ForeignKey("characters.id"), nullable=True)
    series_bible = Column(JSON, nullable=True)  # 시리즈 설정 (캐릭터 관계, 세계관 등)
    user_key = Column(String(80), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    books = relationship(
        "Book",
        back_populates="series",
        order_by="Book.series_index",
    )
    character = relationship("Character")


class Book(Base):
    __tablename__ = "books"

    id = Column(String(60), primary_key=True)
    job_id = Column(String(60), ForeignKey("jobs.id"), nullable=False, unique=True)
    title = Column(String(80), nullable=False)
    language = Column(String(10), nullable=False)
    target_age = Column(String(10), nullable=False)
    style = Column(String(30), nullable=False)
    theme = Column(String(20), nullable=True)
    character_id = Column(String(60), ForeignKey("characters.id"), nullable=True)
    character_ids = Column(JSON, nullable=True)  # 다중 캐릭터 ID 목록 (가족 등)
    cover_image_url = Column(String(500), nullable=True)
    pdf_url = Column(String(500), nullable=True)
    audio_url = Column(String(500), nullable=True)
    user_key = Column(String(80), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 시리즈 관련 (v0.3)
    series_id = Column(String(60), ForeignKey("series.id"), nullable=True)
    series_index = Column(Integer, nullable=True)  # 시리즈 내 순서 (1, 2, 3...)

    # 다국어 지원 (v0.3)
    title_ko = Column(String(100), nullable=True)  # 한국어 제목
    title_en = Column(String(100), nullable=True)  # 영어 제목

    # 학습 자산 (v0.3)
    learning_assets = Column(JSON, nullable=True)  # LearningAssets JSON

    # Relationships
    job = relationship("Job", back_populates="book")
    pages = relationship("Page", back_populates="book", order_by="Page.page_number")
    character = relationship("Character", back_populates="books")
    series = relationship("Series", back_populates="books")


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (
        UniqueConstraint("book_id", "page_number", name="uq_page_book_number"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(String(60), ForeignKey("books.id"), nullable=False)
    page_number = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    image_url = Column(String(500), nullable=True)
    image_prompt = Column(Text, nullable=True)
    audio_url = Column(String(500), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 다국어 지원 (v0.3)
    text_ko = Column(Text, nullable=True)  # 한국어 텍스트
    text_en = Column(Text, nullable=True)  # 영어 텍스트
    audio_url_ko = Column(String(500), nullable=True)  # 한국어 오디오
    audio_url_en = Column(String(500), nullable=True)  # 영어 오디오

    # 학습 자산 (v0.3)
    vocab = Column(JSON, nullable=True)  # 단어 목록 [{"word": ..., "meaning": ...}, ...]
    comprehension = Column(JSON, nullable=True)  # 이해 질문 [{"question": ..., "answer": ...}, ...]
    quiz = Column(JSON, nullable=True)  # 퀴즈 [{"question": ..., "options": [...], "answer_index": ...}, ...]

    # Relationships
    book = relationship("Book", back_populates="pages")


class Character(Base):
    __tablename__ = "characters"

    id = Column(String(60), primary_key=True)
    name = Column(String(40), nullable=False)
    master_description = Column(Text, nullable=False)
    appearance = Column(JSON, nullable=False)
    clothing = Column(JSON, nullable=False)
    personality_traits = Column(JSON, nullable=False)
    visual_style_notes = Column(String(200), nullable=True)
    user_key = Column(String(80), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    books = relationship("Book", back_populates="character")


class RateLimit(Base):
    __tablename__ = "rate_limits"

    user_key = Column(String(80), primary_key=True)
    request_count = Column(Integer, default=0)
    window_start = Column(DateTime, default=datetime.utcnow)


class UserCredits(Base):
    """사용자 크레딧 정보"""

    __tablename__ = "user_credits"

    user_key = Column(String(80), primary_key=True)
    credits = Column(Integer, default=3)  # 기본 3크레딧 무료 제공
    total_purchased = Column(Integer, default=0)  # 총 구매 크레딧
    total_used = Column(Integer, default=0)  # 총 사용 크레딧
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Subscription(Base):
    """구독 정보"""

    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_key = Column(String(80), nullable=False, index=True)
    plan = Column(String(20), nullable=False)  # free, basic, premium
    status = Column(
        String(20), nullable=False, default="active"
    )  # active, cancelled, expired
    credits_per_month = Column(Integer, nullable=False)  # 월간 크레딧
    current_period_start = Column(DateTime, nullable=False)
    current_period_end = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CreditTransaction(Base):
    """크레딧 거래 기록"""

    __tablename__ = "credit_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_key = Column(String(80), nullable=False, index=True)
    amount = Column(Integer, nullable=False)  # 양수: 충전, 음수: 사용
    balance_after = Column(Integer, nullable=False)  # 거래 후 잔액
    transaction_type = Column(
        String(30), nullable=False
    )  # purchase, subscription, usage, refund, bonus
    description = Column(String(200), nullable=True)
    reference_id = Column(String(80), nullable=True)  # book_id, subscription_id 등
    created_at = Column(DateTime, default=datetime.utcnow)


class DailyStreak(Base):
    """오늘의 동화 스트릭"""

    __tablename__ = "daily_streaks"

    user_key = Column(String(80), primary_key=True)
    current_streak = Column(Integer, default=0)  # 현재 연속 일수
    longest_streak = Column(Integer, default=0)  # 최장 연속 일수
    total_days = Column(Integer, default=0)  # 총 읽은 일수
    last_read_date = Column(DateTime, nullable=True)  # 마지막 읽은 날짜
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DailyStory(Base):
    """오늘의 동화"""

    __tablename__ = "daily_stories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False, index=True)  # 날짜 (UTC 기준)
    theme = Column(String(30), nullable=False)  # 오늘의 테마
    topic = Column(String(100), nullable=False)  # 오늘의 주제
    book_id = Column(
        String(60), ForeignKey("books.id"), nullable=True
    )  # 생성된 책 (선택)
    created_at = Column(DateTime, default=datetime.utcnow)


class ReadingLog(Base):
    """읽기 기록"""

    __tablename__ = "reading_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_key = Column(String(80), nullable=False, index=True)
    book_id = Column(String(60), ForeignKey("books.id"), nullable=False)
    read_date = Column(DateTime, nullable=False)  # 읽은 날짜
    reading_time = Column(Integer, default=0)  # 읽은 시간 (초)
    completed = Column(Boolean, default=False)  # 끝까지 읽었는지
    created_at = Column(DateTime, default=datetime.utcnow)
