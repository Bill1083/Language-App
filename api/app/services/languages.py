"""Static facts about the supported languages."""

LANGUAGES = {
    "fr": {"name": "French", "city": "Paris", "country": "France", "currency": "euros"},
    "it": {"name": "Italian", "city": "Rome", "country": "Italy", "currency": "euros"},
    "ja": {"name": "Japanese", "city": "Tokyo", "country": "Japan", "currency": "yen"},
}

CEFR = ["A1", "A2", "B1", "B2", "C1"]

LEVEL_GUIDE = {
    "A1": "absolute beginner: very short simple sentences (3–7 words), present tense, high-frequency words only",
    "A2": "elementary: short sentences (up to ~10 words), simple past and future, everyday topics",
    "B1": "intermediate: connected sentences, common tenses and moods, opinions and stories",
    "B2": "upper intermediate: natural native-like sentences, complex grammar, abstract topics",
    "C1": "advanced: rich idiomatic language, nuance, register shifts, complex structures",
}

REPLY_LENGTH = {
    "A1": "1–2 short sentences", "A2": "1–3 short sentences", "B1": "2–3 sentences",
    "B2": "2–4 sentences", "C1": "2–5 sentences",
}

LANGUAGE_RULES = {
    "fr": (
        "French: give every noun with its article (le/la/l'/les, un/une) and its gender (m/f) — for l'/les nouns "
        "state the gender explicitly. Add a conjugation table (person → form) for every verb a grammar point "
        "introduces. Pronunciation notes call out liaison, elision and silent final letters. Use correct French "
        "typography (space before ? ! : ;)."
    ),
    "it": (
        "Italian: give every noun with its article (il/lo/la/l'/i/gli/le, un/uno/una/un') and gender (m/f). Add a "
        "conjugation table for every verb a grammar point introduces. Pronunciation notes call out double "
        "consonants, stress and c/g before e/i."
    ),
    "ja": (
        "Japanese: write with kanji where a native would at this level, and put furigana markup on EVERY word that "
        "contains kanji, as {漢字|かな} — e.g. {日本|にほん}に{行|い}きます, {食|た}べる. Words written only in kana "
        "carry no markup. Never write romaji in Japanese fields. Give `reading` (kana) for every vocab entry. Use "
        "です/ます polite style unless the lesson teaches plain form, and label each grammar point's register in "
        "`politeness` (polite / plain / both). Grammar points about particles say which particle and why."
    ),
}


def level_index(cefr: str) -> int:
    return CEFR.index(cefr) if cefr in CEFR else 0
