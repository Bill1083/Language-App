"""Seed the course skeleton from curriculum/*.yaml into the database.

Runs on every API start. Idempotent: rows are matched by slug. When a lesson's
skeleton changes in YAML its generated content is invalidated (unless an admin
hand-edited it), so the next visit regenerates it.
"""

import hashlib
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Language, Lesson, Level, Scenario, Unit
from .kana import BUILDER_VERSION, SCRIPTS, kana_data
from .languages import CEFR, LANGUAGES
from .yaml_loader import load_yaml_file

log = logging.getLogger("parlo.curriculum")
COURSE_FILES = ("fr", "it", "ja")


def skeleton_hash(skeleton: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(skeleton, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_course(lang: str) -> dict[str, Any]:
    return load_yaml_file(get_settings().curriculum_dir / f"{lang}.yaml")


class _Upserter:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.levels: dict[tuple[str, str], Level] = {}
        self.units: dict[str, Unit] = {}
        self.lessons: dict[str, Lesson] = {}

    async def load(self) -> None:
        for lv in (await self.db.execute(select(Level))).scalars():
            self.levels[(lv.language_code, lv.cefr)] = lv
        for u in (await self.db.execute(select(Unit))).scalars():
            self.units[u.slug] = u
        for le in (await self.db.execute(select(Lesson))).scalars():
            self.lessons[le.slug] = le

    async def level(self, lang: str, cefr: str, order: int) -> Level:
        lv = self.levels.get((lang, cefr))
        if lv is None:
            lv = Level(language_code=lang, cefr=cefr, order=order)
            self.db.add(lv)
            await self.db.flush()
            self.levels[(lang, cefr)] = lv
        lv.order = order
        return lv

    async def unit(self, slug: str, level: Level, order: int, title: str, theme: str, objectives: list[str]) -> Unit:
        u = self.units.get(slug)
        if u is None:
            u = Unit(slug=slug, level_id=level.id, order=order, title=title, theme=theme, objectives_json=objectives)
            self.db.add(u)
            await self.db.flush()
            self.units[slug] = u
        else:
            u.level_id, u.order, u.title, u.theme, u.objectives_json = level.id, order, title, theme, objectives
        return u

    def lesson(self, slug: str, unit: Unit, order: int, kind: str, title: str, skeleton: dict[str, Any]) -> Lesson:
        h = skeleton_hash(skeleton)
        le = self.lessons.get(slug)
        if le is None:
            le = Lesson(slug=slug, unit_id=unit.id, order=order, kind=kind, title=title, skeleton_json=skeleton,
                        skeleton_hash=h, status="pending")
            self.db.add(le)
            self.lessons[slug] = le
            return le
        le.unit_id, le.order, le.kind, le.title = unit.id, order, kind, title
        if le.skeleton_hash != h:
            le.skeleton_json, le.skeleton_hash = skeleton, h
            if not le.edited and le.status in ("ready", "failed"):
                le.status = "pending"  # regenerate from the new skeleton on next visit
        return le


async def seed_curriculum(db: AsyncSession) -> None:
    up = _Upserter(db)
    await up.load()
    existing_langs = {lang.code for lang in (await db.execute(select(Language))).scalars()}
    for code in COURSE_FILES:
        if code not in existing_langs:
            db.add(Language(code=code, name=LANGUAGES[code]["name"], enabled=True))
    await db.flush()

    for code in COURSE_FILES:
        course = load_course(code)
        lessons_count = 0
        if code == "ja":
            await _seed_kana(up)
        for level_order, cefr in enumerate(CEFR, start=1):
            units = (course.get("levels") or {}).get(cefr) or []
            level = await up.level(code, cefr, level_order)
            for u_order, unit_data in enumerate(units, start=1):
                slug = f"{code}-{cefr}-u{u_order:02d}".lower()
                unit = await up.unit(slug, level, u_order, unit_data["unit"], unit_data.get("theme", ""),
                                     unit_data.get("objectives", []))
                for l_order, lesson in enumerate(unit_data.get("lessons", []), start=1):
                    skeleton = {
                        "title": lesson["title"],
                        "objectives": lesson.get("objectives", []),
                        "vocab": lesson.get("vocab", []),
                        "grammar": lesson.get("grammar", []),
                    }
                    up.lesson(f"{slug}-l{l_order}", unit, l_order, "lesson", lesson["title"], skeleton)
                    lessons_count += 1
                up.lesson(f"{slug}-cp", unit, 100, "checkpoint", f"Checkpoint: {unit_data['unit']}",
                          {"unit": unit_data["unit"]})
            if units:
                test_unit = await up.unit(f"{code}-{cefr}-test".lower(), level, 99, f"{cefr} level test", "test",
                                          [f"Show you've mastered {cefr} to unlock the next level"])
                up.lesson(f"{code}-{cefr}-test".lower(), test_unit, 1, "level_test", f"{cefr} level test",
                          {"level": cefr})
        log.info("seeded %s: %d lessons", code, lessons_count)
    await seed_scenarios(db)
    await db.commit()


async def _seed_kana(up: _Upserter) -> None:
    data = kana_data()
    level = await up.level("ja", "PRE", 0)
    for u_order, script in enumerate(SCRIPTS, start=1):
        s = data[script]
        unit = await up.unit(f"ja-pre-{script}", level, u_order, s["title"], "writing", s.get("objectives", []))
        # The whole lesson definition (and the builder version) goes into the
        # skeleton, so editing ja_kana.yaml or the builder rebuilds the lesson.
        for i, lesson in enumerate(s["lessons"]):
            up.lesson(f"ja-pre-{script}-l{i + 1}", unit, i + 1, "kana", lesson["title"],
                      {"script": script, "index": i, "chars": lesson["chars"], "words": lesson.get("words", []),
                       "builder": BUILDER_VERSION})
        up.lesson(f"ja-pre-{script}-test", unit, 100, "kana", s["test"]["title"],
                  {"script": script, "index": -1, "test": True, "chars": [c for les in s["lessons"] for c in les["chars"]],
                   "builder": BUILDER_VERSION})


async def seed_scenarios(db: AsyncSession) -> None:
    items = load_yaml_file(get_settings().curriculum_dir / "scenarios.yaml") or []
    existing = {s.slug: s for s in (await db.execute(select(Scenario).where(Scenario.unit_id.is_(None)))).scalars()}
    for item in items:
        s = existing.get(item["slug"]) or Scenario(slug=item["slug"])
        s.title, s.emoji, s.description = item["title"], item.get("emoji", "💬"), item["description"]
        s.goal, s.ai_role, s.user_role = item["goal"], item["ai_role"], item["user_role"]
        s.min_level = item.get("min_level", "A1")
        s.language_code = item.get("language")
        s.system_prompt_template = item.get("notes", "")
        if s.id is None:
            db.add(s)
