"""Course map and unlock rules.

- Levels up to the enrolment's `current_level` are unlocked (placement, a passed
  level test or a manual unlock move it). Levels below the current one are
  fully open for revision; the current level is a path — each lesson unlocks
  the next, and a unit's checkpoint gates the next unit.
- The level test of an unlocked level is always available ("test out").
- Japanese: A1 and above stay locked until the writing-systems module is
  completed or both kana tests are passed.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import Enrolment, Lesson, LessonProgress, Level, Unit
from .languages import CEFR, level_index


def kana_done(enrolment: Enrolment, progress: dict[int, LessonProgress], levels: list[Level]) -> bool:
    if (enrolment.settings_json or {}).get("kana_done"):
        return True
    pre = next((lv for lv in levels if lv.cefr == "PRE"), None)
    if pre is None:
        return True
    tests_passed = 0
    for unit in pre.units:
        lessons = unit.lessons
        test = next((le for le in lessons if le.order == 100), None)
        all_done = all(progress.get(le.id) and progress[le.id].status == "completed" for le in lessons if le.order != 100)
        if (test and progress.get(test.id) and progress[test.id].status == "completed") or all_done:
            tests_passed += 1
    return tests_passed == len(pre.units)


async def load_levels(db: AsyncSession, lang: str) -> list[Level]:
    return list(await db.scalars(
        select(Level).where(Level.language_code == lang).order_by(Level.order)
        .options(selectinload(Level.units).selectinload(Unit.lessons))
    ))


async def load_progress(db: AsyncSession, user_id: int, lesson_ids: list[int]) -> dict[int, LessonProgress]:
    rows = await db.scalars(select(LessonProgress).where(
        LessonProgress.user_id == user_id, LessonProgress.lesson_id.in_(lesson_ids or [0])))
    return {p.lesson_id: p for p in rows}


def _lesson_state(lesson: Lesson, prog: LessonProgress | None, available: bool) -> str:
    if prog and prog.status == "completed":
        return "perfect" if prog.best_accuracy >= 0.999 else "completed"
    return "available" if available else "locked"


async def course_map(db: AsyncSession, user_id: int, enrolment: Enrolment) -> dict[str, Any]:
    lang = enrolment.language_code
    levels = await load_levels(db, lang)
    lesson_ids = [le.id for lv in levels for u in lv.units for le in u.lessons]
    progress = await load_progress(db, user_id, lesson_ids)
    current_idx = level_index(enrolment.current_level)
    kana_ok = kana_done(enrolment, progress, levels)

    out_levels: list[dict[str, Any]] = []
    next_lesson: dict[str, Any] | None = None
    for lv in levels:
        is_pre = lv.cefr == "PRE"
        idx = -1 if is_pre else level_index(lv.cefr)
        unlocked = is_pre or (idx <= current_idx and (lang != "ja" or kana_ok))
        open_all = unlocked and not is_pre and idx < current_idx  # revision mode: everything open
        gate_open = unlocked  # sequential path within the level
        units_out = []
        total = completed = 0
        for unit in lv.units:
            is_test_unit = unit.theme == "test"
            lessons_out = []
            unit_done = unit_total = 0
            # Kana units are independent tracks: each script is its own path.
            if is_pre:
                gate_open = True
            for le in unit.lessons:
                prog = progress.get(le.id)
                done = bool(prog and prog.status == "completed")
                is_test = le.kind == "level_test" or (le.kind == "kana" and le.order == 100)
                available = unlocked and (open_all or gate_open or is_test)
                state = _lesson_state(le, prog, available)
                if not done and not is_test and not open_all:
                    if gate_open and available and next_lesson is None and unlocked:
                        next_lesson = {"id": le.id, "title": le.title, "unit": unit.title, "kind": le.kind,
                                       "level": lv.cefr}
                    gate_open = False
                lessons_out.append({
                    "id": le.id, "slug": le.slug, "title": le.title, "kind": le.kind, "order": le.order,
                    "state": state, "best_accuracy": prog.best_accuracy if prog else None,
                    "ready": le.status == "ready",
                })
                if le.kind in ("lesson", "kana") and le.order != 100:
                    unit_total += 1
                    unit_done += done
            total += unit_total
            completed += unit_done
            first_open = next((x for x in lessons_out if x["state"] != "locked"), None)
            units_out.append({
                "id": unit.id, "slug": unit.slug, "title": unit.title, "theme": unit.theme, "order": unit.order,
                "objectives": unit.objectives_json, "is_test": is_test_unit, "lessons": lessons_out,
                "done": unit_done, "total": unit_total,
                "reached": first_open is not None and not is_test_unit,
                "vocab": [w for le in unit.lessons for w in (le.skeleton_json or {}).get("vocab", [])][:80],
            })
        test_lesson = next((le for u in lv.units for le in u.lessons if le.kind == "level_test"), None)
        test_passed = bool(test_lesson and progress.get(test_lesson.id) and progress[test_lesson.id].status == "completed")
        out_levels.append({
            "cefr": lv.cefr, "order": lv.order, "unlocked": unlocked, "completed": completed, "total": total,
            "test_passed": test_passed, "units": units_out,
        })
    return {
        "language": lang, "current_level": enrolment.current_level, "kana_done": kana_ok,
        "levels": out_levels, "next_lesson": next_lesson,
    }


def lesson_unlocked(course: dict[str, Any], lesson_id: int) -> bool:
    for lv in course["levels"]:
        for u in lv["units"]:
            for le in u["lessons"]:
                if le["id"] == lesson_id:
                    return le["state"] != "locked"
    return False


def upcoming_lessons(course: dict[str, Any], n: int) -> list[int]:
    """The next n lessons on the learner's path that still need content — for pre-generation."""
    ids: list[int] = []
    seen_next = course.get("next_lesson") is None
    for lv in course["levels"]:
        if not lv["unlocked"]:
            continue
        for u in lv["units"]:
            for le in u["lessons"]:
                if course.get("next_lesson") and le["id"] == course["next_lesson"]["id"]:
                    seen_next = True
                if seen_next and le["state"] not in ("completed", "perfect") and le["kind"] != "level_test":
                    if not le["ready"]:
                        ids.append(le["id"])
                    if len(ids) >= n:
                        return ids
    return ids


def next_cefr(cefr: str) -> str:
    i = level_index(cefr)
    return CEFR[min(i + 1, len(CEFR) - 1)]
