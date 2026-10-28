"""Review deck: card creation from lessons, mistakes and conversations, the
daily queue (due cards + capped new cards) and FSRS reviews."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import SrsCard, SrsReview, User, UserVocab, VocabItem
from .fsrs import CardState, Scheduler, format_interval
from .progress import local_day_start_utc, local_today
from .text import has_japanese

scheduler = Scheduler()

KANJI_RANGE = ("一", "鿿")


def has_kanji(text: str) -> bool:
    return any(KANJI_RANGE[0] <= ch <= KANJI_RANGE[1] for ch in text)


def vocab_display(v: VocabItem) -> str:
    return (v.extra_json or {}).get("ruby") or v.lemma


def vocab_card_payloads(v: VocabItem) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    shown = vocab_display(v)
    back = {"meaning": v.meaning, "reading": v.reading, "gender": v.gender, "pos": v.pos,
            "example": v.example, "example_translation": v.example_translation, "text": shown}
    cards = [
        ("recognize", {"text": shown, "audio_text": v.lemma}, back),
        ("produce", {"prompt": v.meaning, "pos": v.pos, "gender": v.gender},
         {"answer": shown, "accepted": [a for a in (v.lemma, v.reading) if a], "audio_text": v.lemma,
          "example": v.example, "example_translation": v.example_translation}),
        ("listen", {"audio_text": v.lemma}, back),
    ]
    if v.language_code == "ja" and has_kanji(v.lemma):
        cards.append(("kanji", {"text": v.lemma}, {"reading": v.reading, "meaning": v.meaning, "text": shown}))
    return cards


async def learn_vocab(db: AsyncSession, user_id: int, vocab: VocabItem, source: str, source_ref: str | None) -> bool:
    """Mark a word as learned and create its review cards. Returns True if it was new to the user."""
    res = await db.execute(
        insert(UserVocab).values(user_id=user_id, vocab_item_id=vocab.id, status="learning")
        .on_conflict_do_nothing().returning(UserVocab.vocab_item_id)
    )
    is_new = res.scalar() is not None
    for card_type, front, back in vocab_card_payloads(vocab):
        await db.execute(
            insert(SrsCard).values(
                user_id=user_id, language_code=vocab.language_code, card_type=card_type, front_json=front,
                back_json=back, source=source, source_ref=source_ref, vocab_item_id=vocab.id, fsrs_state_json={},
                due_at=datetime.now(UTC),
            ).on_conflict_do_nothing(index_elements=["user_id", "vocab_item_id", "card_type"],
                                     index_where=SrsCard.vocab_item_id.is_not(None))
        )
    return is_new


async def add_mistake_card(db: AsyncSession, user_id: int, lang: str, *, prompt: str, answer: str,
                           explanation: str | None, source: str, source_ref: str, context: str | None = None,
                           wrong: str | None = None) -> SrsCard:
    existing = await db.scalar(select(SrsCard).where(
        SrsCard.user_id == user_id, SrsCard.card_type == "mistake", SrsCard.source_ref == source_ref))
    if existing:
        existing.due_at = min(existing.due_at, datetime.now(UTC))
        return existing
    card = SrsCard(
        user_id=user_id, language_code=lang, card_type="mistake", source=source, source_ref=source_ref,
        front_json={"prompt": prompt, "context": context, "wrong": wrong},
        back_json={"answer": answer, "explanation": explanation, "audio_text": answer if answer and (
            lang != "ja" or has_japanese(answer)) else None},
        fsrs_state_json={}, due_at=datetime.now(UTC),
    )
    db.add(card)
    await db.flush()
    return card


def _is_new(card: SrsCard) -> bool:
    return not (card.fsrs_state_json or {}).get("reps")


async def queue(db: AsyncSession, user: User, lang: str, *, limit: int = 50, mistakes_only: bool = False
                ) -> tuple[list[SrsCard], dict[str, int]]:
    now = datetime.now(UTC)
    new_limit = int((user.settings_json or {}).get("new_cards_per_day", 15))
    today = local_today(user).isoformat()
    introduced = await db.scalar(select(func.count()).select_from(SrsCard).where(
        SrsCard.user_id == user.id, SrsCard.language_code == lang,
        SrsCard.fsrs_state_json["introduced_on"].astext == today)) or 0
    new_allowed = max(0, new_limit - introduced)

    base = [SrsCard.user_id == user.id, SrsCard.language_code == lang, SrsCard.suspended.is_(False)]
    if mistakes_only:
        base.append(SrsCard.card_type == "mistake")
    started = SrsCard.fsrs_state_json["reps"].isnot(None)
    due_filter = and_(*base, started, SrsCard.due_at <= now)
    new_filter = and_(*base, ~started)

    due_count = await db.scalar(select(func.count()).select_from(SrsCard).where(due_filter)) or 0
    new_mistakes = await db.scalar(select(func.count()).select_from(SrsCard).where(
        new_filter, SrsCard.card_type == "mistake")) or 0
    new_vocab = await db.scalar(select(func.count()).select_from(SrsCard).where(
        new_filter, SrsCard.card_type != "mistake")) or 0
    due = list(await db.scalars(select(SrsCard).where(due_filter).order_by(SrsCard.due_at).limit(limit)))
    room = max(0, limit - len(due))
    # New mistake cards are never capped; new vocab cards are, recognition before production.
    fresh = list(await db.scalars(
        select(SrsCard).where(new_filter, SrsCard.card_type == "mistake").order_by(SrsCard.id).limit(room)))
    vocab_cap = min(room - len(fresh), new_allowed) if not mistakes_only else 0
    if vocab_cap > 0:
        priority = case((SrsCard.card_type == "recognize", 0), (SrsCard.card_type == "produce", 2), else_=1)
        fresh += list(await db.scalars(
            select(SrsCard).where(new_filter, SrsCard.card_type != "mistake")
            .order_by(priority, SrsCard.created_at, SrsCard.id).limit(vocab_cap)))
    new_available = new_mistakes + (0 if mistakes_only else min(new_vocab, new_allowed))
    counts = {"due": due_count, "new": new_available, "new_vocab_total": new_vocab, "mistakes_new": new_mistakes}
    return due + fresh, counts


async def due_count(db: AsyncSession, user: User, lang: str) -> int:
    _cards, counts = await queue(db, user, lang, limit=0)
    return counts["due"] + counts["new"]


def card_json(card: SrsCard, with_preview: bool = True) -> dict[str, Any]:
    state = CardState.from_json(card.fsrs_state_json)
    out = {
        "id": card.id, "card_type": card.card_type, "front": card.front_json, "back": card.back_json,
        "source": card.source, "language": card.language_code, "is_new": _is_new(card),
        "due_at": card.due_at.isoformat(), "reps": state.reps, "lapses": state.lapses,
    }
    if with_preview:
        out["intervals"] = {str(k): format_interval(v) for k, v in scheduler.preview(state).items()}
    return out


async def review(db: AsyncSession, user: User, card: SrsCard, rating: int, elapsed_ms: int = 0,
                 reviewed_at: datetime | None = None) -> SrsCard:
    now = reviewed_at or datetime.now(UTC)
    state = CardState.from_json(card.fsrs_state_json)
    new_state = scheduler.review(state, rating, now)
    data = new_state.to_json()
    data["introduced_on"] = (card.fsrs_state_json or {}).get("introduced_on") or local_today(user).isoformat()
    card.fsrs_state_json = data
    card.due_at = new_state.due or now
    db.add(SrsReview(card_id=card.id, user_id=user.id, rating=rating, elapsed_ms=max(0, min(elapsed_ms, 600000)),
                     reviewed_at=now))
    if card.vocab_item_id and new_state.stability and new_state.stability >= 21:
        uv = await db.get(UserVocab, (user.id, card.vocab_item_id))
        if uv:
            uv.status = "known"
    return card


async def reviews_today(db: AsyncSession, user: User) -> int:
    start = local_day_start_utc(user, local_today(user))
    return await db.scalar(select(func.count()).select_from(SrsReview).where(
        SrsReview.user_id == user.id, SrsReview.reviewed_at >= start)) or 0


async def forecast(db: AsyncSession, user: User, lang: str, days: int = 7) -> list[int]:
    now = datetime.now(UTC)
    rows = await db.execute(select(SrsCard.due_at).where(
        SrsCard.user_id == user.id, SrsCard.language_code == lang, SrsCard.fsrs_state_json["reps"].isnot(None),
        SrsCard.due_at <= now + timedelta(days=days)))
    buckets = [0] * days
    for (due,) in rows:
        idx = max(0, (due - now).days)
        if idx < days:
            buckets[idx] += 1
    return buckets
