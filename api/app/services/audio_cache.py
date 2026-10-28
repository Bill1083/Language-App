"""TTS audio cache: every clip is stored on disk keyed by
sha256(provider + voice + lang + speed + text), so a sentence is paid for once."""

import asyncio
import hashlib
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..config import get_settings
from ..models import AudioCache
from .ai import AIService, tts_for
from .text import speakable

_locks: dict[str, asyncio.Lock] = {}
SPEEDS = (0.75, 1.0, 1.25)


def clamp_speed(speed: float) -> float:
    return min(SPEEDS, key=lambda s: abs(s - speed))


def cache_key(provider: str, voice: str, lang: str, speed: float, text: str) -> str:
    raw = f"{provider}|{voice}|{lang}|{speed:.2f}|{text}"
    return hashlib.sha256(raw.encode()).hexdigest()


def path_for(key: str) -> Path:
    return get_settings().audio_cache_dir / key[:2] / f"{key}.mp3"


def audio_url(key: str) -> str:
    return f"/api/v1/audio/{key}.mp3"


async def tts_key(ai: AIService, text: str, lang: str, *, purpose: str = "lesson", gender: str = "female",
                  speed: float = 1.0, voice: str | None = None) -> str:
    """Return the cache key for this clip, synthesising it first if needed."""
    text = speakable(text)
    if not text:
        raise ValueError("Nothing to say")
    cfg = await ai.config()
    provider = tts_for(cfg, purpose).name
    voice = voice or cfg.voice_for(provider, lang, gender)
    speed = clamp_speed(speed)
    key = cache_key(provider, voice, lang, speed, text)
    path = path_for(key)
    if path.exists():
        return key
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        if path.exists():
            return key
        audio, _mime, provider_name = await ai.synthesize(text, lang, voice, speed, purpose)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_bytes(audio)
        tmp.replace(path)
        await ai.db.execute(
            insert(AudioCache)
            .values(key=key, path=str(path), lang=lang, voice=voice, provider=provider_name, chars=len(text))
            .on_conflict_do_nothing()
        )
        await ai.db.commit()
    _locks.pop(key, None)
    return key


async def cached_only(db, key: str) -> Path | None:
    path = path_for(key)
    if path.exists():
        return path
    row = await db.scalar(select(AudioCache).where(AudioCache.key == key))
    return Path(row.path) if row and Path(row.path).exists() else None
