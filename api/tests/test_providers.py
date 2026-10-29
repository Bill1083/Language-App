"""Provider adapters against mocked HTTP (httpx.MockTransport) — no network."""

import base64
import json

import httpx
import pytest

from app.providers.base import ChatMessage, ProviderError, Usage, extract_json
from app.providers.llm import AnthropicLLM, GeminiLLM, OpenAIChatLLM, OpenAICompatibleLLM, make_llm
from app.providers.stt import DeepgramSTT, GeminiSTT, OpenAISTT
from app.providers.tts import GoogleTTS, LocalTTS, make_tts


def mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def sse(*events: dict | str) -> bytes:
    lines = []
    for e in events:
        lines.append("data: " + (e if isinstance(e, str) else json.dumps(e)))
        lines.append("")
    return ("\n".join(lines) + "\n").encode()


MSGS = [ChatMessage("user", "Bonjour"), ChatMessage("assistant", "Salut !"), ChatMessage("user", "Ça va ?")]


# --------------------------------------------------------------------------- Gemini


async def test_gemini_complete_builds_request_and_parses_usage():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["key"] = req.headers["x-goog-api-key"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": '{"ok": true}'}]}}],
            "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 30, "thoughtsTokenCount": 10},
        })

    llm = GeminiLLM("k123", client=mock_client(handler))
    result = await llm.complete(model="gemini-x", messages=MSGS, system="sys", json_mode=True, thinking="low")
    assert seen["url"].endswith("/models/gemini-x:generateContent")
    assert seen["key"] == "k123"
    body = seen["body"]
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
    assert result.text == '{"ok": true}'  # thought parts are dropped
    assert (result.usage.input_tokens, result.usage.output_tokens) == (120, 40)


async def test_gemini_retries_without_thinking_when_rejected():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        calls.append(body)
        if "thinkingConfig" in body["generationConfig"]:
            return httpx.Response(400, json={"error": {"message": "thinking level not supported"}})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    result = await GeminiLLM("k", client=mock_client(handler)).complete(model="m", messages=MSGS, thinking="minimal")
    assert result.text == "ok" and len(calls) == 2


async def test_gemini_stream_yields_text_and_usage():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params["alt"] == "sse"
        return httpx.Response(200, content=sse(
            {"candidates": [{"content": {"parts": [{"text": "Bonjour"}]}}]},
            {"candidates": [{"content": {"parts": [{"text": " !"}]}}],
             "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 4}},
        ), headers={"content-type": "text/event-stream"})

    usage = Usage()
    chunks = [c async for c in GeminiLLM("k", client=mock_client(handler)).stream(model="m", messages=MSGS, usage=usage)]
    assert "".join(chunks) == "Bonjour !"
    assert (usage.input_tokens, usage.output_tokens) == (50, 4)


async def test_gemini_audio_counts_audio_tokens_separately():
    def handler(req: httpx.Request) -> httpx.Response:
        parts = json.loads(req.content)["contents"][0]["parts"]
        assert parts[0]["inlineData"]["mimeType"] == "audio/webm"
        assert base64.b64decode(parts[0]["inlineData"]["data"]) == b"AUDIO"
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": "je suis allé"}]}}],
            "usageMetadata": {"promptTokenCount": 300, "candidatesTokenCount": 5,
                              "promptTokensDetails": [{"modality": "AUDIO", "tokenCount": 256},
                                                      {"modality": "TEXT", "tokenCount": 44}]}})

    stt = GeminiSTT("k", model="gemini-x", client=mock_client(handler))
    result = await stt.transcribe(b"AUDIO", "audio/webm;codecs=opus", "fr", 8.0)
    assert result.text == "je suis allé"
    assert result.usage.audio_input_tokens == 256 and result.usage.input_tokens == 44


async def test_gemini_stt_prompt_demands_verbatim():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["prompt"] = json.loads(req.content)["contents"][0]["parts"][1]["text"]
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "x"}]}}]})

    await GeminiSTT("k", client=mock_client(handler)).transcribe(b"a", "audio/webm", "ja")
    prompt = captured["prompt"]
    assert "VERBATIM" in prompt and "[?]" in prompt and "Do NOT correct" in prompt and "Japanese" in prompt


async def test_rate_limit_is_retryable_error():
    def handler(req):
        return httpx.Response(429, json={"error": {"message": "quota"}})

    with pytest.raises(ProviderError) as e:
        await GeminiLLM("k", client=mock_client(handler)).complete(model="m", messages=MSGS)
    assert e.value.retryable and e.value.status == 429 and "quota" in str(e.value)


async def test_missing_key_raises():
    with pytest.raises(ProviderError):
        await GeminiLLM("", client=mock_client(lambda r: httpx.Response(200))).complete(model="m", messages=MSGS)


# --------------------------------------------------------------------------- Anthropic


async def test_anthropic_complete_and_stream():
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert req.headers["x-api-key"] == "ak" and req.headers["anthropic-version"]
        assert body["messages"][0]["role"] == "user"
        if body.get("stream"):
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse(
                {"type": "message_start", "message": {"usage": {"input_tokens": 11}}},
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Ciao"}},
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "!"}},
                {"type": "message_delta", "usage": {"output_tokens": 3}},
            ))
        assert "JSON" in body["system"]
        return httpx.Response(200, json={"content": [{"type": "text", "text": "{}"}],
                                         "usage": {"input_tokens": 9, "output_tokens": 2}})

    llm = AnthropicLLM("ak", client=mock_client(handler))
    r = await llm.complete(model="claude-x", messages=MSGS, system="s", json_mode=True)
    assert r.text == "{}" and r.usage.output_tokens == 2
    usage = Usage()
    text = "".join([c async for c in llm.stream(model="claude-x", messages=MSGS, usage=usage)])
    assert text == "Ciao!" and (usage.input_tokens, usage.output_tokens) == (11, 3)


# --------------------------------------------------------------------------- OpenAI family


async def test_openai_json_mode_and_temperature_fallback():
    bodies = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        bodies.append(body)
        if "temperature" in body:
            return httpx.Response(400, json={"error": {"message": "Unsupported value: 'temperature'"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"a":1}'}}],
                                         "usage": {"prompt_tokens": 5, "completion_tokens": 3}})

    r = await OpenAIChatLLM("ok", client=mock_client(handler)).complete(model="gpt", messages=MSGS, json_mode=True)
    assert r.text == '{"a":1}' and r.usage.input_tokens == 5
    assert bodies[0]["response_format"] == {"type": "json_object"}
    assert "max_completion_tokens" in bodies[0]


async def test_openai_compatible_needs_no_key_and_uses_base_url():
    def handler(req: httpx.Request) -> httpx.Response:
        assert str(req.url) == "http://ollama:11434/v1/chat/completions"
        assert "authorization" not in req.headers
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse(
            {"choices": [{"delta": {"content": "Hola"}}]},
            {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 1}}, "[DONE]"))

    usage = Usage()
    llm = make_llm("openai_compatible", "", "", client=mock_client(handler))
    assert isinstance(llm, OpenAICompatibleLLM)
    assert "".join([c async for c in llm.stream(model="llama", messages=MSGS, usage=usage)]) == "Hola"
    assert usage.input_tokens == 7


def test_unknown_provider():
    with pytest.raises(ProviderError):
        make_llm("nope", "k")


# --------------------------------------------------------------------------- TTS


async def test_google_tts_decodes_audio_and_sets_voice():
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert req.headers["x-goog-api-key"] == "tk"
        assert body["voice"] == {"languageCode": "ja-JP", "name": "ja-JP-Chirp3-HD-Aoede"}
        assert body["audioConfig"]["speakingRate"] == 0.75
        return httpx.Response(200, json={"audioContent": base64.b64encode(b"MP3DATA").decode()})

    tts = make_tts("google", api_key="tk", client=mock_client(handler))
    assert isinstance(tts, GoogleTTS)
    r = await tts.synthesize("こんにちは", "ja", "ja-JP-Chirp3-HD-Aoede", 0.75)
    assert r.audio == b"MP3DATA" and r.mime == "audio/mpeg" and r.chars == 5


async def test_local_tts_uses_openai_compatible_endpoint():
    def handler(req: httpx.Request) -> httpx.Response:
        assert str(req.url) == "http://tts:8880/v1/audio/speech"
        body = json.loads(req.content)
        assert body["model"] == "kokoro" and body["voice"] == "ff_siwis"
        return httpx.Response(200, content=b"ID3")

    r = await LocalTTS(client=mock_client(handler)).synthesize("Salut", "fr", "ff_siwis")
    assert r.audio == b"ID3"


# --------------------------------------------------------------------------- STT


async def test_openai_stt_whisper_words():
    def handler(req: httpx.Request) -> httpx.Response:
        assert b'name="language"' in req.content and b"verbose_json" in req.content
        return httpx.Response(200, json={"text": " Ciao a tutti ", "duration": 2.5,
                                         "words": [{"word": "Ciao", "start": 0.0, "end": 0.4}]})

    r = await OpenAISTT("k", model="whisper-1", client=mock_client(handler)).transcribe(b"x", "audio/webm", "it")
    assert r.text == "Ciao a tutti" and r.words and r.words[0].word == "Ciao" and r.audio_seconds == 2.5


async def test_deepgram_word_confidence():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Token dk"
        return httpx.Response(200, json={"metadata": {"duration": 1.2}, "results": {"channels": [{"alternatives": [{
            "transcript": "bonjour", "words": [{"word": "bonjour", "punctuated_word": "Bonjour", "confidence": 0.4}]}]}]}})

    r = await DeepgramSTT("dk", client=mock_client(handler)).transcribe(b"x", "audio/webm", "fr")
    assert r.words[0].confidence == 0.4 and r.words[0].word == "Bonjour"


# --------------------------------------------------------------------------- helpers


def test_extract_json_handles_fences_and_chatter():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! Here it is: {"a": [1, 2]} hope that helps') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        extract_json("no json here")


# --------------------------------------------------------------------------- short Japanese clips


def test_short_japanese_is_padded_and_uses_neural2():
    from app.services.audio_cache import prepare_short_japanese

    assert prepare_short_japanese("い", "ja", "google", "female") == ("い。", "ja-JP-Neural2-B")
    assert prepare_short_japanese("いえ", "ja", "google", "male") == ("いえ。", "ja-JP-Neural2-C")
    assert prepare_short_japanese("えき？", "ja", "google", "female") == ("えき？", "ja-JP-Neural2-B")


def test_longer_or_other_language_text_is_untouched():
    from app.services.audio_cache import prepare_short_japanese

    assert prepare_short_japanese("おはようございます", "ja", "google", "female") == ("おはようございます", None)
    assert prepare_short_japanese("un", "fr", "google", "female") == ("un", None)
    # other providers keep their own voice, but still get the padding
    assert prepare_short_japanese("う", "ja", "openai", "female") == ("う。", None)
