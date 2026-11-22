"""Reels: clips start at natural beginnings, end at natural ends, last 15–45 s, and are
ordered by how well they match the learner."""

import random

from app.services.reels import MAX_MS, MIN_MS, clip_score, cut_clips, known_share, level_of, rank


def dialogue(n: int, *, line_ms: int = 2500, gap_ms: int = 400, pause_every: int = 0, end: str = "。"):
    """n lines; every `pause_every`th line is followed by a 1.5 s pause."""
    lines, t = [], 0
    for i in range(n):
        lines.append((t, t + line_ms, f"せりふ{i}{end}"))
        t += line_ms + (1500 if pause_every and (i + 1) % pause_every == 0 else gap_ms)
    return lines


def starts_ok(lines, clip):
    i = clip.first
    return i == 0 or lines[i][0] - lines[i - 1][1] >= 300


def test_clips_are_15_to_45_seconds_of_whole_lines_in_order():
    lines = dialogue(80, pause_every=5)
    clips = cut_clips(lines)
    assert len(clips) >= 5
    for c in clips:
        assert MIN_MS <= c.end_ms - c.start_ms <= MAX_MS
        assert c.start_ms <= lines[c.first][0] and c.end_ms >= lines[c.last][1]
    assert all(a.last < b.first for a, b in zip(clips, clips[1:]))


def test_a_clip_never_starts_in_the_middle_of_a_sentence():
    # lines ending in 、 run on into the next one with no pause
    lines = []
    t = 0
    for i in range(60):
        cont = i % 3 != 2
        lines.append((t, t + 2000, f"文{i}" + ("、" if cont else "。")))
        t += 2000 + (100 if cont else 1200)
    for c in cut_clips(lines):
        assert c.first == 0 or lines[c.first - 1][2].endswith("。"), c
        assert lines[c.last][2].endswith("。") or c.last == len(lines) - 1, c


def test_without_pauses_or_punctuation_only_the_first_line_can_start():
    lines = [(i * 2100, i * 2100 + 2000, f"line {i}") for i in range(60)]  # 100 ms gaps, no punctuation
    clips = cut_clips(lines)
    assert [c.first for c in clips] == []  # nowhere is a natural end either, so no clips at all


def test_picture_cuts_open_new_starts_in_short_pauses():
    lines = [(i * 2600, i * 2600 + 2300, f"台詞{i}") for i in range(60)]  # 300 ms gaps, no punctuation
    without = cut_clips(lines)
    with_cuts = cut_clips(lines, keyframes=[k * 2600 - 100 for k in range(8, 60, 8)])
    assert len(with_cuts) > len(without)
    for c in with_cuts:
        assert c.first == 0 or any(lines[c.first - 1][1] <= k <= lines[c.first][0] + 200
                                   for k in range(8 * 2600 - 100, 60 * 2600, 8 * 2600))


def test_a_short_video_is_one_reel():
    lines = dialogue(8)
    clips = cut_clips(lines)
    assert len(clips) == 1 and clips[0].first == 0 and clips[0].last == 7


def test_lead_in_never_reaches_back_into_the_previous_line():
    lines = dialogue(80, pause_every=5)
    for c in cut_clips(lines):
        if c.first:
            assert c.start_ms > lines[c.first - 1][1]


def test_kanji_and_speed_move_the_level():
    easy = clip_score("ja", "A2", ["{日本|にほん}に{行|い}きます。"], 4000, {"日": 4, "本": 4, "行": 4})
    hard = clip_score("ja", "A2", ["{憲法|けんぽう}を{審議|しんぎ}する。"], 4000, {"憲": 1, "法": 2, "審": 1, "議": 2})
    fast = clip_score("ja", "A2", ["にほんにいきますよねそうですよね"], 1500, {})
    assert easy < hard and level_of(easy) in ("A1", "A2") and level_of(hard) in ("B1", "B2", "C1")
    assert fast > clip_score("ja", "A2", ["にほんにいきます"], 3000, {})


def test_known_share_counts_words_and_kanji():
    assert known_share(["駅", "電車"], "駅電車", {"駅"}, {"駅", "電"}) == (0.5 + 2 / 3) / 2
    assert known_share([], "", set(), set()) is None


def test_ranking_prefers_the_target_level_and_spreads_videos():
    clips = [{"video_id": v, "score": s, "known": k}
             for v, s, k in [(1, 0.0, 0.9), (1, 0.2, 0.8), (1, 3.5, 0.2), (2, 1.1, 0.5), (2, 0.1, 0.85)]]
    ranked = rank(clips, 0.0, "level", random.Random(1))
    assert ranked[-1]["score"] == 3.5
    assert all(a["video_id"] != b["video_id"] for a, b in zip(ranked[:3], ranked[1:3]))
    harder = rank(clips, 1.0, "harder", random.Random(1))
    assert harder[0]["score"] == 1.1


def test_clips_prefer_scene_starts_over_any_sentence():
    lines = dialogue(80, pause_every=7)  # every line ends in 。; a 1.5 s pause every 7 lines
    pauses = {i for i in range(1, 80) if lines[i][0] - lines[i - 1][1] >= 1000}
    clips = cut_clips(lines)
    assert clips and all(c.first == 0 or c.first in pauses for c in clips)
    # and they end with the scene where they can
    assert sum(1 for c in clips if c.last + 1 in pauses or c.last == 79) >= len(clips) - 1


def test_long_talk_without_pauses_still_starts_at_sentences():
    lines = dialogue(60)  # 400 ms gaps, every line a full sentence, no pauses at all
    clips = cut_clips(lines)
    assert len(clips) >= 3
    assert all(c.first == 0 or lines[c.first - 1][2].endswith("。") for c in clips)
