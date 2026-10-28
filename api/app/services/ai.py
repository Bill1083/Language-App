"""The one place the app calls AI providers.

Every call goes through `AIService`, which resolves the effective provider
config, enforces the per-user daily budget, retries transient failures,
validates structured output with Pydantic and logs the call to `ai_usage`.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
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
from ..providers.llm import LLMProvider, make_llm
from ..providers.stt import GeminiSTT, STTProvider, make_stt
from ..providers.tts import TTSProvider, make_tts
from . import pricing
from .runtime_config import AIConfig, get_ai_config

log = logging.getLogger("parlo.ai")
T = TypeVar("T", bound=BaseModel)


class BudgetExceeded(Exception):
    pass


def network_error(provider: str, e: Exception) -> ProviderError:
    """Timeouts, DNS failures, bad base URLs… surface as a retryable provider error."""
    return ProviderError(f"{provider} unreachable ({e.__class__.__name__}: {e})", retryable=True)


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


def stt_for(cfg: AIConfig) -> STTProvider:
    return make_stt(cfg.stt_provider, api_key=cfg.key_for(cfg.stt_provider, "stt"),
                    base_url=cfg.stt_base_url, model=cfg.stt_model_name())


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
        model = cfg.llm_models[kind]
        started = time.monotonic()
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                result = await llm.complete(model=model, **kwargs)
                await self.log(
                    task=task, provider=llm.name, model=model, usage=result.usage,
                    cost=pricing.llm_cost(model, result.usage.input_tokens, result.usage.output_tokens,
                                          result.usage.audio_input_tokens, cfg.pricing),
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
                return result
            except (ProviderError, httpx.HTTPError) as e:
                last_error = e if isinstance(e, ProviderError) else network_error(llm.name, e)
                if not last_error.retryable or attempt == 1:
                    break
                await asyncio.sleep(1.5)
        await self.log(task=task, provider=llm.name, model=model, ok=False,
                       latency_ms=int((time.monotonic() - started) * 1000))
        raise last_error  # type: ignore[misc]

    async def llm_text(self, task: str, kind: str, *, system: str, messages: list[ChatMessage],
                       temperature: float = 0.7, max_tokens: int = 800, thinking: str | None = "low") -> str:
        result = await self._complete(task, kind, messages=messages, system=system, temperature=temperature,
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
                         temperature: float = 0.8, max_tokens: int = 600) -> AsyncIterator[str]:
        await self.check_budget()
        cfg = await self.config()
        llm = llm_for(cfg)
        model = cfg.llm_models[kind]
        usage = Usage()
        started = time.monotonic()
        produced = 0
        ok = False
        try:
            async for delta in llm.stream(model=model, messages=messages, system=system, usage=usage,
                                          temperature=temperature, max_tokens=max_tokens, thinking="minimal"):
                produced += len(delta)
                yield delta
            ok = True
        except httpx.HTTPError as e:
            raise network_error(llm.name, e) from e
        finally:
            if not usage.output_tokens and produced:
                usage.output_tokens = produced // 3  # rough fallback when a provider omits stream usage
            await self.log(task=task, provider=llm.name, model=model, usage=usage, ok=ok,
                           cost=pricing.llm_cost(model, usage.input_tokens, usage.output_tokens, 0, cfg.pricing),
                           latency_ms=int((time.monotonic() - started) * 1000))

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
                         feedback_instructions: str | None = None) -> STTResult:
        await self.check_budget()
        cfg = await self.config()
        stt = stt_for(cfg)
        started = time.monotonic()
        try:
            if feedback_instructions and isinstance(stt, GeminiSTT):
                result = await stt.transcribe_with_feedback(audio, mime, lang, feedback_instructions, duration_s)
            else:
                result = await stt.transcribe(audio, mime, lang, duration_s)
        except (ProviderError, httpx.HTTPError, ValueError) as e:
            await self.log(task="stt", provider=stt.name, model=stt.model, audio_seconds=duration_s, ok=False)
            if isinstance(e, httpx.HTTPError):
                raise network_error(stt.name, e) from e
            if isinstance(e, ValueError):
                raise ProviderError(f"{stt.name} returned an unreadable transcript: {e}") from e
            raise
        if result.usage.input_tokens or result.usage.audio_input_tokens:
            cost = pricing.llm_cost(stt.model, result.usage.input_tokens, result.usage.output_tokens,
                                    result.usage.audio_input_tokens, cfg.pricing)
        else:
            cost = pricing.stt_cost(stt.name, result.audio_seconds or duration_s, cfg.pricing)
        await self.log(task="stt", provider=stt.name, model=stt.model, usage=result.usage,
                       audio_seconds=result.audio_seconds or duration_s, cost=cost,
                       latency_ms=int((time.monotonic() - started) * 1000))
        return result
