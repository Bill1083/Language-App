"""Per-turn conversation feedback (spec Section 6). The LLM must return this;
it is validated here, with light coercion for the usual model quirks."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ErrorType = Literal[
    "grammar", "vocabulary", "spelling", "gender", "conjugation", "particle", "word_order", "politeness", "accent"
]
ERROR_TYPES = set(ErrorType.__args__)  # type: ignore[attr-defined]

_TYPE_ALIASES = {
    "verb": "conjugation", "tense": "conjugation", "agreement": "gender", "article": "gender",
    "word choice": "vocabulary", "lexical": "vocabulary", "order": "word_order", "word order": "word_order",
    "register": "politeness", "formality": "politeness", "orthography": "spelling", "typo": "spelling",
    "accents": "accent", "diacritic": "accent", "preposition": "grammar", "syntax": "grammar",
}


class FeedbackError(BaseModel):
    type: ErrorType
    original: str
    correction: str
    explanation: str

    @field_validator("type", mode="before")
    @classmethod
    def coerce_type(cls, v: object) -> object:
        if isinstance(v, str):
            key = v.strip().lower().replace("-", "_")
            if key in ERROR_TYPES:
                return key
            return _TYPE_ALIASES.get(key.replace("_", " "), "grammar")
        return v


class NewVocab(BaseModel):
    word: str
    reading: str | None = None
    meaning: str


class Feedback(BaseModel):
    overall: Literal["perfect", "minor_issues", "errors"]
    score: int = Field(ge=0, le=100)
    corrected: str
    more_natural: str | None = None
    errors: list[FeedbackError] = Field(default_factory=list)
    praise: str | None = None
    new_vocab: list[NewVocab] = Field(default_factory=list)
    # Only filled in scenario / unit mode: has the learner met the scenario goal yet?
    goal_achieved: bool | None = None

    @field_validator("score", mode="before")
    @classmethod
    def coerce_score(cls, v: object) -> object:
        if isinstance(v, float):
            v = round(v * 100) if v <= 1 else round(v)
        if isinstance(v, str) and v.strip().isdigit():
            v = int(v.strip())
        if isinstance(v, int):
            return max(0, min(100, v))
        return v

    @field_validator("overall", mode="before")
    @classmethod
    def coerce_overall(cls, v: object) -> object:
        if isinstance(v, str):
            key = v.strip().lower().replace(" ", "_").replace("-", "_")
            return {"minor": "minor_issues", "minor_issue": "minor_issues", "error": "errors",
                    "correct": "perfect", "major_errors": "errors"}.get(key, key)
        return v

    @field_validator("more_natural", "praise", mode="before")
    @classmethod
    def empty_to_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @model_validator(mode="after")
    def consistent(self) -> "Feedback":
        # A "perfect" verdict can't carry errors, and errors can't be "perfect".
        if self.errors and self.overall == "perfect":
            self.overall = "minor_issues"
        if not self.errors and self.overall == "errors":
            self.overall = "minor_issues"
        return self


class GoalCheck(BaseModel):
    achieved: bool
