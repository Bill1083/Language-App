"""Read subtitle files (SRT, WebVTT, ASS/SSA) into timed lines.

Formatting is stripped (HTML-style tags, ASS override blocks like {\\an8}),
line breaks inside a cue become spaces, and YouTube's "rolling" auto-captions
— where each cue repeats the previous line plus a few new words — are collapsed
so every sentence appears once.
"""

import re
from dataclasses import dataclass

MAX_LINES = 3000  # ~2 hours of dialogue; protects the annotation step from huge files
MAX_LINE_CHARS = 300


@dataclass
class Cue:
    start_ms: int
    end_ms: int
    text: str


class SubtitleError(ValueError):
    pass


_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
_TAGS = re.compile(r"<[^>]+>")
_ASS_OVERRIDES = re.compile(r"\{[^}]*\}")
_SPACES = re.compile(r"[ \t　]+")
_NOT_DIALOGUE = {"sign", "signs", "song", "songs", "op", "ed", "opening", "ending", "kara", "karaoke", "title",
                 "lyrics", "insert"}


def decode(data: bytes) -> str:
    """Subtitle files come in UTF-8 (with or without BOM), UTF-16 or Shift-JIS."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    for encoding in ("utf-8-sig", "cp932"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SubtitleError("Couldn't read the subtitle file — save it as UTF-8 and try again.")


def _ms(stamp: str) -> int:
    m = _TIME.search(stamp)
    if not m:
        raise SubtitleError(f"Unreadable timestamp: {stamp.strip()[:40]}")
    h, mi, s, frac = m.groups()
    return ((int(h or 0) * 60 + int(mi)) * 60 + int(s)) * 1000 + int(frac.ljust(3, "0")[:3])


def _clean(text: str) -> str:
    text = text.replace("\\N", " ").replace("\\n", " ").replace("\\h", " ")
    text = _ASS_OVERRIDES.sub("", _TAGS.sub("", text))
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return _SPACES.sub(" ", " ".join(part.strip() for part in text.splitlines())).strip()


def _parse_blocks(text: str) -> list[Cue]:
    """SRT and WebVTT: blank-line separated blocks with an `a --> b` line."""
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        at = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if at is None:
            continue  # WEBVTT header, NOTE/STYLE blocks, stray numbers
        start, _, end = lines[at].partition("-->")
        body = _clean("\n".join(lines[at + 1:]))
        if body:
            cues.append(Cue(_ms(start), _ms(end.split()[0] if end.split() else end), body))
    return cues


def _parse_ass(text: str) -> list[Cue]:
    cues, fields = [], None
    for line in text.splitlines():
        if line.startswith("Format:") and fields is None and "Text" in line:
            fields = [f.strip().lower() for f in line[7:].split(",")]
        elif line.startswith("Dialogue:"):
            names = fields or ["layer", "start", "end", "style", "name", "marginl", "marginr", "marginv",
                               "effect", "text"]
            parts = line[9:].split(",", len(names) - 1)
            row = dict(zip(names, (p.strip() for p in parts), strict=False))
            # On-screen signs, song lyrics and karaoke aren't dialogue
            if set(re.findall(r"[a-z]+", row.get("style", "").lower())) & _NOT_DIALOGUE:
                continue
            body = _clean(row.get("text", ""))
            if body:
                cues.append(Cue(_ms(row["start"]), _ms(row["end"]), body))
    return cues


def _collapse_rolling(cues: list[Cue]) -> list[Cue]:
    """YouTube auto-captions repeat the previous line at the start of the next cue."""
    out: list[Cue] = []
    shown = ""  # the previous cue's full text (before trimming what it repeated)
    for cue in cues:
        if out and cue.start_ms <= out[-1].end_ms + 100:
            prev = out[-1]
            if cue.text in (shown, prev.text):  # the same words again: just keep them on screen longer
                prev.end_ms = max(prev.end_ms, cue.end_ms)
                continue
            if shown and cue.text.startswith(shown):
                rest = cue.text[len(shown):].strip()
                out.append(Cue(prev.end_ms, cue.end_ms, rest))
                shown = cue.text
                continue
        out.append(cue)
        shown = cue.text
    return out


def parse(data: bytes, filename: str = "") -> list[Cue]:
    text = decode(data)
    name = filename.lower()
    if name.endswith((".ass", ".ssa")) or "[Events]" in text:
        cues = _parse_ass(text)
    else:
        cues = _parse_blocks(text)
    cues = sorted((c for c in cues if c.end_ms > c.start_ms), key=lambda c: c.start_ms)
    cues = _collapse_rolling(cues)
    if not cues:
        raise SubtitleError("No subtitle lines found — is this an .srt, .vtt or .ass file?")
    if len(cues) > MAX_LINES:
        raise SubtitleError(f"That's {len(cues)} lines — the limit is {MAX_LINES}.")
    for c in cues:
        c.text = c.text[:MAX_LINE_CHARS]
    return cues
