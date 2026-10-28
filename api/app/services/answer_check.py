"""Typed-answer checking (Section 5 "Answer checking").

Pipeline: normalise both sides → exact match → accent-only difference (FR/IT,
"almost correct") → typo tolerance on non-critical characters → wrong.
Free translations that still don't match are judged by the LLM in the router.

"Critical" differences are never forgiven as typos: short function words
(articles, particles, pronouns: le/la, il/lo, は/が) and differences confined
to a word's ending (conjugation and agreement: parle/parles, petit/petite).
"""

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal

from .text import ruby_reading, strip_ruby

Verdict = Literal["correct", "typo", "accent", "wrong"]

LATIN_PUNCT = re.compile(r"[.,!?;:¡¿…\"“”«»()\[\]{}/\\]")
JA_PUNCT = re.compile(r"[。、，．・！？!?「」『』（）()\[\]【】〜~…\s,.]")
APOSTROPHES = re.compile(r"[’‘ʼ`´]")
DASHES = re.compile(r"[-‐‑–—]")
JA_PARTICLES = set("はがをにでへともかのや")

EN_CONTRACTIONS = {
    "i'm": "i am", "you're": "you are", "we're": "we are", "they're": "they are", "he's": "he is",
    "she's": "she is", "it's": "it is", "that's": "that is", "what's": "what is", "there's": "there is",
    "don't": "do not", "doesn't": "does not", "didn't": "did not", "isn't": "is not", "aren't": "are not",
    "wasn't": "was not", "can't": "cannot", "can not": "cannot", "won't": "will not", "i'll": "i will",
    "you'll": "you will", "we'll": "we will", "i've": "i have", "you've": "you have", "we've": "we have",
    "i'd": "i would", "let's": "let us", "couldn't": "could not", "wouldn't": "would not",
    "shouldn't": "should not", "haven't": "have not", "hasn't": "has not",
}


@dataclass
class Segment:
    text: str
    kind: Literal["same", "accent", "typo"] = "same"


@dataclass
class CheckResult:
    verdict: Verdict
    matched: str | None = None  # the accepted answer (display form) the user was closest to
    segments: list[Segment] = field(default_factory=list)  # matched answer with problem words marked

    @property
    def is_correct(self) -> bool:
        return self.verdict != "wrong"


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def normalize(text: str, lang: str) -> str:
    text = unicodedata.normalize("NFC", strip_ruby(text)).strip()
    if lang == "ja":
        text = unicodedata.normalize("NFKC", text)  # full/half width
        return JA_PUNCT.sub("", text).lower()
    text = APOSTROPHES.sub("'", text).casefold()
    text = text.replace(" ", " ").replace(" ", " ")
    text = DASHES.sub(" ", text)
    text = LATIN_PUNCT.sub(" ", text)
    text = re.sub(r"\s*'\s*", "'", text)
    text = re.sub(r"\s+", " ", text).strip()
    if lang == "en":
        for short, full in EN_CONTRACTIONS.items():
            text = re.sub(rf"\b{re.escape(short)}\b", full, text)
    return text


def expand_alternatives(answer: str) -> list[str]:
    """'Je m'appelle (Marie)' → both with and without the optional part."""
    variants = {answer}
    if "(" in answer and ")" in answer:
        variants.add(re.sub(r"\s*\([^)]*\)", "", answer))
        variants.add(re.sub(r"[()]", "", answer))
    out: set[str] = set()
    for v in variants:
        out.add(strip_ruby(v))
        out.add(ruby_reading(v))  # Japanese: accept kana as well as kanji
    return [re.sub(r"\s+", " ", v).strip() for v in out if v.strip()]


def levenshtein(a: str, b: str) -> int:
    """Edit distance where swapping two adjacent letters counts as one edit
    (optimal string alignment) — "bonjuor" is one typo away from "bonjour"."""
    if a == b:
        return 0
    rows = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        rows[i][0] = i
    for j in range(len(b) + 1):
        rows[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            rows[i][j] = min(rows[i - 1][j] + 1, rows[i][j - 1] + 1, rows[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                rows[i][j] = min(rows[i][j], rows[i - 2][j - 2] + 1)
    return rows[-1][-1]


def _ending_only(a: str, b: str) -> bool:
    """True when two words differ only in their last two characters (inflection)."""
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return i >= min(len(a), len(b)) - 2


def _word_typo_ok(user: str, expected: str) -> bool:
    if len(user) <= 3 or len(expected) <= 3:
        return False  # articles, pronouns, short function words are critical
    if _ending_only(user, expected):
        return False  # conjugation / agreement
    allowed = 2 if len(expected) >= 9 else 1
    return levenshtein(user, expected) <= allowed


def _latin_compare(user: str, expected: str) -> tuple[Verdict, list[int], list[int]] | None:
    """Compare normalised Latin-script strings word by word.

    Returns the verdict plus indices of expected words with accent / typo issues,
    or None when the answer is simply wrong.
    """
    uw, ew = user.split(" "), expected.split(" ")
    if len(uw) != len(ew):
        return None
    accent_idx, typo_idx = [], []
    for i, (u, e) in enumerate(zip(uw, ew)):
        if u == e:
            continue
        if strip_accents(u) == strip_accents(e):
            accent_idx.append(i)
        elif _word_typo_ok(strip_accents(u), strip_accents(e)):
            typo_idx.append(i)
        else:
            return None
    if typo_idx:
        return "typo", accent_idx, typo_idx
    if accent_idx:
        return "accent", accent_idx, typo_idx
    return "correct", [], []


def _ja_typo_ok(user: str, expected: str) -> bool:
    if len(expected) < 6 or levenshtein(user, expected) != 1:
        return False
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, expected, user).get_opcodes():
        if tag != "equal":
            changed = set(expected[i1:i2]) | set(user[j1:j2])
            if changed & JA_PARTICLES:
                return False
    return True


def _segments(display: str, accent_idx: list[int], typo_idx: list[int]) -> list[Segment]:
    words = display.split(" ")
    segs: list[Segment] = []
    for i, w in enumerate(words):
        kind = "accent" if i in accent_idx else "typo" if i in typo_idx else "same"
        text = w if i == len(words) - 1 else w + " "
        if segs and segs[-1].kind == kind:
            segs[-1].text += text
        else:
            segs.append(Segment(text, kind))
    return segs


def check_answer(answer: str, accepted: list[str], lang: str, *, typo_tolerance: bool = True) -> CheckResult:
    """Check a typed answer against the accepted answers for a target language
    ("fr" | "it" | "ja") or English ("en")."""
    candidates: list[str] = []
    for acc in accepted:
        candidates.extend(expand_alternatives(acc))
    if not answer.strip() or not candidates:
        return CheckResult("wrong", strip_ruby(accepted[0]) if accepted else None)

    user = normalize(answer, lang)
    normed = [(c, normalize(c, lang)) for c in candidates]

    for display, n in normed:
        if user == n:
            return CheckResult("correct", display, [Segment(display)])

    if lang == "ja":
        if typo_tolerance:
            for display, n in normed:
                if _ja_typo_ok(user, n):
                    return CheckResult("typo", display, [Segment(display, "typo")])
        best = max(normed, key=lambda c: SequenceMatcher(None, user, c[1]).ratio())[0]
        return CheckResult("wrong", best, [Segment(best)])

    best_partial: CheckResult | None = None
    for display, n in normed:
        outcome = _latin_compare(user, n)
        if outcome is None:
            continue
        verdict, accent_idx, typo_idx = outcome
        if verdict == "typo" and not typo_tolerance:
            continue
        disp_words = display.split(" ")
        segs = _segments(display, accent_idx, typo_idx) if len(disp_words) == len(n.split(" ")) else [Segment(display)]
        result = CheckResult(verdict, display, segs)
        if verdict == "accent":
            return result
        best_partial = best_partial or result
    if best_partial:
        return best_partial

    closest = max(normed, key=lambda c: SequenceMatcher(None, strip_accents(user), strip_accents(c[1])).ratio())[0]
    return CheckResult("wrong", closest, [Segment(closest)])


def check_choice(selected: int | None, answer_index: int) -> CheckResult:
    return CheckResult("correct" if selected == answer_index else "wrong")
