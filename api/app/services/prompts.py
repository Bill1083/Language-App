"""Prompt templates for content generation and answer judging."""

import json

from .languages import LANGUAGE_RULES, LANGUAGES, LEVEL_GUIDE

EXERCISE_SPEC = """Exercise objects (JSON). Every exercise has "type" and "explanation" (1–2 sentences on WHY the
answer is right — meaning, grammar rule or nuance; shown after the learner answers).

- {"type":"multiple_choice","prompt":"What does this mean?","question":"<text>","question_lang":"target"|"en",
   "options":["…","…","…","…"],"options_lang":"en"|"target","answer_index":0,"explanation":"…"}
- {"type":"listening_choice","audio_text":"<target sentence that is spoken>","options":["…","…","…"],
   "options_lang":"target"|"en","answer_index":0,"explanation":"…"}
- {"type":"word_bank","prompt":"<English sentence>","answer":"<target sentence>","answer_tiles":["…","…"],
   "distractors":["…","…"],"accepted":["<other correct target sentences>"],"explanation":"…"}
- {"type":"translate","direction":"to_target"|"to_english","source":"<sentence>","answers":["…","…"],"explanation":"…"}
- {"type":"fill_blank","sentence":"<target sentence with exactly one ___>","answers":["…"],"hint":"(base form)",
   "translation":"<English of the full sentence>","options":["…","…","…"] or null,
   "focus":"vocabulary|conjugation|article|particle|agreement|other","explanation":"…"}
- {"type":"match_pairs","pairs":[{"left":"<target>","right":"<English>"}, … 4–5 pairs],"explanation":""}
- {"type":"dictation","text":"<short target sentence>","translation":"…","accepted":[],"explanation":"…"}
- {"type":"speak","text":"<short target sentence to read aloud>","translation":"…","explanation":"…"}
- {"type":"reading","title":"…","passage":"<80–200 words>","translation":"…",
   "questions":[{"question":"<in English>","options":["…","…","…"],"answer_index":0}],"explanation":"…"}

Answer rules:
- "answers" / "accepted" must list EVERY reasonable correct variant: optional words, alternative word orders,
  contractions, tu/vous (or polite/plain) variants when the English is ambiguous, synonyms at this level.
  For to_english list several natural English renderings.
- Distractors are plausible for a learner but unambiguously wrong.
- word_bank.answer_tiles splits "answer" into tiles in order (words for French/Italian — keep elided forms
  like "l'" or "j'" attached to their word; natural chunks such as word+particle for Japanese).
- fill_blank: exactly one ___; use "options" for article / particle / conjugation choice drills.
- Put the answer in a random position — do not always use answer_index 0."""

LESSON_SYSTEM = """You are an expert {language} teacher and course author writing one lesson of a structured
course for English-speaking adults. Target CEFR level: {cefr} ({level_guide}).

Style:
- Natural, modern, everyday {language} — the way people actually speak, never stilted textbook phrasing.
- Explanations in clear, friendly English. Each grammar explanation is 2–5 short sentences, then examples.
- Restrict yourself to vocabulary the learner already knows (listed in the request) plus this lesson's new
  vocabulary, apart from unavoidable function words.
- {language_rules}

Return ONE JSON object:
{{
  "intro": "<1–2 sentences: what you'll be able to do after this lesson>",
  "vocab": [{{"word":"…","reading":null,"meaning":"<English>","pos":"noun|verb|adjective|adverb|phrase|…",
             "gender":"m|f|null","plural":null,"example":"<target sentence>","example_translation":"…",
             "emoji":"<one emoji or null>","note":"<usage note or null>"}}],
  "grammar": [{{"title":"…","explanation":"…","examples":[{{"target":"…","english":"…"}}],
               "table":{{"title":"…","headers":["…"],"rows":[["…"]]}} or null,"politeness":null}}],
  "pronunciation": ["<short tip>"],
  "exercises": [ {exercise_count} exercise objects ]
}}

{exercise_spec}

Mix at least six exercise types, ramp from recognition to production, and make sure every new vocab word
appears in at least one exercise. Include one "speak" exercise and one "dictation"."""

TEST_SYSTEM = """You are an expert {language} teacher writing a {what} for English-speaking adults at CEFR {cefr}
({level_guide}). It tests ONLY material already taught (listed in the request) — no new vocabulary or grammar.

- {language_rules}

Return ONE JSON object: {{"intro": "<one sentence>", "vocab": [], "grammar": [], "pronunciation": [],
"exercises": [ {exercise_count} exercise objects ]}}

{exercise_spec}

Cover every lesson listed, mix exercise types (no "speak" exercises — tests must be answerable silently), and
favour production (translate, fill_blank, word_bank) over recognition."""

PLACEMENT_SYSTEM = """You write adaptive placement tests for {language} learners whose native language is English.
Return JSON: {{"items": [ ... 30 items ... ]}} — exactly 6 items for each CEFR level A1, A2, B1, B2, C1.
Each item: {{"level":"A1","question":"<question>","question_lang":"target"|"en","options":["…","…","…","…"],
"answer_index":<0-3>,"skill":"grammar|vocabulary|reading"}}.
Questions are multiple choice: fill-the-gap sentences (use ___), "what does … mean", or a 1–3 sentence text with a
comprehension question. Each item must clearly discriminate its level. Vary the answer position. {language_rules}"""

UNIT_SCENARIO_SYSTEM = """Design a short role-play conversation scenario in {language} for a CEFR {cefr} learner,
practising the unit described in the request. The setting is {city}, {country}. Return JSON:
{{"title":"<short English title>","emoji":"<one emoji>","description":"<one English sentence setting the scene>",
"goal":"<a concrete task the learner must accomplish, in English, e.g. 'Order two coffees and ask for the bill'>",
"ai_role":"<who the AI plays, in English>","user_role":"<who the learner plays, in English>"}}"""

JUDGE_SYSTEM = """You check translations for a {language} course. Decide whether the learner's answer is a correct
and natural translation of the source, with the same meaning as the reference answers. Accept valid alternatives
(word order, synonyms, register) at CEFR {cefr}. Reject real grammar errors, wrong meaning, wrong tense or missing
content. Minor spelling slips in a correct structure are acceptable. Return JSON:
{{"correct": true|false, "explanation": "<one or two sentences in English; if wrong, say what is wrong>"}}"""


def lesson_system(lang: str, cefr: str, exercise_count: str = "12–16") -> str:
    return LESSON_SYSTEM.format(
        language=LANGUAGES[lang]["name"], cefr=cefr, level_guide=LEVEL_GUIDE.get(cefr, ""),
        language_rules=LANGUAGE_RULES[lang], exercise_count=exercise_count, exercise_spec=EXERCISE_SPEC,
    )


def test_system(lang: str, cefr: str, what: str, exercise_count: str) -> str:
    return TEST_SYSTEM.format(
        language=LANGUAGES[lang]["name"], cefr=cefr, level_guide=LEVEL_GUIDE.get(cefr, ""), what=what,
        language_rules=LANGUAGE_RULES[lang], exercise_count=exercise_count, exercise_spec=EXERCISE_SPEC,
    )


def lesson_request(unit_title: str, skeleton: dict, known_vocab: list[str]) -> str:
    return json.dumps({
        "unit": unit_title,
        "lesson": skeleton.get("title"),
        "objectives": skeleton.get("objectives", []),
        "new_vocab": skeleton.get("vocab", []),
        "grammar_points": skeleton.get("grammar", []),
        "already_known_vocab": known_vocab[-250:],
    }, ensure_ascii=False, indent=1)


def placement_system(lang: str) -> str:
    return PLACEMENT_SYSTEM.format(language=LANGUAGES[lang]["name"], language_rules=LANGUAGE_RULES[lang])


def unit_scenario_system(lang: str, cefr: str) -> str:
    meta = LANGUAGES[lang]
    return UNIT_SCENARIO_SYSTEM.format(language=meta["name"], cefr=cefr, city=meta["city"], country=meta["country"])


def judge_system(lang: str, cefr: str) -> str:
    return JUDGE_SYSTEM.format(language=LANGUAGES[lang]["name"], cefr=cefr)
