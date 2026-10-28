import hashlib
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert

from ..config import get_settings
from ..deps import CurrentUser, Db, rate_limit
from ..models import Lesson, LessonProgress, Level, Unit, UserVocab, VocabItem
from ..providers.base import ChatMessage
from ..redis_client import get_redis
from ..services.ai import AIService
from ..services.conversation import LookupResult, lookup_system
from ..services.srs import has_kanji, learn_vocab
from ..services.text import strip_ruby

router = APIRouter(tags=["vocab"])


class WordIn(BaseModel):
    word: str = Field(min_length=1, max_length=160)
    meaning: str = Field(min_length=1, max_length=300)
    reading: str | None = Field(default=None, max_length=160)
    gender: str | None = Field(default=None, max_length=8)
    pos: str | None = Field(default=None, max_length=32)
    example: str | None = Field(default=None, max_length=500)
    example_translation: str | None = Field(default=None, max_length=500)
    source: str = Field(default="custom", pattern="^(custom|conversation|lesson)$")
    source_ref: str | None = None


class LookupIn(BaseModel):
    lang: str
    word: str = Field(min_length=1, max_length=80)
    context: str = Field(default="", max_length=600)


def vocab_json(v: VocabItem, uv: UserVocab | None = None, unit_title: str | None = None) -> dict[str, Any]:
    extra = v.extra_json or {}
    return {
        "id": v.id, "lemma": v.lemma, "reading": v.reading, "ruby": extra.get("ruby"), "meaning": v.meaning,
        "pos": v.pos, "gender": v.gender, "level": v.level, "example": v.example,
        "example_translation": v.example_translation, "emoji": extra.get("emoji"), "plural": extra.get("plural"),
        "note": extra.get("note"), "source": v.source, "unit": unit_title,
        "status": uv.status if uv else None, "learned_at": uv.learned_at.isoformat() if uv else None,
    }


@router.get("/vocab/{lang}")
async def list_vocab(lang: str, user: CurrentUser, db: Db, q: str = "", level: str = "", status: str = "",
                     unit_id: int | None = None, page: int = 1, per_page: int = 50) -> dict[str, Any]:
    per_page = min(max(per_page, 10), 200)
    query = (select(VocabItem, UserVocab, Unit.title)
             .join(UserVocab, (UserVocab.vocab_item_id == VocabItem.id) & (UserVocab.user_id == user.id))
             .outerjoin(Unit, Unit.id == VocabItem.unit_id)
             .where(VocabItem.language_code == lang))
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(VocabItem.lemma.ilike(like), VocabItem.meaning.ilike(like),
                                VocabItem.reading.ilike(like)))
    if level:
        query = query.where(VocabItem.level == level)
    if status:
        query = query.where(UserVocab.status == status)
    if unit_id:
        query = query.where(VocabItem.unit_id == unit_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.execute(query.order_by(UserVocab.learned_at.desc(), VocabItem.id.desc())
                            .offset((page - 1) * per_page).limit(per_page))
    units = await db.execute(select(Unit.id, Unit.title, Level.cefr).join(Level, Unit.level_id == Level.id)
                             .where(Level.language_code == lang, Unit.theme != "test").order_by(Level.order, Unit.order))
    return {"items": [vocab_json(v, uv, t) for v, uv, t in rows], "total": total, "page": page,
            "units": [{"id": i, "title": t, "level": c} for i, t, c in units]}


async def save_word(db, user, lang: str, body: WordIn) -> VocabItem:
    lemma = strip_ruby(body.word).strip()
    extra = {"ruby": body.word} if "{" in body.word else {}
    values = dict(language_code=lang, lemma=lemma, reading=body.reading, meaning=body.meaning.strip(), pos=body.pos,
                  gender=body.gender, example=body.example, example_translation=body.example_translation,
                  extra_json=extra, source=body.source, created_by=user.id)
    await db.execute(insert(VocabItem).values(**values).on_conflict_do_nothing(constraint="uq_vocab_lemma_meaning"))
    item = await db.scalar(select(VocabItem).where(VocabItem.language_code == lang, VocabItem.lemma == lemma,
                                                   VocabItem.meaning == values["meaning"]))
    assert item is not None
    await learn_vocab(db, user.id, item, "manual" if body.source == "custom" else body.source, body.source_ref)
    await db.commit()
    return item


@router.post("/vocab/{lang}")
async def add_word(lang: str, body: WordIn, user: CurrentUser, db: Db) -> dict[str, Any]:
    item = await save_word(db, user, lang, body)
    uv = await db.get(UserVocab, (user.id, item.id))
    return vocab_json(item, uv)


@router.post("/lookup")
async def lookup(body: LookupIn, user: CurrentUser, db: Db) -> dict[str, Any]:
    word = body.word.strip().strip(".,!?;:«»\"'“”。、！？「」")
    if not word:
        raise HTTPException(400, "Nothing to look up")
    known = await db.scalar(select(VocabItem).join(UserVocab, (UserVocab.vocab_item_id == VocabItem.id)
                                                   & (UserVocab.user_id == user.id))
                            .where(VocabItem.language_code == body.lang,
                                   func.lower(VocabItem.lemma).in_([word.lower(), f"le {word.lower()}",
                                                                    f"la {word.lower()}", f"il {word.lower()}"]))
                            .limit(1))
    if known:
        return {"word": word, "lemma": known.lemma, "reading": known.reading, "meaning": known.meaning,
                "pos": known.pos, "gender": known.gender, "notes": None, "in_deck": True, "vocab_item_id": known.id}
    redis = get_redis()
    key = "lookup:" + hashlib.sha256(f"{body.lang}|{word}|{body.context}".encode()).hexdigest()
    if cached := await redis.get(key):
        return json.loads(cached) | {"in_deck": False}
    await rate_limit(f"ai:{user.id}", get_settings().rate_limit_per_min)
    ai = AIService(db, user.id, user.role == "admin")
    result = await ai.llm_json("lookup", "conversation", LookupResult, system=lookup_system(body.lang),
                               messages=[ChatMessage("user", json.dumps({"word": word, "sentence": body.context},
                                                                        ensure_ascii=False))],
                               temperature=0.1, max_tokens=400, thinking="minimal")
    data = result.model_dump()
    await redis.set(key, json.dumps(data, ensure_ascii=False), ex=30 * 86400)
    return data | {"in_deck": False}


@router.get("/grammar/{lang}")
async def grammar_reference(lang: str, user: CurrentUser, db: Db, q: str = "") -> dict[str, Any]:
    rows = await db.execute(
        select(Lesson.id, Lesson.title, Lesson.content_json, Unit.title, Level.cefr, LessonProgress.status)
        .join(Unit, Lesson.unit_id == Unit.id).join(Level, Unit.level_id == Level.id)
        .outerjoin(LessonProgress, (LessonProgress.lesson_id == Lesson.id) & (LessonProgress.user_id == user.id))
        .where(Level.language_code == lang, Lesson.kind == "lesson", Lesson.status == "ready")
        .order_by(Level.order, Unit.order, Lesson.order))
    out = []
    needle = q.strip().lower()
    for lesson_id, title, content, unit, cefr, status in rows:
        if status != "completed":
            continue
        for g in (content or {}).get("grammar", []):
            blob = json.dumps(g, ensure_ascii=False).lower()
            if needle and needle not in blob and needle not in title.lower():
                continue
            out.append({"lesson_id": lesson_id, "lesson": title, "unit": unit, "level": cefr, "grammar": g})
    return {"items": out}


@router.get("/kanji/{lang}")
async def known_kanji(lang: str, user: CurrentUser, db: Db) -> dict[str, Any]:
    if lang != "ja":
        return {"kanji": "", "count": 0}
    lemmas = await db.scalars(select(VocabItem.lemma).join(UserVocab, (UserVocab.vocab_item_id == VocabItem.id)
                                                           & (UserVocab.user_id == user.id))
                              .where(VocabItem.language_code == "ja"))
    chars = sorted({ch for lemma in lemmas for ch in lemma if has_kanji(ch)})
    return {"kanji": "".join(chars), "count": len(chars)}
