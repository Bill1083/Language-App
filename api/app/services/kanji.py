"""Kanji as characters: dictionary data (curriculum/kanji.json, from KANJIDIC2),
which lesson introduces each kanji in course order, the "New kanji" cards shown
in lessons, and the memory hooks written for them."""

import hashlib
import json
import logging
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import Text, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import AppSetting, Kanji, Lesson, Level, SrsCard, Unit
from ..providers.base import ChatMessage
from .text import strip_ruby

log = logging.getLogger("parlo.kanji")

DATA_KEY = "kanji_data_hash"  # app_settings row: hash of the kanji.json last loaded
FULL_INTROS = 4  # full "New kanji" cards per lesson; the rest share one overview card
KANJI_RANGE = ("一", "鿿")


def kanji_chars(text: str) -> list[str]:
    """The kanji in a (possibly furigana-marked) string, in order, without repeats."""
    out: list[str] = []
    for ch in strip_ruby(text or ""):
        if KANJI_RANGE[0] <= ch <= KANJI_RANGE[1] and ch not in out:
            out.append(ch)
    return out


def format_kun(reading: str) -> str:
    """KANJIDIC kun readings mark the okurigana with a dot: た.べる → た(べる)."""
    r = reading.strip("-")
    stem, _, tail = r.partition(".")
    return f"{stem}({tail})" if tail else stem


@lru_cache
def _data_file() -> tuple[str, dict[str, Any]]:
    raw = (get_settings().curriculum_dir / "kanji.json").read_bytes()
    data = {k: v for k, v in json.loads(raw).items() if not k.startswith("_")}
    return hashlib.sha256(raw).hexdigest(), data


async def seed_kanji(db: AsyncSession) -> None:
    """Load kanji.json into the kanji table when the file changed (keeps written hooks)."""
    global _new_by_lesson
    _new_by_lesson = None
    digest, data = _data_file()
    row = await db.get(AppSetting, DATA_KEY)
    if row is not None and row.value_json == digest:
        return
    rows = [{"char": ch, "meanings": v["m"], "on_readings": v["on"], "kun_readings": v["kun"], "strokes": v["s"],
             "grade": v["g"], "jlpt": v["j"], "freq": v["f"], "parts": v["p"]} for ch, v in data.items()]
    for i in range(0, len(rows), 500):
        stmt = insert(Kanji).values(rows[i:i + 500])
        await db.execute(stmt.on_conflict_do_update(
            index_elements=[Kanji.char],
            set_={c: stmt.excluded[c] for c in ("meanings", "on_readings", "kun_readings", "strokes", "grade",
                                                 "jlpt", "freq", "parts")}))
    if row is None:
        db.add(AppSetting(key=DATA_KEY, value_json=digest))
    else:
        row.value_json = digest
    log.info("loaded %d kanji", len(rows))


def lesson_kanji(lesson: Lesson) -> list[str]:
    """Every kanji in a lesson's course words."""
    out: list[str] = []
    for word in (lesson.skeleton_json or {}).get("vocab", []):
        out += [c for c in kanji_chars(str(word)) if c not in out]
    return out


_new_by_lesson: dict[int, list[str]] | None = None


async def new_kanji_by_lesson(db: AsyncSession) -> dict[int, list[str]]:
    """Lesson id → the kanji whose first appearance in the Japanese course is that
    lesson. Computed from course order, so it's the same for everyone and nothing
    has to be stored on the lesson (no regeneration)."""
    global _new_by_lesson
    if _new_by_lesson is None:
        lessons = await db.scalars(
            select(Lesson).join(Unit, Unit.id == Lesson.unit_id).join(Level, Level.id == Unit.level_id)
            .where(Level.language_code == "ja", Lesson.kind == "lesson")
            .order_by(Level.order, Unit.order, Lesson.order))
        seen: set[str] = set()
        result: dict[int, list[str]] = {}
        for lesson in lessons:
            new = [c for c in lesson_kanji(lesson) if c not in seen]
            seen.update(new)
            if new:
                result[lesson.id] = new
        _new_by_lesson = result
    return _new_by_lesson


def _words_with(lesson: Lesson, char: str, limit: int = 3) -> list[dict[str, Any]]:
    """Words of this lesson that use the kanji, as shown in the lesson (with furigana)."""
    out = []
    for v in (lesson.content_json or {}).get("vocab", []):
        if char in strip_ruby(str(v.get("word", ""))):
            out.append({"word": v.get("word"), "reading": v.get("reading"), "meaning": v.get("meaning")})
    if not out:  # content not generated yet: fall back to the course word list
        out = [{"word": w, "reading": None, "meaning": None}
               for w in (lesson.skeleton_json or {}).get("vocab", []) if char in str(w)]
    return out[:limit]


def kanji_info(k: Kanji) -> dict[str, Any]:
    kun = list(dict.fromkeys(format_kun(r) for r in k.kun_readings))[:3]  # た.べる and -た.べる read the same
    return {"char": k.char, "meanings": k.meanings, "on": k.on_readings[:2], "kun": kun, "parts": k.parts,
            "strokes": k.strokes, "hook": k.hook}


async def intro_cards(db: AsyncSession, lesson: Lesson) -> tuple[list[dict[str, Any]], list[str]]:
    """The "New kanji" cards for a lesson and the kanji still missing a memory hook.
    The most common kanji get full cards; any others share one overview card."""
    new = (await new_kanji_by_lesson(db)).get(lesson.id, [])
    if not new:
        return [], []
    rows = {k.char: k for k in await db.scalars(select(Kanji).where(Kanji.char.in_(new)))}
    known = [c for c in new if c in rows]
    by_use = sorted(known, key=lambda c: rows[c].freq or 9999)
    full, rest = set(by_use[:FULL_INTROS]), by_use[FULL_INTROS:]
    cards: list[dict[str, Any]] = []
    for i, ch in enumerate(c for c in known if c in full):
        cards.append({"id": -(i + 1), "type": "kanji_intro", "char": ch, **kanji_info(rows[ch]),
                      "words": _words_with(lesson, ch)})
    if rest:
        # Each with the word it appears in here: a dictionary reading like 私 = シ would mislead.
        cards.append({"id": -99, "type": "kanji_more", "chars": rest,
                      "kanji": [{"char": c, "meaning": ", ".join(rows[c].meanings[:2]),
                                 "word": next(iter(_words_with(lesson, c, 1)), None)} for c in rest]})
    return cards, [c for c in full if not rows[c].hook]


_NOT_A_USE = {"grammar_note", "kana_intro", "kanji_intro", "kanji_more"}


def _uses(ex: dict[str, Any], chars: list[str]) -> bool:
    """Does this exercise ask you to read one of these kanji? A word card counts only
    for its own word (not its example sentence); notes and other intro cards never do."""
    if ex.get("type") == "vocab_intro":
        return any(c in str((ex.get("vocab") or {}).get("word", "")) for c in chars)
    if ex.get("type") in _NOT_A_USE:
        return False
    return any(c in json.dumps(ex, ensure_ascii=False) for c in chars)


def place_intro_cards(exercises: list[dict[str, Any]], cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Put each kanji card just before the first exercise that uses its kanji."""
    out = list(exercises)
    # Each card goes in after any already placed before the same exercise, so insert
    # in course order (full cards -1, -2, … then the overview).
    for card in sorted(cards, key=lambda c: (c["type"] == "kanji_more", -c["id"])):
        chars = card.get("chars") or [card["char"]]
        at = next((i for i, ex in enumerate(out) if _uses(ex, chars)), len(out))
        out.insert(at, card)
    return out


# ---------------------------------------------------------------- memory hooks

HOOK_SYSTEM = (
    "You write memory hooks for English-speaking learners of Japanese kanji. For each kanji given, write ONE "
    "short, vivid sentence (at most 16 words) that links what the character looks like — or the parts listed — "
    "to its meaning, and uses the meaning word. No readings, no romaji, no Japanese except the kanji itself. "
    'Return JSON: {"items": [{"char": "日", "hook": "..."}]} with one item per kanji.')


class _Hook(BaseModel):
    char: str = Field(max_length=4)
    hook: str = Field(max_length=240)


class _Hooks(BaseModel):
    items: list[_Hook]


async def write_hooks(db: AsyncSession, ai: Any, chars: list[str]) -> int:
    """Generate and store hooks for kanji that don't have one (and update their review cards)."""
    rows = list(await db.scalars(select(Kanji).where(Kanji.char.in_(chars), Kanji.hook.is_(None))))
    if not rows:
        return 0
    listing = "\n".join(f"{k.char}: meaning {', '.join(k.meanings) or '?'}; parts {' '.join(k.parts) or 'none'}"
                        for k in rows)
    result = await ai.llm_json("kanji_hooks", "feedback", _Hooks, system=HOOK_SYSTEM,
                               messages=[ChatMessage("user", listing)], temperature=0.6, max_tokens=1500)
    hooks = {h.char: h.hook.strip() for h in result.items if h.hook.strip()}
    for k in rows:
        if k.char in hooks:
            k.hook = hooks[k.char]
            await db.execute(
                update(SrsCard).where(SrsCard.card_type == "kanji_char", SrsCard.source_ref == f"kanji:{k.char}")
                .values(back_json=SrsCard.back_json.op("||")(
                    func.jsonb_build_object(literal("hook", Text), literal(hooks[k.char], Text)))))
    await db.commit()
    return len(hooks)
