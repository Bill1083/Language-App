"""AI conversation practice: prompts, streamed replies, per-turn feedback,
pronunciation flags, helpers (hint / how-do-I-say / translate / lookup) and
the end-of-session summary."""

import json
import re
from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Conversation, ConversationTurn, Scenario, UserVocab, VocabItem
from ..providers.base import ChatMessage
from ..schemas.feedback import Feedback
from .answer_check import normalize, strip_accents
from .languages import LANGUAGE_RULES, LANGUAGES, LEVEL_GUIDE, REPLY_LENGTH
from .text import strip_ruby

HISTORY_TURNS = 30
START_TOKEN = "(The conversation begins now. Say your opening line, in character.)"

DEFAULT_SETTINGS = {
    "input": "voice", "ai_voice": True, "speed": 1.0, "voice_gender": "female", "politeness": "polite",
    "furigana": "always", "romaji": "auto", "strictness": "normal", "feedback": True, "topic": "",
}


# --------------------------------------------------------------------------- prompts


def _ja_rules(settings: dict[str, Any]) -> str:
    register = ("polite です/ます style" if settings.get("politeness", "polite") == "polite"
                else "casual plain form (like friends talking)")
    return (f"Use {register}. Write natural Japanese with kanji, and put furigana markup on EVERY word containing "
            "kanji, as {漢字|かな} — e.g. {今日|きょう}は{何|なに}を{食|た}べますか。 Never use romaji.")


async def known_vocab_sample(db: AsyncSession, user_id: int, lang: str, limit: int = 120) -> list[str]:
    rows = await db.scalars(
        select(VocabItem.lemma).join(UserVocab, UserVocab.vocab_item_id == VocabItem.id)
        .where(UserVocab.user_id == user_id, VocabItem.language_code == lang)
        .order_by(UserVocab.learned_at.desc()).limit(limit))
    return list(rows)


def system_prompt(conv: Conversation, scenario: Scenario | None, known: list[str]) -> str:
    lang = conv.language_code
    meta = LANGUAGES[lang]
    settings = {**DEFAULT_SETTINGS, **(conv.settings_json or {})}
    level = conv.level
    if conv.mode == "tutor":
        prompt = (
            f"You are a patient, encouraging {meta['name']} tutor for a native English speaker at CEFR {level}. "
            f"The learner asks questions in English about {meta['name']} grammar, vocabulary, culture and usage. "
            f"Answer in clear, friendly English with short {meta['name']} examples, each followed by its English "
            "translation in parentheses. If the learner writes in "
            f"{meta['name']}, reply to it, then briefly point out and explain any mistakes. Keep answers under "
            "150 words unless they ask for more. Plain text only — no markdown headings or tables."
        )
        if lang == "ja":
            prompt += " Put furigana markup on Japanese kanji as {漢字|かな}."
        return prompt

    if conv.mode in ("scenario", "unit") and scenario:
        situation = (
            f"Role-play scenario: {scenario.description}\nSetting: {meta['city']}, {meta['country']}.\n"
            f"You play: {scenario.ai_role}.\nThe learner plays: {scenario.user_role}.\n"
            f"The learner's goal: {scenario.goal}. Let them work towards it naturally — respond as your character "
            "would, and don't do the task for them. When the goal is complete, wrap up the scene politely."
        )
        if scenario.system_prompt_template:
            situation += f"\n{scenario.system_prompt_template}"
    else:
        topic = settings.get("topic") or "everyday life — work, hobbies, food, travel, plans"
        situation = (
            f"You are a friendly local from {meta['city']} chatting with the learner. Talk naturally about: {topic}. "
            "Show interest, share small details about yourself and ask questions."
        )

    rules = [
        f"Speak ONLY {meta['name']}. Never switch to English, even if the learner does — if they use English, "
        f"answer in simple {meta['name']}.",
        f"Learner level: CEFR {level} ({LEVEL_GUIDE.get(level, '')}). Keep each reply to "
        f"{REPLY_LENGTH.get(level, '1–3 sentences')}.",
        "Never correct the learner's mistakes or comment on their language — feedback is handled separately. "
        "Respond to what they meant.",
        "Keep the conversation moving: if the learner gives a short answer, ask a simple follow-up question.",
        "Stay in character. Plain text only — no markdown, emojis, stage directions or translations.",
    ]
    if known:
        rules.append("Where natural, reuse words the learner knows: " + ", ".join(known[:120]) + ".")
    if lang == "ja":
        rules.append(_ja_rules(settings))
    return situation + "\n\nRules:\n- " + "\n- ".join(rules)


def history_messages(turns: list[ConversationTurn]) -> list[ChatMessage]:
    msgs = [ChatMessage("user", START_TOKEN)]
    for t in turns[-HISTORY_TURNS:]:
        msgs.append(ChatMessage("assistant" if t.role == "assistant" else "user", t.text))
    return msgs


STRICTNESS = {
    "gentle": "GENTLE: flag only errors that change the meaning or are clearly ungrammatical. Ignore style, "
              "naturalness and small slips. Leave more_natural null unless the sentence is very unnatural.",
    "normal": "NORMAL: flag every grammar, vocabulary, spelling, agreement and conjugation error. Mention "
              "naturalness in more_natural only when the sentence is clearly unidiomatic.",
    "strict": "STRICT: flag everything, including naturalness, register, word choice and missing accents; always "
              "give more_natural.",
}


def feedback_system(conv: Conversation, scenario: Scenario | None, voice: bool) -> str:
    lang = conv.language_code
    meta = LANGUAGES[lang]
    settings = {**DEFAULT_SETTINGS, **(conv.settings_json or {})}
    goal_field = ', "goal_achieved": true|false' if scenario and conv.mode in ("scenario", "unit") else ""
    parts = [
        f"You are an expert {meta['name']} teacher giving feedback on ONE message from a learner (CEFR {conv.level}, "
        "native English speaker) in a practice conversation.",
        "Strictness — " + STRICTNESS.get(settings.get("strictness", "normal"), STRICTNESS["normal"]),
    ]
    if voice:
        parts.append("The message was spoken and then transcribed verbatim by speech recognition: ignore "
                     "punctuation and capitalisation. Words marked [?] were unclear in the audio — don't count them "
                     "as errors unless clearly wrong.")
    if lang == "ja":
        expected = "polite です/ます" if settings.get("politeness", "polite") == "polite" else "casual plain"
        parts.append(f"Check particles, verb forms and politeness ({expected} style is expected — flag "
                     "inconsistency as type politeness). Use {漢字|かな} furigana markup in corrected and more_natural.")
    else:
        parts.append(LANGUAGE_RULES[lang].split(":")[0] + ": check gender/article agreement, conjugation and accents.")
    parts.append(f"""Return ONE JSON object:
{{"overall": "perfect"|"minor_issues"|"errors", "score": 0-100, "corrected": "…", "more_natural": "…" or null,
 "errors": [{{"type": "grammar|vocabulary|spelling|gender|conjugation|particle|word_order|politeness|accent",
             "original": "<exact wrong fragment copied from the learner's message>", "correction": "<fixed fragment>",
             "explanation": "<one short English sentence>"}}],
 "praise": "<one specific thing done well>" or null,
 "new_vocab": [{{"word": "…", "reading": "<kana reading for Japanese, else null>", "meaning": "…"}}]{goal_field}}}
Rules:
- corrected = the learner's message with the minimum changes needed, keeping their meaning. If it was already
  correct, repeat it unchanged and use overall "perfect" with no errors.
- One error object per distinct mistake. "original" must appear verbatim in the learner's message.
- score: 100 perfect; minor issues 70–95; real errors below 70 depending on severity and count.
- If the learner wrote (mostly) in English, overall "errors", score ≤ 20, corrected = how to say it in {meta['name']}.
- new_vocab: up to 3 useful words from your corrections or more_natural version (empty list if none).
- Explanations are short, specific and kind.""")
    if goal_field and scenario:
        parts.append(f'goal_achieved: true only if, considering the whole conversation so far, the learner has now '
                     f'accomplished the scenario goal: "{scenario.goal}".')
    return "\n\n".join(parts)


def feedback_request(turns: list[ConversationTurn], turn: ConversationTurn) -> str:
    context = [{"speaker": "learner" if t.role == "user" else "partner", "text": t.text}
               for t in turns if t.id < turn.id][-8:]
    return json.dumps({"conversation_so_far": context, "learner_message": turn.text}, ensure_ascii=False, indent=1)


# --------------------------------------------------------------------------- pronunciation


_TOKEN = re.compile(r"[\w'’\-]+(?:\[\?\])?", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(strip_ruby(text))


def pronunciation_flags(transcript: str, corrected: str, lang: str, error_fragments: list[str],
                        words: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Possible pronunciation problems: words the recogniser marked unclear or
    heard with low confidence, and words that differ from the intended
    (corrected) sentence without being explained by a grammar error. This is an
    approximation from speech recognition, not phoneme-level assessment."""
    flags: list[dict[str, Any]] = []
    explained = {normalize(f, lang) for f in error_fragments if f}

    def is_explained(fragment: str) -> bool:
        n = normalize(fragment, lang)
        return any(n and (n in e or e in n) for e in explained)

    if lang == "ja":
        heard, meant = normalize(transcript.replace("[?]", ""), "ja"), normalize(strip_ruby(corrected), "ja")
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, heard, meant).get_opcodes():
            if tag == "replace" and not is_explained(heard[i1:i2]):
                flags.append({"heard": heard[i1:i2], "expected": meant[j1:j2], "reason": "mismatch"})
        for m in re.finditer(r"(\S{1,4})\[\?\]", transcript):
            flags.append({"heard": m.group(1), "expected": None, "reason": "unclear"})
        return flags[:6]

    heard_tokens = _tokens(transcript)
    meant_tokens = _tokens(corrected)
    clean = [t.replace("[?]", "") for t in heard_tokens]
    key = lambda t: strip_accents(normalize(t, lang))  # noqa: E731
    sm = SequenceMatcher(None, [key(t) for t in clean], [key(t) for t in meant_tokens])
    expected_for: dict[int, str] = {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            for k in range(i1, i2):
                expected_for[k] = " ".join(meant_tokens[j1:j2]) if i2 - i1 > 1 else meant_tokens[j1]
                if i2 - i1 == j2 - j1:
                    expected_for[k] = meant_tokens[j1 + (k - i1)]
    low_conf = {}
    for w in words or []:
        if w.get("confidence") is not None and w["confidence"] < 0.6:
            low_conf[key(w["word"])] = w["confidence"]
    for i, tok in enumerate(heard_tokens):
        word = clean[i]
        reason = None
        if tok.endswith("[?]"):
            reason = "unclear"
        elif key(word) in low_conf:
            reason = "low_confidence"
        elif i in expected_for and not is_explained(word):
            reason = "mismatch"
        if reason:
            flags.append({"heard": word, "expected": expected_for.get(i, word), "reason": reason,
                          "confidence": low_conf.get(key(word))})
    return flags[:6]


# --------------------------------------------------------------------------- helper schemas


class Suggestion(BaseModel):
    target: str
    english: str


class HintResult(BaseModel):
    suggestions: list[Suggestion] = Field(min_length=1, max_length=4)


class SayResult(BaseModel):
    target: str
    reading: str | None = None
    english: str
    notes: str | None = None
    alternatives: list[str] = Field(default_factory=list)


class LookupResult(BaseModel):
    word: str
    lemma: str
    reading: str | None = None
    meaning: str
    pos: str | None = None
    gender: str | None = None
    notes: str | None = None


class SummaryMistake(BaseModel):
    title: str
    explanation: str
    wrong: str | None = None
    right: str | None = None


class SummaryDraft(BaseModel):
    top_mistakes: list[SummaryMistake] = Field(default_factory=list, max_length=3)
    suggested_lessons: list[int] = Field(default_factory=list, max_length=2)
    suggested_drill: str | None = None
    encouragement: str = ""


def hint_system(conv: Conversation, scenario: Scenario | None) -> str:
    meta = LANGUAGES[conv.language_code]
    goal = f" Their goal: {scenario.goal}." if scenario else ""
    ja = " Use {漢字|かな} furigana markup on kanji." if conv.language_code == "ja" else ""
    return (f"A {meta['name']} learner at CEFR {conv.level} is stuck in a conversation.{goal} Suggest 2–3 short, "
            f"natural things they could say next, at their level, each with an English gloss.{ja} "
            'Return JSON: {"suggestions": [{"target": "…", "english": "…"}]}')


def say_system(lang: str, level: str, politeness: str) -> str:
    meta = LANGUAGES[lang]
    ja = (f" Use {'polite です/ます' if politeness == 'polite' else 'casual plain'} style, {{漢字|かな}} furigana "
          "markup, and give the full kana reading.") if lang == "ja" else ""
    return (f"Translate what a CEFR {level} learner wants to say into natural, simple {meta['name']} they could use "
            f"in conversation right now.{ja} Return JSON: "
            '{"target": "…", "reading": null, "english": "<the meaning>", "notes": "<short usage tip or null>", '
            '"alternatives": ["<another natural way>"]}')


def lookup_system(lang: str) -> str:
    meta = LANGUAGES[lang]
    return (f"You are a {meta['name']}–English learner's dictionary. Given a word as it appears in a sentence, return "
            "its dictionary form and meaning in this context. Return JSON: "
            '{"word": "<as given>", "lemma": "<dictionary form; nouns with article for French/Italian>", '
            '"reading": "<kana reading for Japanese, else null>", "meaning": "<short English meaning in context>", '
            '"pos": "<part of speech>", "gender": "m|f|null", "notes": "<one short note: conjugation/form, or null>"}')


def summary_system(lang: str, lessons: list[dict[str, Any]]) -> str:
    meta = LANGUAGES[lang]
    return (f"Summarise a {meta['name']} learner's practice conversation for them. You get every learner message with "
            "the errors already found. Group recurring mistakes into at most 3 themes (most frequent first) with a "
            "short English explanation and one wrong→right example each. Pick up to 2 lessons from the list that "
            "best target those weak spots (by id), suggest one short drill, and write one sentence of honest, warm "
            "encouragement. Lessons: " + json.dumps(lessons, ensure_ascii=False) + "\nReturn JSON: "
            '{"top_mistakes": [{"title": "…", "explanation": "…", "wrong": "…", "right": "…"}], '
            '"suggested_lessons": [<lesson id>], "suggested_drill": "…", "encouragement": "…"}')


def feedback_or_none(data: Any) -> Feedback | None:
    try:
        return Feedback.model_validate(data)
    except Exception:
        return None
