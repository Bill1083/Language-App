"""LLM adapters: Gemini, Anthropic, and the OpenAI chat-completions family
(OpenAI, OpenRouter, any OpenAI-compatible endpoint such as Ollama)."""

import base64
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .base import (
    ChatMessage,
    LLMResult,
    ProviderError,
    Usage,
    http_client,
    iter_sse,
    raise_for_status,
)

JSON_INSTRUCTION = "Respond with a single valid JSON object only — no markdown fences, no commentary."


class LLMProvider:
    name = "base"

    def __init__(self, api_key: str, base_url: str = "", client: httpx.AsyncClient | None = None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = client

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client or http_client()

    def _require_key(self) -> None:
        if not self.api_key:
            raise ProviderError(f"No API key configured for {self.name}")

    async def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        system: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        thinking: str | None = None,
    ) -> LLMResult:
        raise NotImplementedError

    def stream(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        usage: Usage,
        system: str | None = None,
        temperature: float = 0.8,
        max_tokens: int = 600,
        thinking: str | None = None,
    ) -> AsyncIterator[str]:
        raise NotImplementedError

    supports_audio = False

    async def complete_audio(
        self, *, model: str, prompt: str, audio: bytes, mime: str, json_mode: bool = False, system: str | None = None
    ) -> LLMResult:
        raise ProviderError(f"{self.name} does not accept audio input")


# --------------------------------------------------------------------------- Gemini


class GeminiLLM(LLMProvider):
    name = "gemini"
    supports_audio = True
    DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"

    def _url(self, model: str, method: str) -> str:
        base = self.base_url or self.DEFAULT_BASE
        return f"{base}/models/{model}:{method}"

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key, "content-type": "application/json"}

    @staticmethod
    def _contents(messages: list[ChatMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            role = "model" if m.role == "assistant" else "user"
            if out and out[-1]["role"] == role:  # Gemini wants alternating turns
                out[-1]["parts"][0]["text"] += "\n\n" + m.content
            else:
                out.append({"role": role, "parts": [{"text": m.content}]})
        return out

    def _body(self, contents, system, json_mode, temperature, max_tokens, thinking) -> dict[str, Any]:
        config: dict[str, Any] = {"temperature": temperature, "maxOutputTokens": max_tokens}
        if json_mode:
            config["responseMimeType"] = "application/json"
        if thinking:
            config["thinkingConfig"] = {"thinkingLevel": thinking}
        body: dict[str, Any] = {"contents": contents, "generationConfig": config}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body

    @staticmethod
    def _usage(meta: dict[str, Any] | None) -> Usage:
        meta = meta or {}
        audio = 0
        for detail in meta.get("promptTokensDetails", []) or []:
            if detail.get("modality") == "AUDIO":
                audio += int(detail.get("tokenCount", 0))
        prompt = int(meta.get("promptTokenCount", 0))
        out = int(meta.get("candidatesTokenCount", 0)) + int(meta.get("thoughtsTokenCount", 0))
        return Usage(input_tokens=prompt - audio, output_tokens=out, audio_input_tokens=audio)

    @staticmethod
    def _text(data: dict[str, Any]) -> str:
        parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))

    async def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        resp = await self.client.post(url, headers=self._headers(), json=body)
        if resp.status_code == 400 and "thinkingConfig" in body.get("generationConfig", {}) and "thinking" in resp.text.lower():
            # Not every model accepts every thinking level: retry without it.
            body["generationConfig"].pop("thinkingConfig")
            resp = await self.client.post(url, headers=self._headers(), json=body)
        raise_for_status(resp, "Gemini")
        return resp.json()

    async def complete(self, *, model, messages, system=None, json_mode=False, temperature=0.7, max_tokens=1024, thinking=None):
        self._require_key()
        body = self._body(self._contents(messages), system, json_mode, temperature, max_tokens, thinking)
        data = await self._post(self._url(model, "generateContent"), body)
        text = self._text(data)
        if not text:
            reason = ((data.get("candidates") or [{}])[0]).get("finishReason") or data.get("promptFeedback")
            raise ProviderError(f"Gemini returned no text ({reason})", retryable=True)
        return LLMResult(text=text, model=model, provider=self.name, usage=self._usage(data.get("usageMetadata")))

    async def stream(self, *, model, messages, usage, system=None, temperature=0.8, max_tokens=600, thinking=None):
        self._require_key()
        body = self._body(self._contents(messages), system, False, temperature, max_tokens, thinking)
        url = self._url(model, "streamGenerateContent") + "?alt=sse"
        async with self.client.stream("POST", url, headers=self._headers(), json=body) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                if resp.status_code == 400 and thinking and "thinking" in resp.text.lower():
                    async for chunk in self.stream(model=model, messages=messages, usage=usage, system=system,
                                                   temperature=temperature, max_tokens=max_tokens, thinking=None):
                        yield chunk
                    return
                raise_for_status(resp, "Gemini")
            async for data in iter_sse(resp):
                chunk = json.loads(data)
                if chunk.get("usageMetadata"):
                    u = self._usage(chunk["usageMetadata"])
                    usage.input_tokens, usage.output_tokens = u.input_tokens, u.output_tokens
                text = self._text(chunk)
                if text:
                    yield text

    async def complete_audio(self, *, model, prompt, audio, mime, json_mode=False, system=None):
        self._require_key()
        contents = [{
            "role": "user",
            "parts": [
                {"inlineData": {"mimeType": mime.split(";")[0], "data": base64.b64encode(audio).decode()}},
                {"text": prompt},
            ],
        }]
        body = self._body(contents, system, json_mode, 0.0, 2048, "low")
        data = await self._post(self._url(model, "generateContent"), body)
        return LLMResult(text=self._text(data), model=model, provider=self.name, usage=self._usage(data.get("usageMetadata")))


# --------------------------------------------------------------------------- Anthropic


class AnthropicLLM(LLMProvider):
    name = "anthropic"
    DEFAULT_BASE = "https://api.anthropic.com/v1"

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}

    def _body(self, model, messages, system, json_mode, temperature, max_tokens) -> dict[str, Any]:
        sys_text = system or ""
        if json_mode:
            sys_text = f"{sys_text}\n\n{JSON_INSTRUCTION}".strip()
        msgs: list[dict[str, str]] = []
        for m in messages:
            if msgs and msgs[-1]["role"] == m.role:
                msgs[-1]["content"] += "\n\n" + m.content
            else:
                msgs.append({"role": m.role, "content": m.content})
        if not msgs or msgs[0]["role"] != "user":
            msgs.insert(0, {"role": "user", "content": "(start)"})
        body: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": msgs, "temperature": temperature}
        if sys_text:
            body["system"] = sys_text
        return body

    async def complete(self, *, model, messages, system=None, json_mode=False, temperature=0.7, max_tokens=1024, thinking=None):
        self._require_key()
        base = self.base_url or self.DEFAULT_BASE
        resp = await self.client.post(f"{base}/messages", headers=self._headers(),
                                      json=self._body(model, messages, system, json_mode, temperature, max_tokens))
        raise_for_status(resp, "Anthropic")
        data = resp.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        u = data.get("usage", {})
        return LLMResult(text=text, model=model, provider=self.name,
                         usage=Usage(input_tokens=u.get("input_tokens", 0), output_tokens=u.get("output_tokens", 0)))

    async def stream(self, *, model, messages, usage, system=None, temperature=0.8, max_tokens=600, thinking=None):
        self._require_key()
        base = self.base_url or self.DEFAULT_BASE
        body = self._body(model, messages, system, False, temperature, max_tokens) | {"stream": True}
        async with self.client.stream("POST", f"{base}/messages", headers=self._headers(), json=body) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                raise_for_status(resp, "Anthropic")
            async for data in iter_sse(resp):
                event = json.loads(data)
                kind = event.get("type")
                if kind == "message_start":
                    usage.input_tokens = event.get("message", {}).get("usage", {}).get("input_tokens", 0)
                elif kind == "content_block_delta" and event.get("delta", {}).get("type") == "text_delta":
                    yield event["delta"]["text"]
                elif kind == "message_delta":
                    usage.output_tokens = event.get("usage", {}).get("output_tokens", usage.output_tokens)
                elif kind == "error":
                    raise ProviderError(f"Anthropic stream error: {event.get('error')}", retryable=True)


# --------------------------------------------------------------------------- OpenAI family


class OpenAIChatLLM(LLMProvider):
    name = "openai"
    DEFAULT_BASE = "https://api.openai.com/v1"

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        return headers

    def _base(self) -> str:
        return self.base_url or self.DEFAULT_BASE

    def _body(self, model, messages, system, json_mode, temperature, max_tokens) -> dict[str, Any]:
        msgs = ([{"role": "system", "content": system + (f"\n\n{JSON_INSTRUCTION}" if json_mode else "")}]
                if system else [])
        msgs += [{"role": m.role, "content": m.content} for m in messages]
        body: dict[str, Any] = {"model": model, "messages": msgs, "temperature": temperature}
        if self.name == "openai":
            body["max_completion_tokens"] = max_tokens
        else:
            body["max_tokens"] = max_tokens
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    async def _post(self, body: dict[str, Any]) -> httpx.Response:
        resp = await self.client.post(f"{self._base()}/chat/completions", headers=self._headers(), json=body)
        if resp.status_code == 400 and "temperature" in resp.text:
            body.pop("temperature", None)  # some reasoning models only allow the default
            resp = await self.client.post(f"{self._base()}/chat/completions", headers=self._headers(), json=body)
        return resp

    async def complete(self, *, model, messages, system=None, json_mode=False, temperature=0.7, max_tokens=1024, thinking=None):
        if self.name != "openai_compatible":
            self._require_key()
        resp = await self._post(self._body(model, messages, system, json_mode, temperature, max_tokens))
        raise_for_status(resp, self.name)
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        u = data.get("usage") or {}
        return LLMResult(
            text=(choice.get("message") or {}).get("content") or "",
            model=model, provider=self.name,
            usage=Usage(input_tokens=u.get("prompt_tokens", 0), output_tokens=u.get("completion_tokens", 0)),
        )

    async def stream(self, *, model, messages, usage, system=None, temperature=0.8, max_tokens=600, thinking=None):
        if self.name != "openai_compatible":
            self._require_key()
        body = self._body(model, messages, system, False, temperature, max_tokens)
        body |= {"stream": True, "stream_options": {"include_usage": True}}
        async with self.client.stream("POST", f"{self._base()}/chat/completions", headers=self._headers(), json=body) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                raise_for_status(resp, self.name)
            async for data in iter_sse(resp):
                chunk = json.loads(data)
                if chunk.get("usage"):
                    usage.input_tokens = chunk["usage"].get("prompt_tokens", 0)
                    usage.output_tokens = chunk["usage"].get("completion_tokens", 0)
                for choice in chunk.get("choices") or []:
                    delta = (choice.get("delta") or {}).get("content")
                    if delta:
                        yield delta


class OpenRouterLLM(OpenAIChatLLM):
    name = "openrouter"
    DEFAULT_BASE = "https://openrouter.ai/api/v1"


class OpenAICompatibleLLM(OpenAIChatLLM):
    name = "openai_compatible"
    DEFAULT_BASE = "http://ollama:11434/v1"


LLM_PROVIDERS: dict[str, type[LLMProvider]] = {
    "gemini": GeminiLLM,
    "anthropic": AnthropicLLM,
    "openai": OpenAIChatLLM,
    "openrouter": OpenRouterLLM,
    "openai_compatible": OpenAICompatibleLLM,
}

DEFAULT_MODELS: dict[str, dict[str, str]] = {
    "gemini": {"conversation": "gemini-3.8-flash", "feedback": "gemini-3.8-flash", "content": "gemini-3.8-flash"},
    "anthropic": {"conversation": "claude-haiku-5-5", "feedback": "claude-sonnet-5-5", "content": "claude-sonnet-5-5"},
    "openai": {"conversation": "gpt-5-mini", "feedback": "gpt-5-mini", "content": "gpt-5"},
    "openrouter": {"conversation": "google/gemini-3.8-flash", "feedback": "google/gemini-3.8-flash",
                   "content": "google/gemini-3.8-flash"},
    "openai_compatible": {"conversation": "llama3.1", "feedback": "llama3.1", "content": "llama3.1"},
}


def make_llm(provider: str, api_key: str, base_url: str = "", client: httpx.AsyncClient | None = None) -> LLMProvider:
    try:
        cls = LLM_PROVIDERS[provider]
    except KeyError:
        raise ProviderError(f"Unknown LLM provider '{provider}'") from None
    return cls(api_key, base_url, client)
