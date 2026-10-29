"""Review deck: card creation from lessons, kana, mistakes and conversations,
the daily queue (due cards + capped new cards), practice by level or unit, and
FSRS reviews."""

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import String, and_, case, cast, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Lesson, LessonProgress, SrsCard, SrsReview, Unit, User, UserVocab, VocabItem
from .fsrs import CardState, Scheduler, format_interval
from .kana import lesson_chars
from .languages import CEFR
from .progress import local_day_start_utc, local_today
from .text import has_japanese, strip_ruby

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
                due_at=datetime.now(UTC), level=vocab.level, unit_id=vocab.unit_id,
            ).on_conflict_do_nothing(index_elements=["user_id", "vocab_item_id", "card_type"],
                                     index_where=SrsCard.vocab_item_id.is_not(None))
        )
    return is_new


async def add_mistake_card(db: AsyncSession, user_id: int, lang: str, *, prompt: str, answer: str,
                           explanation: str | None, source: str, source_ref: str, context: str | None = None,
                           wrong: str | None = None, level: str | None = None, unit_id: int | None = None) -> SrsCard:
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
        fsrs_state_json={}, due_at=datetime.now(UTC), level=level, unit_id=unit_id,
    )
    db.add(card)
    await db.flush()
    return card


async def lesson_words(db: AsyncSession, lesson: Lesson, lang: str) -> list[VocabItem]:
    """The vocab items a lesson teaches, looked up by its own word list: a word
    taught in several lessons belongs to all of them."""
    keys = [(strip_ruby(str(v["word"]))[:160], str(v["meaning"])[:300])
            for v in (lesson.content_json or {}).get("vocab", [])]
    if not keys:
        return []
    return list(await db.scalars(select(VocabItem).where(
        VocabItem.language_code == lang, tuple_(VocabItem.lemma, VocabItem.meaning).in_(keys))))


def kana_card(user_id: int, lesson: Lesson, char: dict[str, str]) -> SrsCard:
    return SrsCard(
        user_id=user_id, language_code="ja", card_type="kana", source="lesson", source_ref=f"kana:{char['char']}",
        front_json={"char": char["char"], "script": (lesson.skeleton_json or {}).get("script")},
        back_json={"romaji": char["romaji"], "mnemonic": char["mnemonic"], "audio_text": char["audio_text"]},
        level="PRE", unit_id=lesson.unit_id, fsrs_state_json={}, due_at=datetime.now(UTC),
    )


def _kana_lesson_chars(lesson: Lesson) -> list[dict[str, str]]:
    sk = lesson.skeleton_json or {}
    if sk.get("index", -1) < 0 or sk.get("script") is None:
        return []  # script tests teach nothing new
    return lesson_chars(sk["script"], sk["index"])


async def learn_kana(db: AsyncSession, user_id: int, lesson: Lesson) -> int:
    """Review cards for the characters a finished kana lesson taught."""
    existing = set(await db.scalars(select(SrsCard.source_ref).where(
        SrsCard.user_id == user_id, SrsCard.card_type == "kana")))
    added = 0
    for char in _kana_lesson_chars(lesson):
        if f"kana:{char['char']}" not in existing:
            db.add(kana_card(user_id, lesson, char))
            added += 1
    return added


async def ensure_kana_cards(db: AsyncSession, user_id: int) -> int:
    """Backfill kana cards (and the lessons' example words) for kana lessons
    finished before kana review existed. Two queries when nothing is missing."""
    lessons = list(await db.scalars(
        select(Lesson).join(LessonProgress, LessonProgress.lesson_id == Lesson.id)
        .where(LessonProgress.user_id == user_id, LessonProgress.status == "completed", Lesson.kind == "kana")))
    if not lessons:
        return 0
    existing = set(await db.scalars(select(SrsCard.source_ref).where(
        SrsCard.user_id == user_id, SrsCard.card_type == "kana")))
    added = 0
    for lesson in lessons:
        missing = [c for c in _kana_lesson_chars(lesson) if f"kana:{c['char']}" not in existing]
        if not missing:
            continue
        for char in missing:
            db.add(kana_card(user_id, lesson, char))
            existing.add(f"kana:{char['char']}")
            added += 1
        for item in await lesson_words(db, lesson, "ja"):
            await learn_vocab(db, user_id, item, "lesson", f"lesson:{lesson.id}")
    if added:
        await db.commit()
    return added


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
        priority = case((SrsCard.card_type.in_(["kana", "recognize"]), 0), (SrsCard.card_type == "produce", 2), else_=1)
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


TYPE_PRIORITY = case((SrsCard.card_type.in_(["kana", "recognize"]), 0),
                     (SrsCard.card_type.in_(["listen", "kanji", "mistake"]), 1), else_=2)


async def practice(db: AsyncSession, user: User, lang: str, *, level: str | None = None,
                   unit_id: int | None = None, limit: int = 30) -> list[SrsCard]:
    """Cards from one level or unit regardless of due date, one card per word,
    most overdue first. Ratings still go through FSRS, which accounts for
    reviewing early, so practising never corrupts the schedule."""
    q = select(SrsCard).where(SrsCard.user_id == user.id, SrsCard.language_code == lang,
                              SrsCard.suspended.is_(False))
    if unit_id:
        q = q.where(SrsCard.unit_id == unit_id)
    elif level:
        q = q.where(SrsCard.level == level)
    cards = list(await db.scalars(q.order_by(SrsCard.due_at, TYPE_PRIORITY, SrsCard.id).limit(1000)))
    seen: set[Any] = set()
    picked: list[SrsCard] = []
    for c in cards:
        key = c.vocab_item_id or c.source_ref or c.id
        if key in seen:
            continue
        seen.add(key)
        picked.append(c)
        if len(picked) >= limit:
            break
    random.shuffle(picked)
    return picked


LEVEL_ORDER = ["PRE", *CEFR]


async def level_summary(db: AsyncSession, user: User, lang: str) -> list[dict[str, Any]]:
    """What there is to practise, per level and unit: items (words, kana,
    mistakes), cards, and how many are due now."""
    now = datetime.now(UTC)
    item = func.coalesce(cast(SrsCard.vocab_item_id, String), SrsCard.source_ref, cast(SrsCard.id, String))
    due = func.sum(case((and_(SrsCard.fsrs_state_json["reps"].isnot(None), SrsCard.due_at <= now), 1), else_=0))
    base = [SrsCard.user_id == user.id, SrsCard.language_code == lang, SrsCard.suspended.is_(False),
            SrsCard.level.is_not(None)]
    rows = await db.execute(select(SrsCard.level, func.count(func.distinct(item)), func.count(), due)
                            .where(*base).group_by(SrsCard.level))
    levels = {lv: {"level": lv, "items": int(n), "cards": int(c), "due": int(d or 0), "units": []}
              for lv, n, c, d in rows}
    units = await db.execute(
        select(SrsCard.level, Unit.id, Unit.title, Unit.order, func.count(func.distinct(item)), due)
        .join(Unit, Unit.id == SrsCard.unit_id).where(*base)
        .group_by(SrsCard.level, Unit.id, Unit.title, Unit.order).order_by(Unit.order))
    for lv, uid, title, _order, n, d in units:
        if lv in levels:
            levels[lv]["units"].append({"id": uid, "title": title, "items": int(n), "due": int(d or 0)})
    return [levels[lv] for lv in LEVEL_ORDER if lv in levels]


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
