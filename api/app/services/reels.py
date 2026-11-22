"""Reels: short clips cut from every video in the library, matched to the learner.

Clips are made of whole subtitle lines. One starts only where a viewer can come in
cold — the first line, a line after a pause, after a finished sentence, or (for
uploaded files) after a cut in the picture — and ends where a sentence finishes,
so every clip is a small self-contained moment. Each clip gets a static difficulty
(the video's level, its kanji and how fast people talk); at feed time it also gets
a per-person "% known" from the learner's own words and kanji.
"""

import random
import re
import statistics
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Enrolment, Kanji, UserVocab, Video, VideoClip, VideoLine, VocabItem
from ..redis_client import get_redis
from .kanji import kanji_chars
from .languages import CEFR
from .srs import known_kanji_chars
from .text import strip_ruby

CLIPS_VERSION = 3  # bump when the cutting rules change: existing videos are re-cut
MIN_MS, MAX_MS, TARGET_MS = 15_000, 45_000, 28_000
SHORT_VIDEO_MS = 60_000  # a whole short video is one reel
LEAD_MS, TAIL_MS = 300, 500  # a beat before the first line and after the last
PAUSE_MS = 1_000  # silence long enough to start a new moment
SEEN_DAYS = 3

_SENTENCE_END = re.compile(r"[。．！？!?♪」』）)\.…]\s*$")
_TRAILING = re.compile(r"[、,，:：;；\-–—]\s*$")
_PUNCT = re.compile(r"[\s\W_]+", re.UNICODE)

DIFFICULTIES = {"easier": -1, "level": 0, "harder": 1, "challenge": 2}
# how much of a clip you should already know at each setting
TARGET_KNOWN = {"easier": 0.95, "level": 0.8, "harder": 0.6, "challenge": 0.4}


@dataclass
class Span:
    first: int
    last: int
    start_ms: int
    end_ms: int


# ---------------------------------------------------------------- cutting

def _start_strength(lines: list[tuple[int, int, str]], i: int, keyframes: list[int]) -> int:
    """2 = a new moment (the first line, a pause, a cut in the picture), 1 = a new
    sentence straight after the last one, 0 = mid-sentence."""
    if i == 0:
        return 2
    gap = lines[i][0] - lines[i - 1][1]
    prev = lines[i - 1][2]
    if gap >= PAUSE_MS:
        return 2
    # a cut in the picture during a short pause (uploaded files only)
    lo, hi = lines[i - 1][1], lines[i][0] + 200
    if gap >= 250 and not _TRAILING.search(prev) and any(lo <= k <= hi for k in keyframes):
        return 2
    return 1 if gap >= 300 and _SENTENCE_END.search(prev) else 0


def _can_end(lines: list[tuple[int, int, str]], j: int) -> bool:
    if j == len(lines) - 1:
        return True
    text = lines[j][2]
    if _TRAILING.search(text):
        return False  # the sentence carries on into the next line
    gap = lines[j + 1][0] - lines[j][1]
    return bool(_SENTENCE_END.search(text)) or gap >= 700


def cut_clips(lines: list[tuple[int, int, str]], keyframes: list[int] | None = None) -> list[Span]:
    """Whole-line clips of 15–45 s that start at a natural beginning and end at a natural end.
    `lines` are (start_ms, end_ms, text) in order; `keyframes` are picture cuts in ms."""
    if not lines:
        return []
    keyframes = sorted(keyframes or [])

    def span(i: int, j: int) -> Span:
        before = lines[i - 1][1] if i > 0 else 0
        after = lines[j + 1][0] if j + 1 < len(lines) else lines[j][1] + TAIL_MS
        start = max(before + (lines[i][0] - before) // 2, lines[i][0] - LEAD_MS, 0)
        end = min(lines[j][1] + TAIL_MS, max(lines[j][1], after - 100))
        return Span(i, j, start, end)

    if lines[-1][1] - lines[0][0] <= SHORT_VIDEO_MS:
        whole = span(0, len(lines) - 1)
        return [whole] if whole.end_ms - whole.start_ms >= 5_000 else []

    strength = [_start_strength(lines, i, keyframes) for i in range(len(lines))]

    def cost(s: Span) -> float:
        # near 28 s, and much better if the next line opens a new moment (end with the scene)
        scene_end = s.last == len(lines) - 1 or strength[s.last + 1] == 2
        return abs(s.end_ms - s.start_ms - TARGET_MS) - (12_000 if scene_end else 0)

    clips: list[Span] = []
    i = 0
    while i < len(lines):
        if not strength[i]:
            i += 1
            continue
        if strength[i] == 1:
            # a plain new sentence only starts a clip in long talk with no pause nearby
            soon = next((k for k in range(i + 1, len(lines)) if lines[k][0] - lines[i][0] > MAX_MS
                         or strength[k] == 2), None)
            if soon is not None and strength[soon] == 2 and lines[soon][0] - lines[i][0] <= MAX_MS:
                i = soon
                continue
        best: Span | None = None
        for j in range(i, len(lines)):
            s = span(i, j)
            length = s.end_ms - s.start_ms
            if length > MAX_MS:
                break
            if length >= MIN_MS and _can_end(lines, j) and (best is None or cost(s) < cost(best)):
                best = s
        if best is None:
            i += 1
            continue
        clips.append(best)
        i = best.last + 1
    return clips


# ---------------------------------------------------------------- difficulty

_JLPT_TO_LEVEL = {4: 0, 3: 1, 2: 2.5, 1: 4}  # old JLPT 4 (≈N5) → A1 … 1 (≈N1) → C1


def clip_score(lang: str, video_level: str | None, texts: list[str], speech_ms: int,
               kanji_jlpt: dict[str, int | None]) -> float:
    """0 (A1) … 4 (C1). The video's overall level, adjusted for this clip's kanji and speed."""
    parts: list[float] = []
    if video_level in CEFR:
        parts.append(float(CEFR.index(video_level)))
    plain = "".join(strip_ruby(t) for t in texts)
    if lang == "ja":
        chars = kanji_chars(plain)
        levels = sorted(_JLPT_TO_LEVEL.get(kanji_jlpt.get(c) or 0, 4.0) for c in chars)
        # the harder end of the clip's kanji, not the single rarest one; counted twice, since
        # the video's level comes from whole batches of lines and this is about the clip itself
        parts += [levels[int(len(levels) * 0.8)] if levels else 0.0] * 2
        rate = len(_PUNCT.sub("", plain)) / max(1.0, speech_ms / 1000)  # characters per second
        adjust = 1.0 if rate > 9 else 0.5 if rate > 7 else -0.5 if rate < 4 else 0.0
    else:
        rate = len(plain.split()) / max(1.0, speech_ms / 1000)  # words per second
        adjust = 1.0 if rate > 3.8 else 0.5 if rate > 3 else -0.5 if rate < 2 else 0.0
    base = statistics.fmean(parts) if parts else 1.0
    return max(0.0, min(4.0, base + adjust))


def level_of(score: float) -> str:
    return CEFR[max(0, min(len(CEFR) - 1, round(score)))]


async def build_clips(db: AsyncSession, video_id: int, keyframes: list[int] | None = None) -> int:
    """(Re)cut a ready video into reels clips."""
    video = await db.get(Video, video_id)
    if video is None or video.status != "ready":
        return 0
    rows = list(await db.scalars(select(VideoLine).where(VideoLine.video_id == video_id).order_by(VideoLine.idx)))
    spans = cut_clips([(r.start_ms, r.end_ms, strip_ruby(r.ja or r.raw)) for r in rows], keyframes)
    chars = {c for r in rows for c in kanji_chars(strip_ruby(r.ja or r.raw))} if video.language_code == "ja" else set()
    jlpt = dict((await db.execute(select(Kanji.char, Kanji.jlpt).where(Kanji.char.in_(chars)))).all()) if chars else {}
    await db.execute(delete(VideoClip).where(VideoClip.video_id == video_id))
    for s in spans:
        part = rows[s.first:s.last + 1]
        texts = [r.ja or r.raw for r in part]
        score = clip_score(video.language_code, video.level, texts, sum(r.end_ms - r.start_ms for r in part), jlpt)
        words = list(dict.fromkeys(strip_ruby(w["word"]) for r in part for w in (r.words or []) if w.get("word")))
        kanji = "".join(kanji_chars("".join(strip_ruby(t) for t in texts)))[:400] if video.language_code == "ja" else ""
        db.add(VideoClip(video_id=video_id, first_idx=part[0].idx, last_idx=part[-1].idx, start_ms=s.start_ms,
                         end_ms=s.end_ms, level=level_of(score), score=round(score, 2), words=words, kanji=kanji))
    video.clips_version = CLIPS_VERSION
    await db.commit()
    return len(spans)


# ---------------------------------------------------------------- the feed

def known_share(clip_words: list[str], clip_kanji: str, known_words: set[str], known_kanji: set[str]) -> float | None:
    """Share of the clip's key words (and, for Japanese, its kanji) the learner knows."""
    shares = []
    if clip_words:
        shares.append(sum(1 for w in clip_words if w in known_words) / len(clip_words))
    if clip_kanji:
        shares.append(sum(1 for c in clip_kanji if c in known_kanji) / len(clip_kanji))
    return statistics.fmean(shares) if shares else None


def rank(clips: list[dict[str, Any]], target_level: float, difficulty: str, rng: random.Random) -> list[dict[str, Any]]:
    """Closest to the target level first, then closest to the target share known,
    with a little shuffle; then spread so the same video doesn't play twice in a row."""
    want = TARGET_KNOWN[difficulty]

    def key(c: dict[str, Any]) -> float:
        known = c["known"] if c["known"] is not None else want
        return abs(c["score"] - target_level) + 1.5 * abs(known - want) + rng.random() * 0.35

    ordered = sorted(clips, key=key)
    spread: list[dict[str, Any]] = []
    while ordered:
        pick = next((k for k, c in enumerate(ordered[:6]) if not spread or c["video_id"] != spread[-1]["video_id"]), 0)
        spread.append(ordered.pop(pick))
    return spread


def _seen_key(user_id: int, lang: str) -> str:
    return f"reels:seen:{user_id}:{lang}"


async def mark_seen(user_id: int, lang: str, clip_id: int) -> None:
    redis = get_redis()
    key = _seen_key(user_id, lang)
    await redis.zadd(key, {str(clip_id): time.time()})
    await redis.zremrangebyscore(key, 0, time.time() - SEEN_DAYS * 86400)
    await redis.expire(key, SEEN_DAYS * 86400)


async def feed(db: AsyncSession, user_id: int, lang: str, difficulty: str, limit: int,
               exclude: set[int]) -> list[dict[str, Any]]:
    """The next clips for this person, best match first (each with its lines)."""
    level = await db.scalar(select(Enrolment.current_level).where(
        Enrolment.user_id == user_id, Enrolment.language_code == lang))
    base = CEFR.index(level) if level in CEFR else 0
    target = max(0, min(len(CEFR) - 1, base + DIFFICULTIES[difficulty]))

    rows = (await db.execute(
        select(VideoClip, Video).join(Video, Video.id == VideoClip.video_id)
        .where(Video.language_code == lang, Video.status == "ready"))).all()
    if not rows:
        return []
    known_words = set(strip_ruby(w) for w in await db.scalars(
        select(VocabItem.lemma).join(UserVocab, UserVocab.vocab_item_id == VocabItem.id)
        .where(UserVocab.user_id == user_id, VocabItem.language_code == lang)))
    known_kanji = set(await known_kanji_chars(db, user_id)) if lang == "ja" else set()

    redis = get_redis()
    seen_at = {int(k): t for k, t in await redis.zrange(_seen_key(user_id, lang), 0, -1, withscores=True)}
    candidates = []
    for clip, video in rows:
        if clip.id in exclude:
            continue
        candidates.append({"clip": clip, "video": video, "video_id": video.id, "score": clip.score,
                           "known": known_share(clip.words, clip.kanji, known_words, known_kanji)})
    fresh = [c for c in candidates if c["clip"].id not in seen_at]
    rng = random.Random()
    picked = rank(fresh, target, difficulty, rng)[:limit]
    if len(picked) < limit:  # everything watched lately: replay the longest-ago first
        stale = sorted((c for c in candidates if c["clip"].id in seen_at), key=lambda c: seen_at[c["clip"].id])
        picked += stale[:limit - len(picked)]
    return picked


async def videos_needing_clips(db: AsyncSession) -> list[int]:
    return list(await db.scalars(select(Video.id).where(Video.status == "ready", Video.clips_version < CLIPS_VERSION)))
