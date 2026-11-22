"""Watch library: YouTube links, and preparing subtitle lines for learners.

Each line gets (Japanese) furigana markup and a hiragana version, an English
translation and a few words worth learning, in batches of lines so the model sees
the surrounding dialogue. Parlo never downloads anything from YouTube: videos play
in YouTube's own player and the subtitles come from a file the user provides.
"""

import asyncio
import logging
import re
import statistics
import unicodedata
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Video, VideoLine
from ..providers.base import ChatMessage, http_client
from .languages import CEFR, LANGUAGES
from .text import strip_ruby

log = logging.getLogger("parlo.videos")

BATCH = 25  # lines per model call: enough context, small enough to answer quickly
PARALLEL = 3  # model calls at once per video
_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


# ---------------------------------------------------------------- YouTube

def youtube_id(url: str) -> str | None:
    """The 11-character video id from any common YouTube link (watch, youtu.be, shorts,
    embed, live, mobile), or None. Also finds a link inside shared text."""
    m = re.search(r"https?://\S+", url or "")
    url = (m.group(0) if m else url or "").strip()
    try:
        u = urlparse(url if "://" in url else f"https://{url}")
    except ValueError:
        return None
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.").removeprefix("music.")
    candidate = None
    if host == "youtu.be":
        candidate = u.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "youtube-nocookie.com"):
        if u.path == "/watch":
            candidate = (parse_qs(u.query).get("v") or [None])[0]
        else:
            parts = [p for p in u.path.split("/") if p]
            if len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v"):
                candidate = parts[1]
    return candidate if candidate and _ID.match(candidate) else None


def thumbnail(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


async def youtube_info(video_id: str) -> dict[str, Any]:
    """Title and channel from YouTube's public oEmbed endpoint (no API key)."""
    try:
        resp = await http_client().get(
            "https://www.youtube.com/oembed",
            params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"}, timeout=8.0)
        if resp.status_code == 200:
            data = resp.json()
            return {"title": str(data.get("title") or "")[:200], "author": str(data.get("author_name") or "")[:120]}
        if resp.status_code in (401, 403):
            return {"title": "", "author": "", "embeddable": False}
    except (httpx.HTTPError, ValueError) as e:
        log.warning("oembed failed for %s: %s", video_id, e)
    return {"title": "", "author": ""}


# ---------------------------------------------------------------- annotation

class _Word(BaseModel):
    word: str = Field(max_length=80)
    reading: str | None = Field(default=None, max_length=80)
    meaning: str = Field(max_length=160)


class _Line(BaseModel):
    i: int
    ja: str = Field(max_length=900)
    kana: str | None = Field(default=None, max_length=900)
    en: str = Field(max_length=900)
    words: list[_Word] = Field(default_factory=list)


class _Batch(BaseModel):
    level: str | None = None
    lines: list[_Line]


def annotate_system(lang: str) -> str:
    name = LANGUAGES[lang]["name"]
    if lang == "ja":
        text_rule = ("ja: the line exactly as given — same characters, nothing added or dropped — with furigana "
                     "markup on every word that contains kanji, as {漢字|かな}, e.g. {今日|きょう}は{雨|あめ}だね。\n"
                     "- kana: the whole line in hiragana (keep katakana words in katakana, keep punctuation)\n")
        word_rule = "word in dictionary form with {漢字|かな} markup if it has kanji, reading in kana"
    else:
        text_rule = "ja: the line exactly as given\n- kana: null\n"
        word_rule = "word in dictionary form (with its article for nouns), reading: null"
    return (
        f"You prepare {name} subtitle lines from one video for an English-speaking learner. You get numbered "
        "lines in order. For each line return:\n"
        "- i: its number\n"
        f"- {text_rule}"
        "- en: a natural English translation, short like a subtitle; use the neighbouring lines for context\n"
        f"- words: up to 3 words worth learning from the line ({word_rule}, meaning: short English). Skip "
        "particles, names, interjections and very common words.\n"
        "Also return level: the CEFR level (A1, A2, B1, B2 or C1) a learner needs to follow these lines.\n"
        'Return JSON: {"level": "A2", "lines": [{"i": 0, "ja": "...", "kana": "...", "en": "...", '
        '"words": [{"word": "...", "reading": "...", "meaning": "..."}]}]}'
    )


def _same_text(a: str, b: str) -> bool:
    """Did the model keep the line's characters? (ignores spacing and width variants)"""
    norm = lambda s: re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))  # noqa: E731
    return norm(strip_ruby(a)) == norm(b)


def apply_batch(lang: str, rows: list[VideoLine], result: _Batch) -> None:
    by_i = {line.i: line for line in result.lines}
    for row in rows:
        line = by_i.get(row.idx)
        if line is None:
            row.ja, row.kana, row.en, row.words = row.raw, None, "", []
            continue
        row.ja = line.ja if _same_text(line.ja, row.raw) else row.raw  # never let the model rewrite the line
        row.kana = (line.kana or None) if lang == "ja" else None
        row.en = line.en.strip()
        row.words = [w.model_dump() for w in line.words[:3]]


async def annotate(ai: Any, lang: str, rows: list[VideoLine]) -> _Batch:
    listing = "\n".join(f"{r.idx}: {r.raw}" for r in rows)
    return await ai.llm_json("video_lines", "content", _Batch, system=annotate_system(lang),
                             messages=[ChatMessage("user", listing)], temperature=0.2,
                             max_tokens=min(8192, 300 + 260 * len(rows)), thinking="low")


def overall_level(levels: list[str | None]) -> str | None:
    idx = [CEFR.index(lv) for lv in levels if lv in CEFR]
    return CEFR[int(statistics.median_low(idx))] if idx else None


async def prepare_video(db: AsyncSession, ai: Any, video_id: int) -> Video:
    """Annotate every line still missing its English, a few batches at a time,
    recording progress as it goes (a failed run resumes where it stopped)."""
    video = await db.get(Video, video_id)
    if video is None:
        raise ValueError(f"video {video_id} not found")
    rows = list(await db.scalars(select(VideoLine).where(VideoLine.video_id == video_id).order_by(VideoLine.idx)))
    video.status, video.error = "processing", None
    await db.commit()
    await ai.config()  # load once: the batches below then never touch this session concurrently
    todo = [r for r in rows if r.en is None]
    done = len(rows) - len(todo)
    gate = asyncio.Semaphore(PARALLEL)

    async def run(batch: list[VideoLine]) -> tuple[list[VideoLine], _Batch]:
        async with gate:
            return batch, await annotate(ai, video.language_code, batch)

    levels: list[str | None] = []
    tasks = [asyncio.create_task(run(todo[i:i + BATCH])) for i in range(0, len(todo), BATCH)]
    try:
        for finished in asyncio.as_completed(tasks):
            batch, result = await finished
            apply_batch(video.language_code, batch, result)
            levels.append(result.level)
            done += len(batch)
            video.progress = int(done * 100 / max(1, len(rows)))
            await db.commit()
    except Exception as e:
        for t in tasks:  # don't keep paying for batches whose results can't be saved
            t.cancel()
        await db.rollback()
        video = await db.get(Video, video_id)
        assert video is not None
        video.status, video.error = "failed", f"Couldn't prepare the subtitles: {str(e)[:300]}"
        await db.commit()
        raise
    video.level = overall_level(levels) or video.level
    video.status, video.progress = "ready", 100
    await db.commit()
    return video
