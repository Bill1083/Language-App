"""Effective AI configuration = `.env` defaults + admin overrides from the DB.

Cached in-process for a few seconds so every request doesn't hit the
settings table; admin writes call `invalidate()`. The worker reads the same
table, so a change in the admin panel reaches it within CACHE_SECONDS.
"""

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import AppSetting
from ..providers.llm import DEFAULT_MODELS
from ..providers.stt import DEFAULT_STT_MODELS
from ..providers.tts import DEFAULT_VOICES

CACHE_SECONDS = 10
LANGS = ("fr", "it", "ja")

# Keys an admin may override (anything else in app_settings is internal).
OVERRIDABLE = {
    "llm_provider", "llm_base_url", "llm_model_conversation", "llm_model_feedback", "llm_model_content",
    "tts_provider_lesson", "tts_provider_conversation", "tts_base_url", "tts_azure_region",
    "stt_provider", "stt_base_url", "stt_model", "stt_combined_feedback",
    "daily_ai_budget_usd", "voices", "keys", "pricing",
}

PROVIDER_KEY_ENV = {
    "gemini": "gemini_api_key", "anthropic": "anthropic_api_key", "openai": "openai_api_key",
    "openrouter": "openrouter_api_key", "groq": "groq_api_key", "deepgram": "deepgram_api_key",
    "elevenlabs": "elevenlabs_api_key", "azure": "azure_speech_key",
}


@dataclass
class AIConfig:
    llm_provider: str
    llm_base_url: str
    llm_models: dict[str, str]  # conversation | feedback | content
    tts_provider_lesson: str
    tts_provider_conversation: str
    tts_base_url: str
    tts_azure_region: str
    stt_provider: str
    stt_base_url: str
    stt_model: str
    stt_combined_feedback: bool
    daily_ai_budget_usd: float
    voices: dict[str, dict[str, dict[str, str]]]  # provider -> lang -> gender -> voice
    keys: dict[str, str] = field(default_factory=dict)  # admin-entered keys
    pricing: dict[str, Any] = field(default_factory=dict)

    def key_for(self, provider: str, capability: str) -> str:
        env = get_settings()
        candidates = [self.keys.get(provider, "")]
        if capability == "llm" and env.llm_provider == provider:
            candidates.append(env.llm_api_key)
        if capability == "tts" and provider in (env.tts_provider_lesson, env.tts_provider_conversation):
            candidates.append(env.tts_api_key)
        if capability == "stt" and env.stt_provider == provider:
            candidates.append(env.stt_api_key)
        if provider in PROVIDER_KEY_ENV:
            candidates.append(getattr(env, PROVIDER_KEY_ENV[provider]))
        if provider == "gemini":  # STT_API_KEY defaults to LLM_API_KEY when both are Gemini
            if env.llm_provider == "gemini":
                candidates.append(env.llm_api_key)
            if env.stt_provider == "gemini":
                candidates.append(env.stt_api_key)
        if provider == "google_cloud":
            candidates.append(env.tts_api_key)
        return next((c for c in candidates if c), "")

    def voice_for(self, provider: str, lang: str, gender: str = "female") -> str:
        gender = "male" if gender == "male" else "female"
        return (
            self.voices.get(provider, {}).get(lang, {}).get(gender)
            or DEFAULT_VOICES.get(provider, {}).get(lang, {}).get(gender)
            or ""
        )

    def stt_model_name(self) -> str:
        return self.stt_model or DEFAULT_STT_MODELS.get(self.stt_provider, "")


_cache: tuple[float, AIConfig] | None = None


def invalidate() -> None:
    global _cache
    _cache = None


def _env_voices() -> dict[str, dict[str, dict[str, str]]]:
    env = get_settings()
    out: dict[str, dict[str, dict[str, str]]] = {}
    for provider in {env.tts_provider_lesson, env.tts_provider_conversation}:
        for lang in LANGS:
            female = getattr(env, f"tts_voice_{lang}", "")
            male = getattr(env, f"tts_voice_{lang}_male", "")
            if female or male:
                slot = out.setdefault(provider, {}).setdefault(lang, {})
                if female:
                    slot["female"] = female
                if male:
                    slot["male"] = male
    return out


def _merge_voices(base: dict, override: dict) -> dict:
    merged = {p: {lang: dict(g) for lang, g in langs.items()} for p, langs in base.items()}
    for provider, langs in (override or {}).items():
        for lang, genders in (langs or {}).items():
            for gender, voice in (genders or {}).items():
                if voice:
                    merged.setdefault(provider, {}).setdefault(lang, {})[gender] = voice
    return merged


async def load_overrides(db: AsyncSession) -> dict[str, Any]:
    rows = await db.execute(select(AppSetting).where(AppSetting.key.in_(OVERRIDABLE)))
    return {row.key: row.value_json for row in rows.scalars()}


async def get_ai_config(db: AsyncSession) -> AIConfig:
    global _cache
    if _cache and _cache[0] > time.monotonic():
        return _cache[1]
    env = get_settings()
    o = await load_overrides(db)

    def pick(key: str, default: Any) -> Any:
        value = o.get(key)
        return default if value in (None, "") else value

    llm_provider = pick("llm_provider", env.llm_provider)
    defaults = DEFAULT_MODELS.get(llm_provider, DEFAULT_MODELS["gemini"])
    same_llm = llm_provider == env.llm_provider
    llm_models = {
        task: pick(f"llm_model_{task}", (getattr(env, f"llm_model_{task}") if same_llm else "") or defaults[task])
        for task in ("conversation", "feedback", "content")
    }
    stt_provider = pick("stt_provider", env.stt_provider)
    cfg = AIConfig(
        llm_provider=llm_provider,
        llm_base_url=pick("llm_base_url", env.llm_base_url if same_llm else ""),
        llm_models=llm_models,
        tts_provider_lesson=pick("tts_provider_lesson", env.tts_provider_lesson),
        tts_provider_conversation=pick("tts_provider_conversation", env.tts_provider_conversation),
        tts_base_url=pick("tts_base_url", env.tts_base_url),
        tts_azure_region=pick("tts_azure_region", env.tts_azure_region),
        stt_provider=stt_provider,
        stt_base_url=pick("stt_base_url", env.stt_base_url if stt_provider == env.stt_provider else ""),
        stt_model=pick("stt_model", env.stt_model if stt_provider == env.stt_provider else ""),
        stt_combined_feedback=bool(pick("stt_combined_feedback", env.stt_combined_feedback)),
        daily_ai_budget_usd=float(pick("daily_ai_budget_usd", env.daily_ai_budget_usd)),
        voices=_merge_voices(_env_voices(), o.get("voices") or {}),
        keys={k: v for k, v in (o.get("keys") or {}).items() if v},
        pricing=o.get("pricing") or {},
    )
    _cache = (time.monotonic() + CACHE_SECONDS, cfg)
    return cfg


def mask(key: str) -> str:
    return f"••••{key[-4:]}" if key else ""
