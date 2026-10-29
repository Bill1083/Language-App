"""Conversation practice: REST endpoints plus the WebSocket that streams AI
replies (text deltas, then sentence-by-sentence audio) and pushes feedback
events produced by the worker."""

import asyncio
import contextlib
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..db import SessionLocal
from ..deps import CurrentUser, Db, rate_limit, user_from_token
from ..models import Conversation, ConversationTurn, Enrolment, Recording, Scenario, Unit, User
from ..providers.base import ChatMessage, ProviderError
from ..providers.stt import audio_ext
from ..redis_client import get_redis
from ..security import SESSION_COOKIE, allowed_ws_origin
from ..services import conversation as cs
from ..services.ai import AIService, BudgetExceeded, overloaded
from ..services.audio_cache import audio_url, tts_key
from ..services.jobs import enqueue, finish_conversation_rewards, store_feedback
from ..services.languages import CEFR, level_index
from ..services.lesson_gen import unit_scenario
from ..services.text import speakable, take_complete_sentences

router = APIRouter(tags=["conversations"])
log = logging.getLogger("parlo.conversation")


class ConversationIn(BaseModel):
    lang: str
    mode: str = Field(pattern="^(scenario|free|unit|tutor)$")
    scenario_id: int | None = None
    unit_id: int | None = None
    level: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class SettingsIn(BaseModel):
    settings: dict[str, Any]


class SayIn(BaseModel):
    english: str = Field(min_length=1, max_length=500)


def scenario_json(s: Scenario) -> dict[str, Any]:
    return {"id": s.id, "slug": s.slug, "title": s.title, "emoji": s.emoji, "description": s.description,
            "goal": s.goal, "ai_role": s.ai_role, "user_role": s.user_role, "min_level": s.min_level,
            "unit_id": s.unit_id}


def turn_json(t: ConversationTurn) -> dict[str, Any]:
    stt = t.stt_json or {}
    return {
        "id": t.id, "role": t.role, "text": t.text, "translation": t.translation,
        "recording_url": f"/api/v1/recordings/{t.audio_key}" if t.audio_key else None,
        "audio_urls": [audio_url(k) for k in (t.audio_keys_json or [])],
        "voice": bool(stt.get("provider")), "pronunciation": stt.get("pronunciation") or [],
        "pronunciation_notes": stt.get("pronunciation_notes") or [],
        "feedback": t.feedback_json, "score": t.score, "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def conversation_json(c: Conversation, scenario: Scenario | None = None, turns: bool = False) -> dict[str, Any]:
    out = {
        "id": c.id, "language": c.language_code, "mode": c.mode, "title": c.title, "level": c.level,
        "settings": {**cs.DEFAULT_SETTINGS, **(c.settings_json or {})}, "goal_achieved": c.goal_achieved,
        "started_at": c.started_at.isoformat(), "ended_at": c.ended_at.isoformat() if c.ended_at else None,
        "summary": c.summary_json, "scenario": scenario_json(scenario) if scenario else None,
    }
    if turns:
        out["turns"] = [turn_json(t) for t in c.turns]
    return out


async def _own_conversation(db, user: User, conv_id: int, with_turns: bool = False) -> Conversation:
    q = select(Conversation).where(Conversation.id == conv_id)
    if with_turns:
        q = q.options(selectinload(Conversation.turns))
    conv = await db.scalar(q)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "Conversation not found")
    return conv


# --------------------------------------------------------------------------- REST


@router.get("/scenarios")
async def list_scenarios(user: CurrentUser, db: Db, lang: str) -> list[dict[str, Any]]:
    rows = await db.scalars(select(Scenario).where(
        Scenario.unit_id.is_(None), or_(Scenario.language_code.is_(None), Scenario.language_code == lang)))
    items = sorted(rows, key=lambda s: (level_index(s.min_level), s.title))
    return [scenario_json(s) for s in items]


@router.get("/conversations")
async def list_conversations(user: CurrentUser, db: Db, lang: str | None = None, q: str = "",
                             page: int = 1) -> dict[str, Any]:
    query = select(Conversation).where(Conversation.user_id == user.id)
    if lang:
        query = query.where(Conversation.language_code == lang)
    if q.strip():
        like = f"%{q.strip()}%"
        sub = select(ConversationTurn.conversation_id).where(ConversationTurn.text.ilike(like))
        query = query.where(or_(Conversation.title.ilike(like), Conversation.id.in_(sub)))
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    convs = list(await db.scalars(query.order_by(Conversation.started_at.desc()).offset((page - 1) * 20).limit(20)))
    stats = {}
    if convs:
        rows = await db.execute(
            select(ConversationTurn.conversation_id, func.count(), func.avg(ConversationTurn.score))
            .where(ConversationTurn.conversation_id.in_([c.id for c in convs]), ConversationTurn.role == "user")
            .group_by(ConversationTurn.conversation_id))
        stats = {cid: (n, avg) for cid, n, avg in rows}
    items = []
    for c in convs:
        n, avg = stats.get(c.id, (0, None))
        items.append(conversation_json(c) | {"turns": n, "avg_score": round(avg) if avg is not None else None})
    return {"items": items, "total": total}


@router.post("/conversations")
async def create_conversation(body: ConversationIn, user: CurrentUser, db: Db) -> dict[str, Any]:
    enrolment = await db.get(Enrolment, (user.id, body.lang))
    if enrolment is None:
        raise HTTPException(404, "You're not enrolled in this language")
    level = body.level if body.level in CEFR else enrolment.current_level
    scenario: Scenario | None = None
    if body.mode == "scenario":
        scenario = await db.get(Scenario, body.scenario_id) if body.scenario_id else None
        if scenario is None:
            raise HTTPException(400, "Pick a scenario")
    elif body.mode == "unit":
        unit = await db.get(Unit, body.unit_id) if body.unit_id else None
        if unit is None:
            raise HTTPException(400, "Pick a unit")
        await rate_limit(f"ai:{user.id}", get_settings().rate_limit_per_min)
        scenario = await unit_scenario(db, unit, AIService(db, user.id, user.role == "admin"))
    prefs = user.settings_json or {}
    settings = {**cs.DEFAULT_SETTINGS,
                "voice_gender": prefs.get("voice_gender", "female"), "speed": prefs.get("speech_speed", 1.0),
                "furigana": prefs.get("furigana", "always"), "romaji": prefs.get("romaji", "auto"),
                "strictness": prefs.get("strictness", "normal"), **body.settings}
    if body.mode == "tutor":
        settings["feedback"] = False
    titles = {"free": "Free conversation", "tutor": "Tutor"}
    title = scenario.title if scenario else titles[body.mode]
    if body.mode == "free" and settings.get("topic"):
        title = f"Free chat: {str(settings['topic'])[:60]}"
    conv = Conversation(user_id=user.id, language_code=body.lang, mode=body.mode, level=level,
                        scenario_id=scenario.id if scenario else None, title=title, settings_json=settings)
    db.add(conv)
    await db.commit()
    return conversation_json(conv, scenario) | {"turns": []}


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: int, user: CurrentUser, db: Db) -> dict[str, Any]:
    conv = await _own_conversation(db, user, conv_id, with_turns=True)
    scenario = await db.get(Scenario, conv.scenario_id) if conv.scenario_id else None
    return conversation_json(conv, scenario, turns=True)


@router.patch("/conversations/{conv_id}")
async def update_conversation(conv_id: int, body: SettingsIn, user: CurrentUser, db: Db) -> dict[str, Any]:
    conv = await _own_conversation(db, user, conv_id)
    allowed = {k: v for k, v in body.settings.items() if k in cs.DEFAULT_SETTINGS}
    conv.settings_json = {**(conv.settings_json or {}), **allowed}
    await db.commit()
    return {"settings": {**cs.DEFAULT_SETTINGS, **conv.settings_json}}


@router.post("/conversations/{conv_id}/end")
async def end_conversation(conv_id: int, user: CurrentUser, db: Db) -> dict[str, Any]:
    conv = await _own_conversation(db, user, conv_id)
    if conv.ended_at is None:
        conv.ended_at = datetime.now(UTC)
        await db.commit()
        rewards = await finish_conversation_rewards(conv.id)
        await enqueue("summarize_conversation", conv.id, job_id=f"summary-{conv.id}")
        return {"ok": True, "rewards": rewards}
    return {"ok": True, "rewards": {}}


@router.post("/conversations/{conv_id}/summary/retry")
async def retry_summary(conv_id: int, user: CurrentUser, db: Db) -> dict[str, bool]:
    await _own_conversation(db, user, conv_id)
    await enqueue("summarize_conversation", conv_id)
    return {"ok": True}


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: int, user: CurrentUser, db: Db) -> dict[str, bool]:
    conv = await _own_conversation(db, user, conv_id)
    recs = list(await db.scalars(select(Recording).where(Recording.conversation_id == conv.id)))
    for rec in recs:
        if rec.path:
            Path(rec.path).unlink(missing_ok=True)
    await db.delete(conv)
    await db.commit()
    return {"ok": True}


@router.post("/conversations/{conv_id}/audio")
async def upload_audio(conv_id: int, user: CurrentUser, db: Db, audio: UploadFile = File(...),
                       duration_ms: int = Form(0)) -> dict[str, Any]:
    conv = await _own_conversation(db, user, conv_id)
    env = get_settings()
    if duration_ms > (env.max_recording_seconds + 2) * 1000:
        raise HTTPException(413, f"Recordings are limited to {env.max_recording_seconds} seconds")
    data = await audio.read()
    if not data:
        raise HTTPException(400, "Empty recording")
    if len(data) > env.max_upload_bytes:
        raise HTTPException(413, "Recording too large")
    rec_id = uuid.uuid4().hex
    mime = audio.content_type or "audio/webm"
    folder = env.recordings_dir / str(user.id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{rec_id}.{audio_ext(mime)}"
    path.write_bytes(data)
    db.add(Recording(id=rec_id, user_id=user.id, path=str(path), mime=mime, duration_ms=duration_ms,
                     conversation_id=conv.id))
    await db.commit()
    return {"recording_id": rec_id}


@router.post("/conversations/{conv_id}/hint")
async def hint(conv_id: int, user: CurrentUser, db: Db) -> dict[str, Any]:
    conv = await _own_conversation(db, user, conv_id, with_turns=True)
    await rate_limit(f"ai:{user.id}", get_settings().rate_limit_per_min)
    scenario = await db.get(Scenario, conv.scenario_id) if conv.scenario_id else None
    context = [{"speaker": "learner" if t.role == "user" else "partner", "text": t.text} for t in conv.turns[-8:]]
    result = await AIService(db, user.id, user.role == "admin").llm_json(
        "hint", "conversation", cs.HintResult, system=cs.hint_system(conv, scenario),
        messages=[ChatMessage("user", json.dumps({"conversation": context}, ensure_ascii=False))],
        temperature=0.7, max_tokens=600, thinking="minimal")
    return result.model_dump()


@router.post("/conversations/{conv_id}/say")
async def how_do_i_say(conv_id: int, body: SayIn, user: CurrentUser, db: Db) -> dict[str, Any]:
    conv = await _own_conversation(db, user, conv_id)
    await rate_limit(f"ai:{user.id}", get_settings().rate_limit_per_min)
    settings = {**cs.DEFAULT_SETTINGS, **(conv.settings_json or {})}
    result = await AIService(db, user.id, user.role == "admin").llm_json(
        "how_do_i_say", "conversation", cs.SayResult,
        system=cs.say_system(conv.language_code, conv.level, settings.get("politeness", "polite")),
        messages=[ChatMessage("user", body.english)], temperature=0.3, max_tokens=500, thinking="minimal")
    return result.model_dump()


@router.post("/turns/{turn_id}/translate")
async def translate_turn(turn_id: int, user: CurrentUser, db: Db) -> dict[str, Any]:
    turn = await db.get(ConversationTurn, turn_id)
    if turn is None:
        raise HTTPException(404, "Message not found")
    conv = await _own_conversation(db, user, turn.conversation_id)
    if not turn.translation:
        await rate_limit(f"ai:{user.id}", get_settings().rate_limit_per_min)
        turn.translation = await AIService(db, user.id, user.role == "admin").llm_text(
            "translate", "conversation",
            system=f"Translate this {cs.LANGUAGES[conv.language_code]['name']} message into natural English. "
                   "Output only the translation.",
            messages=[ChatMessage("user", cs.strip_ruby(turn.text))], temperature=0.1, max_tokens=500,
            thinking="minimal")
        await db.commit()
    return {"translation": turn.translation}


@router.post("/turns/{turn_id}/feedback/retry")
async def retry_feedback(turn_id: int, user: CurrentUser, db: Db) -> dict[str, bool]:
    turn = await db.get(ConversationTurn, turn_id)
    if turn is None or turn.role != "user":
        raise HTTPException(404, "Message not found")
    await _own_conversation(db, user, turn.conversation_id)
    await enqueue("analyze_turn", turn.id)
    return {"ok": True}


# --------------------------------------------------------------------------- WebSocket


class ConversationSocket:
    def __init__(self, ws: WebSocket, user: User, conv_id: int):
        self.ws = ws
        self.user = user
        self.conv_id = conv_id
        self.send_lock = asyncio.Lock()
        self.busy = False

    async def send(self, payload: dict[str, Any]) -> None:
        async with self.send_lock:
            with contextlib.suppress(Exception):
                await self.ws.send_text(json.dumps(payload, ensure_ascii=False, default=str))

    async def forward_events(self) -> None:
        pubsub = get_redis().pubsub()
        await pubsub.subscribe(f"conv:{self.conv_id}")
        try:
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    await self.send(json.loads(message["data"]))
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe()
                await pubsub.aclose()

    async def load(self, db) -> tuple[Conversation, Scenario | None]:
        conv = await db.scalar(select(Conversation).where(Conversation.id == self.conv_id)
                               .options(selectinload(Conversation.turns)))
        assert conv is not None
        scenario = await db.get(Scenario, conv.scenario_id) if conv.scenario_id else None
        return conv, scenario

    async def synth(self, text: str, lang: str, settings: dict[str, Any]) -> str | None:
        async with SessionLocal() as s:
            try:
                return await tts_key(AIService(s, self.user.id, self.user.role == "admin"), text, lang,
                                     purpose="conversation", gender=settings.get("voice_gender", "female"),
                                     speed=float(settings.get("speed", 1.0)))
            except Exception as e:  # audio is optional; the text reply still stands
                log.warning("conversation TTS failed: %s", e)
                return None

    async def ai_reply(self) -> None:
        async with SessionLocal() as db:
            conv, scenario = await self.load(db)
            settings = {**cs.DEFAULT_SETTINGS, **(conv.settings_json or {})}
            voice_on = bool(settings.get("ai_voice", True))
            known = await cs.known_vocab_sample(db, self.user.id, conv.language_code)
            ai = AIService(db, self.user.id, self.user.role == "admin")
            stream_id = uuid.uuid4().hex[:8]
            await self.send({"type": "ai_start", "stream_id": stream_id})
            full, buffer = "", ""
            tts_tasks: list[asyncio.Task] = []

            async def speak(sentence: str, index: int) -> str | None:
                key = await self.synth(sentence, conv.language_code, settings)
                if key:
                    await self.send({"type": "ai_audio", "stream_id": stream_id, "index": index, "url": audio_url(key)})
                return key

            def queue_sentences(sentences: list[str]) -> None:
                for sentence in sentences:
                    if speakable(sentence) and voice_on and conv.mode != "tutor":
                        tts_tasks.append(asyncio.create_task(speak(sentence, len(tts_tasks))))

            async def notice(message: str) -> None:  # e.g. switching to the backup model
                await self.send({"type": "ai_status", "stream_id": stream_id, "message": message})

            temperature = 0.5 if conv.mode == "tutor" else 0.85
            max_tokens = 900 if conv.mode == "tutor" else 400
            async for delta in ai.llm_stream("conversation", "conversation",
                                             system=cs.system_prompt(conv, scenario, known),
                                             messages=cs.history_messages(conv.turns),
                                             temperature=temperature, max_tokens=max_tokens, on_retry=notice):
                full += delta
                buffer += delta
                await self.send({"type": "ai_delta", "stream_id": stream_id, "delta": delta})
                done, buffer = take_complete_sentences(buffer)
                queue_sentences(done)
            queue_sentences([buffer] if buffer.strip() else [])
            keys = [k for k in await asyncio.gather(*tts_tasks)] if tts_tasks else []
            turn = ConversationTurn(conversation_id=conv.id, role="assistant", text=full.strip(),
                                    audio_keys_json=[k for k in keys if k] or None)
            db.add(turn)
            await db.commit()
            await self.send({"type": "ai_done", "stream_id": stream_id, "turn": turn_json(turn)})

    async def user_turn(self, msg: dict[str, Any]) -> None:
        env = get_settings()
        async with SessionLocal() as db:
            conv, scenario = await self.load(db)
            if conv.ended_at:
                await self.send({"type": "error", "message": "This conversation has ended."})
                return
            settings = {**cs.DEFAULT_SETTINGS, **(conv.settings_json or {})}
            ai = AIService(db, self.user.id, self.user.role == "admin")
            await ai.check_budget()
            stt_json: dict[str, Any] | None = None
            audio_key: str | None = None
            combined_feedback = None
            if msg["type"] == "user_audio":
                rec = await db.get(Recording, str(msg.get("recording_id", "")))
                if rec is None or rec.user_id != self.user.id or not rec.path:
                    await self.send({"type": "error", "message": "Recording not found — try again."})
                    return
                await self.send({"type": "transcribing", "client_id": msg.get("client_id")})
                audio = Path(rec.path).read_bytes()
                cfg = await ai.config()
                want_combined = (cfg.stt_combined_feedback and cfg.stt_provider == "gemini"
                                 and settings.get("feedback", True) and conv.mode != "tutor")
                async def notice(message: str) -> None:  # e.g. switching to the backup model
                    await self.send({"type": "transcribing", "client_id": msg.get("client_id"), "message": message})

                result = await ai.transcribe(
                    audio, rec.mime, conv.language_code, rec.duration_ms / 1000,
                    feedback_instructions=cs.feedback_system(conv, scenario, True) if want_combined else None,
                    on_retry=notice)
                text = result.text.strip()
                stt_json = {"provider": result.provider, "model": result.model,
                            "words": [w.__dict__ for w in result.words] if result.words else None,
                            "pronunciation_notes": result.extra.get("pronunciation_notes") or []}
                combined_feedback = cs.feedback_or_none(result.extra.get("feedback")) if want_combined else None
                if env.store_recordings:
                    audio_key = rec.id
                else:
                    Path(rec.path).unlink(missing_ok=True)
                    rec.path = None
                if not text:
                    await db.commit()
                    await self.send({"type": "error", "client_id": msg.get("client_id"),
                                     "message": "I couldn't hear any speech — try again, a little closer to the mic."})
                    return
            else:
                text = str(msg.get("text", "")).strip()[: env.max_text_chars]
                if not text:
                    return
            turn = ConversationTurn(conversation_id=conv.id, role="user", text=text, audio_key=audio_key,
                                    stt_json=stt_json)
            db.add(turn)
            await db.commit()
            await self.send({"type": "user_turn", "client_id": msg.get("client_id"), "turn": turn_json(turn)})
            if settings.get("feedback", True) and conv.mode != "tutor":
                if combined_feedback is not None:
                    await store_feedback(db, conv, turn, combined_feedback.model_dump(), self.user)
                else:
                    await enqueue("analyze_turn", turn.id)

    async def handle(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "ping":
            await self.send({"type": "pong"})
            return
        if kind not in ("user_text", "user_audio", "start"):
            return
        if self.busy:
            await self.send({"type": "error", "message": "Still replying — one moment.", "client_id": msg.get("client_id")})
            return
        self.busy = True
        try:
            await rate_limit(f"ai:{self.user.id}", get_settings().rate_limit_per_min)
            if kind != "start":
                await self.user_turn(msg)
            async with SessionLocal() as db:
                conv, _ = await self.load(db)
                last = conv.turns[-1] if conv.turns else None
            if kind == "start" and last is not None:
                return  # opener already exists
            if kind == "start" or (last and last.role == "user"):
                await self.ai_reply()
        except BudgetExceeded as e:
            await self.send({"type": "error", "message": str(e), "retryable": False, "client_id": msg.get("client_id")})
        except ProviderError as e:
            log.warning("provider error in conversation %s: %s", self.conv_id, e)
            busy = overloaded(e)
            message = ("The AI service is overloaded right now — try again in a minute." if busy
                       else "AI provider unavailable — retry.")
            await self.send({"type": "error", "message": message, "detail": str(e)[:300],
                             "retryable": True, "client_id": msg.get("client_id")})
        except HTTPException as e:
            await self.send({"type": "error", "message": e.detail, "retryable": True, "client_id": msg.get("client_id")})
        finally:
            self.busy = False


@router.websocket("/conversations/{conv_id}/ws")
async def conversation_ws(ws: WebSocket, conv_id: int) -> None:
    async with SessionLocal() as db:
        user = await user_from_token(db, ws.cookies.get(SESSION_COOKIE))
        conv = await db.get(Conversation, conv_id) if user else None
    origin = ws.headers.get("origin")
    origin_ok = allowed_ws_origin(origin, ws.headers.get("host"), ws.headers.get("x-forwarded-host"))
    # Accept before closing so the browser receives the close code; closing
    # during the handshake only shows up as an anonymous network error (1006).
    if user is None or conv is None or conv.user_id != user.id:
        await ws.accept()
        await ws.close(code=4401, reason="not signed in")
        return
    if not origin_ok:
        log.warning("websocket origin %s rejected (host %s, forwarded host %s)", origin,
                    ws.headers.get("host"), ws.headers.get("x-forwarded-host"))
        await ws.accept()
        await ws.close(code=4403, reason="origin not allowed")
        return
    await ws.accept()
    sock = ConversationSocket(ws, user, conv_id)
    forwarder = asyncio.create_task(sock.forward_events())
    tasks: set[asyncio.Task] = set()
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            task = asyncio.create_task(sock.handle(msg))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
    except WebSocketDisconnect:
        pass
    finally:
        # In-flight replies are left to finish so the AI turn is still saved.
        forwarder.cancel()
