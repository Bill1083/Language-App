"""The authored skeletons and the kana module must stay well-formed."""

import pytest
import yaml

from app.config import get_settings
from app.services.curriculum import COURSE_FILES, load_course
from app.services.jobs import lesson_audio_texts
from app.services.kana import SCRIPTS, build_kana_lesson, kana_data
from app.services.languages import CEFR

LEVEL_FIELDS = {"unit", "theme", "objectives", "lessons"}


@pytest.mark.parametrize("lang", COURSE_FILES)
def test_course_skeleton_is_complete(lang):
    course = load_course(lang)
    assert course["language"] == lang
    levels = course["levels"]
    assert list(levels) == CEFR
    titles = set()
    for cefr, units in levels.items():
        assert 8 <= len(units) <= 12, f"{lang} {cefr}: {len(units)} units"
        for unit in units:
            assert LEVEL_FIELDS <= set(unit), f"{lang} {cefr} unit missing fields: {unit.get('unit')}"
            assert 4 <= len(unit["lessons"]) <= 6, f"{lang} {cefr} {unit['unit']}"
            for lesson in unit["lessons"]:
                assert lesson["title"] and lesson["objectives"], lesson
                assert len(lesson["vocab"]) >= 4, f"{lang} {cefr} {lesson['title']}: too little vocab"
                assert lesson["grammar"], f"{lang} {cefr} {lesson['title']}: no grammar point"
                titles.add((cefr, unit["unit"], lesson["title"]))


def test_scenarios_file():
    items = yaml.safe_load((get_settings().curriculum_dir / "scenarios.yaml").read_text(encoding="utf-8"))
    slugs = [i["slug"] for i in items]
    assert len(slugs) == len(set(slugs)) >= 10
    for i in items:
        assert {"title", "description", "goal", "ai_role", "user_role", "min_level"} <= set(i)
        assert i["min_level"] in CEFR


@pytest.mark.parametrize("script", SCRIPTS)
def test_kana_lessons_build(script):
    data = kana_data()[script]
    for idx in range(len(data["lessons"])):
        content = build_kana_lesson(script, idx, seed=idx)
        types = {e["type"] for e in content["exercises"]}
        assert {"kana_intro", "kana_choice"} <= types
        for ex in content["exercises"]:
            if "answer_index" in ex:
                assert 0 <= ex["answer_index"] < len(ex["options"])
                assert len(set(ex["options"])) == len(ex["options"])
    test = build_kana_lesson(script, -1, seed=1)
    assert test["is_test"] and len(test["exercises"]) == 20


def test_kana_words_only_use_taught_characters():
    taught: set[str] = set()
    for script in SCRIPTS:
        for lesson in kana_data()[script]["lessons"]:
            taught |= {ch for c in lesson["chars"] for ch in c[0]}
            taught |= {"ゃ", "ゅ", "ょ", "ャ", "ュ", "ョ", "ァ", "ィ"}
            for word in lesson.get("words", []):
                missing = {ch for ch in word[0] if ch not in taught}
                assert not missing, f"{lesson['title']}: {word[0]} uses untaught {missing}"


def test_audio_texts_for_precache():
    content = build_kana_lesson("hiragana", 0, seed=3)
    texts = lesson_audio_texts(content["exercises"], "ja")
    assert "あ" in texts and len(texts) == len(set(texts))
