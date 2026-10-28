"""Data export: everything as JSON, vocabulary as CSV, review deck as Anki CSV."""

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..deps import CurrentUser, Db
from ..models import (
    Achievement,
    Conversation,
    Enrolment,
    Lesson,
    LessonProgress,
    SrsCard,
    Streak,
    UserVocab,
    VocabItem,
    XpEvent,
)
from ..services.text import strip_ruby

router = APIRouter(prefix="/export", tags=["export"])


def _download(content: str, filename: str, media: str) -> Response:
    return Response(content, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


async def _vocab_rows(db, user_id: int, lang: str | None):
    q = (select(VocabItem, UserVocab).join(UserVocab, UserVocab.vocab_item_id == VocabItem.id)
         .where(UserVocab.user_id == user_id).order_by(VocabItem.language_code, UserVocab.learned_at))
    if lang:
        q = q.where(VocabItem.language_code == lang)
    return list((await db.execute(q)).all())


@router.get("/json")
async def export_json(user: CurrentUser, db: Db) -> Response:
    progress = await db.execute(select(LessonProgress, Lesson.slug, Lesson.title)
                                .join(Lesson, Lesson.id == LessonProgress.lesson_id)
                                .where(LessonProgress.user_id == user.id))
    convs = await db.scalars(select(Conversation).where(Conversation.user_id == user.id)
                             .options(selectinload(Conversation.turns)).order_by(Conversation.started_at))
    cards = await db.scalars(select(SrsCard).where(SrsCard.user_id == user.id))
    streak = await db.get(Streak, user.id)
    data: dict[str, Any] = {
        "exported_at": datetime.now(UTC).isoformat(),
        "user": {"email": user.email, "display_name": user.display_name, "settings": user.settings_json},
        "enrolments": [{"language": e.language_code, "level": e.current_level, "placement": e.placement_result}
                       for e in await db.scalars(select(Enrolment).where(Enrolment.user_id == user.id))],
        "lesson_progress": [{"lesson": slug, "title": title, "status": p.status, "best_accuracy": p.best_accuracy,
                             "completed_at": p.completed_at, "attempts": p.attempts} for p, slug, title in progress],
        "vocabulary": [{"language": v.language_code, "word": v.lemma, "reading": v.reading, "meaning": v.meaning,
                        "gender": v.gender, "status": uv.status, "learned_at": uv.learned_at}
                       for v, uv in await _vocab_rows(db, user.id, None)],
        "review_cards": [{"language": c.language_code, "type": c.card_type, "front": c.front_json, "back": c.back_json,
                          "source": c.source, "due_at": c.due_at, "fsrs": c.fsrs_state_json} for c in cards],
        "conversations": [{
            "language": c.language_code, "mode": c.mode, "title": c.title, "level": c.level,
            "started_at": c.started_at, "ended_at": c.ended_at, "goal_achieved": c.goal_achieved,
            "summary": c.summary_json,
            "turns": [{"role": t.role, "text": t.text, "translation": t.translation, "feedback": t.feedback_json,
                       "created_at": t.created_at} for t in c.turns],
        } for c in convs],
        "xp_events": [{"language": x.language_code, "amount": x.amount, "reason": x.reason, "date": x.local_date,
                       "seconds": x.seconds} for x in await db.scalars(select(XpEvent).where(XpEvent.user_id == user.id))],
        "streak": {"current": streak.current, "longest": streak.longest} if streak else None,
        "achievements": [{"key": a.key, "earned_at": a.earned_at}
                         for a in await db.scalars(select(Achievement).where(Achievement.user_id == user.id))],
    }
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return _download(json.dumps(data, ensure_ascii=False, indent=1, default=str), f"parlo-export-{stamp}.json",
                     "application/json")


@router.get("/vocab.csv")
async def export_vocab(user: CurrentUser, db: Db, lang: str | None = None) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["language", "word", "reading", "meaning", "gender", "part_of_speech", "level", "example",
                "example_translation", "status", "learned_at"])
    for v, uv in await _vocab_rows(db, user.id, lang):
        w.writerow([v.language_code, v.lemma, v.reading or "", v.meaning, v.gender or "", v.pos or "", v.level or "",
                    strip_ruby(v.example or ""), v.example_translation or "", uv.status, uv.learned_at.date()])
    return _download("﻿" + buf.getvalue(), f"parlo-vocab-{lang or 'all'}.csv", "text/csv; charset=utf-8")


@router.get("/anki.csv")
async def export_anki(user: CurrentUser, db: Db, lang: str | None = None) -> Response:
    """Front;Back;Tags — import into Anki as "Basic" notes with ';' as the separator."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    for v, _uv in await _vocab_rows(db, user.id, lang):
        front = v.lemma + (f" ({v.reading})" if v.reading and v.reading != v.lemma else "")
        back = v.meaning + (f"<br><i>{strip_ruby(v.example)}</i>" if v.example else "")
        w.writerow([front, back, f"parlo {v.language_code} {v.level or ''}".strip()])
    mistakes = await db.scalars(select(SrsCard).where(SrsCard.user_id == user.id, SrsCard.card_type == "mistake",
                                                      *([SrsCard.language_code == lang] if lang else [])))
    for c in mistakes:
        w.writerow([c.front_json.get("prompt", ""), strip_ruby(c.back_json.get("answer", "")) +
                    (f"<br>{c.back_json['explanation']}" if c.back_json.get("explanation") else ""),
                    f"parlo {c.language_code} mistake"])
    return _download(buf.getvalue(), f"parlo-anki-{lang or 'all'}.csv", "text/csv; charset=utf-8")
