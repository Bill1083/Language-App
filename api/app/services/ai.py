"""The one place the app calls AI providers.

Every call goes through `AIService`, which resolves the effective provider
config, enforces the per-user daily budget, retries transient failures (on
the backup model when the main one is overloaded), validates structured
output with Pydantic and logs the call to `ai_usage`.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, time as dtime
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import SessionLocal
from ..models import AiUsage
from ..providers.base import ChatMessage, LLMResult, ProviderError, STTResult, Usage, extract_json
from ..providers.llm import DEFAULT_FALLBACK_MODELS, LLMProvider, make_llm
from ..providers.stt import GeminiSTT, STTProvider, make_stt
from ..providers.tts import TTSProvider, make_tts
from . import pricing
from .runtime_config import AIConfig, get_ai_config

log = logging.getLogger("parlo.ai")
T = TypeVar("T", bound=BaseModel)


FIRST_TOKEN_TIMEOUT = 12.0  # s for a streamed reply to start before moving on to the next model
STALL_TIMEOUT = 30.0  # s without a token once a streamed reply has started
STT_TIMEOUT = 12.0  # s for a transcript (combined transcript + feedback gets twice that)
OVERLOAD_COOLDOWN = 300.0  # s to try the backup model first after the main one was overloaded
RETRY_DELAY = 1.5  # s before retrying the same model
OVERLOAD_STATUSES = {429, 500, 502, 503, 504, 529}
# Non-streamed calls: an overloaded Gemini can sit on a request for a minute and then hang up.
COMPLETE_TIMEOUTS = {"conversation": 20.0, "feedback": 45.0, "content": 150.0}

RETRY_NOTICE = "The AI is busy right now — trying again…"
BACKUP_NOTICE = "The AI is busy right now — switching to the backup model…"

_cooling: dict[str, float] = {}  # "provider:model" -> monotonic time until which it counts as overloaded


class BudgetExceeded(Exception):
    pass


def network_error(provider: str, e: Exception) -> ProviderError:
    """Timeouts, DNS failures, bad base URLs… surface as a retryable provider error."""
    if isinstance(e, httpx.TimeoutException):
        return ProviderError(f"{provider} timed out ({e.__class__.__name__})", retryable=True, status=504)
    return ProviderError(f"{provider} unreachable ({e.__class__.__name__}: {e})", retryable=True)


def overloaded(e: ProviderError) -> bool:
    return e.status in OVERLOAD_STATUSES


def mark_overloaded(provider: str, model: str) -> None:
    _cooling[f"{provider}:{model}"] = time.monotonic() + OVERLOAD_COOLDOWN


def clear_overloaded(provider: str, model: str) -> None:
    _cooling.pop(f"{provider}:{model}", None)


def _ordered(provider: str, main: str, backup: str) -> list[str]:
    if not backup or backup == main:
        return [main, main]
    if _cooling.get(f"{provider}:{main}", 0.0) > time.monotonic():
        return [backup, main]
    return [main, backup]


def model_order(cfg: AIConfig, kind: str) -> list[str]:
    """Models to try for one call: the task's own model, then the backup —
    backup first while the main model is cooling down after an overload.
    Without a backup the same model is tried twice."""
    return _ordered(cfg.llm_provider, cfg.llm_models[kind], cfg.backup_model)


def stt_model_order(cfg: AIConfig) -> list[str]:
    """Same for transcription: Gemini STT can fall back to the backup Gemini model."""
    backup = ""
    if cfg.stt_provider == "gemini":
        backup = cfg.backup_model if cfg.llm_provider == "gemini" else DEFAULT_FALLBACK_MODELS.get("gemini", "")
    return _ordered(cfg.stt_provider, cfg.stt_model_name(), backup)


async def _timed(chunks: AsyncIterator[str], provider: str) -> AsyncIterator[str]:
    """Re-yield a provider stream, failing if it doesn't start or stalls (an
    overloaded model can sit on the request for a minute before saying so)."""
    limit = FIRST_TOKEN_TIMEOUT
    try:
        while True:
            try:
                chunk = await asyncio.wait_for(anext(chunks), limit)
            except StopAsyncIteration:
                return
            except TimeoutError:
                what = "didn't start replying" if limit == FIRST_TOKEN_TIMEOUT else "stopped replying"
                raise ProviderError(f"{provider} {what} within {limit:.0f} s", retryable=True, status=504) from None
            limit = STALL_TIMEOUT
            yield chunk
    finally:
        await chunks.aclose()  # type: ignore[attr-defined]


def llm_for(cfg: AIConfig) -> LLMProvider:
    return make_llm(cfg.llm_provider, cfg.key_for(cfg.llm_provider, "llm"), cfg.llm_base_url)


def tts_for(cfg: AIConfig, purpose: str) -> TTSProvider:
    provider = cfg.tts_provider_conversation if purpose == "conversation" else cfg.tts_provider_lesson
    env = get_settings()
    return make_tts(
        provider,
        api_key=cfg.key_for(provider, "tts"),
        base_url=cfg.tts_base_url if provider in ("local", "openai") else "",
        region=cfg.tts_azure_region,
        credentials_file=env.google_application_credentials if provider == "google" else "",
    )


def stt_for(cfg: AIConfig, model: str | None = None) -> STTProvider:
    return make_stt(cfg.stt_provider, api_key=cfg.key_for(cfg.stt_provider, "stt"),
                    base_url=cfg.stt_base_url, model=model or cfg.stt_model_name())


async def spent_today(db: AsyncSession, user_id: int) -> float:
    start = datetime.combine(datetime.now(UTC).date(), dtime.min, tzinfo=UTC)
    total = await db.scalar(
        select(func.coalesce(func.sum(AiUsage.est_cost), 0.0)).where(
            AiUsage.user_id == user_id, AiUsage.created_at >= start
        )
    )
    return float(total or 0.0)


class AIService:
    def __init__(self, db: AsyncSession, user_id: int | None = None, is_admin: bool = False):
        self.db = db
        self.user_id = user_id
        self.is_admin = is_admin
        self._cfg: AIConfig | None = None
        self.failures: list[str] = []  # "model: error" for attempts of the last call that failed

    async def config(self) -> AIConfig:
        if self._cfg is None:
            self._cfg = await get_ai_config(self.db)
        return self._cfg

    # ------------------------------------------------------------------ budget & logging

    async def budget_status(self) -> tuple[float, float]:
        cfg = await self.config()
        if self.user_id is None:
            return 0.0, cfg.daily_ai_budget_usd
        return await spent_today(self.db, self.user_id), cfg.daily_ai_budget_usd

    async def check_budget(self) -> None:
        if self.is_admin or self.user_id is None:
            return
        spent, budget = await self.budget_status()
        if budget > 0 and spent >= budget:
            raise BudgetExceeded(
                f"Today's AI budget (${budget:.2f}) is used up. It resets at midnight UTC — or ask an admin to raise it."
            )

    async def log(self, *, task: str, provider: str, model: str, usage: Usage | None = None, chars: int = 0,
                  audio_seconds: float = 0.0, cost: float = 0.0, latency_ms: int = 0, ok: bool = True) -> None:
        usage = usage or Usage()
        try:
            async with SessionLocal() as s:  # own session: logging must never ride on the caller's transaction
                s.add(AiUsage(
                    user_id=self.user_id, task=task, provider=provider, model=model,
                    input_tokens=usage.input_tokens + usage.audio_input_tokens, output_tokens=usage.output_tokens,
                    chars=chars, audio_seconds=audio_seconds, est_cost=round(cost, 6), latency_ms=latency_ms, ok=ok,
                ))
                await s.commit()
        except Exception:  # pragma: no cover - logging is best effort
            log.exception("failed to log AI usage")

    # ------------------------------------------------------------------ LLM

    async def _complete(self, task: str, kind: str, **kwargs) -> LLMResult:
        await self.check_budget()
        cfg = await self.config()
        llm = llm_for(cfg)
        models = model_order(cfg, kind)
        self.failures = []
        error: ProviderError | None = None
        for i, model in enumerate(models):
            if i and model == models[i - 1]:
                await asyncio.sleep(RETRY_DELAY)
            started = time.monotonic()
            limit = COMPLETE_TIMEOUTS.get(kind, 60.0)
            try:
                result = await asyncio.wait_for(llm.complete(model=model, **kwargs), limit)
            except TimeoutError:
                error = ProviderError(f"{llm.name} didn't answer within {limit:.0f} s", retryable=True, status=504)
            except ProviderError as e:
                error = e
            except httpx.HTTPError as e:
                error = network_error(llm.name, e)
            else:
                await self.log(
                    task=task, provider=llm.name, model=model, usage=result.usage,
                    cost=pricing.llm_cost(model, result.usage.input_tokens, result.usage.output_tokens,
                                          result.usage.audio_input_tokens, cfg.pricing),
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
                return result
            await self.log(task=task, provider=llm.name, model=model, ok=False,
                           latency_ms=int((time.monotonic() - started) * 1000))
            self.failures.append(f"{model}: {error}")
            if overloaded(error):
                mark_overloaded(llm.name, model)
            if not error.retryable:
                break
            log.warning("%s failed on %s (%s)", task, model, error)
        raise error  # type: ignore[misc]

    async def llm_result(self, task: str, kind: str, *, system: str, messages: list[ChatMessage],
                         temperature: float = 0.7, max_tokens: int = 800, thinking: str | None = "low") -> LLMResult:
        return await self._complete(task, kind, messages=messages, system=system, temperature=temperature,
                                    max_tokens=max_tokens, thinking=thinking)

    async def llm_text(self, task: str, kind: str, *, system: str, messages: list[ChatMessage],
                       temperature: float = 0.7, max_tokens: int = 800, thinking: str | None = "low") -> str:
        result = await self.llm_result(task, kind, system=system, messages=messages, temperature=temperature,
                                       max_tokens=max_tokens, thinking=thinking)
        return result.text.strip()

    async def llm_json(self, task: str, kind: str, schema: type[T], *, system: str, messages: list[ChatMessage],
                       temperature: float = 0.4, max_tokens: int = 2048, thinking: str | None = "low") -> T:
        msgs = list(messages)
        last_error: Exception | None = None
        for _ in range(2):
            result = await self._complete(task, kind, messages=msgs, system=system, json_mode=True,
                                          temperature=temperature, max_tokens=max_tokens, thinking=thinking)
            try:
                return schema.model_validate(extract_json(result.text))
            except (ValueError, ValidationError) as e:
                last_error = e
                msgs = msgs + [
                    ChatMessage("assistant", result.text[:4000]),
                    ChatMessage("user", f"That JSON was invalid: {str(e)[:800]}\nReturn the corrected JSON object only."),
                ]
        raise ProviderError(f"Model returned invalid JSON for {task}: {last_error}")

    async def llm_stream(self, task: str, kind: str, *, system: str, messages: list[ChatMessage],
                         temperature: float = 0.8, max_tokens: int = 600,
                         on_retry: Callable[[str], Awaitable[None]] | None = None) -> AsyncIterator[str]:
        """Stream a reply. Until the first token arrives a failure or a slow start
        moves on to the next model (`on_retry` hears about it); after that an
        error ends the reply."""
        await self.check_budget()
        cfg = await self.config()
        llm = llm_for(cfg)
        models = model_order(cfg, kind)
        self.failures = []
        for i, model in enumerate(models):
            usage = Usage()
            started = time.monotonic()
            produced = 0
            error: ProviderError | None = None
            try:
                async for delta in _timed(llm.stream(model=model, messages=messages, system=system, usage=usage,
                                                     temperature=temperature, max_tokens=max_tokens,
                                                     thinking="minimal"), llm.name):
                    produced += len(delta)
                    yield delta
            except ProviderError as e:
                error = e
            except httpx.HTTPError as e:
                error = network_error(llm.name, e)
            finally:
                if not usage.output_tokens and produced:
                    usage.output_tokens = produced // 3  # rough fallback when a provider omits stream usage
                await self.log(task=task, provider=llm.name, model=model, usage=usage, ok=error is None,
                               cost=pricing.llm_cost(model, usage.input_tokens, usage.output_tokens, 0, cfg.pricing),
                               latency_ms=int((time.monotonic() - started) * 1000))
            if error is None:
                return
            self.failures.append(f"{model}: {error}")
            if overloaded(error):
                mark_overloaded(llm.name, model)
            if produced or not error.retryable or i == len(models) - 1:
                raise error
            log.warning("%s failed on %s (%s) — trying the next model", task, model, error)
            same = models[i + 1] == model
            if on_retry:
                await on_retry(RETRY_NOTICE if same else BACKUP_NOTICE)
            if same:
                await asyncio.sleep(RETRY_DELAY)

    # ------------------------------------------------------------------ TTS / STT

    async def synthesize(self, text: str, lang: str, voice: str, speed: float, purpose: str) -> tuple[bytes, str, str]:
        """Raw synthesis (no cache) — use services.audio_cache.tts_key for normal use."""
        await self.check_budget()
        cfg = await self.config()
        tts = tts_for(cfg, purpose)
        started = time.monotonic()
        try:
            result = await tts.synthesize(text, lang, voice, speed)
        except (ProviderError, httpx.HTTPError) as e:
            await self.log(task=f"tts_{purpose}", provider=tts.name, model=voice, chars=len(text), ok=False)
            if isinstance(e, httpx.HTTPError):
                raise network_error(tts.name, e) from e
            raise
        await self.log(task=f"tts_{purpose}", provider=tts.name, model=voice, chars=result.chars,
                       cost=pricing.tts_cost(tts.name, result.chars, cfg.pricing),
                       latency_ms=int((time.monotonic() - started) * 1000))
        return result.audio, result.mime, tts.name

    async def transcribe(self, audio: bytes, mime: str, lang: str, duration_s: float,
                         feedback_instructions: str | None = None,
                         on_retry: Callable[[str], Awaitable[None]] | None = None) -> STTResult:
        """Transcribe with a time limit; an overloaded or slow model moves on to
        the backup (Gemini) or is retried once (other providers)."""
        await self.check_budget()
        cfg = await self.config()
        models = stt_model_order(cfg)
        self.failures = []
        error: ProviderError | None = None
        for i, model in enumerate(models):
            if i and model == models[i - 1]:
                await asyncio.sleep(RETRY_DELAY)
            stt = stt_for(cfg, model)
            combined = bool(feedback_instructions) and isinstance(stt, GeminiSTT)
            limit = STT_TIMEOUT * (2 if combined else 1)
            started = time.monotonic()
            try:
                if combined:
                    call = stt.transcribe_with_feedback(audio, mime, lang, feedback_instructions or "", duration_s)
                else:
                    call = stt.transcribe(audio, mime, lang, duration_s)
                result = await asyncio.wait_for(call, limit)
            except TimeoutError:
                error = ProviderError(f"{stt.name} took longer than {limit:.0f} s to transcribe", retryable=True,
                                      status=504)
            except ProviderError as e:
                error = e
            except httpx.HTTPError as e:
                error = network_error(stt.name, e)
            except ValueError as e:
                error = ProviderError(f"{stt.name} returned an unreadable transcript: {e}", retryable=True)
            else:
                if result.usage.input_tokens or result.usage.audio_input_tokens:
                    cost = pricing.llm_cost(stt.model, result.usage.input_tokens, result.usage.output_tokens,
                                            result.usage.audio_input_tokens, cfg.pricing)
                else:
                    cost = pricing.stt_cost(stt.name, result.audio_seconds or duration_s, cfg.pricing)
                await self.log(task="stt", provider=stt.name, model=stt.model, usage=result.usage,
                               audio_seconds=result.audio_seconds or duration_s, cost=cost,
                               latency_ms=int((time.monotonic() - started) * 1000))
                return result
            await self.log(task="stt", provider=stt.name, model=stt.model, audio_seconds=duration_s, ok=False,
                           latency_ms=int((time.monotonic() - started) * 1000))
            self.failures.append(f"{model}: {error}")
            if overloaded(error):
                mark_overloaded(stt.name, model)
            if not error.retryable or i == len(models) - 1:
                break
            log.warning("stt failed on %s (%s) — trying the next model", model, error)
            if on_retry:
                await on_retry(RETRY_NOTICE if models[i + 1] == model else BACKUP_NOTICE)
        raise error  # type: ignore[misc]
