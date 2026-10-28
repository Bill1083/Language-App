import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select, tuple_, update
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..deps import CurrentUser, Db, rate_limit
from ..models import (
    ContentFlag,
    Enrolment,
    Exercise,
    ExerciseAttempt,
    Lesson,
    LessonProgress,
    LlmJudgement,
    Unit,
    VocabItem,
)
from ..providers.base import ChatMessage
from ..services import prompts
from ..services.ai import AIService
from ..services.answer_check import check_answer, normalize, strip_accents
from ..services.course import course_map, lesson_unlocked, next_cefr
from ..services.jobs import enqueue
from ..services.languages import level_index
from ..services.progress import XP, award_xp, check_achievements, grant_and_describe
from ..services.srs import add_mistake_card, learn_vocab
from ..services.text import strip_ruby

router = APIRouter(tags=["course"])


class Judgement(BaseModel):
    correct: bool
    explanation: str


class AnswerIn(BaseModel):
    answer: str | None = Field(default=None, max_length=2000)
    selected: int | None = None
    client_correct: bool | None = None  # for match_pairs / speak, graded in the browser


class CompleteIn(BaseModel):
    correct: int
    total: int
    seconds: int = 0
    mistakes: list[int] = Field(default_factory=list)


class FlagIn(BaseModel):
    target_type: str = Field(pattern="^(lesson|exercise|vocab|turn)$")
    target_id: int
    reason: str = Field(min_length=1, max_length=1000)


async def _enrolment(db, user, lang: str) -> Enrolment:
    e = await db.get(Enrolment, (user.id, lang))
    if e is None:
        raise HTTPException(404, "You're not enrolled in this language yet")
    return e


@router.get("/course/{lang}")
async def get_course(lang: str, user: CurrentUser, db: Db) -> dict[str, Any]:
    return await course_map(db, user.id, await _enrolment(db, user, lang))


async def _lesson_with_context(db, lesson_id: int) -> Lesson:
    lesson = await db.scalar(select(Lesson).where(Lesson.id == lesson_id).options(
        selectinload(Lesson.unit).selectinload(Unit.level), selectinload(Lesson.exercises)))
    if lesson is None:
        raise HTTPException(404, "Lesson not found")
    return lesson


@router.get("/lessons/{lesson_id}")
async def get_lesson(lesson_id: int, user: CurrentUser, db: Db, response: Response) -> dict[str, Any]:
    lesson = await _lesson_with_context(db, lesson_id)
    lang = lesson.unit.level.language_code
    enrolment = await _enrolment(db, user, lang)
    course = await course_map(db, user.id, enrolment)
    if not lesson_unlocked(course, lesson.id) and user.role != "admin":
        raise HTTPException(403, "This lesson is locked — finish the earlier lessons first")
    meta = {"id": lesson.id, "title": lesson.title, "kind": lesson.kind, "language": lang,
            "level": lesson.unit.level.cefr, "unit": {"id": lesson.unit.id, "title": lesson.unit.title},
            "status": lesson.status}
    if lesson.status != "ready":
        if lesson.status in ("pending", "failed") or (lesson.status == "queued" and not lesson.exercises):
            await db.execute(update(Lesson).where(Lesson.id == lesson.id).values(status="queued"))
            await db.commit()
            await enqueue("generate_lesson", lesson.id, job_id=f"lesson-{lesson.id}")
            meta["status"] = "queued"
        response.status_code = 202
        return meta | {"error": lesson.error if lesson.status == "failed" else None}
    progress = await db.get(LessonProgress, (user.id, lesson.id))
    # Keep the learner's path warm: generate what's next while they work on this one.
    await enqueue("pregenerate", user.id, lang, job_id=f"pregen-{user.id}-{lang}")
    return meta | {
        "content": lesson.content_json,
        "exercises": [{"id": ex.id, "type": ex.type, **ex.payload_json} for ex in lesson.exercises],
        "progress": {"status": progress.status, "best_accuracy": progress.best_accuracy} if progress else None,
    }


def _expected_answers(ex: Exercise) -> tuple[list[str], str, bool]:
    """(accepted answers, language of the answer, typo tolerance)"""
    p = ex.payload_json
    lang_target = "target"
    if ex.type == "translate":
        return p["answers"], ("en" if p["direction"] == "to_english" else lang_target), True
    if ex.type == "fill_blank":
        return p["answers"], lang_target, p.get("focus") == "vocabulary"
    if ex.type == "dictation":
        return [p["text"], *p.get("accepted", [])], lang_target, True
    if ex.type == "word_bank":
        return [p["answer"], *p.get("accepted", [])], lang_target, False
    return [], lang_target, False


def _correct_display(ex: Exercise) -> str | None:
    p = ex.payload_json
    if ex.type in ("multiple_choice", "listening_choice", "kana_choice"):
        return p["options"][p["answer_index"]]
    if ex.type == "translate":
        return p["answers"][0]
    if ex.type == "fill_blank":
        return p["sentence"].replace("___", p["answers"][0])
    if ex.type in ("dictation", "speak"):
        return p["text"]
    if ex.type == "word_bank":
        return p["answer"]
    return None


def _mistake_prompt(ex: Exercise) -> str:
    p = ex.payload_json
    return {
        "translate": lambda: f"Translate: {p['source']}",
        "fill_blank": lambda: f"Fill the blank: {p['sentence']}" + (f" {p['hint']}" if p.get("hint") else ""),
        "dictation": lambda: "Write what you hear",
        "word_bank": lambda: f"Translate: {p['prompt']}",
        "multiple_choice": lambda: f"{p['prompt']} — {p['question']}",
        "listening_choice": lambda: "What did you hear?",
        "kana_choice": lambda: f"Read: {p['char']}" if p.get("mode") == "char_to_romaji" else f"Which is “{p['romaji']}”?",
    }.get(ex.type, lambda: p.get("prompt", "Review"))()


async def _judge(ai: AIService, db, lang: str, cefr: str, ex: Exercise, answer: str) -> Judgement:
    p = ex.payload_json
    key_src = json.dumps([lang, p["source"], p["answers"], normalize(answer, "en" if p["direction"] == "to_english" else lang)],
                         ensure_ascii=False)
    key = hashlib.sha256(key_src.encode()).hexdigest()
    cached = await db.get(LlmJudgement, key)
    if cached:
        return Judgement(correct=cached.is_correct, explanation=cached.explanation)
    request = json.dumps({"direction": p["direction"], "source": p["source"], "reference_answers": p["answers"],
                          "learner_answer": answer}, ensure_ascii=False)
    verdict = await ai.llm_json("answer_judge", "feedback", Judgement, system=prompts.judge_system(lang, cefr),
                                messages=[ChatMessage("user", request)], temperature=0.0, max_tokens=400,
                                thinking="minimal")
    db.add(LlmJudgement(key=key, is_correct=verdict.correct, explanation=verdict.explanation))
    return verdict


@router.post("/exercises/{exercise_id}/answer")
async def answer_exercise(exercise_id: int, body: AnswerIn, user: CurrentUser, db: Db) -> dict[str, Any]:
    ex = await db.scalar(select(Exercise).where(Exercise.id == exercise_id).options(
        selectinload(Exercise.lesson).selectinload(Lesson.unit).selectinload(Unit.level)))
    if ex is None:
        raise HTTPException(404, "Exercise not found")
    lang = ex.lesson.unit.level.language_code
    cefr = ex.lesson.unit.level.cefr
    p = ex.payload_json
    result: dict[str, Any] = {"explanation": p.get("explanation", ""), "correct_answer": _correct_display(ex),
                              "judged_by_ai": False, "segments": None}
    if ex.type in ("multiple_choice", "listening_choice", "kana_choice"):
        ok = body.selected == p["answer_index"]
        result |= {"verdict": "correct" if ok else "wrong", "correct_index": p["answer_index"]}
        given = p["options"][body.selected] if body.selected is not None and 0 <= body.selected < len(p["options"]) else ""
    elif ex.type in ("translate", "fill_blank", "dictation", "word_bank"):
        accepted, answer_lang, typo = _expected_answers(ex)
        check_lang = "en" if answer_lang == "en" else lang
        given = body.answer or ""
        checked = check_answer(given, accepted, check_lang, typo_tolerance=typo)
        result |= {"verdict": checked.verdict, "matched": checked.matched,
                   "segments": [s.__dict__ for s in checked.segments]}
        if ex.type == "fill_blank" and checked.matched:
            result["correct_answer"] = p["sentence"].replace("___", checked.matched)
        if checked.verdict == "wrong" and ex.type == "translate" and given.strip():
            await rate_limit(f"ai:{user.id}", get_settings().rate_limit_per_min)
            try:
                verdict = await _judge(AIService(db, user.id, user.role == "admin"), db, lang, cefr, ex, given)
                if verdict.correct:
                    result |= {"verdict": "ai_accepted", "judged_by_ai": True, "explanation": verdict.explanation,
                               "correct_answer": p["answers"][0], "segments": None}
                else:
                    result |= {"judged_by_ai": True, "ai_explanation": verdict.explanation}
            except Exception as e:  # judging is a bonus; never block the lesson on it
                result["judge_error"] = str(e)[:200]
    else:  # match_pairs, speak, intro cards — graded client-side
        ok = body.client_correct is not False
        result["verdict"] = "correct" if ok else "wrong"
        given = body.answer or ""
    result["is_correct"] = result["verdict"] != "wrong"
    db.add(ExerciseAttempt(user_id=user.id, exercise_id=ex.id, answer=given[:2000],
                           is_correct=result["is_correct"], verdict=result["verdict"]))
    if not result["is_correct"] and ex.type not in ("speak", "match_pairs", "reading", "kana_intro", "vocab_intro",
                                                    "grammar_note"):
        await add_mistake_card(db, user.id, lang, prompt=_mistake_prompt(ex), answer=result["correct_answer"] or "",
                               explanation=result.get("ai_explanation") or p.get("explanation"), source="lesson",
                               source_ref=f"exercise:{ex.id}", wrong=given or None,
                               context=p.get("translation"))
    await db.commit()
    return result


@router.post("/exercises/{exercise_id}/speak")
async def speak_exercise(exercise_id: int, user: CurrentUser, db: Db, audio: UploadFile = File(...),
                         duration_ms: int = Form(0)) -> dict[str, Any]:
    ex = await db.scalar(select(Exercise).where(Exercise.id == exercise_id).options(
        selectinload(Exercise.lesson).selectinload(Lesson.unit).selectinload(Unit.level)))
    if ex is None or ex.type != "speak":
        raise HTTPException(404, "Speaking exercise not found")
    await rate_limit(f"ai:{user.id}", get_settings().rate_limit_per_min)
    data = await audio.read()
    if len(data) > get_settings().max_upload_bytes:
        raise HTTPException(413, "Recording too long")
    lang = ex.lesson.unit.level.language_code
    ai = AIService(db, user.id, user.role == "admin")
    stt = await ai.transcribe(data, audio.content_type or "audio/webm", lang, duration_ms / 1000)
    return word_check(ex.payload_json["text"], stt.text, lang)


def word_check(expected: str, heard: str, lang: str) -> dict[str, Any]:
    """Word-level comparison for "Speak it" — which intended words were recognised."""
    from difflib import SequenceMatcher

    exp_plain = strip_ruby(expected)
    if lang == "ja":
        e_norm, h_norm = normalize(exp_plain, "ja"), normalize(heard.replace("[?]", ""), "ja")
        sm = SequenceMatcher(None, e_norm, h_norm)
        matched = sum(b.size for b in sm.get_matching_blocks())
        accuracy = matched / max(1, len(e_norm))
        words = [{"word": e_norm[i1:i2], "ok": tag == "equal"} for tag, i1, i2, _, _ in sm.get_opcodes() if i2 > i1]
    else:
        e_words = exp_plain.split()
        key = lambda w: strip_accents(normalize(w, lang))  # noqa: E731
        h_keys = [key(w) for w in heard.replace("[?]", "").split()]
        sm = SequenceMatcher(None, [key(w) for w in e_words], h_keys)
        ok_idx = {i for tag, i1, i2, _, _ in sm.get_opcodes() if tag == "equal" for i in range(i1, i2)}
        words = [{"word": w, "ok": i in ok_idx} for i, w in enumerate(e_words)]
        accuracy = len(ok_idx) / max(1, len(e_words))
    verdict = "correct" if accuracy >= 0.85 else "typo" if accuracy >= 0.6 else "wrong"
    return {"transcript": heard, "words": words, "accuracy": round(accuracy, 2), "verdict": verdict,
            "is_correct": verdict != "wrong",
            "note": "Approximate — based on speech recognition, not a phoneme-level assessment."}


@router.post("/lessons/{lesson_id}/complete")
async def complete_lesson(lesson_id: int, body: CompleteIn, user: CurrentUser, db: Db) -> dict[str, Any]:
    lesson = await _lesson_with_context(db, lesson_id)
    lang = lesson.unit.level.language_code
    enrolment = await _enrolment(db, user, lang)
    accuracy = body.correct / body.total if body.total else 1.0
    content = lesson.content_json or {}
    is_test = bool(content.get("is_test")) or lesson.kind in ("checkpoint", "level_test")
    pass_mark = float(content.get("pass_mark", 0.8)) if is_test else 0.0
    passed = accuracy >= pass_mark
    response: dict[str, Any] = {"accuracy": round(accuracy, 3), "passed": passed, "is_test": is_test,
                                "pass_mark": pass_mark, "new_words": [], "achievements": [], "level_up": None}

    prog = await db.get(LessonProgress, (user.id, lesson.id))
    if prog is None:
        prog = LessonProgress(user_id=user.id, lesson_id=lesson.id, status="started", best_accuracy=0, attempts=0)
        db.add(prog)
    prog.attempts += 1
    first_completion = prog.status != "completed"
    if passed:
        prog.status = "completed"
        prog.completed_at = prog.completed_at or datetime.now(UTC)
        prog.best_accuracy = max(prog.best_accuracy, accuracy)

    xp = 0
    if passed:
        base = {"checkpoint": XP["checkpoint"], "level_test": XP["level_test"], "kana": XP["kana"]}.get(lesson.kind,
                                                                                                     XP["lesson"])
        xp = base if first_completion else max(2, base // 3)
        if accuracy >= 0.999:
            xp += XP["lesson_perfect"]
        # Learn this lesson's words: they join the vocabulary list and the review deck.
        if lesson.kind == "lesson":
            # Look words up by the lesson's own list: a word taught in several lessons
            # belongs to all of them, not just the one that generated it first.
            keys = [(strip_ruby(v["word"])[:160], v["meaning"][:300]) for v in content.get("vocab", [])]
            items = list(await db.scalars(select(VocabItem).where(
                VocabItem.language_code == lang, tuple_(VocabItem.lemma, VocabItem.meaning).in_(keys)))) if keys else []
            for item in items:
                if await learn_vocab(db, user.id, item, "lesson", f"lesson:{lesson.id}"):
                    response["new_words"].append({"id": item.id, "lemma": item.lemma, "reading": item.reading,
                                                  "meaning": item.meaning, "ruby": (item.extra_json or {}).get("ruby")})
        if lesson.kind == "level_test":
            cefr = lesson.unit.level.cefr
            response["achievements"] += await grant_and_describe(db, user.id, f"level_{cefr.lower()}")
            if level_index(enrolment.current_level) <= level_index(cefr) and cefr != "C1":
                response["level_up"] = {"from": enrolment.current_level, "to": next_cefr(cefr)}
                enrolment.current_level = next_cefr(cefr)
        if lesson.kind == "kana" and lesson.order == 100:
            script = (lesson.skeleton_json or {}).get("script", "")
            response["achievements"] += await grant_and_describe(db, user.id, f"kana_{script}")
    else:
        xp = 2  # effort still counts towards the daily goal

    reward = await award_xp(db, user, lang, xp, "test" if is_test else "lesson", seconds=body.seconds)
    response |= {"xp": xp, "streak": reward["streak"], "goal_just_met": reward["goal_just_met"],
                 "used_freeze": reward["used_freeze"]}
    response["achievements"] += await check_achievements(db, user)
    enrolment.last_active_at = datetime.now(UTC)
    await db.commit()
    await enqueue("pregenerate", user.id, lang, job_id=f"pregen-{user.id}-{lang}")
    return response


@router.post("/flags")
async def flag(body: FlagIn, user: CurrentUser, db: Db) -> dict[str, bool]:
    db.add(ContentFlag(user_id=user.id, target_type=body.target_type, target_id=body.target_id, reason=body.reason))
    await db.commit()
    return {"ok": True}
