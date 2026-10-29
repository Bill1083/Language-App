"""Japanese writing-systems lessons, built from curriculum/ja_kana.yaml
without the LLM (deterministic, free, and instantly available)."""

import random
from functools import lru_cache
from typing import Any

from ..config import get_settings
from .yaml_loader import load_yaml_file

SCRIPTS = ("hiragana", "katakana")
# Bump when the builder's output changes: it is part of each kana lesson's
# skeleton, so a new version makes existing kana lessons rebuild on next visit.
BUILDER_VERSION = 2


@lru_cache
def kana_data() -> dict[str, Any]:
    return load_yaml_file(get_settings().curriculum_dir / "ja_kana.yaml")


def _chars(lesson: dict[str, Any]) -> list[dict[str, str]]:
    """[kana, romaji, mnemonic, optional example to play instead of the bare sign]"""
    return [{"char": str(c[0]), "romaji": str(c[1]), "mnemonic": str(c[2]),
             "audio_text": str(c[3]) if len(c) > 3 else str(c[0])} for c in lesson["chars"]]


def _words(lesson: dict[str, Any]) -> list[dict[str, str]]:
    return [{"word": str(w[0]), "romaji": str(w[1]), "meaning": str(w[2])} for w in lesson.get("words", [])]


def lesson_chars(script: str, index: int) -> list[dict[str, str]]:
    """Characters a kana lesson teaches that make sense as review cards."""
    return _drillable(_chars(kana_data()[script]["lessons"][index]))


def all_chars(script: str, upto: int | None = None) -> list[dict[str, str]]:
    lessons = kana_data()[script]["lessons"]
    out: list[dict[str, str]] = []
    for lesson in lessons[: upto if upto is not None else len(lessons)]:
        out.extend(_chars(lesson))
    return out


def _drillable(chars: list[dict[str, str]]) -> list[dict[str, str]]:
    return [c for c in chars if not c["romaji"].startswith("(")]


def _choice(rng: random.Random, target: dict[str, str], pool: list[dict[str, str]], mode: str) -> dict[str, Any]:
    field = "romaji" if mode == "char_to_romaji" else "char"
    seen = {target[field]}
    distractors: list[str] = []
    for c in rng.sample(pool, len(pool)):
        if c[field] not in seen:
            seen.add(c[field])
            distractors.append(c[field])
        if len(distractors) == 3:
            break
    options = distractors + [target[field]]
    rng.shuffle(options)
    return {
        "type": "kana_choice",
        "mode": mode,
        "char": target["char"],
        "romaji": target["romaji"],
        "options": options,
        "answer_index": options.index(target[field]),
        "explanation": f"{target['char']} is read “{target['romaji']}”. {target['mnemonic']}",
    }


def build_kana_lesson(script: str, index: int, seed: int) -> dict[str, Any]:
    """Content for lesson `index` (0-based) of a script, or the script test when index == -1."""
    rng = random.Random(seed)
    data = kana_data()[script]
    if index == -1:
        pool = _drillable(all_chars(script))
        targets = rng.sample(pool, min(20, len(pool)))
        exercises: list[dict[str, Any]] = []
        for i, t in enumerate(targets):
            if i % 4 == 3:
                options = [t["char"]] + [c["char"] for c in rng.sample([p for p in pool if p["char"] != t["char"]], 3)]
                rng.shuffle(options)
                exercises.append({"type": "listening_choice", "audio_text": t["char"], "options": options,
                                  "options_lang": "target", "answer_index": options.index(t["char"]),
                                  "explanation": f"You heard {t['char']} ({t['romaji']})."})
            else:
                exercises.append(_choice(rng, t, pool, "char_to_romaji" if i % 2 == 0 else "romaji_to_char"))
        return {"intro": f"Show what you know: {len(exercises)} questions on all of {data['title']}. "
                         "Score 80% or more to pass.", "vocab": [], "grammar": [], "pronunciation": [],
                "exercises": exercises, "is_test": True, "pass_mark": 0.8}

    lesson = data["lessons"][index]
    chars = _chars(lesson)
    pool = _drillable(all_chars(script, index + 1))
    exercises = []
    # Introduce in pairs, drilling each pair straight away, then mix.
    for start in range(0, len(chars), 2):
        group = chars[start : start + 2]
        for c in group:
            exercises.append({"type": "kana_intro", "char": c["char"], "romaji": c["romaji"],
                              "mnemonic": c["mnemonic"], "script": script, "audio_text": c["audio_text"]})
        for c in _drillable(group):
            exercises.append(_choice(rng, c, pool, "char_to_romaji"))
    drill = _drillable(chars)
    for c in rng.sample(drill, len(drill)):
        exercises.append(_choice(rng, c, pool, "romaji_to_char"))
    for c in rng.sample(drill, min(3, len(drill))):
        options = [c["char"]] + [p["char"] for p in rng.sample([p for p in pool if p["char"] != c["char"]],
                                                              min(3, len(pool) - 1))]
        rng.shuffle(options)
        exercises.append({"type": "listening_choice", "audio_text": c["char"], "options": options,
                          "options_lang": "target", "answer_index": options.index(c["char"]),
                          "explanation": f"You heard {c['char']} ({c['romaji']})."})
    if len(drill) >= 3:
        exercises.append({"type": "match_pairs", "explanation": "",
                          "pairs": [{"left": c["char"], "right": c["romaji"]} for c in drill[:5]]})
    words = _words(lesson)
    vocab = [{"word": w["word"], "reading": w["word"], "romaji": w["romaji"], "meaning": w["meaning"]} for w in words]
    exercises.extend({"type": "vocab_intro", "vocab": v} for v in vocab)
    for w in words[:3]:
        others = [x["meaning"] for x in words if x["word"] != w["word"]][:3]
        if len(others) < 2:
            continue
        options = [w["meaning"]] + others
        rng.shuffle(options)
        exercises.append({"type": "multiple_choice", "prompt": "Sound it out — what does it mean?",
                          "question": w["word"], "question_lang": "target", "options": options,
                          "options_lang": "en", "answer_index": options.index(w["meaning"]),
                          "explanation": f"{w['word']} reads “{w['romaji']}” and means “{w['meaning']}”."})
    return {
        "intro": f"Learn {', '.join(c['char'] for c in chars)} — then read your first words with them.",
        "vocab": vocab, "grammar": [], "pronunciation": [], "exercises": exercises,
    }
