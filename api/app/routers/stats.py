from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import case, func, select

from ..deps import CurrentUser, Db
from ..models import (
    Achievement,
    Conversation,
    ConversationTurn,
    Enrolment,
    ExerciseAttempt,
    LessonProgress,
    Scenario,
    SrsReview,
    UserVocab,
    VocabItem,
    XpEvent,
)
from ..services.course import course_map
from ..services.languages import level_index
from ..services.progress import ACHIEVEMENTS, daily_status, local_today
from ..services.srs import due_count, has_kanji

router = APIRouter(tags=["stats"])

REASON_LABELS = {"lesson": "Lessons", "test": "Tests", "review": "Reviews", "conversation": "Conversations",
                 "placement": "Placement"}


@router.get("/dashboard")
async def dashboard(user: CurrentUser, db: Db, lang: str | None = None) -> dict[str, Any]:
    enrolments = list(await db.scalars(select(Enrolment).where(Enrolment.user_id == user.id)
                                       .order_by(Enrolment.created_at)))
    if not enrolments:
        return {"daily": await daily_status(db, user), "enrolments": [], "language": None}
    lang = lang or (user.settings_json or {}).get("active_language") or enrolments[0].language_code
    enrolment = next((e for e in enrolments if e.language_code == lang), enrolments[0])
    lang = enrolment.language_code

    course = await course_map(db, user.id, enrolment)
    level = next((lv for lv in course["levels"] if lv["cefr"] == enrolment.current_level), None)
    reviews_due = await due_count(db, user, lang)

    scenarios = list(await db.scalars(select(Scenario).where(
        Scenario.unit_id.is_(None), (Scenario.language_code.is_(None)) | (Scenario.language_code == lang))))
    done_ids = set(await db.scalars(select(Conversation.scenario_id).where(
        Conversation.user_id == user.id, Conversation.language_code == lang, Conversation.scenario_id.is_not(None))))
    fitting = [s for s in scenarios if level_index(s.min_level) <= level_index(enrolment.current_level)]
    fitting.sort(key=lambda s: (s.id in done_ids, -level_index(s.min_level), s.id))
    suggestion = fitting[0] if fitting else None

    recent = await db.execute(
        select(XpEvent.reason, XpEvent.language_code, func.sum(XpEvent.amount), func.max(XpEvent.created_at),
               func.count())
        .where(XpEvent.user_id == user.id, XpEvent.created_at >= datetime.now(UTC) - timedelta(days=7))
        .group_by(XpEvent.reason, XpEvent.language_code, XpEvent.local_date)
        .order_by(func.max(XpEvent.created_at).desc()).limit(8))

    others = []
    for e in enrolments:
        words = await db.scalar(select(func.count()).select_from(UserVocab).join(
            VocabItem, VocabItem.id == UserVocab.vocab_item_id).where(
            UserVocab.user_id == user.id, VocabItem.language_code == e.language_code)) or 0
        others.append({"language_code": e.language_code, "current_level": e.current_level, "words": words})

    return {
        "language": lang,
        "daily": await daily_status(db, user),
        "next_lesson": course["next_lesson"],
        "kana_done": course["kana_done"],
        "level": {"cefr": enrolment.current_level, "completed": level["completed"] if level else 0,
                  "total": level["total"] if level else 0},
        "reviews_due": reviews_due,
        "suggested_scenario": {"id": suggestion.id, "title": suggestion.title, "emoji": suggestion.emoji,
                               "goal": suggestion.goal, "min_level": suggestion.min_level} if suggestion else None,
        "recent": [{"reason": r, "label": REASON_LABELS.get(r, r.title()), "language": lng, "xp": int(xp or 0),
                    "at": at.isoformat(), "count": n} for r, lng, xp, at, n in recent],
        "enrolments": others,
    }


@router.get("/stats/summary")
async def summary(user: CurrentUser, db: Db, lang: str | None = None) -> dict[str, Any]:
    def by_lang(q, col):
        return q.where(col == lang) if lang else q

    xp_total = await db.scalar(by_lang(select(func.coalesce(func.sum(XpEvent.amount), 0)).where(
        XpEvent.user_id == user.id), XpEvent.language_code)) or 0
    seconds = await db.scalar(by_lang(select(func.coalesce(func.sum(XpEvent.seconds), 0)).where(
        XpEvent.user_id == user.id), XpEvent.language_code)) or 0
    words_q = select(VocabItem.lemma).join(UserVocab, UserVocab.vocab_item_id == VocabItem.id).where(
        UserVocab.user_id == user.id)
    lemmas = list(await db.scalars(by_lang(words_q, VocabItem.language_code)))
    lessons = await db.scalar(select(func.count()).select_from(LessonProgress).where(
        LessonProgress.user_id == user.id, LessonProgress.status == "completed")) or 0
    convs = await db.scalar(by_lang(select(func.count()).select_from(Conversation).where(
        Conversation.user_id == user.id), Conversation.language_code)) or 0
    reviews = await db.scalar(select(func.count()).select_from(SrsReview).where(SrsReview.user_id == user.id)) or 0
    kanji = {ch for lemma in lemmas for ch in lemma if has_kanji(ch)} if lang in (None, "ja") else set()
    return {"xp_total": int(xp_total), "minutes_total": int(seconds) // 60, "words": len(lemmas),
            "kanji": len(kanji), "lessons": lessons, "conversations": convs, "reviews": reviews,
            "daily": await daily_status(db, user)}


@router.get("/stats/heatmap")
async def heatmap(user: CurrentUser, db: Db, days: int = 365) -> list[dict[str, Any]]:
    since = local_today(user) - timedelta(days=min(days, 400))
    rows = await db.execute(select(XpEvent.local_date, func.sum(XpEvent.amount), func.sum(XpEvent.seconds))
                            .where(XpEvent.user_id == user.id, XpEvent.local_date >= since)
                            .group_by(XpEvent.local_date))
    return [{"date": d.isoformat(), "xp": int(xp or 0), "minutes": int(s or 0) // 60} for d, xp, s in rows]


@router.get("/stats/charts")
async def charts(user: CurrentUser, db: Db, lang: str | None = None) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=120)
    week = func.date_trunc("week", ExerciseAttempt.created_at)
    acc = await db.execute(select(week, func.avg(case((ExerciseAttempt.is_correct, 1.0), else_=0.0)), func.count())
                           .where(ExerciseAttempt.user_id == user.id, ExerciseAttempt.created_at >= since)
                           .group_by(week).order_by(week))
    time_q = select(XpEvent.reason, func.sum(XpEvent.seconds)).where(XpEvent.user_id == user.id)
    if lang:
        time_q = time_q.where(XpEvent.language_code == lang)
    times = await db.execute(time_q.group_by(XpEvent.reason))
    conv_q = (select(Conversation.started_at, func.avg(ConversationTurn.score))
              .join(ConversationTurn, ConversationTurn.conversation_id == Conversation.id)
              .where(Conversation.user_id == user.id, ConversationTurn.score.is_not(None)))
    if lang:
        conv_q = conv_q.where(Conversation.language_code == lang)
    scores = await db.execute(conv_q.group_by(Conversation.id, Conversation.started_at)
                              .order_by(Conversation.started_at).limit(60))
    fb_q = (select(ConversationTurn.feedback_json).join(Conversation, Conversation.id == ConversationTurn.conversation_id)
            .where(Conversation.user_id == user.id, ConversationTurn.feedback_json.is_not(None)))
    if lang:
        fb_q = fb_q.where(Conversation.language_code == lang)
    error_types: dict[str, int] = {}
    for fb in await db.scalars(fb_q.order_by(ConversationTurn.id.desc()).limit(500)):
        for e in (fb or {}).get("errors", []):
            error_types[e.get("type", "grammar")] = error_types.get(e.get("type", "grammar"), 0) + 1
    return {
        "accuracy_weekly": [{"week": w.date().isoformat(), "accuracy": round(float(a or 0) * 100), "answers": n}
                            for w, a, n in acc],
        "time_by_activity": [{"activity": REASON_LABELS.get(r, r), "minutes": int(s or 0) // 60} for r, s in times],
        "conversation_scores": [{"date": d.date().isoformat(), "score": round(float(s))} for d, s in scores],
        "error_types": sorted(({"type": k, "count": v} for k, v in error_types.items()), key=lambda x: -x["count"]),
    }


@router.get("/achievements")
async def achievements(user: CurrentUser, db: Db) -> list[dict[str, Any]]:
    earned = {a.key: a.earned_at for a in await db.scalars(select(Achievement).where(Achievement.user_id == user.id))}
    return [{"key": k, **v, "earned_at": earned[k].isoformat() if k in earned else None}
            for k, v in ACHIEVEMENTS.items()]
