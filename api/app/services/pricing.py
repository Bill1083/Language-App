"""Estimated prices (USD) for the usage dashboard and the daily budget.

These are estimates — check each provider's pricing page. Admins can override
any entry from the admin panel (stored as the `pricing` app setting); entries
are matched on the longest model-name prefix.
"""

from typing import Any

DEFAULT_PRICING: dict[str, Any] = {
    # per 1M tokens: input, output, audio_input
    "llm": {
        "gemini-3.8-flash": {"input": 0.50, "output": 3.00, "audio_input": 1.00},
        "gemini-3.5-flash-lite": {"input": 0.10, "output": 0.40, "audio_input": 0.30},
        "gemini-2.5-flash": {"input": 0.30, "output": 2.50, "audio_input": 1.00},
        "gemini": {"input": 0.50, "output": 3.00, "audio_input": 1.00},
        "claude-haiku": {"input": 1.00, "output": 5.00},
        "claude-sonnet": {"input": 3.00, "output": 15.00},
        "claude-opus": {"input": 5.00, "output": 25.00},
        "gpt-5-mini": {"input": 0.25, "output": 2.00},
        "gpt-5": {"input": 1.25, "output": 10.00},
        "google/gemini": {"input": 0.50, "output": 3.00},
        "llama": {"input": 0, "output": 0},
    },
    # per 1M characters
    "tts": {"google": 30.0, "openai": 15.0, "elevenlabs": 120.0, "azure": 16.0, "local": 0.0},
    # per audio minute (token-billed providers are priced via "llm")
    "stt": {"openai": 0.006, "groq": 0.0007, "deepgram": 0.0043, "google_cloud": 0.016, "local": 0.0},
}


def _merged(overrides: dict[str, Any] | None) -> dict[str, Any]:
    merged = {k: dict(v) for k, v in DEFAULT_PRICING.items()}
    for section, entries in (overrides or {}).items():
        if isinstance(entries, dict):
            merged.setdefault(section, {}).update(entries)
    return merged


def _llm_rate(model: str, table: dict[str, Any]) -> dict[str, float]:
    best = ""
    for prefix in table:
        if model.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    return table.get(best, {"input": 0.0, "output": 0.0})


def llm_cost(model: str, input_tokens: int, output_tokens: int, audio_tokens: int = 0,
             overrides: dict[str, Any] | None = None) -> float:
    rate = _llm_rate(model, _merged(overrides)["llm"])
    audio_rate = rate.get("audio_input", rate.get("input", 0.0))
    return (input_tokens * rate.get("input", 0.0) + output_tokens * rate.get("output", 0.0)
            + audio_tokens * audio_rate) / 1_000_000


def tts_cost(provider: str, chars: int, overrides: dict[str, Any] | None = None) -> float:
    return chars * float(_merged(overrides)["tts"].get(provider, 0.0)) / 1_000_000


def stt_cost(provider: str, seconds: float, overrides: dict[str, Any] | None = None) -> float:
    return seconds / 60 * float(_merged(overrides)["stt"].get(provider, 0.0))


def pricing_table(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    return _merged(overrides)
