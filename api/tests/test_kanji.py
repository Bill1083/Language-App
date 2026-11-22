"""Kanji layer: data file, helpers and where intro cards go in a lesson."""

import json
from types import SimpleNamespace

from app.config import get_settings
from app.services.curriculum import load_course
from app.services.kanji import format_kun, kanji_chars, lesson_kanji, place_intro_cards


def test_kanji_chars_reads_through_furigana_without_repeats():
    assert kanji_chars("{日本|にほん}の{日曜日|にちようび}") == ["日", "本", "曜"]
    assert kanji_chars("ひらがなだけ") == []


def test_kun_readings_show_okurigana_in_brackets():
    assert format_kun("た.べる") == "た(べる)"
    assert format_kun("-び") == "び"
    assert format_kun("ひと") == "ひと"


def test_every_kanji_in_the_course_has_dictionary_data():
    data = json.loads((get_settings().curriculum_dir / "kanji.json").read_text(encoding="utf-8"))
    assert data["_source"].startswith("KANJIDIC2")
    course = load_course("ja")
    words = [w for units in course["levels"].values() for u in units for le in u["lessons"] for w in le["vocab"]]
    missing = {c for w in words for c in kanji_chars(str(w))} - set(data)
    assert not missing
    hi = data["日"]
    assert "day" in hi["m"] and "ニチ" in hi["on"] and hi["s"] == 4


def test_lesson_kanji_comes_from_the_course_words():
    lesson = SimpleNamespace(skeleton_json={"vocab": ["日本", "日本人", "イギリス", "会社員"]})
    assert lesson_kanji(lesson) == ["日", "本", "人", "会", "社", "員"]


def test_intro_cards_sit_just_before_the_first_exercise_using_them():
    exercises = [
        {"id": 1, "type": "vocab_intro", "vocab": {"word": "{日本|にほん}"}},
        {"id": 2, "type": "vocab_intro", "vocab": {"word": "{会社員|かいしゃいん}"}},
        {"id": 3, "type": "multiple_choice", "question": "{日本人|にほんじん}"},
    ]
    cards = [{"id": -1, "type": "kanji_intro", "char": "日"}, {"id": -2, "type": "kanji_intro", "char": "本"},
             {"id": -3, "type": "kanji_intro", "char": "社"},
             {"id": -99, "type": "kanji_more", "chars": ["人", "会"]}]
    order = [e["id"] for e in place_intro_cards(exercises, cards)]
    # 日 then 本 before the first word using them; 社 and the overview of 会 before 会社員;
    # 人 is also in the overview, which goes where its first kanji appears.
    assert order == [-1, -2, 1, -3, -99, 2, 3]


def test_example_sentences_and_notes_do_not_count_as_using_a_kanji():
    exercises = [
        {"id": 1, "type": "vocab_intro", "vocab": {"word": "{私|わたし}", "example": "{私|わたし}は{学生|がくせい}です。"}},
        {"id": 2, "type": "grammar_note", "grammar": {"examples": [{"target": "{学生|がくせい}"}]}},
        {"id": 3, "type": "vocab_intro", "vocab": {"word": "{学生|がくせい}"}},
    ]
    order = [e["id"] for e in place_intro_cards(exercises, [{"id": -1, "type": "kanji_intro", "char": "学"}])]
    assert order == [1, 2, -1, 3]
