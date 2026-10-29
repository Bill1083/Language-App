"""Database schema. Mirrors Section 10 of the spec, plus the few tables the
implementation needs on top (sessions, runtime settings, caches, push)."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

Json = dict[str, Any]


def _now_col() -> Any:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# --------------------------------------------------------------------------- users & auth


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(16), default="user")  # admin | user
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    settings_json: Mapped[Json] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _now_col()
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of the cookie token
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = _now_col()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(300))


class Invite(Base):
    __tablename__ = "invites"
    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = _now_col()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppSetting(Base):
    """Admin overrides of `.env` defaults (providers, models, voices, keys, pricing)."""

    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value_json: Mapped[Any] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# --------------------------------------------------------------------------- languages & course


class Language(Base):
    __tablename__ = "languages"
    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Enrolment(Base):
    __tablename__ = "enrolments"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    language_code: Mapped[str] = mapped_column(ForeignKey("languages.code"), primary_key=True)
    current_level: Mapped[str] = mapped_column(String(4), default="A1")
    placement_result: Mapped[Json | None] = mapped_column(JSONB)
    daily_goal: Mapped[int] = mapped_column(Integer, default=30)
    settings_json: Mapped[Json] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _now_col()
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Level(Base):
    __tablename__ = "levels"
    __table_args__ = (UniqueConstraint("language_code", "cefr"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    language_code: Mapped[str] = mapped_column(ForeignKey("languages.code"))
    cefr: Mapped[str] = mapped_column(String(8))  # PRE (Japanese writing systems), A1..C1
    order: Mapped[int] = mapped_column(Integer)
    units: Mapped[list["Unit"]] = relationship(back_populates="level", order_by="Unit.order")


class Unit(Base):
    __tablename__ = "units"
    id: Mapped[int] = mapped_column(primary_key=True)
    level_id: Mapped[int] = mapped_column(ForeignKey("levels.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    order: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(120))
    theme: Mapped[str] = mapped_column(String(60))
    objectives_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    level: Mapped[Level] = relationship(back_populates="units")
    lessons: Mapped[list["Lesson"]] = relationship(back_populates="unit", order_by="Lesson.order")


class Lesson(Base):
    __tablename__ = "lessons"
    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(48), unique=True)
    order: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16), default="lesson")  # lesson | checkpoint | level_test | kana
    title: Mapped[str] = mapped_column(String(160))
    skeleton_json: Mapped[Json] = mapped_column(JSONB, default=dict)
    skeleton_hash: Mapped[str] = mapped_column(String(64), default="")
    content_json: Mapped[Json | None] = mapped_column(JSONB)
    # pending | queued | generating | ready | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model_used: Mapped[str | None] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer, default=0)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    unit: Mapped[Unit] = relationship(back_populates="lessons")
    exercises: Mapped[list["Exercise"]] = relationship(
        back_populates="lesson", order_by="Exercise.order", cascade="all, delete-orphan"
    )


class Exercise(Base):
    __tablename__ = "exercises"
    id: Mapped[int] = mapped_column(primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), index=True)
    order: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(24))
    payload_json: Mapped[Json] = mapped_column(JSONB)
    lesson: Mapped[Lesson] = relationship(back_populates="exercises")


class PlacementBank(Base):
    __tablename__ = "placement_banks"
    language_code: Mapped[str] = mapped_column(ForeignKey("languages.code"), primary_key=True)
    items_json: Mapped[list[Json]] = mapped_column(JSONB)
    generated_at: Mapped[datetime] = _now_col()
    model_used: Mapped[str | None] = mapped_column(String(120))


class LessonProgress(Base):
    __tablename__ = "lesson_progress"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="started")  # started | completed
    best_accuracy: Mapped[float] = mapped_column(Float, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class ExerciseAttempt(Base):
    __tablename__ = "exercise_attempts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # SET NULL: regenerating a lesson replaces its exercises but keeps answer history (accuracy stats)
    exercise_id: Mapped[int | None] = mapped_column(ForeignKey("exercises.id", ondelete="SET NULL"), index=True)
    answer: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    verdict: Mapped[str] = mapped_column(String(16))  # correct | typo | accent | ai_accepted | wrong
    created_at: Mapped[datetime] = _now_col()


class LlmJudgement(Base):
    """Cache of "is this free translation a valid alternative?" answers."""

    __tablename__ = "llm_judgements"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _now_col()


# --------------------------------------------------------------------------- vocab & SRS


class VocabItem(Base):
    __tablename__ = "vocab_items"
    __table_args__ = (UniqueConstraint("language_code", "lemma", "meaning", name="uq_vocab_lemma_meaning"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    language_code: Mapped[str] = mapped_column(ForeignKey("languages.code"), index=True)
    lemma: Mapped[str] = mapped_column(String(160))
    reading: Mapped[str | None] = mapped_column(String(160))
    meaning: Mapped[str] = mapped_column(String(300))
    pos: Mapped[str | None] = mapped_column(String(32))
    gender: Mapped[str | None] = mapped_column(String(8))
    level: Mapped[str | None] = mapped_column(String(4))
    example: Mapped[str | None] = mapped_column(Text)
    example_translation: Mapped[str | None] = mapped_column(Text)
    extra_json: Mapped[Json] = mapped_column(JSONB, default=dict)
    audio_key: Mapped[str | None] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(16), default="lesson")  # lesson | conversation | custom
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"))
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("lessons.id", ondelete="SET NULL"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class UserVocab(Base):
    __tablename__ = "user_vocab"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    vocab_item_id: Mapped[int] = mapped_column(ForeignKey("vocab_items.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="learning")  # learning | known
    learned_at: Mapped[datetime] = _now_col()


class SrsCard(Base):
    __tablename__ = "srs_cards"
    __table_args__ = (
        Index("ix_srs_due", "user_id", "language_code", "due_at"),
        Index("ix_srs_level", "user_id", "language_code", "level"),
        Index("uq_srs_vocab_card", "user_id", "vocab_item_id", "card_type", unique=True,
              postgresql_where="vocab_item_id IS NOT NULL"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    language_code: Mapped[str] = mapped_column(ForeignKey("languages.code"))
    # recognize (target->EN) | produce (EN->target typed) | listen (audio->meaning) | kanji (kanji->reading)
    # | mistake (fix-the-error card)
    card_type: Mapped[str] = mapped_column(String(16))
    front_json: Mapped[Json] = mapped_column(JSONB)
    back_json: Mapped[Json] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(16))  # lesson | mistake | conversation | manual
    source_ref: Mapped[str | None] = mapped_column(String(80))
    vocab_item_id: Mapped[int | None] = mapped_column(ForeignKey("vocab_items.id", ondelete="CASCADE"))
    # Where the card's content was taught, for "practise A1 / this unit / kana"
    level: Mapped[str | None] = mapped_column(String(8))
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"), index=True)
    fsrs_state_json: Mapped[Json] = mapped_column(JSONB, default=dict)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _now_col()


class SrsReview(Base):
    __tablename__ = "srs_reviews"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("srs_cards.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    reviewed_at: Mapped[datetime] = _now_col()
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------- conversations


class Scenario(Base):
    __tablename__ = "scenarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    language_code: Mapped[str | None] = mapped_column(ForeignKey("languages.code"))  # NULL = every language
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(120))
    emoji: Mapped[str] = mapped_column(String(16), default="💬")
    description: Mapped[str] = mapped_column(Text)
    goal: Mapped[str] = mapped_column(Text)
    ai_role: Mapped[str] = mapped_column(String(200))
    user_role: Mapped[str] = mapped_column(String(200))
    min_level: Mapped[str] = mapped_column(String(4), default="A1")
    system_prompt_template: Mapped[str] = mapped_column(Text, default="")


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    language_code: Mapped[str] = mapped_column(ForeignKey("languages.code"))
    mode: Mapped[str] = mapped_column(String(16))  # scenario | free | unit | tutor
    scenario_id: Mapped[int | None] = mapped_column(ForeignKey("scenarios.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(160), default="")
    level: Mapped[str] = mapped_column(String(4))
    settings_json: Mapped[Json] = mapped_column(JSONB, default=dict)
    goal_achieved: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = _now_col()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary_json: Mapped[Json | None] = mapped_column(JSONB)
    turns: Mapped[list["ConversationTurn"]] = relationship(
        back_populates="conversation", order_by="ConversationTurn.id", cascade="all, delete-orphan"
    )


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(12))  # user | assistant
    text: Mapped[str] = mapped_column(Text)
    translation: Mapped[str | None] = mapped_column(Text)
    audio_key: Mapped[str | None] = mapped_column(String(80))  # user recording id
    audio_keys_json: Mapped[list[str] | None] = mapped_column(JSONB)  # AI reply audio, one per sentence
    stt_json: Mapped[Json | None] = mapped_column(JSONB)
    feedback_json: Mapped[Json | None] = mapped_column(JSONB)
    score: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _now_col()
    conversation: Mapped[Conversation] = relationship(back_populates="turns")


class Recording(Base):
    __tablename__ = "recordings"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    path: Mapped[str | None] = mapped_column(String(300))  # NULL once deleted / not stored
    mime: Mapped[str] = mapped_column(String(60))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = _now_col()


# --------------------------------------------------------------------------- motivation


class Streak(Base):
    __tablename__ = "streaks"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    current: Mapped[int] = mapped_column(Integer, default=0)
    longest: Mapped[int] = mapped_column(Integer, default=0)
    last_active_date: Mapped[date | None] = mapped_column(Date)
    freezes_available: Mapped[int] = mapped_column(Integer, default=1)
    freeze_week: Mapped[str | None] = mapped_column(String(10))  # ISO week the freeze was last granted


class XpEvent(Base):
    __tablename__ = "xp_events"
    __table_args__ = (Index("ix_xp_user_created", "user_id", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    language_code: Mapped[str | None] = mapped_column(String(8))
    amount: Mapped[int] = mapped_column(Integer)
    seconds: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(24))  # lesson | review | conversation | placement | test
    local_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = _now_col()


class Achievement(Base):
    __tablename__ = "achievements"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    earned_at: Mapped[datetime] = _now_col()


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = _now_col()
    last_sent_date: Mapped[date | None] = mapped_column(Date)


# --------------------------------------------------------------------------- ops


class AiUsage(Base):
    __tablename__ = "ai_usage"
    __table_args__ = (Index("ix_ai_usage_user_created", "user_id", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    task: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(120))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    audio_seconds: Mapped[float] = mapped_column(Float, default=0)
    chars: Mapped[int] = mapped_column(Integer, default=0)
    est_cost: Mapped[float] = mapped_column(Float, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _now_col()


class ContentFlag(Base):
    __tablename__ = "content_flags"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    target_type: Mapped[str] = mapped_column(String(24))  # lesson | exercise | vocab | turn
    target_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | resolved | dismissed
    created_at: Mapped[datetime] = _now_col()


class AudioCache(Base):
    __tablename__ = "audio_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    path: Mapped[str] = mapped_column(String(300))
    lang: Mapped[str] = mapped_column(String(8))
    voice: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(24))
    chars: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _now_col()
