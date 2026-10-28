"""Lesson content generation: skeleton → LLM → validation → stored lesson.

Generated once and kept in the DB. The worker calls `generate_lesson` (also
for pre-generating lessons ahead of the learner); the API only enqueues.
"""

import json
import logging
import random
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import Exercise, Lesson, Level, PlacementBank, Scenario, Unit, VocabItem
from ..providers.base import ChatMessage
from ..schemas.lesson import LessonDraft, PlacementBankDraft, UnitScenarioDraft, VocabEntry, validate_exercises
from . import prompts
from .ai import AIService
from .kana import build_kana_lesson
from .languages import CEFR
from .text import ruby_reading, strip_ruby

log = logging.getLogger("parlo.lessons")

MIN_EXERCISES = {"lesson": 8, "checkpoint": 8, "level_test": 12}


async def load_lesson(db: AsyncSession, lesson_id: int) -> Lesson | None:
    return await db.scalar(
        select(Lesson).where(Lesson.id == lesson_id)
        .options(selectinload(Lesson.unit).selectinload(Unit.level))
    )


async def known_vocab_before(db: AsyncSession, lesson: Lesson) -> list[str]:
    """Vocab from every earlier lesson in the course, taken from the skeletons."""
    lang = lesson.unit.level.language_code
    rows = await db.execute(
        select(Lesson.skeleton_json, Level.order, Unit.order, Lesson.order)
        .join(Unit, Lesson.unit_id == Unit.id).join(Level, Unit.level_id == Level.id)
        .where(Level.language_code == lang, Lesson.kind == "lesson")
        .order_by(Level.order, Unit.order, Lesson.order)
    )
    here = (lesson.unit.level.order, lesson.unit.order, lesson.order)
    out: list[str] = []
    for skeleton, lv_o, u_o, l_o in rows:
        if (lv_o, u_o, l_o) >= here:
            break
        out.extend(skeleton.get("vocab", []))
    return out


async def unit_skeletons(db: AsyncSession, unit_ids: list[int]) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(Lesson.skeleton_json, Unit.title).join(Unit, Lesson.unit_id == Unit.id)
        .where(Lesson.unit_id.in_(unit_ids), Lesson.kind == "lesson").order_by(Unit.order, Lesson.order)
    )
    return [{"unit": title, **sk} for sk, title in rows]


def _shuffle_options(ex: dict[str, Any], rng: random.Random) -> None:
    """Models favour answer_index 0 — shuffle choices so position carries no signal."""
    if ex["type"] in ("multiple_choice", "listening_choice") and "answer_index" in ex:
        correct = ex["options"][ex["answer_index"]]
        rng.shuffle(ex["options"])
        ex["answer_index"] = ex["options"].index(correct)
    elif ex["type"] == "reading":
        for q in ex["questions"]:
            correct = q["options"][q["answer_index"]]
            rng.shuffle(q["options"])
            q["answer_index"] = q["options"].index(correct)
    elif ex["type"] == "fill_blank" and ex.get("options"):
        rng.shuffle(ex["options"])


def assemble(draft: LessonDraft, exercises: list[dict[str, Any]], seed: int, kind: str) -> dict[str, Any]:
    rng = random.Random(seed)
    for ex in exercises:
        _shuffle_options(ex, rng)
    if kind != "lesson":
        return {"intro": draft.intro, "vocab": [], "grammar": [], "pronunciation": [], "exercises": exercises,
                "is_test": True, "pass_mark": 0.8}
    vocab = [v.model_dump(exclude_none=True) for v in draft.vocab]
    grammar = [g.model_dump(exclude_none=True) for g in draft.grammar]
    half = (len(vocab) + 1) // 2
    split = max(2, len(exercises) // 3)
    sequence: list[dict[str, Any]] = []
    sequence += [{"type": "vocab_intro", "vocab": v} for v in vocab[:half]]
    sequence += exercises[:split]
    sequence += [{"type": "grammar_note", "grammar": g} for g in grammar]
    sequence += [{"type": "vocab_intro", "vocab": v} for v in vocab[half:]]
    sequence += exercises[split:]
    return {"intro": draft.intro, "vocab": vocab, "grammar": grammar, "pronunciation": draft.pronunciation,
            "exercises": sequence}


async def _draft(ai: AIService, lesson: Lesson, db: AsyncSession) -> LessonDraft:
    lang = lesson.unit.level.language_code
    cefr = lesson.unit.level.cefr
    if lesson.kind == "lesson":
        system = prompts.lesson_system(lang, cefr)
        known = await known_vocab_before(db, lesson)
        request = prompts.lesson_request(lesson.unit.title, lesson.skeleton_json, known)
    elif lesson.kind == "checkpoint":
        system = prompts.test_system(lang, cefr, "unit checkpoint quiz", "14")
        request = json.dumps({"unit": lesson.unit.title,
                                      "lessons": await unit_skeletons(db, [lesson.unit_id])}, ensure_ascii=False)
    else:  # level_test
        unit_ids = list(await db.scalars(select(Unit.id).where(Unit.level_id == lesson.unit.level_id)))
        skeletons = await unit_skeletons(db, unit_ids)
        system = prompts.test_system(lang, cefr, f"{cefr} level test", "20")
        request = json.dumps({"level": cefr, "lessons": [
            {"unit": s["unit"], "title": s["title"], "vocab": s.get("vocab", [])[:8], "grammar": s.get("grammar", [])}
            for s in skeletons]}, ensure_ascii=False)

    messages = [ChatMessage("user", request)]
    draft = await ai.llm_json("lesson_generation", "content", LessonDraft, system=system, messages=messages,
                              temperature=0.6, max_tokens=16000)
    good, errors = validate_exercises(draft.exercises)
    if len(good) < MIN_EXERCISES.get(lesson.kind, 8):
        log.warning("lesson %s: only %d valid exercises, retrying (%s)", lesson.slug, len(good), errors[:5])
        messages += [ChatMessage("assistant", draft.model_dump_json()[:6000]),
                     ChatMessage("user", "Several exercises were invalid:\n- " + "\n- ".join(errors[:12])
                                 + "\nReturn the full corrected lesson JSON.")]
        draft = await ai.llm_json("lesson_generation", "content", LessonDraft, system=system, messages=messages,
                                  temperature=0.4, max_tokens=16000)
        good, errors = validate_exercises(draft.exercises)
        if len(good) < MIN_EXERCISES.get(lesson.kind, 8) // 2:
            raise ValueError(f"Too few valid exercises after retry: {errors[:3]}")
    draft.exercises = good
    return draft


async def save_content(db: AsyncSession, lesson: Lesson, content: dict[str, Any], model: str | None) -> None:
    await db.execute(delete(Exercise).where(Exercise.lesson_id == lesson.id))
    for i, ex in enumerate(content["exercises"]):
        db.add(Exercise(lesson_id=lesson.id, order=i, type=ex["type"], payload_json=ex))
    lesson.content_json = {k: v for k, v in content.items() if k != "exercises"}
    lesson.status = "ready"
    lesson.error = None
    lesson.generated_at = datetime.now(UTC)
    lesson.model_used = model
    lesson.version = (lesson.version or 0) + 1
    await db.flush()
    await upsert_lesson_vocab(db, lesson, content.get("vocab", []))


async def upsert_lesson_vocab(db: AsyncSession, lesson: Lesson, vocab: list[dict[str, Any]]) -> None:
    lang = lesson.unit.level.language_code
    for v in vocab:
        entry = VocabEntry.model_validate(v)
        lemma = strip_ruby(entry.word)
        reading = entry.reading or (ruby_reading(entry.word) if lang == "ja" and "{" in entry.word else None)
        extra = {k: v[k] for k in ("plural", "emoji", "note", "romaji") if v.get(k)}
        if "{" in entry.word:
            extra["ruby"] = entry.word
        values = dict(language_code=lang, lemma=lemma[:160], reading=reading, meaning=entry.meaning[:300],
                      pos=entry.pos, gender=entry.gender, level=lesson.unit.level.cefr, example=entry.example,
                      example_translation=entry.example_translation, extra_json=extra, source="lesson",
                      unit_id=lesson.unit_id, lesson_id=lesson.id)
        await db.execute(
            insert(VocabItem).values(**values).on_conflict_do_update(
                constraint="uq_vocab_lemma_meaning",
                # keep the lesson/unit/level that first introduced the word
                set_={k: values[k] for k in ("reading", "pos", "gender", "example", "example_translation",
                                             "extra_json")},
            )
        )


async def generate_lesson(db: AsyncSession, lesson_id: int, ai: AIService | None = None, force: bool = False) -> Lesson:
    lesson = await load_lesson(db, lesson_id)
    if lesson is None:
        raise ValueError(f"lesson {lesson_id} not found")
    if lesson.status == "ready" and not force:
        return lesson
    lesson.status = "generating"
    await db.commit()
    try:
        if lesson.kind == "kana":
            sk = lesson.skeleton_json
            content = build_kana_lesson(sk["script"], sk["index"], seed=lesson.id)
            await save_content(db, lesson, content, model="kana-builder")
        else:
            ai = ai or AIService(db)
            draft = await _draft(ai, lesson, db)
            content = assemble(draft, draft.exercises, seed=lesson.id * 7919 + lesson.version, kind=lesson.kind)
            cfg = await ai.config()
            await save_content(db, lesson, content, model=f"{cfg.llm_provider}/{cfg.llm_models['content']}")
        await db.commit()
        log.info("generated lesson %s (%s)", lesson.slug, lesson.kind)
    except Exception as e:
        await db.rollback()
        lesson = await load_lesson(db, lesson_id)
        assert lesson is not None
        lesson.status = "failed"
        lesson.error = str(e)[:2000]
        await db.commit()
        log.exception("lesson %s failed", lesson_id)
        raise
    return lesson


async def generate_placement_bank(db: AsyncSession, lang: str, ai: AIService | None = None) -> PlacementBank:
    ai = ai or AIService(db)
    draft = await ai.llm_json("placement_generation", "content", PlacementBankDraft,
                              system=prompts.placement_system(lang),
                              messages=[ChatMessage("user", "Write the 30-item placement bank now.")],
                              temperature=0.6, max_tokens=8000)
    items = [i.model_dump() for i in draft.items]
    rng = random.Random(lang)
    for i in items:
        correct = i["options"][i["answer_index"]]
        rng.shuffle(i["options"])
        i["answer_index"] = i["options"].index(correct)
    cfg = await ai.config()
    bank = await db.get(PlacementBank, lang)
    if bank is None:
        bank = PlacementBank(language_code=lang, items_json=items)
        db.add(bank)
    bank.items_json = items
    bank.model_used = cfg.llm_models["content"]
    await db.commit()
    return bank


async def unit_scenario(db: AsyncSession, unit: Unit, ai: AIService) -> Scenario:
    existing = await db.scalar(select(Scenario).where(Scenario.unit_id == unit.id))
    if existing:
        return existing
    level = await db.get(Level, unit.level_id)
    assert level is not None
    skeletons = await unit_skeletons(db, [unit.id])
    vocab = [w for s in skeletons for w in s.get("vocab", [])]
    grammar = [g for s in skeletons for g in s.get("grammar", [])]
    draft = await ai.llm_json(
        "unit_scenario", "content", UnitScenarioDraft,
        system=prompts.unit_scenario_system(level.language_code, level.cefr),
        messages=[ChatMessage("user", json.dumps(
            {"unit": unit.title, "theme": unit.theme, "objectives": unit.objectives_json,
             "vocab": vocab[:60], "grammar": grammar}, ensure_ascii=False))],
        temperature=0.8, max_tokens=1000,
    )
    scenario = Scenario(
        slug=f"unit-{unit.slug}", language_code=level.language_code, unit_id=unit.id, title=draft.title,
        emoji=draft.emoji[:16], description=draft.description, goal=draft.goal, ai_role=draft.ai_role,
        user_role=draft.user_role, min_level=level.cefr if level.cefr in CEFR else "A1",
        system_prompt_template="Use this unit's vocabulary where natural: " + ", ".join(vocab[:60]),
    )
    db.add(scenario)
    await db.commit()
    return scenario
