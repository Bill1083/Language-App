"""Uploaded video files: storage, limits, and turning an upload into a playable,
subtitled video.

Files are never re-encoded (too heavy for a small VPS). They're repackaged so a
phone browser can play them — `.mkv` → `.mp4`/`.webm` with the streams copied,
audio converted only when its codec won't play — and anything a phone can't play
is refused with a tip. Subtitles come from, in order: a file the user attached, a
Japanese text track inside the file, or transcribing the audio with timestamps.
"""

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Video, VideoLine
from .subtitles import Cue, SubtitleError, parse

log = logging.getLogger("parlo.video_files")

CHUNK_BYTES = 6 * 1024 * 1024  # under the 8 MB proxy body limit, so uploads need no Nginx change
CLIP_SECONDS = 120  # audio sent to speech-to-text per request
ACCEPTED = (".mp4", ".m4v", ".mov", ".webm", ".mkv")
PLAYABLE_VIDEO = {"h264": "mp4", "vp8": "webm", "vp9": "webm", "av1": "webm"}
LANG_TAGS = {"ja": ("jpn", "ja", "jp"), "fr": ("fra", "fre", "fr"), "it": ("ita", "it")}
TEXT_SUBTITLES = {"ass", "ssa", "subrip", "srt", "webvtt", "mov_text", "text"}


class VideoFileError(ValueError):
    """Something about the file the user should fix (shown to them as is)."""


# ---------------------------------------------------------------- storage & limits

def video_dir(video_id: int) -> Path:
    return get_settings().videos_dir / str(video_id)


def upload_dir(video_id: int) -> Path:
    return video_dir(video_id) / "upload"


def chunk_count(size: int) -> int:
    return max(1, -(-size // CHUNK_BYTES))


def can_upload(user: Any) -> bool:
    return get_settings().video_uploaders == "everyone" or user.role == "admin"


async def storage_used(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.coalesce(func.sum(Video.size_bytes), 0))
                               .where(Video.source == "file")) or 0)


def limits() -> dict[str, Any]:
    s = get_settings()
    return {"max_file_bytes": s.video_max_file_mb * 1024 * 1024, "max_minutes": s.video_max_minutes,
            "quota_bytes": int(s.video_storage_gb * 1024 ** 3), "chunk_bytes": CHUNK_BYTES}


def remove_files(video_id: int) -> None:
    shutil.rmtree(video_dir(video_id), ignore_errors=True)


# ---------------------------------------------------------------- ffmpeg

async def _run(*args: str, timeout: float = 900) -> bytes:
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        raise VideoFileError("Processing the file took too long") from None
    if proc.returncode != 0:
        tail = err.decode(errors="replace").strip().splitlines()[-1:] or ["unknown error"]
        raise VideoFileError(f"{Path(args[0]).name} failed: {tail[0][:200]}")
    return out


async def probe(path: Path) -> dict[str, Any]:
    out = await _run("ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path),
                     timeout=60)
    return json.loads(out)


def plan_output(info: dict[str, Any]) -> tuple[str, list[str]]:
    """(container, ffmpeg codec args) to make a phone-playable copy without re-encoding the picture."""
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise VideoFileError("There's no video in that file.")
    codec = video.get("codec_name", "?")
    container = PLAYABLE_VIDEO.get(codec)
    if container is None:
        raise VideoFileError(
            f"This video is encoded as {codec.upper()}, which phones can't play in a browser. Convert it to "
            "H.264 MP4 (HandBrake's \"Fast 1080p30\" preset works) and upload it again.")
    args = ["-map", f"0:{video['index']}", "-c:v", "copy"]
    if audio is not None:
        args += ["-map", f"0:{audio['index']}"]
        ok_audio = {"mp4": {"aac", "mp3"}, "webm": {"opus", "vorbis"}}[container]
        if audio.get("codec_name") in ok_audio:
            args += ["-c:a", "copy"]
        else:  # converting only the sound is quick
            args += ["-c:a", "aac", "-b:a", "160k"] if container == "mp4" else ["-c:a", "libopus", "-b:a", "128k"]
    if container == "mp4":
        args += ["-movflags", "+faststart"]  # start playing before the whole file arrives
    return container, args


def subtitle_stream(info: dict[str, Any], lang: str) -> dict[str, Any] | None:
    """A text subtitle track in the course language (image-based ones like PGS can't be read)."""
    tags = LANG_TAGS.get(lang, (lang,))
    for s in info.get("streams", []):
        if s.get("codec_type") != "subtitle" or s.get("codec_name") not in TEXT_SUBTITLES:
            continue
        t = {k.lower(): str(v).lower() for k, v in (s.get("tags") or {}).items()}
        if t.get("language") in tags or (lang == "ja" and ("japanese" in t.get("title", "")
                                                           or "日本語" in t.get("title", ""))):
            return s
    return None


async def keyframes(path: Path) -> list[int]:
    """Keyframe times in ms, read from the container without decoding. Encoders put a
    keyframe at each cut in the picture, so these mark possible scene changes."""
    try:
        out = await _run("ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,flags",
                         "-of", "csv=p=0", str(path), timeout=120)
    except VideoFileError:
        return []
    times = []
    for row in out.decode(errors="replace").splitlines():
        pts, _, flags = row.partition(",")
        if flags.startswith("K"):
            try:
                times.append(int(float(pts) * 1000))
            except ValueError:
                continue
    return times


def duration_of(info: dict[str, Any]) -> float:
    try:
        return float(info.get("format", {}).get("duration") or 0)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------- processing

def merge_segments(clips: list[tuple[float, list[tuple[float, float, str]]]]) -> list[Cue]:
    """Clip-relative segments → one timeline in ms, in order, without overlaps."""
    cues: list[Cue] = []
    for offset, segments in clips:
        for start, end, text in segments:
            s_ms, e_ms = int((offset + start) * 1000), int((offset + end) * 1000)
            if cues and s_ms < cues[-1].end_ms:
                s_ms = cues[-1].end_ms
            if e_ms > s_ms and text:
                cues.append(Cue(s_ms, e_ms, text))
    return cues


async def assemble(video: Video) -> Path:
    """Join the uploaded pieces into the original file."""
    pieces = upload_dir(video.id)
    expected = chunk_count(video.size_bytes)
    missing = [n for n in range(expected) if not (pieces / str(n)).exists()]
    if missing:
        raise VideoFileError(f"The upload is incomplete ({len(missing)} pieces missing) — upload the file again.")
    original = video_dir(video.id) / f"original{Path(video.file_key or '').suffix.lower() or '.mp4'}"
    with original.open("wb") as out:
        for n in range(expected):
            with (pieces / str(n)).open("rb") as piece:
                shutil.copyfileobj(piece, out, 1024 * 1024)
    shutil.rmtree(pieces, ignore_errors=True)
    return original


async def _transcribe(ai: Any, video: Video, source: Path, seconds: float, on_clip) -> list[Cue]:
    work = video_dir(video.id) / "audio"
    work.mkdir(parents=True, exist_ok=True)
    try:
        await _run("ffmpeg", "-v", "error", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
                   "-c:a", "libmp3lame", "-b:a", "48k", "-f", "segment", "-segment_time", str(CLIP_SECONDS),
                   str(work / "clip%04d.mp3"))
        clips = sorted(work.glob("clip*.mp3"))
        results = []
        for i, clip in enumerate(clips):
            segments = await ai.transcribe_segments(clip.read_bytes(), "audio/mpeg", video.language_code,
                                                    min(CLIP_SECONDS, max(1, seconds - i * CLIP_SECONDS)))
            results.append((i * CLIP_SECONDS, segments))
            await on_clip(i + 1, len(clips))
        return merge_segments(results)
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def process_file(db: AsyncSession, ai: Any, video_id: int) -> Video:
    """Upload → playable file, poster and subtitle lines (then the usual annotation step)."""
    video = await db.get(Video, video_id)
    if video is None:
        raise ValueError(f"video {video_id} not found")
    folder = video_dir(video_id)

    async def step(stage: str) -> None:
        video.status, video.stage, video.error = "processing", stage, None
        await db.commit()

    await step("repackaging")
    source = await assemble(video) if upload_dir(video_id).exists() else next(folder.glob("original.*"), None)
    if source is None:
        raise VideoFileError("The uploaded file is missing — upload it again.")
    info = await probe(source)
    seconds = duration_of(info)
    max_minutes = get_settings().video_max_minutes
    if seconds > max_minutes * 60:
        raise VideoFileError(f"That video is {seconds / 60:.0f} minutes long — the limit is {max_minutes}.")
    container, codec_args = plan_output(info)
    target = folder / f"video.{container}"
    await _run("ffmpeg", "-v", "error", "-y", "-i", str(source), *codec_args, str(target))
    await _run("ffmpeg", "-v", "error", "-y", "-ss", str(min(5.0, seconds / 3)), "-i", str(target),
               "-frames:v", "1", "-vf", "scale=640:-2", str(folder / "poster.jpg"), timeout=120)

    has_lines = bool(await db.scalar(select(func.count()).select_from(VideoLine)
                                     .where(VideoLine.video_id == video_id)))
    if not has_lines:
        await step("subtitles")
        cues: list[Cue] = []
        track = subtitle_stream(info, video.language_code)
        if track is not None:
            ext = "ass" if track.get("codec_name") in ("ass", "ssa") else "srt"
            sub_file = folder / f"track.{ext}"
            await _run("ffmpeg", "-v", "error", "-y", "-i", str(source), "-map", f"0:{track['index']}",
                       str(sub_file), timeout=120)
            try:
                cues = parse(sub_file.read_bytes(), sub_file.name)
                video.subtitle_source = "embedded"
            except SubtitleError:
                cues = []
            sub_file.unlink(missing_ok=True)
        if not cues:
            await step("transcribing")

            async def on_clip(done: int, total: int) -> None:
                video.progress = int(done * 100 / total)
                await db.commit()

            cues = await _transcribe(ai, video, source, seconds, on_clip)
            video.subtitle_source = "transcribed"
            if not cues:
                raise VideoFileError("No speech was found in this video.")
        db.add_all(VideoLine(video_id=video_id, idx=i, start_ms=c.start_ms, end_ms=c.end_ms, raw=c.text, words=[])
                   for i, c in enumerate(cues))
        video.line_count = len(cues)
    if source != target:
        source.unlink(missing_ok=True)
    video.file_key = f"{video_id}/{target.name}"
    video.mime = f"video/{container}"
    video.duration_s = int(seconds)
    video.size_bytes = sum(p.stat().st_size for p in folder.iterdir() if p.is_file())
    video.stage, video.progress = None, 0
    await db.commit()
    return video
