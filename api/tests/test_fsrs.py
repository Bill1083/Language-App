import random
from datetime import UTC, datetime, timedelta

import pytest

from app.services.fsrs import DEFAULT_W, CardState, Rating, Scheduler, State, format_interval

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def sched(**kw) -> Scheduler:
    return Scheduler(enable_fuzzing=False, **kw)


def test_new_card_good_moves_through_learning_steps():
    s = sched()
    c = s.review(CardState(), Rating.GOOD, NOW)
    assert c.state == State.LEARNING and c.step == 1
    assert c.due - NOW == timedelta(minutes=10)
    assert c.stability == pytest.approx(DEFAULT_W[2])
    c2 = s.review(c, Rating.GOOD, c.due)
    assert c2.state == State.REVIEW
    assert c2.due - c.due >= timedelta(days=1)


def test_new_card_again_restarts_at_first_step():
    c = sched().review(CardState(), Rating.AGAIN, NOW)
    assert c.state == State.LEARNING and c.step == 0
    assert c.due - NOW == timedelta(minutes=1)


def test_easy_graduates_immediately():
    c = sched().review(CardState(), Rating.EASY, NOW)
    assert c.state == State.REVIEW
    assert (c.due - NOW).days >= round(DEFAULT_W[3]) - 1


def test_initial_difficulty_orders_by_rating():
    s = sched()
    ds = [s.init_difficulty(r) for r in Rating]
    assert ds == sorted(ds, reverse=True)
    assert all(1 <= d <= 10 for d in ds)


def test_intervals_grow_with_successful_reviews():
    s = sched()
    c = s.review(CardState(), Rating.EASY, NOW)
    gaps = []
    t = NOW
    for _ in range(5):
        t = c.due
        prev_due = c.due
        c = s.review(c, Rating.GOOD, t)
        gaps.append(c.due - prev_due)
    assert all(b > a for a, b in zip(gaps, gaps[1:]))


def test_lapse_goes_to_relearning_and_reduces_stability():
    s = sched()
    c = s.review(CardState(), Rating.EASY, NOW)
    c = s.review(c, Rating.GOOD, c.due)
    before = c.stability
    lapsed = s.review(c, Rating.AGAIN, c.due)
    assert lapsed.state == State.RELEARNING
    assert lapsed.lapses == 1
    assert lapsed.stability < before
    assert lapsed.due - c.due == timedelta(minutes=10)
    back = s.review(lapsed, Rating.GOOD, lapsed.due)
    assert back.state == State.REVIEW


def test_rating_order_gives_ordered_intervals():
    s = sched()
    c = s.review(CardState(), Rating.EASY, NOW)
    preview = s.preview(c, c.due + timedelta(days=2))
    assert preview[Rating.AGAIN] < preview[Rating.HARD] < preview[Rating.GOOD] < preview[Rating.EASY]


def test_desired_retention_090_interval_equals_stability():
    s = sched()
    assert s.next_interval(10.0) == 10
    assert sched(desired_retention=0.95).next_interval(10.0) < 10


def test_retrievability_decays():
    s = sched()
    c = s.review(CardState(), Rating.EASY, NOW)
    r_soon = s.retrievability(c, NOW + timedelta(days=1))
    r_late = s.retrievability(c, NOW + timedelta(days=30))
    assert 1.0 >= r_soon > r_late > 0


def test_fuzz_stays_in_range_and_preview_is_deterministic():
    s = Scheduler(rng=random.Random(1))
    base = Scheduler(enable_fuzzing=False)
    c = base.review(CardState(), Rating.EASY, NOW)
    for _ in range(20):
        fuzzed = s.review(c, Rating.GOOD, c.due + timedelta(days=15))
        plain = base.review(c, Rating.GOOD, c.due + timedelta(days=15))
        ratio = (fuzzed.due - c.due).days / max(1, (plain.due - c.due).days)
        assert 0.75 < ratio < 1.3
    assert s.preview(c) == s.preview(c)


def test_state_round_trips_through_json():
    c = sched().review(CardState(), Rating.GOOD, NOW)
    again = CardState.from_json(c.to_json())
    assert again == c
    assert CardState.from_json(None) == CardState()


def test_format_interval():
    assert format_interval(timedelta(minutes=1)) == "1m"
    assert format_interval(timedelta(hours=5)) == "5h"
    assert format_interval(timedelta(days=3)) == "3d"
    assert format_interval(timedelta(days=90)) == "3mo"
