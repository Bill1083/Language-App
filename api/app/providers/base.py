"""Shared types for the three provider interfaces (LLM, TTS, STT).

Every adapter talks plain HTTP through httpx so there is one dependency to
mock in tests and no vendor SDK to keep in step with.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

_client: httpx.AsyncClient | None = None


def http_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0))
    return _client


class ProviderError(Exception):
    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


def raise_for_status(resp: httpx.Response, provider: str) -> None:
    if resp.status_code < 400:
        return
    try:
        detail = resp.json()
        if isinstance(detail, dict):
            err = detail.get("error", detail)
            detail = err.get("message", err) if isinstance(err, dict) else err
    except Exception:
        detail = resp.text[:300]
    retryable = resp.status_code in (408, 409, 429, 500, 502, 503, 504, 529)
    raise ProviderError(f"{provider} error {resp.status_code}: {detail}", retryable=retryable, status=resp.status_code)


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    audio_input_tokens: int = 0


@dataclass
class LLMResult:
    text: str
    model: str
    provider: str
    usage: Usage = field(default_factory=Usage)


@dataclass
class TTSResult:
    audio: bytes
    mime: str
    chars: int


@dataclass
class STTWord:
    word: str
    start: float | None = None
    end: float | None = None
    confidence: float | None = None


@dataclass
class STTResult:
    text: str
    provider: str
    model: str
    words: list[STTWord] | None = None
    audio_seconds: float = 0.0
    usage: Usage = field(default_factory=Usage)
    extra: dict[str, Any] = field(default_factory=dict)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_json(text: str) -> Any:
    """Parse a JSON object out of an LLM reply, tolerating code fences and chatter."""
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = min((i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise ValueError("No JSON found in model output")
    closer = "}" if cleaned[start] == "{" else "]"
    end = cleaned.rfind(closer)
    if end <= start:
        raise ValueError("Unterminated JSON in model output")
    return json.loads(cleaned[start : end + 1])


async def iter_sse(resp: httpx.Response):
    """Yield the `data:` payloads of a server-sent-events response."""
    async for line in resp.aiter_lines():
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            data = line[5:].strip()
            if data == "[DONE]":
                return
            yield data
