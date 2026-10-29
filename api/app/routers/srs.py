from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..deps import CurrentUser, Db
from ..models import SrsCard, Unit
from ..services.languages import CEFR
from ..services.progress import award_xp, check_achievements
from ..services.srs import (
    card_json,
    completed_lessons,
    ensure_kana_cards,
    forecast,
    level_summary,
    practice,
    practice_blocks,
    practice_from_lessons,
    practice_item,
    queue,
    review,
)

LEVEL_LABELS = {"PRE": "Kana", **{c: c for c in CEFR}}

router = APIRouter(prefix="/srs", tags=["srs"])


class ReviewIn(BaseModel):
    card_id: int
    rating: int = Field(ge=1, le=4)
    elapsed_ms: int = 0
    reviewed_at: datetime | None = None  # set when an offline review is replayed


class SessionIn(BaseModel):
    lang: str
    reviewed: int = Field(ge=0, le=1000)
    seconds: int = Field(ge=0, le=4 * 3600)


@router.get("/{lang}/queue")
async def get_queue(lang: str, user: CurrentUser, db: Db, mistakes: bool = False, limit: int = 50) -> dict[str, Any]:
    cards, counts = await queue(db, user, lang, limit=min(max(limit, 1), 200), mistakes_only=mistakes)
    return {"cards": [card_json(c) for c in cards], "counts": counts}


@router.get("/{lang}/stats")
async def deck_stats(lang: str, user: CurrentUser, db: Db) -> dict[str, Any]:
    if lang == "ja":
        await ensure_kana_cards(db, user.id)
    _, counts = await queue(db, user, lang, limit=0)
    total = await db.scalar(select(func.count()).select_from(SrsCard).where(
        SrsCard.user_id == user.id, SrsCard.language_code == lang)) or 0
    mistakes = await db.scalar(select(func.count()).select_from(SrsCard).where(
        SrsCard.user_id == user.id, SrsCard.language_code == lang, SrsCard.card_type == "mistake")) or 0
    return {"counts": counts, "total": total, "mistakes": mistakes, "forecast": await forecast(db, user, lang)}


@router.get("/{lang}/levels")
async def practice_levels(lang: str, user: CurrentUser, db: Db) -> list[dict[str, Any]]:
    """Everything learnt so far, grouped by level and unit, for "practise A1 / kana"."""
    if lang == "ja":
        await ensure_kana_cards(db, user.id)
    return [lv | {"label": LEVEL_LABELS.get(lv["level"], lv["level"])} for lv in await level_summary(db, user, lang)]


def _ids(csv: str | None, extra: int | None = None) -> list[int]:
    ids = [int(u) for u in (csv or "").split(",") if u.strip().isdigit()]
    return ids + ([extra] if extra else [])


def _joined(titles: list[str], noun: str) -> str:
    return " · ".join(titles) if len(titles) <= 2 else f"{len(titles)} {noun}"


async def _practice_cards(db, user, lang: str, *, level: str | None, units: str | None, unit_id: int | None,
                          lessons: str | None, order: str, limit: int, card_types: list[str] | None = None,
                          by_lesson: bool = False):
    """Resolve a practice selection (lesson blocks, units or a whole level) to cards and a title."""
    lesson_ids, unit_ids = _ids(lessons), _ids(units, unit_id)
    if not (level or unit_ids or lesson_ids):
        raise HTTPException(400, "Pick the blocks you want to practise")
    if lang == "ja":
        await ensure_kana_cards(db, user.id)
    limit = min(max(limit, 1), 100)
    if lesson_ids or by_lesson:
        chosen = await completed_lessons(db, user.id, lang, lesson_ids=lesson_ids, unit_ids=unit_ids, level=level)
        cards = await practice_from_lessons(db, user, lang, chosen, order=order, limit=limit, card_types=card_types)
        if lesson_ids:
            return cards, _joined([le.title for le in chosen], "blocks")
    else:
        cards = await practice(db, user, lang, level=level, unit_ids=unit_ids, order=order, limit=limit,
                               card_types=card_types)
    if not unit_ids:
        return cards, LEVEL_LABELS.get(level or "", level or "")
    titles = list(await db.scalars(select(Unit.title).where(Unit.id.in_(unit_ids)).order_by(Unit.order)))
    return cards, _joined(titles, "units")


@router.get("/{lang}/practice/blocks")
async def get_practice_blocks(lang: str, user: CurrentUser, db: Db) -> list[dict[str, Any]]:
    """Finished lessons from the course map, by level and unit, to pick for practice."""
    if lang == "ja":
        await ensure_kana_cards(db, user.id)
    return [lv | {"label": LEVEL_LABELS.get(lv["level"], lv["level"])} for lv in await practice_blocks(db, user, lang)]


@router.get("/{lang}/practice")
async def practice_session(lang: str, user: CurrentUser, db: Db, level: str | None = None, unit_id: int | None = None,
                           units: str | None = None, lessons: str | None = None, order: str = "shuffle",
                           limit: int = 30) -> dict[str, Any]:
    """Flashcards for lesson blocks ("lessons=12,13"), units ("units=3,4") or a level."""
    cards, title = await _practice_cards(db, user, lang, level=level, units=units, unit_id=unit_id, lessons=lessons,
                                         order=order, limit=limit)
    return {"cards": [card_json(c) for c in cards], "title": title,
            "counts": {"due": len(cards), "new": 0, "mistakes_new": 0}}


@router.get("/{lang}/practice/items")
async def practice_items(lang: str, user: CurrentUser, db: Db, level: str | None = None, unit_id: int | None = None,
                         units: str | None = None, lessons: str | None = None, order: str = "course",
                         limit: int = 20) -> dict[str, Any]:
    """Words (meaning → type the word) and kana (symbol → type the romaji) for typing practice."""
    cards, title = await _practice_cards(db, user, lang, level=level, units=units, unit_id=unit_id, lessons=lessons,
                                         order=order, limit=min(limit, 50), card_types=["produce", "kana"],
                                         by_lesson=True)
    return {"items": [practice_item(c) for c in cards], "title": title}


@router.post("/review")
async def post_review(body: ReviewIn, user: CurrentUser, db: Db) -> dict[str, Any]:
    card = await db.get(SrsCard, body.card_id)
    if card is None or card.user_id != user.id:
        raise HTTPException(404, "Card not found")
    when = body.reviewed_at
    if when is not None:
        when = when if when.tzinfo else when.replace(tzinfo=UTC)
        when = min(when, datetime.now(UTC))
    await review(db, user, card, body.rating, body.elapsed_ms, when)
    await db.commit()
    return card_json(card, with_preview=False)


@router.post("/session")
async def finish_session(body: SessionIn, user: CurrentUser, db: Db) -> dict[str, Any]:
    if body.reviewed == 0:
        return {"xp": 0}
    reward = await award_xp(db, user, body.lang, body.reviewed, "review", seconds=body.seconds)
    achievements = await check_achievements(db, user)
    await db.commit()
    return reward | {"achievements": achievements}


@router.post("/cards/{card_id}/suspend")
async def suspend(card_id: int, user: CurrentUser, db: Db) -> dict[str, bool]:
    card = await db.get(SrsCard, card_id)
    if card is None or card.user_id != user.id:
        raise HTTPException(404, "Card not found")
    card.suspended = True
    await db.commit()
    return {"ok": True}
