from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    JSON,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from src.core.database import Base
from src.core.utils import utcnow


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status_created", "status", "created_at"),
        Index("ix_jobs_user_profile_created", "user_key", "profile_id", "created_at"),
        # 동일 (user_key, idempotency_key) 잡 중복 생성을 DB 레벨에서 차단(더블탭/재시도
        # 동시요청의 크레딧 이중차감 방지). idempotency_key가 NULL인 잡은 제약 대상 아님.
        Index(
            "uq_jobs_user_idempotency",
            "user_key",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id = Column(String(60), primary_key=True)
    status = Column(
        String(20), nullable=False, default="queued"
    )  # queued, running, failed, done
    progress = Column(Integer, default=0)
    current_step = Column(String(120), default="queued")  # M32: 안정 키
    error_code = Column(String(60), nullable=True)
    error_message = Column(String(300), nullable=True)
    moderation_input = Column(JSON, nullable=True)
    moderation_output = Column(JSON, nullable=True)
    user_key = Column(String(80), nullable=False, index=True)
    profile_id = Column(String(60), nullable=True, index=True)
    idempotency_key = Column(String(80), nullable=True, index=True)
    retry_count = Column(Integer, default=0)  # Number of retry attempts
    last_retry_at = Column(DateTime, nullable=True)  # Last retry timestamp
    # M12/R3-5: 이 잡이 S3에 영속화한 이미지 키 목록. 잡이 실패하면 책 행이 만들어지지
    # 않아 image_url 역산 경로가 존재하지 않고, 이미 올라간 아동 얼굴 파생 일러스트가
    # 어떤 파기 경로에도 닿지 않는 고아가 된다 — 생성 시점에 여기 기록해 추적 가능하게.
    image_keys = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    story_draft = relationship("StoryDraftDB", back_populates="job", uselist=False)
    image_prompts = relationship("ImagePromptsDB", back_populates="job", uselist=False)
    book = relationship("Book", back_populates="job", uselist=False)


class StoryDraftDB(Base):
    __tablename__ = "story_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(60), ForeignKey("jobs.id"), nullable=False, unique=True)
    draft = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    job = relationship("Job", back_populates="story_draft")


class ImagePromptsDB(Base):
    __tablename__ = "image_prompts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(60), ForeignKey("jobs.id"), nullable=False, unique=True)
    prompts = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=utcnow)

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
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    books = relationship(
        "Book",
        back_populates="series",
        order_by="Book.series_index",
    )
    character = relationship("Character")


class Book(Base):
    __tablename__ = "books"
    __table_args__ = (
        Index("ix_books_user_created", "user_key", "created_at"),
        Index("ix_books_user_profile_created", "user_key", "profile_id", "created_at"),
    )

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
    profile_id = Column(String(60), nullable=True, index=True)
    created_at = Column(DateTime, default=utcnow)

    # 시리즈 관련 (v0.3)
    series_id = Column(String(60), ForeignKey("series.id"), nullable=True)
    series_index = Column(Integer, nullable=True)  # 시리즈 내 순서 (1, 2, 3...)

    # 연령 리텔(grow-with-child) 원본 책 — 같은 이야기의 다른 연령 변형을 묶는다
    retelling_source_book_id = Column(
        # M10: 마이그레이션과 일치하도록 ondelete=SET NULL 명시(원본 삭제 시 변형 링크 해제).
        String(60), ForeignKey("books.id", ondelete="SET NULL"), nullable=True
    )

    # 다국어 지원 (v0.3)
    title_ko = Column(String(100), nullable=True)  # 한국어 제목
    title_en = Column(String(100), nullable=True)  # 영어 제목

    # 학습 자산 (v0.3)
    learning_assets = Column(JSON, nullable=True)  # LearningAssets JSON

    # Relationships
    job = relationship("Job", back_populates="book")
    pages = relationship(
        "Page",
        back_populates="book",
        order_by="Page.page_number",
        cascade="all, delete-orphan",
    )
    character = relationship("Character", back_populates="books")
    series = relationship("Series", back_populates="books")


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (
        UniqueConstraint("book_id", "page_number", name="uq_page_book_number"),
        Index("ix_pages_book_id", "book_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(String(60), ForeignKey("books.id"), nullable=False)
    page_number = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    image_url = Column(String(500), nullable=True)
    image_prompt = Column(Text, nullable=True)
    audio_url = Column(String(500), nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # 다국어 지원 (v0.3)
    text_ko = Column(Text, nullable=True)  # 한국어 텍스트
    text_en = Column(Text, nullable=True)  # 영어 텍스트
    audio_url_ko = Column(String(500), nullable=True)  # 한국어 오디오
    audio_url_en = Column(String(500), nullable=True)  # 영어 오디오

    # 학습 자산 (v0.3)
    vocab = Column(
        JSON, nullable=True
    )  # 단어 목록 [{"word": ..., "meaning": ...}, ...]
    comprehension = Column(
        JSON, nullable=True
    )  # 이해 질문 [{"question": ..., "answer": ...}, ...]
    quiz = Column(
        JSON, nullable=True
    )  # 퀴즈 [{"question": ..., "options": [...], "answer_index": ...}, ...]

    # Relationships
    book = relationship("Book", back_populates="pages")


class Character(Base):
    __tablename__ = "characters"
    __table_args__ = (
        # H17/G19: 사진·그림 캐릭터 생성은 요청 안에서 vision 분석 + 시트 이미지를 동기로
        # 수행해 최대 수분이 걸린다. 클라 타임아웃 후 서버는 완주하므로 재시도가 중복
        # 캐릭터를 만든다(서재 오염 + vision·이미지 비용 이중 지출). 동일
        # (user_key, idempotency_key)를 DB 레벨에서 차단 — Job/PodOrder 멱등 인프라와
        # 동일 패턴(키가 NULL인 캐릭터는 제약 대상 아님).
        Index(
            "uq_characters_user_idempotency",
            "user_key",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id = Column(String(60), primary_key=True)
    name = Column(String(40), nullable=False)
    master_description = Column(Text, nullable=False)
    appearance = Column(JSON, nullable=False)
    clothing = Column(JSON, nullable=False)
    personality_traits = Column(JSON, nullable=False)
    visual_style_notes = Column(String(200), nullable=True)
    # 식별 가능한 고유 특징(안경/주근깨/곱슬머리 등) — 같은 캐릭터를 날짜·책을 넘어
    # 동일하게 그리기 위해 영속(시리즈 교차 일관성). 이미지 프롬프트에 매 페이지 강제.
    distinctive_features = Column(JSON, nullable=True)
    # 아동 사진/그림에서 파생된 캐릭터 여부 — 보호자 동의 게이트·철회 시 파기 대상 식별
    from_photo = Column(Boolean, nullable=False, default=False)
    # 원본 사진/그림 URL — 얼굴 보존 이미지 생성(gemini)의 레퍼런스로 사용
    source_image_url = Column(String(500), nullable=True)
    user_key = Column(String(80), nullable=False, index=True)
    # 클라이언트 시도-단위 멱등키(H17/G19). 재시도 시 기존 캐릭터를 반환해 재분석을 막는다.
    idempotency_key = Column(String(80), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    books = relationship("Book", back_populates="character")


class BookShare(Base):
    """부모가 만든 책 공개 공유 링크(만료·철회 가능, 검색 비노출, PII 비공개)."""

    __tablename__ = "book_shares"
    __table_args__ = (Index("ix_book_shares_book", "book_id"),)

    id = Column(String(60), primary_key=True)  # 공유 토큰(uuid hex)
    book_id = Column(String(60), ForeignKey("books.id"), nullable=False)
    user_key = Column(String(80), nullable=False, index=True)  # 소유자(부모)
    created_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime, nullable=True)  # 만료 시각(NULL=무기한)
    revoked_at = Column(DateTime, nullable=True)  # 철회 시각(NULL=활성)


class RateLimit(Base):
    __tablename__ = "rate_limits"

    user_key = Column(String(80), primary_key=True)
    request_count = Column(Integer, default=0)
    window_start = Column(DateTime, default=utcnow)


class UserCredits(Base):
    """사용자 크레딧 정보"""

    __tablename__ = "user_credits"

    user_key = Column(String(80), primary_key=True)
    credits = Column(Integer, default=3)  # 기본 3크레딧 무료 제공
    total_purchased = Column(Integer, default=0)  # 총 구매 크레딧
    total_used = Column(Integer, default=0)  # 총 사용 크레딧
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class Subscription(Base):
    """구독 정보"""

    __tablename__ = "subscriptions"
    __table_args__ = (
        # 사용자당 active 구독은 최대 1행 — check-then-write 사이 DB 제약 부재로 인한
        # 동시 이중 active(→ periodic_credits 영구 이중 지급)를 DB 레벨에서 차단(M17).
        # cancelled/expired는 제약 대상 아님(부분 인덱스).
        Index(
            "uq_subscriptions_active_per_user",
            "user_key",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_key = Column(String(80), nullable=False, index=True)
    plan = Column(String(20), nullable=False)  # free, basic, premium
    status = Column(
        String(20), nullable=False, default="active"
    )  # active, cancelled, expired
    credits_per_month = Column(Integer, nullable=False)  # 월간 크레딧
    current_period_start = Column(DateTime, nullable=False)
    current_period_end = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class CreditTransaction(Base):
    """크레딧 거래 기록"""

    __tablename__ = "credit_transactions"
    __table_args__ = (
        Index(
            "uq_credit_transactions_milestone_bonus",
            "user_key",
            "reference_id",
            unique=True,
            sqlite_where=text(
                "transaction_type = 'bonus' "
                "AND reference_id LIKE 'milestone_%'"
            ),
            postgresql_where=text(
                "transaction_type = 'bonus' "
                "AND reference_id LIKE 'milestone_%'"
            ),
        ),
        # M16: 멀티 레플리카 동시 스캔/재전송에서의 이중 환불·N중 지급을 DB로 강제 차단.
        # refund는 job당 1회(reference_id=job_id), purchase는 (user_key, 결제 txn)당 1회.
        Index(
            "uq_credit_transactions_refund",
            "reference_id",
            unique=True,
            sqlite_where=text("transaction_type = 'refund'"),
            postgresql_where=text("transaction_type = 'refund'"),
        ),
        Index(
            "uq_credit_transactions_purchase",
            "user_key",
            "reference_id",
            unique=True,
            sqlite_where=text("transaction_type = 'purchase'"),
            postgresql_where=text("transaction_type = 'purchase'"),
        ),
        # M2/R2-2: clawback(환불 회수)도 refund/purchase와 같은 DB 레벨 멱등이 필요하다.
        # clawback_credits는 트랜잭션 밖 check-then-write라 동시 중복 환불 웹훅 두 건이
        # 모두 '아직 회수 안 됨'을 통과해 크레딧을 이중 회수한다(사용자 손해). 회수는
        # (user_key, reference_id)당 1회.
        Index(
            "uq_credit_transactions_clawback",
            "user_key",
            "reference_id",
            unique=True,
            sqlite_where=text("transaction_type = 'clawback'"),
            postgresql_where=text("transaction_type = 'clawback'"),
        ),
        Index(
            "ix_credit_transactions_reference_type",
            "reference_id",
            "transaction_type",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_key = Column(String(80), nullable=False, index=True)
    amount = Column(Integer, nullable=False)  # 양수: 충전, 음수: 사용
    balance_after = Column(Integer, nullable=False)  # 거래 후 잔액
    transaction_type = Column(
        String(30), nullable=False
    )  # purchase, subscription, usage, refund, bonus
    description = Column(String(200), nullable=True)
    reference_id = Column(String(80), nullable=True)  # book_id, subscription_id 등
    created_at = Column(DateTime, default=utcnow)


class DailyStreak(Base):
    """오늘의 동화 스트릭"""

    __tablename__ = "daily_streaks"

    user_key = Column(String(80), primary_key=True)
    current_streak = Column(Integer, default=0)  # 현재 연속 일수
    longest_streak = Column(Integer, default=0)  # 최장 연속 일수
    total_days = Column(Integer, default=0)  # 총 읽은 일수
    last_read_date = Column(DateTime, nullable=True)  # 마지막 읽은 날짜
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class DailyStory(Base):
    """오늘의 동화"""

    __tablename__ = "daily_stories"
    __table_args__ = (
        # 하루 1행 보장(H14) — check-then-insert 레이스로 중복 행이 생기면 이후 그 날의
        # /streak/today가 MultipleResultsFound로 전 사용자 500이 되던 것을 DB로 차단.
        UniqueConstraint("date", name="uq_daily_stories_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False)  # 날짜 (UTC 기준) — unique 제약이 인덱스 겸함
    theme = Column(String(30), nullable=False)  # 오늘의 테마
    topic = Column(String(100), nullable=False)  # 오늘의 주제
    book_id = Column(
        String(60), ForeignKey("books.id"), nullable=True
    )  # 생성된 책 (선택)
    created_at = Column(DateTime, default=utcnow)


class ReadingLog(Base):
    """읽기 기록"""

    __tablename__ = "reading_logs"
    __table_args__ = (
        Index("ix_reading_logs_user_date", "user_key", "read_date"),
        Index("ix_reading_logs_user_profile_date", "user_key", "profile_id", "read_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_key = Column(String(80), nullable=False, index=True)
    profile_id = Column(String(60), nullable=True, index=True)
    book_id = Column(String(60), ForeignKey("books.id"), nullable=False)
    read_date = Column(DateTime, nullable=False)  # 읽은 날짜
    reading_time = Column(Integer, default=0)  # 읽은 시간 (초)
    completed = Column(Boolean, default=False)  # 끝까지 읽었는지
    created_at = Column(DateTime, default=utcnow)

    # 책 참조(many-to-one). UOW가 Book을 ReadingLog보다 먼저 INSERT하도록 보장한다.
    book = relationship("Book")


class IAPReceipt(Base):
    """인앱 결제 영수증 저장"""

    __tablename__ = "iap_receipts"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "transaction_id",
            name="uq_iap_receipts_platform_transaction_id",
        ),
        # 리플레이 방지의 정본 키: 클라이언트가 보낸 transaction_id가 아니라
        # 스토어가 검증해 돌려준 식별자(Apple original_transaction_id / Google orderId).
        # 같은 영수증을 다른 transaction_id로 재제출하는 공격을 DB 레벨에서 차단한다.
        UniqueConstraint(
            "platform",
            "store_transaction_id",
            name="uq_iap_receipts_platform_store_transaction_id",
        ),
        Index("ix_iap_receipts_user_key", "user_key"),
        Index("ix_iap_receipts_subscription_id", "subscription_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_key = Column(String(80), nullable=False)
    platform = Column(String(20), nullable=False)  # apple, google
    product_id = Column(String(120), nullable=False)
    transaction_id = Column(String(200), nullable=False)
    # 스토어 검증으로 확정된 거래 식별자(없으면 NULL — local 모드에선 transaction_id와 동일).
    store_transaction_id = Column(String(200), nullable=True)
    purchase_token = Column(String(500), nullable=True)
    status = Column(String(40), nullable=False, default="verified")
    payload = Column(JSON, nullable=True)
    # 이 영수증이 개설/재활성한 구독(H5). 웹훅이 '최신 구독' 임의 매칭 대신 이 구독만
    # 갱신하게 해, 업그레이드 후 옛 영수증 통지가 방금 결제한 구독을 죽이는 것을 막는다.
    subscription_id = Column(
        Integer, ForeignKey("subscriptions.id"), nullable=True
    )
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class IapWebhookEvent(Base):
    """IAP 웹훅 이벤트 적재(H4).

    verify 이전 선도착하거나 store 식별자로만 오는 환불/취소 통지가 영수증 조회 미스로
    유실되지 않도록 적재한다. verify 시 매칭 영수증에 sticky 재적용 후 applied=True.
    """

    __tablename__ = "iap_webhook_events"
    __table_args__ = (
        # 중복 웹훅 멱등: 같은 (platform, transaction_id, status)는 1행.
        Index(
            "uq_iap_webhook_events_dedup",
            "platform",
            "transaction_id",
            "status",
            unique=True,
        ),
        Index(
            "ix_iap_webhook_events_lookup",
            "platform",
            "transaction_id",
            "applied",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(20), nullable=False)
    transaction_id = Column(String(200), nullable=False)
    status = Column(String(40), nullable=False)
    payload = Column(JSON, nullable=True)
    applied = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow)


class UserConsent(Base):
    """부모 동의 이력"""

    __tablename__ = "user_consents"
    __table_args__ = (
        Index("ix_user_consents_user_key", "user_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_key = Column(String(80), nullable=False)
    consent_version = Column(String(20), nullable=False, default="v1")
    privacy = Column(Boolean, nullable=False, default=False)
    photos = Column(Boolean, nullable=False, default=False)
    data_processing = Column(Boolean, nullable=False, default=False)
    granted = Column(Boolean, nullable=False, default=False)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class UserSettings(Base):
    """사용자 설정"""

    __tablename__ = "user_settings"

    user_key = Column(String(80), primary_key=True)
    language = Column(String(10), nullable=False, default="ko")
    # 하루/월 경계(스트릭·일일/월간 한도·리포트) 판정용 IANA 타임존(H2/G10). 기본 Asia/Seoul.
    timezone = Column(
        String(40), nullable=False, default="Asia/Seoul", server_default="Asia/Seoul"
    )
    dark_mode = Column(Boolean, nullable=False, default=False)
    bedtime_notification_enabled = Column(Boolean, nullable=False, default=False)
    bedtime_notification_hour = Column(Integer, nullable=True)
    bedtime_notification_minute = Column(Integer, nullable=True)
    sleep_mode_default_minutes = Column(Integer, nullable=False, default=20)
    allow_kakao_share = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ChildProfile(Base):
    """자녀 프로필"""

    __tablename__ = "child_profiles"
    __table_args__ = (
        Index("ix_child_profiles_user_key", "user_key"),
        UniqueConstraint("user_key", "name", name="uq_child_profiles_user_name"),
    )

    id = Column(String(60), primary_key=True)
    user_key = Column(String(80), nullable=False)
    name = Column(String(40), nullable=False)
    # age_band은 NOT NULL 유지(점수/또래 코호트의 기준). 생년월(birth_year/month)이 있으면
    # age_band를 거기서 *파생*해 저장한다(부모 임의선택 제거, 5/7세 경계중복 해소).
    age_band = Column(String(10), nullable=False, default="5-7")
    birth_year = Column(Integer, nullable=True)
    birth_month = Column(Integer, nullable=True)
    preferred_theme = Column(String(30), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ScreenTimeLimit(Base):
    """화면 시간 제한"""

    __tablename__ = "screen_time_limits"

    user_key = Column(String(80), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False)
    daily_limit_minutes = Column(Integer, nullable=False, default=60)
    used_minutes_today = Column(Integer, nullable=False, default=0)
    usage_date = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class AdRewardLog(Base):
    """리워드 광고 적립 로그"""

    __tablename__ = "ad_reward_logs"
    __table_args__ = (
        Index("ix_ad_reward_logs_user_key_created", "user_key", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_key = Column(String(80), nullable=False)
    reward_type = Column(String(40), nullable=False, default="credit")
    reward_amount = Column(Integer, nullable=False, default=1)
    ad_network = Column(String(40), nullable=True)
    ad_unit_id = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=utcnow)


class PodOrder(Base):
    """실물책 주문"""

    __tablename__ = "pod_orders"
    __table_args__ = (
        Index("ix_pod_orders_user_key", "user_key"),
        # 동일 (user_key, idempotency_key) 주문 중복 생성을 DB로 차단(더블탭 이중주문/외부
        # draft 이중 생성 방지, H6). Job 멱등 인프라와 동일 패턴(NULL 키는 제약 제외).
        Index(
            "uq_pod_orders_user_idempotency",
            "user_key",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id = Column(String(60), primary_key=True)
    user_key = Column(String(80), nullable=False)
    book_id = Column(String(60), ForeignKey("books.id"), nullable=False)
    idempotency_key = Column(String(80), nullable=True)  # H6
    provider = Column(String(40), nullable=False, default="printful")
    status = Column(String(30), nullable=False, default="created")
    quantity = Column(Integer, nullable=False, default=1)
    # 지역 견적(사용자 표시·청구 기준, region_currency). provider 실비와 별도 컬럼으로
    # 분리해 한 행에 단위·통화가 혼재하지 않게 한다(H13/G7).
    unit_price = Column(Integer, nullable=False, default=0)
    shipping_fee = Column(Integer, nullable=False, default=0)
    total_price = Column(Integer, nullable=False, default=0)
    currency = Column(String(10), nullable=False, default="KRW")
    # provider(Printful) 실비 — 원통화·정수 cents로 저장(×환산 금지). None=미연동/미확정.
    provider_total = Column(Integer, nullable=True)  # H13/G7
    provider_currency = Column(String(10), nullable=True)  # H13/G7
    shipping_address = Column(JSON, nullable=False)
    provider_order_id = Column(String(120), nullable=True)
    tracking_number = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class VoiceProfile(Base):
    """가족 음성 프로필"""

    __tablename__ = "voice_profiles"
    __table_args__ = (
        Index("ix_voice_profiles_user_key", "user_key"),
    )

    id = Column(String(60), primary_key=True)
    user_key = Column(String(80), nullable=False)
    label = Column(String(40), nullable=False)
    relationship = Column(String(30), nullable=True)
    sample_audio_url = Column(String(500), nullable=False)
    provider_voice_id = Column(String(120), nullable=True)
    consented = Column(Boolean, nullable=False, default=False)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class BranchStoryNode(Base):
    """분기형 스토리 노드"""

    __tablename__ = "branch_story_nodes"
    __table_args__ = (
        Index("ix_branch_story_nodes_book_id", "book_id"),
        UniqueConstraint("book_id", "node_key", name="uq_branch_story_nodes_book_node"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(String(60), ForeignKey("books.id"), nullable=False)
    node_key = Column(String(80), nullable=False)
    page_number = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    image_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class BranchStoryEdge(Base):
    """분기형 스토리 선택지 연결"""

    __tablename__ = "branch_story_edges"
    __table_args__ = (
        Index("ix_branch_story_edges_book_id", "book_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(String(60), ForeignKey("books.id"), nullable=False)
    from_node_key = Column(String(80), nullable=False)
    to_node_key = Column(String(80), nullable=False)
    option_text = Column(String(120), nullable=False)
    created_at = Column(DateTime, default=utcnow)


class PronunciationLog(Base):
    """발음 평가 로그"""

    __tablename__ = "pronunciation_logs"
    __table_args__ = (
        Index("ix_pronunciation_logs_user_key_created", "user_key", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_key = Column(String(80), nullable=False)
    book_id = Column(String(60), ForeignKey("books.id"), nullable=True)
    page_number = Column(Integer, nullable=True)
    transcript = Column(Text, nullable=True)
    expected_text = Column(Text, nullable=True)
    score = Column(Float, nullable=False, default=0.0)
    feedback = Column(Text, nullable=True)
    audio_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    book = relationship("Book")


class QuizAnswer(Base):
    """학습 퀴즈/어휘 응답 기록 — '읽기 성장' 측정의 근거 데이터.

    Page.vocab/comprehension/quiz(JSON)는 생성되어 쌓이지만, 지금까지 아이의
    '응답'을 저장하는 곳이 없어 학습 진척을 측정할 수 없었다. 이 테이블이 그 공백을 메운다.
    """

    __tablename__ = "quiz_answers"
    __table_args__ = (
        Index("ix_quiz_answers_user_created", "user_key", "created_at"),
        Index("ix_quiz_answers_user_book", "user_key", "book_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_key = Column(String(80), nullable=False)
    profile_id = Column(String(60), nullable=True, index=True)
    book_id = Column(String(60), ForeignKey("books.id"), nullable=False)
    page_number = Column(Integer, nullable=True)
    quiz_type = Column(String(20), nullable=False)  # vocab | comprehension | quiz
    question_index = Column(Integer, nullable=True)
    term = Column(String(120), nullable=True)  # 어휘 단어/문항 키 (vocab 학습 추적)
    user_answer = Column(Text, nullable=True)
    correct = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow)

    book = relationship("Book")


class StoragePurgeTask(Base):
    """스토리지 파기 지시(outbox) — 아동 PII 파기의 durable 레코드 (M8/R1-5).

    계정 삭제·동의 철회는 DB 행을 먼저 지우므로, 그 뒤 S3 파기가 실패·중단되면 키를
    되찾을 방법이 없다(행이 없어 URL 역산 불가). 파기 '의도'를 삭제와 같은 트랜잭션에
    커밋해 두면, 즉시 실행이 실패해도 job_monitor 스윕이 멱등 재실행할 수 있다.
    """

    __tablename__ = "storage_purge_tasks"
    __table_args__ = (
        Index("ix_storage_purge_tasks_status", "status", "id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 파기 대상 소유자(감사·역추적용). 행 삭제 후에도 남는 유일한 연결고리다.
    user_key = Column(String(80), nullable=True, index=True)
    reason = Column(String(40), nullable=False)  # account_deletion | consent_revoke | ...
    kind = Column(String(20), nullable=False)  # keys | prefix
    target = Column(Text, nullable=False)  # S3 키 또는 prefix
    status = Column(String(20), nullable=False, default="pending")  # pending|done|failed
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
