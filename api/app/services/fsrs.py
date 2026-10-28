"""FSRS-5 spaced-repetition scheduler.

A compact implementation of the open-source FSRS-5 algorithm
(https://github.com/open-spaced-repetition) with the published default
parameters, learning/relearning steps and interval fuzz — the same model the
py-fsrs reference scheduler uses. Kept in-repo so the card state stored in
`srs_cards.fsrs_state_json` is a format we own.
"""

import math
import random
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from typing import Any

DEFAULT_W = (
    0.40255, 1.18385, 3.173, 15.69105, 7.1949, 0.5345, 1.4604, 0.0046, 1.54575, 0.1192,
    1.01925, 1.9395, 0.11, 0.29605, 2.2698, 0.2315, 2.9898, 0.51655, 0.6621,
)
DECAY = -0.5
FACTOR = 0.9 ** (1 / DECAY) - 1  # = 19/81
FUZZ_RANGES = ((2.5, 7.0, 0.15), (7.0, 20.0, 0.1), (20.0, math.inf, 0.05))


class Rating(IntEnum):
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


class State(IntEnum):
    LEARNING = 1
    REVIEW = 2
    RELEARNING = 3


@dataclass
class CardState:
    state: int = State.LEARNING
    step: int | None = 0
    stability: float | None = None
    difficulty: float | None = None
    due: datetime | None = None
    last_review: datetime | None = None
    reps: int = 0
    lapses: int = 0

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("due", "last_review"):
            d[k] = d[k].isoformat() if d[k] else None
        return d

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> "CardState":
        if not data:
            return cls()
        d = dict(data)
        for k in ("due", "last_review"):
            if d.get(k):
                d[k] = datetime.fromisoformat(d[k])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _clamp_d(d: float) -> float:
    return min(max(d, 1.0), 10.0)


class Scheduler:
    def __init__(
        self,
        w: tuple[float, ...] = DEFAULT_W,
        desired_retention: float = 0.9,
        learning_steps: tuple[timedelta, ...] = (timedelta(minutes=1), timedelta(minutes=10)),
        relearning_steps: tuple[timedelta, ...] = (timedelta(minutes=10),),
        maximum_interval: int = 36500,
        enable_fuzzing: bool = True,
        rng: random.Random | None = None,
    ):
        self.w = w
        self.desired_retention = desired_retention
        self.learning_steps = learning_steps
        self.relearning_steps = relearning_steps
        self.maximum_interval = maximum_interval
        self.enable_fuzzing = enable_fuzzing
        self.rng = rng or random.Random()

    # ------------------------------------------------------------------ model

    def retrievability(self, card: CardState, now: datetime) -> float:
        if card.last_review is None or not card.stability:
            return 0.0
        elapsed = max((now - card.last_review).days, 0)
        return (1 + FACTOR * elapsed / card.stability) ** DECAY

    def init_stability(self, r: Rating) -> float:
        return max(self.w[r - 1], 0.1)

    def init_difficulty(self, r: Rating) -> float:
        return _clamp_d(self.w[4] - math.exp(self.w[5] * (r - 1)) + 1)

    def next_difficulty(self, d: float, r: Rating) -> float:
        delta = -self.w[6] * (r - 3)
        damped = d + delta * (10 - d) / 9
        target = self.w[4] - math.exp(self.w[5] * 3) + 1  # D0(Easy)
        return _clamp_d(self.w[7] * target + (1 - self.w[7]) * damped)

    def short_term_stability(self, s: float, r: Rating) -> float:
        return s * math.exp(self.w[17] * (r - 3 + self.w[18]))

    def recall_stability(self, d: float, s: float, ret: float, r: Rating) -> float:
        hard = self.w[15] if r == Rating.HARD else 1.0
        easy = self.w[16] if r == Rating.EASY else 1.0
        return s * (1 + math.exp(self.w[8]) * (11 - d) * s ** (-self.w[9])
                    * (math.exp(self.w[10] * (1 - ret)) - 1) * hard * easy)

    def forget_stability(self, d: float, s: float, ret: float) -> float:
        long_term = (self.w[11] * d ** (-self.w[12]) * ((s + 1) ** self.w[13] - 1)
                     * math.exp(self.w[14] * (1 - ret)))
        short_cap = s / math.exp(self.w[17] * self.w[18])
        return min(long_term, short_cap)

    def next_interval(self, s: float) -> int:
        ivl = s / FACTOR * (self.desired_retention ** (1 / DECAY) - 1)
        return int(min(max(round(ivl), 1), self.maximum_interval))

    def _fuzz(self, days: int) -> int:
        if not self.enable_fuzzing or days < 2.5:
            return days
        delta = 1.0
        for start, end, factor in FUZZ_RANGES:
            delta += factor * max(min(days, end) - start, 0.0)
        lo = max(2, int(round(days - delta)))
        hi = min(int(round(days + delta)), self.maximum_interval)
        lo = min(lo, hi)
        return self.rng.randint(lo, hi)

    # ------------------------------------------------------------------ review

    def _update_memory(self, card: CardState, r: Rating, now: datetime) -> None:
        if card.stability is None or card.difficulty is None:
            card.stability, card.difficulty = self.init_stability(r), self.init_difficulty(r)
            return
        same_day = card.last_review is not None and (now - card.last_review) < timedelta(days=1)
        if same_day:
            card.stability = self.short_term_stability(card.stability, r)
        else:
            ret = self.retrievability(card, now)
            card.stability = (self.forget_stability(card.difficulty, card.stability, ret) if r == Rating.AGAIN
                              else self.recall_stability(card.difficulty, card.stability, ret, r))
        card.difficulty = self.next_difficulty(card.difficulty, r)
        card.stability = max(card.stability, 0.01)

    def _stepped(self, card: CardState, r: Rating, steps: tuple[timedelta, ...]) -> timedelta:
        """Learning / relearning: walk the steps, graduating to Review at the end."""
        step = card.step or 0
        if not steps or (step >= len(steps) and r != Rating.AGAIN):
            return self._graduate(card)
        if r == Rating.AGAIN:
            card.step = 0
            return steps[0]
        if r == Rating.HARD:
            if step == 0:
                return steps[0] * 1.5 if len(steps) == 1 else (steps[0] + steps[1]) / 2
            return steps[step]
        if r == Rating.GOOD:
            if step + 1 >= len(steps):
                return self._graduate(card)
            card.step = step + 1
            return steps[card.step]
        return self._graduate(card)  # EASY

    def _graduate(self, card: CardState) -> timedelta:
        card.state, card.step = State.REVIEW, None
        return timedelta(days=self._fuzz(self.next_interval(card.stability or 1.0)))

    def review(self, card: CardState, rating: int, now: datetime | None = None) -> CardState:
        now = now or datetime.now(UTC)
        r = Rating(rating)
        c = CardState(**asdict(card))
        self._update_memory(c, r, now)
        if c.state == State.LEARNING:
            ivl = self._stepped(c, r, self.learning_steps)
        elif c.state == State.RELEARNING:
            ivl = self._stepped(c, r, self.relearning_steps)
        else:  # REVIEW
            if r == Rating.AGAIN:
                c.lapses += 1
                if self.relearning_steps:
                    c.state, c.step = State.RELEARNING, 0
                    ivl = self.relearning_steps[0]
                else:
                    ivl = timedelta(days=self.next_interval(c.stability or 1.0))
            else:
                ivl = timedelta(days=self._fuzz(self.next_interval(c.stability or 1.0)))
        c.reps += 1
        c.last_review = now
        c.due = now + ivl
        return c

    def preview(self, card: CardState, now: datetime | None = None) -> dict[int, timedelta]:
        """Next interval for each rating — shown under the review buttons."""
        now = now or datetime.now(UTC)
        saved = self.enable_fuzzing
        self.enable_fuzzing = False
        try:
            return {int(r): self.review(card, r, now).due - now for r in Rating}
        finally:
            self.enable_fuzzing = saved


def format_interval(delta: timedelta) -> str:
    minutes = delta.total_seconds() / 60
    if minutes < 60:
        return f"{max(1, round(minutes))}m"
    hours = minutes / 60
    if hours < 24:
        return f"{round(hours)}h"
    days = hours / 24
    if days < 30:
        return f"{round(days)}d"
    if days < 365:
        return f"{round(days / 30)}mo"
    return f"{days / 365:.1f}y"
