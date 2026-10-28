"""arq worker: lesson pre-generation, audio pre-caching, feedback analysis,
session summaries and housekeeping crons.

Run with:  arq app.worker.WorkerSettings
"""

import logging

from arq import cron

from .logging_setup import setup_logging
from .services import jobs

setup_logging()
log = logging.getLogger("parlo.worker")


async def generate_lesson(ctx, lesson_id: int, force: bool = False) -> str:
    return await jobs.run_generate_lesson(lesson_id, force)


async def precache_lesson_audio(ctx, lesson_id: int) -> int:
    return await jobs.run_precache_lesson_audio(lesson_id)


async def pregenerate(ctx, user_id: int, lang: str) -> list[int]:
    return await jobs.run_pregenerate(user_id, lang)


async def analyze_turn(ctx, turn_id: int) -> None:
    await jobs.run_feedback(turn_id)


async def summarize_conversation(ctx, conversation_id: int) -> None:
    await jobs.run_summary(conversation_id)


async def cleanup_recordings(ctx) -> int:
    return await jobs.run_cleanup_recordings()


async def push_reminders(ctx) -> int:
    return await jobs.run_push_reminders()


async def startup(ctx) -> None:
    log.info("worker started")


class WorkerSettings:
    functions = [generate_lesson, precache_lesson_audio, pregenerate, analyze_turn, summarize_conversation]
    cron_jobs = [
        cron(cleanup_recordings, hour={3}, minute={17}),
        cron(push_reminders, minute={0}),
    ]
    redis_settings = jobs.redis_settings()
    on_startup = startup
    max_jobs = 4
    job_timeout = 300
    keep_result = 3600
    max_tries = 2
