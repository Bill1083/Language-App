"""Watch: a shared library of subtitled videos to learn from."""

from typing import Any

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..deps import CurrentUser, Db
from ..models import User, Video, VideoClip, VideoLine, VideoProgress
from ..services.jobs import enqueue
from ..services.languages import LANGUAGES
from ..services.reels import DIFFICULTIES, mark_seen, videos_needing_clips
from ..services.reels import feed as reels_feed
from ..services.subtitles import SubtitleError, parse
from ..services.video_files import (
    ACCEPTED,
    CHUNK_BYTES,
    can_upload,
    chunk_count,
    limits,
    remove_files,
    storage_used,
    upload_dir,
    video_dir,
)
from ..services.videos import thumbnail, youtube_id, youtube_info
from .vocab import WordIn, save_word

router = APIRouter(prefix="/videos", tags=["videos"])

MAX_SUBTITLE_BYTES = 2 * 1024 * 1024


def video_json(v: Video, user: User, position_ms: int | None = None) -> dict[str, Any]:
    playable = v.source == "file" and "/" in (v.file_key or "")  # set once the playable copy exists
    return {
        "id": v.id, "language": v.language_code, "title": v.title, "source": v.source, "youtube_id": v.youtube_id,
        "thumbnail": thumbnail(v.youtube_id) if v.youtube_id else (
            f"/api/v1/videos/{v.id}/poster" if playable else None), "duration_s": v.duration_s,
        "level": v.level, "status": v.status, "progress": v.progress, "error": v.error, "line_count": v.line_count,
        "can_delete": v.added_by == user.id or user.role == "admin", "position_ms": position_ms or 0,
        "file_url": f"/api/v1/videos/{v.id}/file" if playable else None,
        "poster": f"/api/v1/videos/{v.id}/poster" if playable else None,
        "stage": v.stage, "size_bytes": v.size_bytes, "subtitle_source": v.subtitle_source,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


def line_json(r: VideoLine) -> dict[str, Any]:
    return {"i": r.idx, "start": r.start_ms, "end": r.end_ms, "raw": r.raw, "text": r.ja or r.raw, "kana": r.kana,
            "en": r.en, "words": r.words or []}


async def _video(db, video_id: int) -> Video:
    video = await db.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "Video not found")
    return video


@router.get("/preview")
async def preview(url: str, user: CurrentUser) -> dict[str, Any]:
    """What a pasted YouTube link points at, before adding it."""
    vid = youtube_id(url)
    if vid is None:
        raise HTTPException(400, "That doesn't look like a YouTube link")
    return {"youtube_id": vid, "thumbnail": thumbnail(vid)} | await youtube_info(vid)


@router.get("/limits")
async def upload_limits(user: CurrentUser, db: Db) -> dict[str, Any]:
    """What this person may upload, and how much space is left."""
    return limits() | {"can_upload": can_upload(user), "used_bytes": await storage_used(db)}


class UploadIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    size: int = Field(gt=0)
    lang: str
    title: str | None = Field(default=None, max_length=200)


@router.post("/uploads")
async def start_upload(body: UploadIn, user: CurrentUser, db: Db) -> dict[str, Any]:
    """Reserve space for a video file; the pieces follow with PUT /uploads/{id}/{n}."""
    if not can_upload(user):
        raise HTTPException(403, "Only admins can upload video files on this server")
    if body.lang not in LANGUAGES:
        raise HTTPException(400, "Unknown language")
    ext = Path(body.name).suffix.lower()
    if ext not in ACCEPTED:
        raise HTTPException(400, f"Upload a video file ({', '.join(ACCEPTED)})")
    lim = limits()
    if body.size > lim["max_file_bytes"]:
        raise HTTPException(400, f"That file is {body.size / 1024 ** 3:.1f} GB — the limit is "
                                 f"{lim['max_file_bytes'] / 1024 ** 3:.1f} GB per file.")
    if await storage_used(db) + body.size > lim["quota_bytes"]:
        raise HTTPException(400, "Not enough space left in the video library — delete a video first, or raise "
                                 "VIDEO_STORAGE_GB on the server.")
    video = Video(language_code=body.lang, title=(body.title or Path(body.name).stem).strip()[:200] or "Video",
                  source="file", status="uploading", stage="uploading", size_bytes=body.size,
                  file_key=f"upload{ext}", added_by=user.id)
    db.add(video)
    await db.commit()
    upload_dir(video.id).mkdir(parents=True, exist_ok=True)
    return {"id": video.id, "chunk_bytes": CHUNK_BYTES, "chunks": chunk_count(body.size)}


async def _upload(db, user: User, video_id: int) -> Video:
    video = await _video(db, video_id)
    if video.added_by != user.id or video.status != "uploading":
        raise HTTPException(404, "Upload not found")
    return video


@router.get("/uploads/{video_id}")
async def upload_status(video_id: int, user: CurrentUser, db: Db) -> dict[str, Any]:
    """Which pieces already arrived, so an interrupted upload can resume."""
    video = await _upload(db, user, video_id)
    folder = upload_dir(video.id)
    received = sorted(int(p.name) for p in folder.iterdir() if p.name.isdigit()) if folder.exists() else []
    return {"id": video.id, "chunks": chunk_count(video.size_bytes), "received": received}


@router.put("/uploads/{video_id}/{n}")
async def upload_chunk(video_id: int, n: int, request: Request, user: CurrentUser, db: Db) -> dict[str, bool]:
    video = await _upload(db, user, video_id)
    total = chunk_count(video.size_bytes)
    if not 0 <= n < total:
        raise HTTPException(400, "No such piece")
    expected = CHUNK_BYTES if n < total - 1 else video.size_bytes - CHUNK_BYTES * (total - 1)
    data = await request.body()
    if len(data) != expected:
        raise HTTPException(400, f"Piece {n} should be {expected} bytes, got {len(data)}")
    folder = upload_dir(video.id)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{n}.part"
    tmp.write_bytes(data)
    tmp.replace(folder / str(n))  # a piece only counts once it's fully written
    return {"ok": True}


@router.post("/uploads/{video_id}/subtitles")
async def upload_subtitles(video_id: int, user: CurrentUser, db: Db, subtitles: UploadFile = File(...)
                           ) -> dict[str, Any]:
    """Optional: subtitles to use instead of the file's own track or transcription."""
    video = await _upload(db, user, video_id)
    data = await subtitles.read(MAX_SUBTITLE_BYTES + 1)
    if len(data) > MAX_SUBTITLE_BYTES:
        raise HTTPException(400, "That subtitle file is over 2 MB")
    try:
        cues = parse(data, subtitles.filename or "")
    except SubtitleError as e:
        raise HTTPException(400, str(e)) from e
    await db.execute(VideoLine.__table__.delete().where(VideoLine.video_id == video.id))
    db.add_all(VideoLine(video_id=video.id, idx=i, start_ms=c.start_ms, end_ms=c.end_ms, raw=c.text, words=[])
               for i, c in enumerate(cues))
    video.line_count, video.subtitle_source = len(cues), "file"
    await db.commit()
    return {"lines": len(cues)}


@router.post("/uploads/{video_id}/finish")
async def finish_upload(video_id: int, user: CurrentUser, db: Db) -> dict[str, Any]:
    video = await _upload(db, user, video_id)
    status = await upload_status(video_id, user, db)
    if len(status["received"]) != status["chunks"]:
        raise HTTPException(400, f"{status['chunks'] - len(status['received'])} pieces are still missing")
    video.status, video.stage = "pending", "repackaging"
    await db.commit()
    await enqueue("process_video_file", video.id, job_id=f"video-file-{video.id}")
    return video_json(video, user)


def _file(video: Video, name: str) -> Path:
    path = video_dir(video.id) / name
    if video.source != "file" or not path.is_file():
        raise HTTPException(404, "File not found")
    return path


@router.get("/{video_id}/file")
async def video_file(video_id: int, user: CurrentUser, db: Db) -> FileResponse:
    video = await _video(db, video_id)
    path = _file(video, Path(video.file_key or "").name)
    # FileResponse answers Range requests, so the player can seek without downloading everything
    return FileResponse(path, media_type=video.mime or "video/mp4", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/{video_id}/poster")
async def video_poster(video_id: int, user: CurrentUser, db: Db) -> FileResponse:
    video = await _video(db, video_id)
    return FileResponse(_file(video, "poster.jpg"), media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=86400"})


@router.get("/reels")
async def reels(lang: str, user: CurrentUser, db: Db, difficulty: str = "level", limit: int = 8,
                exclude: str = "") -> dict[str, Any]:
    """The next short clips for this person, matched to their level (see services/reels.py)."""
    if lang not in LANGUAGES:
        raise HTTPException(400, "Unknown language")
    if difficulty not in DIFFICULTIES:
        raise HTTPException(400, "difficulty is easier, level, harder or challenge")
    for video_id in await videos_needing_clips(db):  # videos added before reels existed
        await enqueue("build_clips", video_id, job_id=f"clips-{video_id}")
    skip = {int(x) for x in exclude.split(",") if x.strip().isdigit()}
    picked = await reels_feed(db, user.id, lang, difficulty, max(1, min(limit, 20)), skip)
    items = []
    for c in picked:
        clip, video = c["clip"], c["video"]
        lines = await db.scalars(select(VideoLine).where(
            VideoLine.video_id == video.id, VideoLine.idx >= clip.first_idx, VideoLine.idx <= clip.last_idx)
            .order_by(VideoLine.idx))
        playable = video.source == "file" and "/" in (video.file_key or "")
        items.append({
            "id": clip.id, "video_id": video.id, "title": video.title, "source": video.source,
            "youtube_id": video.youtube_id, "file_url": f"/api/v1/videos/{video.id}/file" if playable else None,
            "poster": f"/api/v1/videos/{video.id}/poster" if playable else (
                thumbnail(video.youtube_id) if video.youtube_id else None),
            "start": clip.start_ms, "end": clip.end_ms, "level": clip.level,
            "known": None if c["known"] is None else round(c["known"] * 100),
            "lines": [line_json(r) for r in lines],
        })
    return {"difficulty": difficulty, "items": items}


@router.post("/reels/{clip_id}/seen")
async def reel_seen(clip_id: int, user: CurrentUser, db: Db) -> dict[str, bool]:
    clip = await db.get(VideoClip, clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    video = await db.get(Video, clip.video_id)
    await mark_seen(user.id, video.language_code if video else "", clip_id)
    return {"ok": True}


@router.get("")
async def list_videos(user: CurrentUser, db: Db, lang: str | None = None) -> list[dict[str, Any]]:
    q = select(Video).where(Video.status != "uploading").order_by(Video.created_at.desc())
    if lang:
        q = q.where(Video.language_code == lang)
    videos = list(await db.scalars(q))
    positions = dict((await db.execute(select(VideoProgress.video_id, VideoProgress.position_ms).where(
        VideoProgress.user_id == user.id))).all())
    return [video_json(v, user, positions.get(v.id)) for v in videos]


@router.post("/youtube")
async def add_youtube(user: CurrentUser, db: Db, url: str = Form(...), lang: str = Form(...),
                      title: str | None = Form(default=None), subtitles: UploadFile = File(...)) -> dict[str, Any]:
    if lang not in LANGUAGES:
        raise HTTPException(400, "Unknown language")
    vid = youtube_id(url)
    if vid is None:
        raise HTTPException(400, "That doesn't look like a YouTube link")
    data = await subtitles.read(MAX_SUBTITLE_BYTES + 1)
    if len(data) > MAX_SUBTITLE_BYTES:
        raise HTTPException(400, "That subtitle file is over 2 MB — is it really a subtitle file?")
    try:
        cues = parse(data, subtitles.filename or "")
    except SubtitleError as e:
        raise HTTPException(400, str(e)) from e
    info = await youtube_info(vid)
    if info.get("embeddable") is False:
        raise HTTPException(400, "This video's owner doesn't allow it to be played in other apps.")
    video = Video(language_code=lang, title=(title or "").strip()[:200] or info["title"] or "YouTube video",
                  source="youtube", youtube_id=vid, duration_s=cues[-1].end_ms // 1000, status="pending",
                  subtitle_source="file",
                  line_count=len(cues), added_by=user.id)
    db.add(video)
    await db.flush()
    db.add_all(VideoLine(video_id=video.id, idx=i, start_ms=c.start_ms, end_ms=c.end_ms, raw=c.text, words=[])
               for i, c in enumerate(cues))
    await db.commit()
    await enqueue("process_video", video.id, job_id=f"video-{video.id}")
    return video_json(video, user)


@router.get("/{video_id}")
async def get_video(video_id: int, user: CurrentUser, db: Db) -> dict[str, Any]:
    video = await db.scalar(select(Video).where(Video.id == video_id).options(selectinload(Video.lines)))
    if video is None:
        raise HTTPException(404, "Video not found")
    progress = await db.get(VideoProgress, (user.id, video_id))
    return video_json(video, user, progress.position_ms if progress else 0) | {
        "lines": [line_json(r) for r in video.lines]}


@router.post("/{video_id}/retry")
async def retry(video_id: int, user: CurrentUser, db: Db) -> dict[str, Any]:
    video = await _video(db, video_id)
    if video.status == "failed":
        if video.source == "file" and not video_dir(video.id).exists():
            raise HTTPException(400, "This file was refused, so it wasn't kept — fix it and upload it again.")
        video.status, video.error = "pending", None
        await db.commit()
        if video.source == "file":
            await enqueue("process_video_file", video.id, job_id=f"video-file-{video.id}")
        else:
            await enqueue("process_video", video.id, job_id=f"video-{video.id}")
    return video_json(video, user)


@router.delete("/{video_id}")
async def delete_video(video_id: int, user: CurrentUser, db: Db) -> dict[str, bool]:
    video = await _video(db, video_id)
    if video.added_by != user.id and user.role != "admin":
        raise HTTPException(403, "Only whoever added this video, or an admin, can delete it")
    await db.delete(video)
    await db.commit()
    remove_files(video_id)
    return {"ok": True}


class PositionIn(BaseModel):
    position_ms: int = Field(ge=0, le=24 * 3600 * 1000)


@router.put("/{video_id}/progress")
async def save_position(video_id: int, body: PositionIn, user: CurrentUser, db: Db) -> dict[str, bool]:
    await _video(db, video_id)
    row = await db.get(VideoProgress, (user.id, video_id))
    if row is None:
        db.add(VideoProgress(user_id=user.id, video_id=video_id, position_ms=body.position_ms))
    else:
        row.position_ms = body.position_ms
    await db.commit()
    return {"ok": True}


class VideoWord(BaseModel):
    word: str = Field(min_length=1, max_length=160)
    reading: str | None = Field(default=None, max_length=160)
    meaning: str = Field(min_length=1, max_length=300)
    example: str | None = Field(default=None, max_length=500)
    example_translation: str | None = Field(default=None, max_length=500)


class WordsIn(BaseModel):
    words: list[VideoWord] = Field(min_length=1, max_length=60)


@router.post("/{video_id}/words")
async def add_words(video_id: int, body: WordsIn, user: CurrentUser, db: Db) -> dict[str, Any]:
    """Add words from a video to the user's deck; returns their ids for "Practise these"."""
    video = await _video(db, video_id)
    ids = []
    for w in body.words:
        item = await save_word(db, user, video.language_code, WordIn(
            word=w.word, reading=w.reading, meaning=w.meaning, example=w.example,
            example_translation=w.example_translation, source="video", source_ref=f"video:{video.id}"))
        ids.append(item.id)
    return {"vocab_ids": ids}
