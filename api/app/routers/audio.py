import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..config import get_settings
from ..deps import CurrentUser, Db, rate_limit
from ..models import Recording
from ..services.ai import AIService
from ..services.audio_cache import audio_url, cached_only, tts_key

router = APIRouter(tags=["audio"])
KEY_RE = re.compile(r"^[0-9a-f]{64}$")


class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=800)
    lang: str = Field(pattern="^(fr|it|ja)$")
    speed: float = 1.0
    gender: str = "female"
    purpose: str = Field(default="lesson", pattern="^(lesson|conversation)$")


@router.post("/tts")
async def tts(body: TTSIn, user: CurrentUser, db: Db) -> dict[str, Any]:
    await rate_limit(f"tts:{user.id}", 120)
    gender = body.gender or (user.settings_json or {}).get("voice_gender", "female")
    key = await tts_key(AIService(db, user.id, user.role == "admin"), body.text, body.lang, purpose=body.purpose,
                        gender=gender, speed=body.speed)
    return {"key": key, "url": audio_url(key)}


@router.get("/audio/{name}")
async def get_audio(name: str, user: CurrentUser, db: Db) -> FileResponse:
    key = name.removesuffix(".mp3")
    if not KEY_RE.match(key):
        raise HTTPException(404, "Not found")
    path = await cached_only(db, key)
    if path is None:
        raise HTTPException(404, "Audio not cached")
    return FileResponse(path, media_type="audio/mpeg",
                        headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.post("/stt")
async def stt(user: CurrentUser, db: Db, audio: UploadFile = File(...), lang: str = Form(...),
              duration_ms: int = Form(0)) -> dict[str, Any]:
    await rate_limit(f"ai:{user.id}", get_settings().rate_limit_per_min)
    data = await audio.read()
    if len(data) > get_settings().max_upload_bytes:
        raise HTTPException(413, "Recording too long")
    result = await AIService(db, user.id, user.role == "admin").transcribe(
        data, audio.content_type or "audio/webm", lang, duration_ms / 1000)
    return {"text": result.text, "provider": result.provider, "model": result.model,
            "words": [w.__dict__ for w in result.words] if result.words else None}


async def _owned_recording(db, user, rec_id: str) -> Recording:
    rec = await db.get(Recording, rec_id)
    if rec is None or rec.user_id != user.id:
        raise HTTPException(404, "Recording not found")
    return rec


@router.get("/recordings/{rec_id}")
async def get_recording(rec_id: str, user: CurrentUser, db: Db) -> FileResponse:
    rec = await _owned_recording(db, user, rec_id)
    if not rec.path or not Path(rec.path).exists():
        raise HTTPException(410, "This recording has been deleted")
    return FileResponse(rec.path, media_type=rec.mime.split(";")[0], headers={"Cache-Control": "private, max-age=86400"})


@router.delete("/recordings/{rec_id}")
async def delete_recording(rec_id: str, user: CurrentUser, db: Db) -> dict[str, bool]:
    rec = await _owned_recording(db, user, rec_id)
    if rec.path:
        Path(rec.path).unlink(missing_ok=True)
        rec.path = None
    await db.commit()
    return {"ok": True}
