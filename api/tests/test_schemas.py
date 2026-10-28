import pytest
from pydantic import ValidationError

from app.schemas.feedback import Feedback
from app.schemas.lesson import LessonDraft, validate_exercises
from app.services.conversation import pronunciation_flags

GOOD_FEEDBACK = {
    "overall": "errors",
    "score": 55,
    "corrected": "Je suis allé au marché.",
    "more_natural": None,
    "errors": [{"type": "conjugation", "original": "j'ai allé", "correction": "je suis allé",
                "explanation": "Aller takes être in the passé composé."}],
    "praise": "Good use of the passé composé structure.",
    "new_vocab": [{"word": "le marché", "reading": None, "meaning": "market"}],
}


def test_feedback_valid():
    fb = Feedback.model_validate(GOOD_FEEDBACK)
    assert fb.overall == "errors" and fb.errors[0].type == "conjugation"


def test_feedback_coerces_common_model_quirks():
    data = GOOD_FEEDBACK | {"overall": "Minor issues", "score": 0.82, "more_natural": "  ",
                            "errors": [{"type": "Verb tense", "original": "a", "correction": "b", "explanation": "c"},
                                       {"type": "Word Order", "original": "a", "correction": "b", "explanation": "c"}]}
    fb = Feedback.model_validate(data)
    assert fb.overall == "minor_issues"
    assert fb.score == 82
    assert fb.more_natural is None
    assert [e.type for e in fb.errors] == ["grammar", "word_order"]


def test_feedback_overall_made_consistent_with_errors():
    assert Feedback.model_validate(GOOD_FEEDBACK | {"overall": "perfect"}).overall == "minor_issues"
    perfect = Feedback.model_validate(GOOD_FEEDBACK | {"overall": "errors", "errors": [], "score": 100})
    assert perfect.overall == "minor_issues"


def test_feedback_rejects_missing_fields_and_bad_score():
    with pytest.raises(ValidationError):
        Feedback.model_validate({"overall": "perfect", "score": 100})
    with pytest.raises(ValidationError):
        Feedback.model_validate(GOOD_FEEDBACK | {"score": "lots"})
    with pytest.raises(ValidationError):
        Feedback.model_validate(GOOD_FEEDBACK | {"overall": "amazing"})


def test_feedback_score_is_clamped():
    assert Feedback.model_validate(GOOD_FEEDBACK | {"score": 140}).score == 100


def test_exercise_validation_keeps_good_and_drops_bad():
    raw = [
        {"type": "multiple_choice", "prompt": "Meaning?", "question": "chat", "options": ["cat", "dog", "bird"],
         "answer_index": 0, "explanation": "chat = cat"},
        {"type": "multiple_choice", "prompt": "Meaning?", "question": "chien", "options": ["cat", "dog"],
         "answer_index": 5},
        {"type": "fill_blank", "sentence": "Je ___ français.", "answers": ["parle"], "focus": "conjugation"},
        {"type": "fill_blank", "sentence": "No blank here.", "answers": ["x"]},
        {"type": "word_bank", "prompt": "I am here", "answer": "Je suis là", "distractors": ["es", "suis"]},
        {"type": "match_pairs", "pairs": [{"left": "un", "right": "one"}, {"left": "deux", "right": "two"},
                                          {"left": "trois", "right": "three"}]},
        {"type": "teleport", "prompt": "?"},
    ]
    good, errors = validate_exercises(raw)
    assert [g["type"] for g in good] == ["multiple_choice", "fill_blank", "word_bank", "match_pairs"]
    assert len(errors) == 3
    word_bank = good[2]
    assert word_bank["answer_tiles"] == ["Je", "suis", "là"]
    assert "suis" not in word_bank["distractors"]


def test_lesson_draft_requires_exercises():
    with pytest.raises(ValidationError):
        LessonDraft.model_validate({"intro": "x", "vocab": [], "exercises": []})
    draft = LessonDraft.model_validate({"vocab": [{"word": "le chat", "meaning": "cat", "gender": "Masculine"}],
                                        "exercises": [{"type": "speak", "text": "x", "translation": "y"}]})
    assert draft.vocab[0].gender == "m"


def test_pronunciation_flags_ignore_explained_grammar_errors():
    flags = pronunciation_flags(
        transcript="Je suis allé au marcher[?] avec mon ami",
        corrected="Je suis allé au marché avec mon ami",
        lang="fr", error_fragments=[], words=None,
    )
    assert flags and flags[0]["heard"] == "marcher" and flags[0]["reason"] == "unclear"

    grammar_only = pronunciation_flags(
        transcript="j'ai allé au parc", corrected="je suis allé au parc", lang="fr",
        error_fragments=["j'ai allé"], words=None,
    )
    assert grammar_only == []


def test_pronunciation_flags_use_low_confidence_words():
    flags = pronunciation_flags("bonjour madame", "bonjour madame", "fr", [],
                                [{"word": "bonjour", "confidence": 0.98}, {"word": "madame", "confidence": 0.31}])
    assert [f["heard"] for f in flags] == ["madame"]
    assert flags[0]["reason"] == "low_confidence"
