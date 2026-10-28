from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..deps import CurrentUser, Db
from ..models import SrsCard
from ..services.progress import award_xp, check_achievements
from ..services.srs import card_json, forecast, queue, review

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
    _, counts = await queue(db, user, lang, limit=0)
    total = await db.scalar(select(func.count()).select_from(SrsCard).where(
        SrsCard.user_id == user.id, SrsCard.language_code == lang)) or 0
    mistakes = await db.scalar(select(func.count()).select_from(SrsCard).where(
        SrsCard.user_id == user.id, SrsCard.language_code == lang, SrsCard.card_type == "mistake")) or 0
    return {"counts": counts, "total": total, "mistakes": mistakes, "forecast": await forecast(db, user, lang)}


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
