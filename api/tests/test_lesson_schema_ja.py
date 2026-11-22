"""Quizzes don't fail over extra fields the model adds."""

from app.schemas.lesson import LessonDraft, QuizDraft


def test_checkpoint_drafts_ignore_grammar_and_tips_in_any_shape():
    raw = {"intro": "x", "grammar": [{"name": "Time particle に", "politeness": "both"}],
           "pronunciation": [{"topic": "は", "tip": "said wa"}], "exercises": [{"type": "speak"}]}
    assert QuizDraft.model_validate(raw).exercises


def test_lesson_tips_given_as_objects_become_text():
    raw = {"pronunciation": [{"topic": "は", "tip": "said wa"}], "exercises": [{"type": "speak"}]}
    assert LessonDraft.model_validate(raw).pronunciation == ["は — said wa"]
