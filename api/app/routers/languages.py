import json
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from ..config import get_settings
from ..deps import CurrentUser, Db
from ..models import Enrolment, Language, PlacementBank
from ..redis_client import get_redis
from ..services.ai import AIService
from ..services.jobs import enqueue
from ..services.languages import CEFR, level_index
from ..services.lesson_gen import generate_placement_bank
from ..services.progress import award_xp

router = APIRouter(tags=["languages"])

PLACEMENT_MAX = 15
PER_LEVEL = 3


class EnrolIn(BaseModel):
    language_code: str
    current_level: str | None = None


class EnrolmentUpdate(BaseModel):
    current_level: str | None = None
    settings: dict[str, Any] | None = None


class PlacementAnswer(BaseModel):
    attempt_id: str
    answer_index: int


def enrolment_json(e: Enrolment) -> dict[str, Any]:
    return {"language_code": e.language_code, "current_level": e.current_level, "settings": e.settings_json or {},
            "placement": e.placement_result}


PROVIDER_NAMES = {"gemini": "Google Gemini", "google": "Google Cloud", "google_cloud": "Google Cloud",
                  "openai": "OpenAI", "groq": "Groq", "deepgram": "Deepgram", "local": "this server",
                  "elevenlabs": "ElevenLabs", "azure": "Microsoft Azure", "anthropic": "Anthropic",
                  "openrouter": "OpenRouter", "openai_compatible": "your own model server"}


@router.get("/meta")
async def meta(db: Db, user: CurrentUser) -> dict[str, Any]:
    """Provider names for user-facing privacy notices ("Voice is sent to … for transcription")."""
    from ..services.runtime_config import get_ai_config

    cfg = await get_ai_config(db)
    return {
        "stt_provider": PROVIDER_NAMES.get(cfg.stt_provider, cfg.stt_provider),
        "tts_provider": PROVIDER_NAMES.get(cfg.tts_provider_lesson, cfg.tts_provider_lesson),
        "llm_provider": PROVIDER_NAMES.get(cfg.llm_provider, cfg.llm_provider),
        "max_recording_seconds": get_settings().max_recording_seconds,
        "store_recordings": get_settings().store_recordings,
        "recording_retention_days": get_settings().recording_retention_days,
    }


@router.get("/languages")
async def list_languages(db: Db, user: CurrentUser) -> list[dict[str, Any]]:
    rows = await db.scalars(select(Language).order_by(Language.name))
    return [{"code": lang.code, "name": lang.name, "enabled": lang.enabled} for lang in rows]


@router.post("/enrolments")
async def enrol(body: EnrolIn, user: CurrentUser, db: Db) -> dict[str, Any]:
    if not await db.get(Language, body.language_code):
        raise HTTPException(404, "Unknown language")
    e = await db.get(Enrolment, (user.id, body.language_code))
    if e is None:
        e = Enrolment(user_id=user.id, language_code=body.language_code,
                      current_level=body.current_level if body.current_level in CEFR else "A1", settings_json={})
        db.add(e)
    settings = dict(user.settings_json or {})
    settings.setdefault("active_language", body.language_code)
    if not settings.get("active_language"):
        settings["active_language"] = body.language_code
    user.settings_json = settings
    await db.commit()
    await enqueue("pregenerate", user.id, body.language_code, job_id=f"pregen-{user.id}-{body.language_code}")
    return enrolment_json(e)


@router.patch("/enrolments/{lang}")
async def update_enrolment(lang: str, body: EnrolmentUpdate, user: CurrentUser, db: Db) -> dict[str, Any]:
    e = await db.get(Enrolment, (user.id, lang))
    if e is None:
        raise HTTPException(404, "Not enrolled in this language")
    if body.current_level:
        if body.current_level not in CEFR:
            raise HTTPException(400, "Unknown level")
        e.current_level = body.current_level
        if lang == "ja" and level_index(body.current_level) > 0:
            e.settings_json = {**(e.settings_json or {}), "kana_done": True}
    if body.settings:
        e.settings_json = {**(e.settings_json or {}), **body.settings}
    await db.commit()
    await enqueue("pregenerate", user.id, lang, job_id=f"pregen-{user.id}-{lang}")
    return enrolment_json(e)


# --------------------------------------------------------------------------- placement


def _public(item: dict[str, Any], idx: int) -> dict[str, Any]:
    return {"id": idx, "level": item["level"], "question": item["question"],
            "question_lang": item.get("question_lang", "target"), "options": item["options"]}


def _next_item(bank: list[dict[str, Any]], state: dict[str, Any]) -> int | None:
    level = CEFR[state["level_idx"]]
    for i, item in enumerate(bank):
        if item["level"] == level and i not in state["asked"]:
            return i
    return None


def _placed_level(state: dict[str, Any]) -> str:
    passed = state["passed"]
    failed = state["failed"]
    if failed:
        return CEFR[min(failed)]
    if passed:
        return CEFR[min(max(passed) + 1, len(CEFR) - 1)]
    return "A1"


@router.post("/placement/{lang}/start")
async def placement_start(lang: str, user: CurrentUser, db: Db) -> dict[str, Any]:
    bank = await db.get(PlacementBank, lang)
    if bank is None:
        bank = await generate_placement_bank(db, lang, AIService(db, user.id, user.role == "admin"))
    attempt = secrets.token_urlsafe(12)
    state = {"user_id": user.id, "lang": lang, "level_idx": 1, "asked": [], "results": [], "passed": [],
             "failed": [], "level_correct": 0, "level_asked": 0, "current": None}
    nxt = _next_item(bank.items_json, state)
    state["current"] = nxt
    state["asked"].append(nxt)
    await get_redis().set(f"placement:{attempt}", json.dumps(state), ex=3600)
    return {"attempt_id": attempt, "question": _public(bank.items_json[nxt], nxt),
            "progress": {"n": 1, "max": PLACEMENT_MAX}}


@router.post("/placement/{lang}/answer")
async def placement_answer(lang: str, body: PlacementAnswer, user: CurrentUser, db: Db) -> dict[str, Any]:
    redis = get_redis()
    raw = await redis.get(f"placement:{body.attempt_id}")
    if not raw:
        raise HTTPException(404, "Placement test expired — start again")
    state = json.loads(raw)
    if state["user_id"] != user.id:
        raise HTTPException(403, "Not your test")
    bank = await db.get(PlacementBank, lang)
    assert bank is not None
    item = bank.items_json[state["current"]]
    correct = body.answer_index == item["answer_index"]
    state["results"].append({"level": item["level"], "correct": correct})
    state["level_asked"] += 1
    state["level_correct"] += int(correct)

    idx = state["level_idx"]
    finished = False
    if state["level_asked"] >= PER_LEVEL or (state["level_asked"] - state["level_correct"]) >= 2 \
            or state["level_correct"] >= 2:
        passed_level = state["level_correct"] >= 2
        (state["passed"] if passed_level else state["failed"]).append(idx)
        state["level_asked"] = state["level_correct"] = 0
        if passed_level:
            if idx + 1 >= len(CEFR) or (idx + 1) in state["failed"]:
                finished = True
            else:
                state["level_idx"] = idx + 1
        else:
            if idx == 0 or (idx - 1) in state["passed"]:
                finished = True
            else:
                state["level_idx"] = idx - 1
    if len(state["results"]) >= PLACEMENT_MAX:
        finished = True
    nxt = None if finished else _next_item(bank.items_json, state)
    if nxt is None:
        finished = True
    response: dict[str, Any] = {"correct": correct, "correct_index": item["answer_index"]}
    if finished:
        level = _placed_level(state)
        state["placed"] = level
        response |= {"done": True, "result": {"level": level, "answered": len(state["results"]),
                                              "correct": sum(r["correct"] for r in state["results"])}}
    else:
        state["current"] = nxt
        state["asked"].append(nxt)
        response |= {"done": False, "question": _public(bank.items_json[nxt], nxt),
                     "progress": {"n": len(state["results"]) + 1, "max": PLACEMENT_MAX}}
    await redis.set(f"placement:{body.attempt_id}", json.dumps(state), ex=3600)
    return response


class PlacementFinish(BaseModel):
    attempt_id: str
    accept: bool = True


@router.post("/placement/{lang}/finish")
async def placement_finish(lang: str, body: PlacementFinish, user: CurrentUser, db: Db) -> dict[str, Any]:
    raw = await get_redis().get(f"placement:{body.attempt_id}")
    if not raw:
        raise HTTPException(404, "Placement test expired — start again")
    state = json.loads(raw)
    if state["user_id"] != user.id or "placed" not in state:
        raise HTTPException(400, "Finish the test first")
    e = await db.get(Enrolment, (user.id, lang))
    if e is None:
        e = Enrolment(user_id=user.id, language_code=lang, current_level="A1", settings_json={})
        db.add(e)
    result = {"level": state["placed"], "results": state["results"]}
    e.placement_result = result
    if body.accept:
        e.current_level = state["placed"]
        if lang == "ja" and level_index(state["placed"]) > 0:
            e.settings_json = {**(e.settings_json or {}), "kana_done": True}
    await award_xp(db, user, lang, 10, "placement", seconds=len(state["results"]) * 20)
    await db.commit()
    await enqueue("pregenerate", user.id, lang, job_id=f"pregen-{user.id}-{lang}")
    return enrolment_json(e)
