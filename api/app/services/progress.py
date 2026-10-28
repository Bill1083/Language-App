"""XP, daily goal, streaks (with weekly freeze) and achievements."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    Achievement,
    Conversation,
    LessonProgress,
    SrsReview,
    Streak,
    User,
    UserVocab,
    XpEvent,
)

XP = {"lesson": 10, "lesson_perfect": 5, "checkpoint": 20, "level_test": 50, "kana": 8, "review": 1,
      "conversation_turn": 2, "conversation_goal": 10, "placement": 10}

ACHIEVEMENTS: dict[str, dict[str, str]] = {
    "first_lesson": {"title": "First steps", "description": "Finish your first lesson", "icon": "🌱"},
    "perfect_lesson": {"title": "Flawless", "description": "Finish a lesson with 100% accuracy", "icon": "💎"},
    "first_conversation": {"title": "Ice breaker", "description": "Have your first AI conversation", "icon": "💬"},
    "conversations_25": {"title": "Chatterbox", "description": "Finish 25 conversations", "icon": "🗣️"},
    "goals_10": {"title": "Mission accomplished", "description": "Achieve 10 scenario goals", "icon": "🎯"},
    "first_review": {"title": "Memory lane", "description": "Do your first review session", "icon": "🧠"},
    "reviews_500": {"title": "Steel trap", "description": "Review 500 cards", "icon": "🗃️"},
    "streak_7": {"title": "Week warrior", "description": "Reach a 7-day streak", "icon": "🔥"},
    "streak_30": {"title": "Unstoppable", "description": "Reach a 30-day streak", "icon": "☄️"},
    "words_100": {"title": "Century", "description": "Learn 100 words", "icon": "📚"},
    "words_500": {"title": "Wordsmith", "description": "Learn 500 words", "icon": "🏛️"},
    "kana_hiragana": {"title": "Hiragana hero", "description": "Pass the hiragana test", "icon": "あ"},
    "kana_katakana": {"title": "Katakana master", "description": "Pass the katakana test", "icon": "ア"},
    **{f"level_{c.lower()}": {"title": f"Finished {c}", "description": f"Pass a {c} level test", "icon": "🏆"}
       for c in ("A1", "A2", "B1", "B2", "C1")},
}


def user_tz(user: User) -> ZoneInfo:
    try:
        return ZoneInfo((user.settings_json or {}).get("timezone") or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def local_today(user: User) -> date:
    return datetime.now(user_tz(user)).date()


def local_day_start_utc(user: User, day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=user_tz(user)).astimezone(UTC)


def iso_week(day: date) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def goal_settings(user: User) -> tuple[str, int]:
    s = user.settings_json or {}
    kind = s.get("daily_goal_type", "xp")
    value = int(s.get("daily_goal_value", 30 if kind == "xp" else 10))
    return kind, max(1, value)


async def get_streak(db: AsyncSession, user_id: int) -> Streak:
    streak = await db.get(Streak, user_id)
    if streak is None:
        streak = Streak(user_id=user_id, current=0, longest=0, freezes_available=1)
        db.add(streak)
        await db.flush()
    return streak


def apply_activity(streak: Streak, today: date) -> bool:
    """Update a streak for activity on `today`. Returns True if a freeze was spent."""
    week = iso_week(today)
    if streak.freeze_week != week:  # one freeze per week, refilled (not stacked)
        streak.freezes_available = 1
        streak.freeze_week = week
    last = streak.last_active_date
    used_freeze = False
    if last == today:
        return False
    if last == today - timedelta(days=1):
        streak.current += 1
    elif last == today - timedelta(days=2) and streak.freezes_available > 0:
        streak.freezes_available -= 1
        streak.current += 1
        used_freeze = True
    else:
        streak.current = 1
    streak.longest = max(streak.longest, streak.current)
    streak.last_active_date = today
    return used_freeze


def effective_streak(streak: Streak | None, today: date) -> int:
    """The streak as shown today: still alive if active today/yesterday, or rescuable by a freeze."""
    if streak is None or streak.last_active_date is None:
        return 0
    gap = (today - streak.last_active_date).days
    if gap <= 1:
        return streak.current
    if gap == 2 and (streak.freezes_available > 0 or streak.freeze_week != iso_week(today)):
        return streak.current
    return 0


async def today_totals(db: AsyncSession, user: User) -> tuple[int, int]:
    today = local_today(user)
    row = (await db.execute(
        select(func.coalesce(func.sum(XpEvent.amount), 0), func.coalesce(func.sum(XpEvent.seconds), 0))
        .where(XpEvent.user_id == user.id, XpEvent.local_date == today)
    )).one()
    return int(row[0]), int(row[1])


async def daily_status(db: AsyncSession, user: User) -> dict[str, Any]:
    xp, seconds = await today_totals(db, user)
    kind, value = goal_settings(user)
    streak = await db.get(Streak, user.id)
    today = local_today(user)
    done = xp if kind == "xp" else seconds // 60
    return {
        "xp_today": xp,
        "minutes_today": seconds // 60,
        "goal_type": kind,
        "goal_value": value,
        "goal_progress": min(1.0, done / value),
        "goal_met": done >= value,
        "streak": effective_streak(streak, today),
        "longest_streak": streak.longest if streak else 0,
        "freezes_available": (1 if not streak or streak.freeze_week != iso_week(today) else streak.freezes_available),
        "active_today": bool(streak and streak.last_active_date == today),
    }


async def award_xp(db: AsyncSession, user: User, lang: str | None, amount: int, reason: str,
                   seconds: int = 0) -> dict[str, Any]:
    today = local_today(user)
    before_xp, before_s = await today_totals(db, user)
    kind, value = goal_settings(user)
    db.add(XpEvent(user_id=user.id, language_code=lang, amount=amount, seconds=max(0, min(seconds, 3 * 3600)),
                   reason=reason, local_date=today))
    streak = await get_streak(db, user.id)
    used_freeze = apply_activity(streak, today)
    await db.flush()
    after_xp, after_s = before_xp + amount, before_s + seconds
    before = before_xp if kind == "xp" else before_s // 60
    after = after_xp if kind == "xp" else after_s // 60
    return {"xp": amount, "xp_today": after_xp, "goal_just_met": before < value <= after,
            "streak": streak.current, "used_freeze": used_freeze}


async def grant(db: AsyncSession, user_id: int, key: str) -> bool:
    result = await db.execute(
        insert(Achievement).values(user_id=user_id, key=key).on_conflict_do_nothing().returning(Achievement.key)
    )
    return result.scalar() is not None


async def check_achievements(db: AsyncSession, user: User) -> list[dict[str, str]]:
    have = set(await db.scalars(select(Achievement.key).where(Achievement.user_id == user.id)))
    earned: list[str] = []

    async def maybe(key: str, condition: bool) -> None:
        if key not in have and condition and await grant(db, user.id, key):
            earned.append(key)

    lessons_done = await db.scalar(select(func.count()).select_from(LessonProgress).where(
        LessonProgress.user_id == user.id, LessonProgress.status == "completed")) or 0
    perfect = await db.scalar(select(func.count()).select_from(LessonProgress).where(
        LessonProgress.user_id == user.id, LessonProgress.best_accuracy >= 0.999)) or 0
    convs = await db.scalar(select(func.count()).select_from(Conversation).where(
        Conversation.user_id == user.id, Conversation.ended_at.is_not(None))) or 0
    goals = await db.scalar(select(func.count()).select_from(Conversation).where(
        Conversation.user_id == user.id, Conversation.goal_achieved.is_(True))) or 0
    reviews = await db.scalar(select(func.count()).select_from(SrsReview).where(SrsReview.user_id == user.id)) or 0
    words = await db.scalar(select(func.count()).select_from(UserVocab).where(UserVocab.user_id == user.id)) or 0
    streak = await db.get(Streak, user.id)
    longest = streak.longest if streak else 0

    await maybe("first_lesson", lessons_done >= 1)
    await maybe("perfect_lesson", perfect >= 1)
    await maybe("first_conversation", convs >= 1)
    await maybe("conversations_25", convs >= 25)
    await maybe("goals_10", goals >= 10)
    await maybe("first_review", reviews >= 1)
    await maybe("reviews_500", reviews >= 500)
    await maybe("streak_7", longest >= 7)
    await maybe("streak_30", longest >= 30)
    await maybe("words_100", words >= 100)
    await maybe("words_500", words >= 500)
    return [{"key": k, **ACHIEVEMENTS[k]} for k in earned]


async def grant_and_describe(db: AsyncSession, user_id: int, key: str) -> list[dict[str, str]]:
    if key in ACHIEVEMENTS and await grant(db, user_id, key):
        return [{"key": key, **ACHIEVEMENTS[key]}]
    return []
