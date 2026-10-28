"""Background job bodies (run by the arq worker) and the enqueue helper the API uses."""

import json
import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..db import SessionLocal
from ..models import (
    Conversation,
    ConversationTurn,
    Enrolment,
    Exercise,
    Lesson,
    Level,
    PushSubscription,
    Recording,
    Scenario,
    Streak,
    Unit,
    User,
)
from ..providers.base import ChatMessage, ProviderError
from ..redis_client import get_redis
from . import conversation as convsvc
from .ai import AIService, BudgetExceeded
from .audio_cache import tts_key
from .course import course_map, upcoming_lessons
from .lesson_gen import generate_lesson
from .progress import award_xp, check_achievements, local_today, user_tz
from .text import has_japanese

log = logging.getLogger("parlo.jobs")
_pool: ArqRedis | None = None
JOB_LOG = "parlo:job_log"


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def enqueue(name: str, *args: Any, job_id: str | None = None, **kwargs: Any) -> None:
    """Enqueue a worker job. `job_id` de-duplicates bursts: arq refuses a job id
    that is queued or has a stored result, so ids carry a one-minute bucket to
    allow the same job again later (e.g. a retry after a failed generation)."""
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
    if job_id:
        job_id = f"{job_id}:{int(time.time() // 60)}"
    await _pool.enqueue_job(name, *args, _job_id=job_id, **kwargs)


async def job_log(event: str, **data: Any) -> None:
    redis = get_redis()
    await redis.lpush(JOB_LOG, json.dumps({"at": datetime.now(UTC).isoformat(), "event": event, **data}))
    await redis.ltrim(JOB_LOG, 0, 99)


async def publish(conversation_id: int, payload: dict[str, Any]) -> None:
    await get_redis().publish(f"conv:{conversation_id}", json.dumps(payload, ensure_ascii=False, default=str))


# --------------------------------------------------------------------------- lessons


async def run_generate_lesson(lesson_id: int, force: bool = False, user_id: int | None = None) -> str:
    async with SessionLocal() as db:
        try:
            lesson = await generate_lesson(db, lesson_id, AIService(db, user_id=None), force=force)
            await job_log("lesson_generated", lesson_id=lesson_id, slug=lesson.slug)
        except Exception as e:
            await job_log("lesson_failed", lesson_id=lesson_id, error=str(e)[:300])
            raise
    await enqueue("precache_lesson_audio", lesson_id, job_id=f"audio-{lesson_id}")
    return "ok"


def lesson_audio_texts(exercises: list[dict[str, Any]], lang: str) -> list[str]:
    texts: list[str] = []
    for ex in exercises:
        t = ex["type"]
        if t == "vocab_intro":
            texts += [ex["vocab"].get("word", ""), ex["vocab"].get("example") or ""]
        elif t == "grammar_note":
            texts += [e["target"] for e in ex["grammar"].get("examples", [])]
        elif t == "kana_intro":
            texts.append(ex["char"])
        elif t == "listening_choice":
            texts.append(ex["audio_text"])
            if ex.get("options_lang") == "target":
                texts += ex["options"]
        elif t in ("dictation", "speak"):
            texts.append(ex["text"])
        elif t == "word_bank":
            texts.append(ex["answer"])
        elif t == "multiple_choice" and ex.get("question_lang") == "target":
            texts.append(ex["question"])
        elif t == "translate" and ex.get("direction") == "to_english":
            texts.append(ex["source"])
        elif t == "fill_blank":
            texts.append(ex["sentence"].replace("___", ex["answers"][0]))
    seen, out = set(), []
    for x in texts:
        x = (x or "").strip()
        if x and x not in seen and (lang != "ja" or has_japanese(x)):
            seen.add(x)
            out.append(x)
    return out


async def run_precache_lesson_audio(lesson_id: int) -> int:
    count = 0
    async with SessionLocal() as db:
        lesson = await db.scalar(select(Lesson).where(Lesson.id == lesson_id).options(
            selectinload(Lesson.unit).selectinload(Unit.level)))
        if lesson is None or lesson.status != "ready":
            return 0
        exercises = list(await db.scalars(select(Exercise.payload_json).where(Exercise.lesson_id == lesson_id)))
        lang = lesson.unit.level.language_code
        ai = AIService(db)
        for text in lesson_audio_texts(exercises, lang):
            try:
                await tts_key(ai, text, lang, purpose="lesson")
                count += 1
            except (ProviderError, ValueError) as e:
                log.warning("precache %s failed: %s", lesson_id, e)
                if isinstance(e, ProviderError) and not e.retryable:
                    break
    await job_log("audio_cached", lesson_id=lesson_id, clips=count)
    return count


async def run_pregenerate(user_id: int, lang: str) -> list[int]:
    async with SessionLocal() as db:
        enrolment = await db.get(Enrolment, (user_id, lang))
        if enrolment is None:
            return []
        course = await course_map(db, user_id, enrolment)
        ids = upcoming_lessons(course, get_settings().pregenerate_ahead)
        if ids:
            await db.execute(update(Lesson).where(Lesson.id.in_(ids), Lesson.status == "pending")
                             .values(status="queued"))
            await db.commit()
    for lid in ids:
        await enqueue("generate_lesson", lid, job_id=f"lesson-{lid}")
    return ids


# --------------------------------------------------------------------------- conversations


async def run_feedback(turn_id: int) -> None:
    async with SessionLocal() as db:
        turn = await db.get(ConversationTurn, turn_id)
        if turn is None or turn.role != "user":
            return
        conv = await db.scalar(select(Conversation).where(Conversation.id == turn.conversation_id))
        assert conv is not None
        user = await db.get(User, conv.user_id)
        assert user is not None
        scenario = await db.get(Scenario, conv.scenario_id) if conv.scenario_id else None
        turns = list(await db.scalars(select(ConversationTurn).where(
            ConversationTurn.conversation_id == conv.id).order_by(ConversationTurn.id)))
        voice = bool(turn.audio_key or (turn.stt_json or {}).get("provider"))
        ai = AIService(db, user.id, user.role == "admin")
        try:
            feedback = await ai.llm_json(
                "feedback", "feedback", convsvc.Feedback,
                system=convsvc.feedback_system(conv, scenario, voice),
                messages=[ChatMessage("user", convsvc.feedback_request(turns, turn))],
                temperature=0.2, max_tokens=2000,
            )
        except (ProviderError, BudgetExceeded) as e:
            await publish(conv.id, {"type": "feedback_error", "turn_id": turn.id, "message": str(e)})
            return
        await store_feedback(db, conv, turn, feedback.model_dump(), user)


async def store_feedback(db, conv: Conversation, turn: ConversationTurn, feedback: dict[str, Any], user: User) -> None:
    stt = dict(turn.stt_json or {})
    if stt.get("provider"):
        stt["pronunciation"] = convsvc.pronunciation_flags(
            turn.text, feedback.get("corrected") or turn.text, conv.language_code,
            [e.get("original", "") for e in feedback.get("errors", [])], stt.get("words"),
        )
        turn.stt_json = stt
    turn.feedback_json = feedback
    turn.score = feedback.get("score")
    newly_achieved = bool(feedback.get("goal_achieved")) and not conv.goal_achieved
    if newly_achieved:
        conv.goal_achieved = True
        await award_xp(db, user, conv.language_code, 10, "conversation")
    await db.commit()
    await publish(conv.id, {"type": "feedback", "turn_id": turn.id, "feedback": feedback,
                            "pronunciation": stt.get("pronunciation") or [],
                            "pronunciation_notes": stt.get("pronunciation_notes") or []})
    if newly_achieved:
        await publish(conv.id, {"type": "goal", "achieved": True})


async def run_summary(conversation_id: int) -> None:
    async with SessionLocal() as db:
        conv = await db.scalar(select(Conversation).where(Conversation.id == conversation_id)
                               .options(selectinload(Conversation.turns)))
        if conv is None:
            return
        user = await db.get(User, conv.user_id)
        assert user is not None
        user_turns = [t for t in conv.turns if t.role == "user"]
        scores = [t.score for t in user_turns if t.score is not None]
        ended = conv.ended_at or datetime.now(UTC)
        errors = [e | {"message": t.text} for t in user_turns for e in (t.feedback_json or {}).get("errors", [])]
        vocab: dict[str, dict[str, Any]] = {}
        for t in user_turns:
            for v in (t.feedback_json or {}).get("new_vocab", []):
                vocab.setdefault(v["word"], v)
        error_types: dict[str, int] = {}
        for e in errors:
            error_types[e.get("type", "grammar")] = error_types.get(e.get("type", "grammar"), 0) + 1
        summary: dict[str, Any] = {
            "duration_s": int((ended - conv.started_at).total_seconds()),
            "turns": len(user_turns),
            "avg_score": round(sum(scores) / len(scores)) if scores else None,
            "goal_achieved": conv.goal_achieved,
            "new_vocab": list(vocab.values())[:20],
            "error_types": error_types,
            "top_mistakes": [], "suggested_lessons": [], "suggested_drill": None, "encouragement": "",
        }
        if user_turns:
            lessons = await _lesson_menu(db, conv.language_code, conv.level)
            ai = AIService(db, user.id, user.role == "admin")
            try:
                draft = await ai.llm_json(
                    "summary", "feedback", convsvc.SummaryDraft,
                    system=convsvc.summary_system(conv.language_code, lessons),
                    messages=[ChatMessage("user", json.dumps(
                        {"messages": [t.text for t in user_turns], "errors": errors[:40]}, ensure_ascii=False))],
                    temperature=0.3, max_tokens=1500,
                )
                valid_ids = {le["id"] for le in lessons}
                summary.update(draft.model_dump())
                summary["suggested_lessons"] = [
                    le for le in lessons if le["id"] in set(draft.suggested_lessons) & valid_ids]
            except (ProviderError, BudgetExceeded) as e:
                summary["error"] = str(e)
        conv.summary_json = summary
        await db.commit()
        await publish(conv.id, {"type": "summary", "summary": summary})


async def _lesson_menu(db, lang: str, cefr: str) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(Lesson.id, Lesson.title, Unit.title, Level.cefr).join(Unit, Lesson.unit_id == Unit.id)
        .join(Level, Unit.level_id == Level.id)
        .where(Level.language_code == lang, Lesson.kind == "lesson", Level.cefr.in_(_near_levels(cefr)))
        .order_by(Level.order, Unit.order, Lesson.order))
    return [{"id": i, "title": t, "unit": u, "level": c} for i, t, u, c in rows]


def _near_levels(cefr: str) -> list[str]:
    order = ["A1", "A2", "B1", "B2", "C1"]
    i = order.index(cefr) if cefr in order else 0
    return order[max(0, i - 1): i + 1]


# --------------------------------------------------------------------------- housekeeping


async def run_cleanup_recordings() -> int:
    days = get_settings().recording_retention_days
    cutoff = datetime.now(UTC) - timedelta(days=days)
    removed = 0
    async with SessionLocal() as db:
        rows = list(await db.scalars(select(Recording).where(Recording.created_at < cutoff,
                                                             Recording.path.is_not(None))))
        for rec in rows:
            try:
                Path(rec.path).unlink(missing_ok=True)  # type: ignore[arg-type]
            except OSError:
                pass
            rec.path = None
            removed += 1
        await db.commit()
    await job_log("recordings_cleanup", removed=removed, retention_days=days)
    return removed


async def run_push_reminders() -> int:
    from .push import send_push  # local import: pywebpush is only needed here

    sent = 0
    async with SessionLocal() as db:
        subs = list(await db.scalars(select(PushSubscription)))
        users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_({s.user_id for s in subs} or {0})))}
        for sub in subs:
            user = users.get(sub.user_id)
            if not user or not (user.settings_json or {}).get("reminders", True):
                continue
            now_local = datetime.now(user_tz(user))
            hour = int((user.settings_json or {}).get("reminder_hour", 19))
            today = local_today(user)
            if now_local.hour != hour or sub.last_sent_date == today:
                continue
            streak = await db.get(Streak, user.id)
            if streak and streak.last_active_date == today:
                continue
            body = (f"Keep your {streak.current}-day streak going — a 5-minute lesson is enough."
                    if streak and streak.current else "A few minutes of practice today? Your lessons are waiting.")
            ok = await send_push(db, sub, {"title": "Time to practise 🌟", "body": body, "url": "/"})
            sub.last_sent_date = today
            sent += ok
        await db.commit()
    return sent


async def finish_conversation_rewards(conversation_id: int) -> dict[str, Any]:
    async with SessionLocal() as db:
        conv = await db.scalar(select(Conversation).where(Conversation.id == conversation_id)
                               .options(selectinload(Conversation.turns)))
        if conv is None:
            return {}
        user = await db.get(User, conv.user_id)
        assert user is not None
        n = sum(1 for t in conv.turns if t.role == "user")
        seconds = int(((conv.ended_at or datetime.now(UTC)) - conv.started_at).total_seconds())
        result = await award_xp(db, user, conv.language_code, n * 2, "conversation", seconds=min(seconds, 3600)) \
            if n else {}
        await check_achievements(db, user)
        await db.commit()
        return result
