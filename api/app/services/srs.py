"""Review deck: card creation from lessons, kana, mistakes and conversations,
the daily queue (due cards + capped new cards), practice by level or unit, and
FSRS reviews."""

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import String, and_, case, cast, func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import Lesson, LessonProgress, Level, SrsCard, SrsReview, Unit, User, UserVocab, VocabItem
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
                   unit_ids: list[int] | None = None, order: str = "shuffle", limit: int = 30,
                   card_types: list[str] | None = None) -> list[SrsCard]:
    """Cards from a level or a set of units regardless of due date, one card
    per word. "course" keeps the course map's order (unit by unit, in the order
    they were learnt); "shuffle" takes the most overdue and shuffles them.
    Ratings still go through FSRS, which accounts for reviewing early, so
    practising never corrupts the schedule."""
    q = (select(SrsCard).outerjoin(Unit, Unit.id == SrsCard.unit_id).outerjoin(Level, Level.id == Unit.level_id)
         .where(SrsCard.user_id == user.id, SrsCard.language_code == lang, SrsCard.suspended.is_(False)))
    if unit_ids:
        q = q.where(SrsCard.unit_id.in_(unit_ids))
    elif level:
        q = q.where(SrsCard.level == level)
    if card_types:
        q = q.where(SrsCard.card_type.in_(card_types))
    if order == "course":
        q = q.order_by(Level.order.nulls_last(), Unit.order.nulls_last(), SrsCard.created_at, TYPE_PRIORITY,
                       SrsCard.id)
    else:
        q = q.order_by(SrsCard.due_at, TYPE_PRIORITY, SrsCard.id)
    cards = list(await db.scalars(q.limit(2000)))
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
    if order != "course":
        random.shuffle(picked)
        return picked
    return loosely_ordered(picked)


async def learned_in(db: AsyncSession, user_id: int, lang: str) -> dict[int, list[int]]:
    """Lesson id -> the words the user learnt in it (kept even if the lesson was regenerated since)."""
    rows = await db.execute(
        select(SrsCard.source_ref, SrsCard.vocab_item_id)
        .where(SrsCard.user_id == user_id, SrsCard.language_code == lang, SrsCard.vocab_item_id.is_not(None),
               SrsCard.source_ref.like("lesson:%"))
        .order_by(SrsCard.created_at, SrsCard.id))
    out: dict[int, list[int]] = {}
    for ref, vocab_id in rows:
        ids = out.setdefault(int(ref.split(":", 1)[1]), [])
        if vocab_id not in ids:
            ids.append(vocab_id)
    return out


async def lesson_keys(db: AsyncSession, lesson: Lesson, lang: str,
                      learned: dict[int, list[int]] | None = None) -> list[tuple[str, Any]]:
    """What a lesson taught, in teaching order: ("kana", "kana:の") and ("vocab", vocab_item_id),
    plus any words `learned` says the user picked up in it."""
    keys: list[tuple[str, Any]] = [("kana", f"kana:{c['char']}") for c in _kana_lesson_chars(lesson)]
    taught = [(strip_ruby(str(v["word"]))[:160], str(v["meaning"])[:300])
              for v in (lesson.content_json or {}).get("vocab", [])]
    position = {key: i for i, key in enumerate(taught)}
    words = sorted(await lesson_words(db, lesson, lang), key=lambda v: position.get((v.lemma, v.meaning), len(taught)))
    keys += [("vocab", v.id) for v in words]
    keys += [("vocab", vid) for vid in (learned or {}).get(lesson.id, []) if ("vocab", vid) not in keys]
    return keys


async def completed_lessons(db: AsyncSession, user_id: int, lang: str, *, lesson_ids: list[int] | None = None,
                            unit_ids: list[int] | None = None, level: str | None = None) -> list[Lesson]:
    """Finished lessons that teach something (not checkpoints, level or script tests), in course order."""
    q = (select(Lesson).join(Unit, Unit.id == Lesson.unit_id).join(Level, Level.id == Unit.level_id)
         .join(LessonProgress, and_(LessonProgress.lesson_id == Lesson.id, LessonProgress.user_id == user_id))
         .where(Level.language_code == lang, LessonProgress.status == "completed",
                Lesson.kind.in_(["lesson", "kana"]), Lesson.order != 100)
         .options(selectinload(Lesson.unit).selectinload(Unit.level))
         .order_by(Level.order, Unit.order, Lesson.order))
    if lesson_ids:
        q = q.where(Lesson.id.in_(lesson_ids))
    elif unit_ids:
        q = q.where(Lesson.unit_id.in_(unit_ids))
    elif level:
        q = q.where(Level.cefr == level)
    return list(await db.scalars(q))


def _card_key(card: SrsCard) -> tuple[str, Any]:
    return ("kana", card.source_ref) if card.card_type == "kana" else ("vocab", card.vocab_item_id)


async def practice_from_lessons(db: AsyncSession, user: User, lang: str, lessons: list[Lesson], *,
                                order: str = "course", limit: int = 20,
                                card_types: list[str] | None = None) -> list[SrsCard]:
    """One card per word / kana the lessons taught. "course" keeps the lessons' order
    (and each lesson's teaching order); "shuffle" picks at random from all of them."""
    learned = await learned_in(db, user.id, lang)
    keys: list[tuple[str, Any]] = []
    for lesson in lessons:
        keys += [k for k in await lesson_keys(db, lesson, lang, learned) if k not in keys]
    refs = [k for kind, k in keys if kind == "kana"]
    ids = [k for kind, k in keys if kind == "vocab"]
    q = select(SrsCard).where(
        SrsCard.user_id == user.id, SrsCard.language_code == lang, SrsCard.suspended.is_(False),
        or_(and_(SrsCard.card_type == "kana", SrsCard.source_ref.in_(refs)), SrsCard.vocab_item_id.in_(ids)))
    if card_types:
        q = q.where(SrsCard.card_type.in_(card_types))
    # Which of a word's cards to use: recognition-type first in course order, most overdue when shuffling.
    q = q.order_by(TYPE_PRIORITY, SrsCard.id) if order == "course" else q.order_by(SrsCard.due_at, SrsCard.id)
    by_key: dict[tuple[str, Any], SrsCard] = {}
    for card in await db.scalars(q):
        by_key.setdefault(_card_key(card), card)
    available = [k for k in keys if k in by_key]
    if order != "course":
        random.shuffle(available)
        return [by_key[k] for k in available[:limit]]
    return loosely_ordered([by_key[k] for k in available[:limit]])


async def practice_blocks(db: AsyncSession, user: User, lang: str) -> list[dict[str, Any]]:
    """The course map's finished lessons, by level and unit, with how many items each has to practise."""
    lessons = await completed_lessons(db, user.id, lang)
    rows = await db.execute(select(SrsCard.card_type, SrsCard.source_ref, SrsCard.vocab_item_id).where(
        SrsCard.user_id == user.id, SrsCard.language_code == lang, SrsCard.suspended.is_(False)))
    have = {("kana", ref) if kind == "kana" else ("vocab", vid) for kind, ref, vid in rows}
    learned = await learned_in(db, user.id, lang)
    levels: dict[str, dict[str, Any]] = {}
    for lesson in lessons:
        items = sum(1 for k in await lesson_keys(db, lesson, lang, learned) if k in have)
        if not items:
            continue
        lv = levels.setdefault(lesson.unit.level.cefr, {"level": lesson.unit.level.cefr, "units": {}})
        unit = lv["units"].setdefault(lesson.unit_id, {"id": lesson.unit_id, "title": lesson.unit.title, "lessons": []})
        unit["lessons"].append({"id": lesson.id, "title": lesson.title, "kind": lesson.kind, "items": items})
    return [{**lv, "units": list(lv["units"].values())} for lv in levels.values()]


COURSE_JITTER = 3.0  # how far (in places) an item may drift from its course position


def loosely_ordered(items: list[Any], spread: float = COURSE_JITTER) -> list[Any]:
    """Course order with a little randomness: each item moves a few places at most,
    so a session follows the course without being the same sequence every time."""
    keyed = [(i + random.uniform(0, spread), item) for i, item in enumerate(items)]
    return [item for _, item in sorted(keyed, key=lambda pair: pair[0])]


def practice_item(card: SrsCard) -> dict[str, Any]:
    """One word or kana for type-the-answer practice: a prompt and what counts as right."""
    f, b = card.front_json or {}, card.back_json or {}
    if card.card_type == "kana":
        return {"card_id": card.id, "kind": "kana", "prompt": f.get("char"), "answer": b.get("romaji"),
                "accepted": [b.get("romaji")], "audio_text": b.get("audio_text") or f.get("char"),
                "hint": b.get("mnemonic")}
    return {"card_id": card.id, "kind": "word", "prompt": f.get("prompt"), "answer": b.get("answer"),
            "accepted": [a for a in [b.get("answer"), *(b.get("accepted") or [])] if a],
            "audio_text": b.get("audio_text"), "pos": f.get("pos"), "gender": f.get("gender"),
            "example": b.get("example"), "example_translation": b.get("example_translation")}


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
