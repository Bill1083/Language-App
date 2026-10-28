"""Lesson content schema (what the LLM generates and the lesson player renders).

The LLM produces vocab, grammar notes and practice exercises; vocab intro and
grammar note cards are built from those server-side so they always agree.
Exercises are validated one by one, so one malformed item is dropped instead
of failing the whole lesson.
"""

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, field_validator, model_validator

BLANK = "___"


class VocabEntry(BaseModel):
    word: str  # with article for FR/IT nouns ("le café"); JA in kanji with {漢字|かな} furigana markup
    reading: str | None = None  # JA kana reading
    meaning: str
    pos: str | None = None
    gender: Literal["m", "f", "m/f"] | None = None
    plural: str | None = None
    example: str | None = None
    example_translation: str | None = None
    emoji: str | None = None
    note: str | None = None

    @field_validator("gender", mode="before")
    @classmethod
    def coerce_gender(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip().lower()
            return {"masculine": "m", "feminine": "f", "masc": "m", "fem": "f", "": None, "n/a": None,
                    "none": None, "both": "m/f"}.get(v, v)
        return v


class Example(BaseModel):
    target: str
    english: str


class Table(BaseModel):
    title: str | None = None
    headers: list[str]
    rows: list[list[str]]


class GrammarPoint(BaseModel):
    title: str
    explanation: str
    examples: list[Example] = Field(default_factory=list)
    table: Table | None = None
    politeness: Literal["polite", "plain", "both"] | None = None  # Japanese register label


class _Base(BaseModel):
    explanation: str = ""


def _check_index(options: list[str], answer_index: int) -> None:
    if not 0 <= answer_index < len(options):
        raise ValueError("answer_index out of range")
    if len({o.strip().lower() for o in options}) != len(options):
        raise ValueError("duplicate options")


class MultipleChoice(_Base):
    type: Literal["multiple_choice"]
    prompt: str
    question: str
    question_lang: Literal["target", "en"] = "target"
    options: list[str] = Field(min_length=2, max_length=6)
    options_lang: Literal["target", "en"] = "en"
    answer_index: int

    @model_validator(mode="after")
    def valid(self):
        _check_index(self.options, self.answer_index)
        return self


class ListeningChoice(_Base):
    type: Literal["listening_choice"]
    audio_text: str
    options: list[str] = Field(min_length=2, max_length=6)
    options_lang: Literal["target", "en"] = "target"
    answer_index: int

    @model_validator(mode="after")
    def valid(self):
        _check_index(self.options, self.answer_index)
        return self


class WordBank(_Base):
    type: Literal["word_bank"]
    prompt: str  # English sentence to translate
    answer: str
    answer_tiles: list[str] = Field(default_factory=list)
    distractors: list[str] = Field(default_factory=list)
    accepted: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid(self):
        if not self.answer_tiles:
            self.answer_tiles = [t for t in re.split(r"\s+", self.answer.strip()) if t]
        if len(self.answer_tiles) < 2:
            raise ValueError("word bank needs at least two tiles")
        self.distractors = [d for d in self.distractors if d not in self.answer_tiles][:4]
        return self


class Translate(_Base):
    type: Literal["translate"]
    direction: Literal["to_target", "to_english"]
    source: str
    answers: list[str] = Field(min_length=1)


class FillBlank(_Base):
    type: Literal["fill_blank"]
    sentence: str
    answers: list[str] = Field(min_length=1)
    hint: str | None = None
    translation: str | None = None
    options: list[str] | None = None
    focus: Literal["vocabulary", "conjugation", "article", "particle", "agreement", "other"] = "other"

    @model_validator(mode="after")
    def valid(self):
        if self.sentence.count(BLANK) != 1:
            raise ValueError(f"sentence must contain exactly one {BLANK}")
        if self.options is not None:
            if not any(a in self.options for a in self.answers):
                raise ValueError("options must include the answer")
            if len(self.options) < 2:
                self.options = None
        return self


class Pair(BaseModel):
    left: str
    right: str


class MatchPairs(_Base):
    type: Literal["match_pairs"]
    pairs: list[Pair] = Field(min_length=3, max_length=6)

    @model_validator(mode="after")
    def valid(self):
        if len({p.left for p in self.pairs}) != len(self.pairs) or len({p.right for p in self.pairs}) != len(self.pairs):
            raise ValueError("pairs must be unique")
        return self


class Dictation(_Base):
    type: Literal["dictation"]
    text: str
    translation: str | None = None
    accepted: list[str] = Field(default_factory=list)


class Speak(_Base):
    type: Literal["speak"]
    text: str
    translation: str


class ReadingQuestion(BaseModel):
    question: str
    options: list[str] = Field(min_length=2, max_length=5)
    answer_index: int

    @model_validator(mode="after")
    def valid(self):
        _check_index(self.options, self.answer_index)
        return self


class Reading(_Base):
    type: Literal["reading"]
    title: str
    passage: str
    translation: str | None = None
    questions: list[ReadingQuestion] = Field(min_length=1, max_length=5)


GeneratedExercise = Annotated[
    MultipleChoice | ListeningChoice | WordBank | Translate | FillBlank | MatchPairs | Dictation | Speak | Reading,
    Field(discriminator="type"),
]
_exercise_adapter: TypeAdapter[Any] = TypeAdapter(GeneratedExercise)


class LessonDraft(BaseModel):
    """Raw LLM output. Exercises stay untyped here and are validated one by one."""

    intro: str = ""
    vocab: list[VocabEntry] = Field(default_factory=list)
    grammar: list[GrammarPoint] = Field(default_factory=list)
    pronunciation: list[str] = Field(default_factory=list)
    exercises: list[dict[str, Any]] = Field(min_length=1)


def validate_exercises(raw: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    good, errors = [], []
    for i, item in enumerate(raw):
        try:
            good.append(_exercise_adapter.validate_python(item).model_dump(exclude_none=True))
        except ValidationError as e:
            errors.append(f"exercise {i} ({item.get('type', '?')}): {e.errors()[0].get('msg')}")
    return good, errors


class PlacementItem(BaseModel):
    level: Literal["A1", "A2", "B1", "B2", "C1"]
    question: str
    question_lang: Literal["target", "en"] = "target"
    options: list[str] = Field(min_length=3, max_length=5)
    answer_index: int
    skill: str = "grammar"

    @model_validator(mode="after")
    def valid(self):
        _check_index(self.options, self.answer_index)
        return self


class PlacementBankDraft(BaseModel):
    items: list[PlacementItem] = Field(min_length=10)


class UnitScenarioDraft(BaseModel):
    title: str
    emoji: str = "💬"
    description: str
    goal: str
    ai_role: str
    user_role: str
