"""Japanese content checks: furigana readings against KANJIDIC, markup, tiles, vocab readings."""

import pytest

from app.services.ja_check import accept_repair, autofix, check_lesson, check_text, plausible_reading


@pytest.mark.parametrize("base,reading", [
    ("学校", "がっこう"), ("一緒", "いっしょ"), ("結婚", "けっこん"), ("日曜日", "にちようび"), ("何時", "なんじ"),
    ("三百", "さんびゃく"), ("六百", "ろっぴゃく"), ("一本", "いっぽん"), ("三本", "さんぼん"), ("十分", "じゅっぷん"),
    ("友達", "ともだち"), ("大丈夫", "だいじょうぶ"), ("時々", "ときどき"), ("毎朝", "まいあさ"),
    ("今日", "きょう"), ("明日", "あした"), ("お土産", "おみやげ"), ("大人", "おとな"), ("一人", "ひとり"),
    ("日本", "にほん"), ("食べ", "たべ"), ("生まれ", "うまれ"), ("手伝", "てつだ"), ("先生", "せんせい"),
    ("電話番号", "でんわばんごう"), ("お母さん", "おかあさん"), ("何", "なに"), ("何", "なん"), ("私", "わたし"),
    ("四", "よん"), ("七", "なな"), ("九", "きゅう"), ("円", "えん"), ("駅", "えき"), ("行", "い"), ("来", "き"),
])
def test_real_readings_pass(base, reading):
    assert plausible_reading(base, reading), (base, reading)


@pytest.mark.parametrize("base,reading", [
    ("先生", "せんせ"), ("駅", "えきい"), ("日本", "にほんご"), ("食べ", "たへ"), ("電車", "でんわ"),
    ("水", "かわ"), ("猫", "いぬ"), ("学校", "がくせい"),
])
def test_wrong_readings_fail(base, reading):
    assert not plausible_reading(base, reading), (base, reading)


def test_text_checks_find_missing_furigana_bad_markup_and_romaji():
    kinds = lambda text: sorted(i.kind for i in check_text(text, "x"))  # noqa: E731
    assert kinds("{私|わたし}は{学生|がくせい}です。") == []
    assert kinds("私は{学生|がくせい}です。") == ["no_furigana"]
    assert kinds("{私|わたし}は{学生|がくせ}です。") == ["reading"]
    assert kinds("{私|わたし は学生です") == ["markup", "no_furigana"]
    assert kinds("{です|です}") == ["kana_furigana"]
    assert kinds("watashi wa {学生|がくせい}です") == ["romaji"]
    assert kinds("Tシャツを{買|か}います。") == []


def test_lesson_checks_cover_vocab_readings_and_word_bank_tiles():
    content = {
        "vocab": [{"word": "{名前|なまえ}", "reading": "なまい", "meaning": "name",
                   "example": "お{名前|なまえ}は？"}],
        "exercises": [
            {"type": "word_bank", "prompt": "I am a student.", "answer": "{私|わたし}は{学生|がくせい}です。",
             "answer_tiles": ["{私|わたし}は", "{学生|がくせい}"], "distractors": []},
            {"type": "multiple_choice", "question": "猫", "question_lang": "target", "options": ["cat", "dog"],
             "options_lang": "en", "answer_index": 0},
            {"type": "translate", "direction": "to_english", "source": "{駅|えき}はどこですか。", "answers": ["x"]},
        ],
    }
    kinds = {i.kind for i in check_lesson(content)}
    assert kinds == {"vocab_reading", "tiles", "no_furigana"}


def test_autofix_takes_readings_from_furigana_and_unmarks_kana():
    content = {"vocab": [{"word": "{名前|なまえ}", "reading": "なまい", "example": "{です|です}"}], "exercises": []}
    assert autofix(content) == 2
    assert content["vocab"][0]["reading"] == "なまえ" and content["vocab"][0]["example"] == "です"


def test_a_word_keeps_the_reading_its_vocab_card_teaches():
    # こんにち is a real reading of 今日, so only the lesson's own vocab can tell it's wrong here
    content = {"vocab": [{"word": "{今日|きょう}", "reading": "きょう", "example": "{今日|きょう}は{暑|あつ}い。"}],
               "exercises": [{"type": "dictation", "text": "{今日|こんにち}は{雨|あめ}です。", "translation": "x"}]}
    issues = check_lesson(content)
    assert [i.kind for i in issues] == ["reading"] and "こんにち" in issues[0].detail


def test_scan_findings_are_caught_and_false_alarms_are_not():
    kinds = lambda text, where="x": sorted(i.kind for i in check_text(text, where))  # noqa: E731
    severity = lambda text, where: [i.severity for i in check_text(text, where)]  # noqa: E731
    assert kinds("{先生|せん・せい}です") == ["markup"]  # dotted readings show up for learners
    assert kinds("{四|___}つ") == ["markup"] and kinds("{___|なな}") == ["markup"]
    assert kinds("降|ふります") == ["markup", "no_furigana"]
    assert kinds("お{父|とう}さんは{元気|げんき}です") == []  # 父さん is read とうさん as a whole
    # alternative typed answers are matched without furigana, so missing furigana there is only a warning
    assert severity("{私|わたし}は友達です", "exercises[3].accepted[1]") == ["warning"]
    assert severity("{私|わたし}は友達です", "exercises[3].answers[0]") == ["error"]


def test_autofix_removes_dots_and_repairs_are_only_accepted_if_the_text_is_unchanged():
    content = {"vocab": [{"word": "{注文|ちゅう・もん}", "reading": "ちゅうもん"}], "exercises": []}
    autofix(content)
    assert content["vocab"][0]["word"] == "{注文|ちゅうもん}" and not check_lesson(content)
    assert accept_repair("私は学生です", "{私|わたし}は{学生|がくせい}です")
    assert not accept_repair("私は学生です", "{私|わたし}は{先生|せんせい}です")  # changed a word
    assert not accept_repair("私は学生です", "{私|わたし}は学生です")  # still missing furigana


def test_readings_are_judged_in_context():
    # per-kanji furigana: 千 is voiced after 三 (さんぜん), 一 is doubled before 本 (いっぽん)
    assert check_text("{三|さん}{千|ぜん}{円|えん}です。", "x") == []
    assert check_text("{一|いっ}{本|ぽん}ください。", "x") == []
    # a fill-in option is read in its sentence: お___さん + {父|とう} = お父さん
    ex = {"type": "fill_blank", "sentence": "お___さんは{元気|げんき}ですか。", "answers": ["{父|とう}"],
          "options": ["{母|かあ}", "{父|とう}", "水"]}
    issues = check_lesson({"exercises": [ex]})
    assert [(i.kind, i.where) for i in issues] == [("no_furigana", "exercises[0].options[2]")]


def test_repairs_of_broken_markup_keep_the_visible_text():
    assert accept_repair("{一日}", "{一日|ついたち}")
    assert accept_repair("本当|ほんとう", "{本当|ほんとう}")
    assert accept_repair("〜人 (にん)", "〜{人|にん}")
    assert accept_repair("降|ふります", "{降|ふ}ります")
    assert not accept_repair("{一日}", "{二日|ふつか}")
