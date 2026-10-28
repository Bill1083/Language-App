import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..deps import AdminUser, Db
from ..models import (
    AiUsage,
    AppSetting,
    ContentFlag,
    Exercise,
    Invite,
    Lesson,
    Level,
    Unit,
    User,
)
from ..providers.base import ChatMessage, ProviderError
from ..providers.llm import DEFAULT_MODELS, LLM_PROVIDERS
from ..providers.stt import DEFAULT_STT_MODELS, STT_PROVIDERS
from ..providers.tts import DEFAULT_VOICES, GOOGLE_CHIRP_VOICES, LOCALES, TTS_PROVIDERS
from ..redis_client import get_redis
from ..schemas.lesson import GrammarPoint, VocabEntry, validate_exercises
from ..security import new_token
from ..services import runtime_config
from ..services.ai import AIService
from ..services.audio_cache import audio_url, tts_key
from ..services.jobs import JOB_LOG, enqueue
from ..services.lesson_gen import generate_placement_bank, save_content
from ..services.pricing import pricing_table
from ..services.runtime_config import OVERRIDABLE, PROVIDER_KEY_ENV, get_ai_config, mask

router = APIRouter(prefix="/admin", tags=["admin"])

TEST_SENTENCES = {"fr": "Bonjour ! Je voudrais un café, s'il vous plaît.",
                  "it": "Buongiorno! Vorrei un caffè, per favore.",
                  "ja": "こんにちは。コーヒーを一つください。"}


# --------------------------------------------------------------------------- users & invites


class UserPatch(BaseModel):
    role: str | None = Field(default=None, pattern="^(admin|user)$")
    is_active: bool | None = None


class InviteIn(BaseModel):
    note: str | None = Field(default=None, max_length=120)
    days: int = Field(default=7, ge=1, le=90)


@router.get("/users")
async def users(admin: AdminUser, db: Db) -> list[dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(days=30)
    cost = dict((await db.execute(select(AiUsage.user_id, func.sum(AiUsage.est_cost))
                                  .where(AiUsage.created_at >= since).group_by(AiUsage.user_id))).all())
    rows = await db.scalars(select(User).order_by(User.created_at))
    return [{"id": u.id, "email": u.email, "display_name": u.display_name, "role": u.role, "is_active": u.is_active,
             "created_at": u.created_at.isoformat(), "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
             "cost_30d": round(float(cost.get(u.id) or 0), 4)} for u in rows]


@router.patch("/users/{user_id}")
async def patch_user(user_id: int, body: UserPatch, admin: AdminUser, db: Db) -> dict[str, bool]:
    u = await db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    if u.id == admin.id and (body.role == "user" or body.is_active is False):
        raise HTTPException(400, "You can't demote or disable yourself")
    if body.role:
        u.role = body.role
    if body.is_active is not None:
        u.is_active = body.is_active
    await db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, admin: AdminUser, db: Db) -> dict[str, bool]:
    if user_id == admin.id:
        raise HTTPException(400, "You can't delete yourself")
    u = await db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    await db.delete(u)
    await db.commit()
    return {"ok": True}


@router.get("/invites")
async def invites(admin: AdminUser, db: Db) -> list[dict[str, Any]]:
    rows = await db.execute(select(Invite, User.email).outerjoin(User, User.id == Invite.used_by)
                            .order_by(Invite.created_at.desc()).limit(100))
    now = datetime.now(UTC)
    return [{"id": i.id, "token": i.token, "url": f"/register?invite={i.token}", "note": i.note,
             "created_at": i.created_at.isoformat(), "expires_at": i.expires_at.isoformat(), "used_by": email,
             "status": "used" if i.used_by else "expired" if i.expires_at < now else "active"} for i, email in rows]


@router.post("/invites")
async def create_invite(body: InviteIn, admin: AdminUser, db: Db) -> dict[str, Any]:
    inv = Invite(token=new_token(18), created_by=admin.id, note=body.note,
                 expires_at=datetime.now(UTC) + timedelta(days=body.days))
    db.add(inv)
    await db.commit()
    return {"id": inv.id, "token": inv.token, "url": f"/register?invite={inv.token}",
            "expires_at": inv.expires_at.isoformat()}


@router.delete("/invites/{invite_id}")
async def revoke_invite(invite_id: int, admin: AdminUser, db: Db) -> dict[str, bool]:
    await db.execute(delete(Invite).where(Invite.id == invite_id, Invite.used_by.is_(None)))
    await db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- providers


@router.get("/config")
async def get_config(admin: AdminUser, db: Db) -> dict[str, Any]:
    cfg = await get_ai_config(db)
    overrides = await runtime_config.load_overrides(db)
    env = get_settings()
    providers = set(LLM_PROVIDERS) | set(TTS_PROVIDERS) | set(STT_PROVIDERS) | {"google_cloud"}
    keys = {p: {"set": bool(cfg.key_for(p, "llm") or cfg.key_for(p, "tts") or cfg.key_for(p, "stt")),
                "masked": mask(cfg.keys.get(p, "") or cfg.key_for(p, "llm") or cfg.key_for(p, "tts")
                               or cfg.key_for(p, "stt")),
                "source": "admin" if cfg.keys.get(p) else "env"} for p in sorted(providers)}
    return {
        "effective": {
            "llm_provider": cfg.llm_provider, "llm_base_url": cfg.llm_base_url,
            "llm_model_conversation": cfg.llm_models["conversation"], "llm_model_feedback": cfg.llm_models["feedback"],
            "llm_model_content": cfg.llm_models["content"], "tts_provider_lesson": cfg.tts_provider_lesson,
            "tts_provider_conversation": cfg.tts_provider_conversation, "tts_base_url": cfg.tts_base_url,
            "tts_azure_region": cfg.tts_azure_region, "stt_provider": cfg.stt_provider,
            "stt_base_url": cfg.stt_base_url, "stt_model": cfg.stt_model_name(),
            "stt_combined_feedback": cfg.stt_combined_feedback, "daily_ai_budget_usd": cfg.daily_ai_budget_usd,
        },
        "voices": {p: {lang: {g: cfg.voice_for(p, lang, g) for g in ("female", "male")} for lang in LOCALES}
                   for p in TTS_PROVIDERS},
        "overrides": {k: v for k, v in overrides.items() if k not in ("keys",)},
        "keys": keys,
        "options": {
            "llm_providers": list(LLM_PROVIDERS), "tts_providers": list(TTS_PROVIDERS),
            "stt_providers": list(STT_PROVIDERS), "default_models": DEFAULT_MODELS,
            "default_stt_models": DEFAULT_STT_MODELS, "default_voices": DEFAULT_VOICES,
            "google_voices": {lang: [f"{loc}-Chirp3-HD-{v}" for v in GOOGLE_CHIRP_VOICES]
                              for lang, loc in LOCALES.items()},
        },
        "registration_mode": env.registration_mode,
        "pricing": pricing_table(cfg.pricing),
    }


@router.put("/config")
async def put_config(body: dict[str, Any], admin: AdminUser, db: Db) -> dict[str, bool]:
    for key, value in body.items():
        if key not in OVERRIDABLE:
            raise HTTPException(400, f"Unknown setting {key}")
        row = await db.get(AppSetting, key)
        if key == "keys":
            current = dict(row.value_json) if row else {}
            for provider, secret in (value or {}).items():
                if provider not in PROVIDER_KEY_ENV and provider not in ("google", "google_cloud"):
                    continue
                if secret is None or secret == "":
                    current.pop(provider, None)  # clear → fall back to .env
                elif not str(secret).startswith("••••"):
                    current[provider] = str(secret).strip()
            value = current
        if value in (None, "") or value == {}:
            if row:
                await db.delete(row)
            continue
        if row:
            row.value_json = value
        else:
            db.add(AppSetting(key=key, value_json=value))
    await db.commit()
    runtime_config.invalidate()
    return {"ok": True}


class LLMTest(BaseModel):
    task: str = Field(default="conversation", pattern="^(conversation|feedback|content)$")


@router.post("/test/llm")
async def test_llm(body: LLMTest, admin: AdminUser, db: Db) -> dict[str, Any]:
    runtime_config.invalidate()
    ai = AIService(db, admin.id, True)
    cfg = await ai.config()
    started = time.monotonic()
    try:
        text = await ai.llm_text("admin_test", body.task, system="Reply in one short sentence.",
                                 messages=[ChatMessage("user", "Say hello in French, Italian and Japanese.")],
                                 max_tokens=200, thinking="minimal")
        return {"ok": True, "latency_ms": int((time.monotonic() - started) * 1000), "sample": text,
                "provider": cfg.llm_provider, "model": cfg.llm_models[body.task]}
    except ProviderError as e:
        return {"ok": False, "latency_ms": int((time.monotonic() - started) * 1000), "error": str(e),
                "provider": cfg.llm_provider, "model": cfg.llm_models[body.task]}


class TTSTest(BaseModel):
    lang: str = Field(pattern="^(fr|it|ja)$")
    voice: str | None = None
    purpose: str = Field(default="lesson", pattern="^(lesson|conversation)$")
    text: str | None = Field(default=None, max_length=300)
    speed: float = 1.0


@router.post("/test/tts")
async def test_tts(body: TTSTest, admin: AdminUser, db: Db) -> dict[str, Any]:
    runtime_config.invalidate()
    ai = AIService(db, admin.id, True)
    started = time.monotonic()
    try:
        key = await tts_key(ai, body.text or TEST_SENTENCES[body.lang], body.lang, purpose=body.purpose,
                            voice=body.voice or None, speed=body.speed)
        return {"ok": True, "latency_ms": int((time.monotonic() - started) * 1000), "url": audio_url(key)}
    except (ProviderError, ValueError) as e:
        return {"ok": False, "latency_ms": int((time.monotonic() - started) * 1000), "error": str(e)}


class STTTest(BaseModel):
    lang: str = Field(pattern="^(fr|it|ja)$")


@router.post("/test/stt")
async def test_stt(body: STTTest, admin: AdminUser, db: Db) -> dict[str, Any]:
    """Round trip without a microphone: synthesise a sentence, then transcribe it back."""
    runtime_config.invalidate()
    ai = AIService(db, admin.id, True)
    expected = TEST_SENTENCES[body.lang]
    try:
        key = await tts_key(ai, expected, body.lang, purpose="lesson")
    except (ProviderError, ValueError) as e:
        return {"ok": False, "error": f"TTS step failed (needed to produce test audio): {e}"}
    from ..services.audio_cache import path_for

    started = time.monotonic()
    try:
        result = await ai.transcribe(path_for(key).read_bytes(), "audio/mpeg", body.lang, 4.0)
        return {"ok": True, "latency_ms": int((time.monotonic() - started) * 1000), "transcript": result.text,
                "expected": expected, "provider": result.provider, "model": result.model}
    except ProviderError as e:
        return {"ok": False, "latency_ms": int((time.monotonic() - started) * 1000), "error": str(e)}


# --------------------------------------------------------------------------- usage


@router.get("/usage")
async def usage(admin: AdminUser, db: Db, days: int = 30) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=min(days, 365))
    day = func.date_trunc("day", AiUsage.created_at)
    by_day = await db.execute(select(day, func.sum(AiUsage.est_cost), func.count()).where(AiUsage.created_at >= since)
                              .group_by(day).order_by(day))
    by_model = await db.execute(
        select(AiUsage.provider, AiUsage.model, func.count(), func.sum(AiUsage.input_tokens),
               func.sum(AiUsage.output_tokens), func.sum(AiUsage.chars), func.sum(AiUsage.audio_seconds),
               func.sum(AiUsage.est_cost), func.avg(AiUsage.latency_ms), func.sum(case((AiUsage.ok.is_(False), 1), else_=0)))
        .where(AiUsage.created_at >= since).group_by(AiUsage.provider, AiUsage.model)
        .order_by(func.sum(AiUsage.est_cost).desc()))
    by_task = await db.execute(select(AiUsage.task, func.count(), func.sum(AiUsage.est_cost))
                               .where(AiUsage.created_at >= since).group_by(AiUsage.task)
                               .order_by(func.sum(AiUsage.est_cost).desc()))
    by_user = await db.execute(select(User.email, func.count(), func.sum(AiUsage.est_cost))
                               .join(User, User.id == AiUsage.user_id, isouter=True)
                               .where(AiUsage.created_at >= since).group_by(User.email))
    today = datetime.combine(datetime.now(UTC).date(), datetime.min.time(), tzinfo=UTC)
    month = today.replace(day=1)
    spent_today = await db.scalar(select(func.coalesce(func.sum(AiUsage.est_cost), 0)).where(AiUsage.created_at >= today))
    spent_month = await db.scalar(select(func.coalesce(func.sum(AiUsage.est_cost), 0)).where(AiUsage.created_at >= month))
    cfg = await get_ai_config(db)
    return {
        "today": round(float(spent_today or 0), 4), "month": round(float(spent_month or 0), 4),
        "daily_budget_per_user": cfg.daily_ai_budget_usd,
        "by_day": [{"day": d.date().isoformat(), "cost": round(float(c or 0), 4), "calls": n} for d, c, n in by_day],
        "by_model": [{"provider": p, "model": m, "calls": n, "input_tokens": int(i or 0), "output_tokens": int(o or 0),
                      "chars": int(ch or 0), "audio_seconds": round(float(a or 0), 1), "cost": round(float(c or 0), 4),
                      "avg_latency_ms": int(lat or 0), "failures": int(f or 0)}
                     for p, m, n, i, o, ch, a, c, lat, f in by_model],
        "by_task": [{"task": t, "calls": n, "cost": round(float(c or 0), 4)} for t, n, c in by_task],
        "by_user": [{"email": e or "(system)", "calls": n, "cost": round(float(c or 0), 4)} for e, n, c in by_user],
    }


# --------------------------------------------------------------------------- content


@router.get("/content")
async def content(admin: AdminUser, db: Db, lang: str) -> dict[str, Any]:
    levels = await db.scalars(select(Level).where(Level.language_code == lang).order_by(Level.order)
                              .options(selectinload(Level.units).selectinload(Unit.lessons)))
    flags = dict((await db.execute(select(ContentFlag.target_id, func.count()).where(
        ContentFlag.target_type == "lesson", ContentFlag.status == "open").group_by(ContentFlag.target_id))).all())
    out = []
    counts: dict[str, int] = {}
    for lv in levels:
        units = []
        for u in lv.units:
            lessons = []
            for le in u.lessons:
                counts[le.status] = counts.get(le.status, 0) + 1
                lessons.append({"id": le.id, "slug": le.slug, "title": le.title, "kind": le.kind, "status": le.status,
                                "version": le.version, "edited": le.edited, "model_used": le.model_used,
                                "generated_at": le.generated_at.isoformat() if le.generated_at else None,
                                "error": le.error, "flags": flags.get(le.id, 0)})
            units.append({"id": u.id, "title": u.title, "lessons": lessons})
        out.append({"cefr": lv.cefr, "units": units})
    return {"levels": out, "counts": counts}


@router.get("/lessons/{lesson_id}")
async def lesson_detail(lesson_id: int, admin: AdminUser, db: Db) -> dict[str, Any]:
    le = await db.scalar(select(Lesson).where(Lesson.id == lesson_id).options(selectinload(Lesson.exercises)))
    if le is None:
        raise HTTPException(404, "Lesson not found")
    return {"id": le.id, "slug": le.slug, "title": le.title, "kind": le.kind, "status": le.status,
            "skeleton": le.skeleton_json, "content": {**(le.content_json or {}),
                                                      "exercises": [ex.payload_json for ex in le.exercises]},
            "error": le.error, "edited": le.edited, "version": le.version}


class LessonEdit(BaseModel):
    content: dict[str, Any]


@router.put("/lessons/{lesson_id}")
async def edit_lesson(lesson_id: int, body: LessonEdit, admin: AdminUser, db: Db) -> dict[str, Any]:
    le = await db.scalar(select(Lesson).where(Lesson.id == lesson_id).options(
        selectinload(Lesson.unit).selectinload(Unit.level)))
    if le is None:
        raise HTTPException(404, "Lesson not found")
    content = body.content
    exercises = content.get("exercises") or []
    try:
        for v in content.get("vocab", []):
            VocabEntry.model_validate(v)
        for g in content.get("grammar", []):
            GrammarPoint.model_validate(g)
    except ValidationError as e:
        raise HTTPException(400, f"Invalid vocab/grammar: {e.errors()[0]}") from None
    builtin = {"vocab_intro", "grammar_note", "kana_intro", "kana_choice"}
    generated = [ex for ex in exercises if ex.get("type") not in builtin]
    _good, errors = validate_exercises(generated)
    if errors:
        raise HTTPException(400, "Invalid exercises: " + "; ".join(errors[:5]))
    await save_content(db, le, content, model=le.model_used)
    le.edited = True
    await db.commit()
    return {"ok": True, "version": le.version}


@router.post("/lessons/{lesson_id}/regenerate")
async def regenerate(lesson_id: int, admin: AdminUser, db: Db) -> dict[str, bool]:
    le = await db.get(Lesson, lesson_id)
    if le is None:
        raise HTTPException(404, "Lesson not found")
    le.status, le.edited = "queued", False
    await db.commit()
    await enqueue("generate_lesson", lesson_id, True)
    return {"ok": True}


class PregenIn(BaseModel):
    lang: str
    cefr: str | None = None
    unit_id: int | None = None


@router.post("/pregenerate")
async def pregenerate(body: PregenIn, admin: AdminUser, db: Db) -> dict[str, int]:
    q = (select(Lesson.id).join(Unit, Lesson.unit_id == Unit.id).join(Level, Unit.level_id == Level.id)
         .where(Level.language_code == body.lang, Lesson.status.in_(["pending", "failed"])))
    if body.cefr:
        q = q.where(Level.cefr == body.cefr)
    if body.unit_id:
        q = q.where(Unit.id == body.unit_id)
    ids = list(await db.scalars(q.order_by(Level.order, Unit.order, Lesson.order).limit(300)))
    for lid in ids:
        le = await db.get(Lesson, lid)
        if le:
            le.status = "queued"
    await db.commit()
    for lid in ids:
        await enqueue("generate_lesson", lid, job_id=f"lesson-{lid}")
    return {"queued": len(ids)}


@router.post("/placement/{lang}/regenerate")
async def regenerate_placement(lang: str, admin: AdminUser, db: Db) -> dict[str, int]:
    bank = await generate_placement_bank(db, lang, AIService(db, admin.id, True))
    return {"items": len(bank.items_json)}


# --------------------------------------------------------------------------- flags & jobs


@router.get("/flags")
async def flags(admin: AdminUser, db: Db, status: str = "open") -> list[dict[str, Any]]:
    rows = await db.execute(select(ContentFlag, User.email).outerjoin(User, User.id == ContentFlag.user_id)
                            .where(ContentFlag.status == status).order_by(ContentFlag.created_at.desc()).limit(200))
    out = []
    for f, email in rows:
        lesson_id = f.target_id if f.target_type == "lesson" else None
        context = None
        if f.target_type == "exercise":
            ex = await db.get(Exercise, f.target_id)
            if ex:
                lesson_id, context = ex.lesson_id, ex.payload_json
        out.append({"id": f.id, "target_type": f.target_type, "target_id": f.target_id, "reason": f.reason,
                    "status": f.status, "created_at": f.created_at.isoformat(), "user": email,
                    "lesson_id": lesson_id, "context": context})
    return out


class FlagPatch(BaseModel):
    status: str = Field(pattern="^(open|resolved|dismissed)$")


@router.patch("/flags/{flag_id}")
async def patch_flag(flag_id: int, body: FlagPatch, admin: AdminUser, db: Db) -> dict[str, bool]:
    f = await db.get(ContentFlag, flag_id)
    if f is None:
        raise HTTPException(404, "Flag not found")
    f.status = body.status
    await db.commit()
    return {"ok": True}


@router.get("/jobs")
async def jobs(admin: AdminUser, db: Db) -> dict[str, Any]:
    redis = get_redis()
    queued = await redis.zcard("arq:queue")
    in_progress = len([k async for k in redis.scan_iter("arq:in-progress:*", count=200)])
    log = [json.loads(x) for x in await redis.lrange(JOB_LOG, 0, 49)]
    statuses = dict((await db.execute(select(Lesson.status, func.count()).group_by(Lesson.status))).all())
    return {"queued": queued, "in_progress": in_progress, "recent": log, "lessons": statuses}
