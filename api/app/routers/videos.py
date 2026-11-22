"""Watch: a shared library of subtitled videos to learn from."""

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..deps import CurrentUser, Db
from ..models import User, Video, VideoLine, VideoProgress
from ..services.jobs import enqueue
from ..services.languages import LANGUAGES
from ..services.subtitles import SubtitleError, parse
from ..services.videos import thumbnail, youtube_id, youtube_info
from .vocab import WordIn, save_word

router = APIRouter(prefix="/videos", tags=["videos"])

MAX_SUBTITLE_BYTES = 2 * 1024 * 1024


def video_json(v: Video, user: User, position_ms: int | None = None) -> dict[str, Any]:
    return {
        "id": v.id, "language": v.language_code, "title": v.title, "source": v.source, "youtube_id": v.youtube_id,
        "thumbnail": thumbnail(v.youtube_id) if v.youtube_id else None, "duration_s": v.duration_s,
        "level": v.level, "status": v.status, "progress": v.progress, "error": v.error, "line_count": v.line_count,
        "can_delete": v.added_by == user.id or user.role == "admin", "position_ms": position_ms or 0,
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


@router.get("")
async def list_videos(user: CurrentUser, db: Db, lang: str | None = None) -> list[dict[str, Any]]:
    q = select(Video).order_by(Video.created_at.desc())
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
        video.status, video.error = "pending", None
        await db.commit()
        await enqueue("process_video", video.id, job_id=f"video-{video.id}")
    return video_json(video, user)


@router.delete("/{video_id}")
async def delete_video(video_id: int, user: CurrentUser, db: Db) -> dict[str, bool]:
    video = await _video(db, video_id)
    if video.added_by != user.id and user.role != "admin":
        raise HTTPException(403, "Only whoever added this video, or an admin, can delete it")
    await db.delete(video)
    await db.commit()
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
