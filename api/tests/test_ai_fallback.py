"""Backup-model fallback and time limits in AIService (providers are faked)."""

import asyncio

import pytest

from app.providers.base import ChatMessage, LLMResult, ProviderError, STTResult
from app.providers.llm import LLMProvider
from app.providers.stt import GeminiSTT
from app.services import ai as ai_mod
from app.services import runtime_config
from app.services.ai import BACKUP_NOTICE, RETRY_NOTICE, AIService
from app.services.runtime_config import AIConfig

MAIN, BACKUP = "gemini-3.8-flash", "gemini-3.5-flash-lite"
HELLO = [ChatMessage("user", "hello")]


def busy() -> ProviderError:
    return ProviderError("Gemini error 503: This model is currently experiencing high demand.", retryable=True,
                         status=503)


class ScriptedLLM(LLMProvider):
    """model -> "ok" | "503" | "hang" | "bad_request" | "break" (fails after one token)."""

    name = "gemini"

    def __init__(self, script: dict[str, str]):
        super().__init__("key")
        self.script = script
        self.calls: list[str] = []

    async def complete(self, *, model, messages, **kwargs):
        self.calls.append(model)
        if self.script[model] == "503":
            raise busy()
        if self.script[model] == "bad_request":
            raise ProviderError("Gemini error 400: bad request", status=400)
        return LLMResult(text=f"hi from {model}", model=model, provider=self.name)

    async def stream(self, *, model, messages, usage, **kwargs):
        self.calls.append(model)
        behaviour = self.script[model]
        if behaviour == "503":
            raise busy()
        if behaviour == "hang":
            await asyncio.sleep(5)
        yield "Bon"
        if behaviour == "break":
            raise busy()
        yield "jour"


@pytest.fixture
def make(monkeypatch):
    ai_mod._cooling.clear()
    monkeypatch.setattr(ai_mod, "RETRY_DELAY", 0)
    monkeypatch.setattr(ai_mod, "_shared", lambda: None)

    async def no_log(self, **kwargs):
        return None

    monkeypatch.setattr(AIService, "log", no_log)

    def build(script: dict[str, str], backup: str = BACKUP) -> tuple[AIService, ScriptedLLM]:
        llm = ScriptedLLM(script)
        monkeypatch.setattr(ai_mod, "llm_for", lambda cfg: llm)
        service = AIService(db=None, user_id=None, is_admin=True)  # type: ignore[arg-type]
        service._cfg = AIConfig(
            llm_provider="gemini", llm_base_url="",
            llm_models={"conversation": MAIN, "feedback": MAIN, "content": MAIN},
            tts_provider_lesson="google", tts_provider_conversation="google", tts_base_url="", tts_azure_region="",
            stt_provider="gemini", stt_base_url="", stt_model=MAIN, stt_combined_feedback=False,
            daily_ai_budget_usd=0, voices={}, llm_fallback_model=backup,
        )
        return service, llm

    yield build
    ai_mod._cooling.clear()


async def collect(service: AIService, notices: list[str] | None = None) -> str:
    async def on_retry(message: str) -> None:
        if notices is not None:
            notices.append(message)

    return "".join([d async for d in service.llm_stream("conversation", "conversation", system="s",
                                                         messages=HELLO, on_retry=on_retry)])


async def test_overloaded_main_model_falls_back_to_the_backup(make):
    service, llm = make({MAIN: "503", BACKUP: "ok"})
    result = await service.llm_result("t", "conversation", system="s", messages=HELLO)
    assert result.model == BACKUP
    assert llm.calls == [MAIN, BACKUP]
    assert "503" in service.failures[0]


async def test_backup_goes_first_while_the_main_model_cools_down(make):
    service, llm = make({MAIN: "503", BACKUP: "ok"})
    await service.llm_text("t", "conversation", system="s", messages=HELLO)
    await service.llm_text("t", "conversation", system="s", messages=HELLO)
    assert llm.calls == [MAIN, BACKUP, BACKUP]


async def test_without_a_backup_the_same_model_is_retried_once(make):
    service, llm = make({MAIN: "503"}, backup="off")
    with pytest.raises(ProviderError):
        await service.llm_text("t", "conversation", system="s", messages=HELLO)
    assert llm.calls == [MAIN, MAIN]


async def test_non_retryable_errors_are_not_retried(make):
    service, llm = make({MAIN: "bad_request", BACKUP: "ok"})
    with pytest.raises(ProviderError):
        await service.llm_text("t", "conversation", system="s", messages=HELLO)
    assert llm.calls == [MAIN]


async def test_stream_switches_to_the_backup_and_says_so(make):
    service, llm = make({MAIN: "503", BACKUP: "ok"})
    notices: list[str] = []
    assert await collect(service, notices) == "Bonjour"
    assert llm.calls == [MAIN, BACKUP]
    assert notices == [BACKUP_NOTICE]


async def test_stream_that_never_starts_times_out_and_falls_back(make, monkeypatch):
    monkeypatch.setattr(ai_mod, "FIRST_TOKEN_TIMEOUT", 0.05)
    service, llm = make({MAIN: "hang", BACKUP: "ok"})
    assert await collect(service) == "Bonjour"
    assert llm.calls == [MAIN, BACKUP]
    assert "didn't start replying" in service.failures[0]


async def test_stream_without_backup_retries_with_a_notice(make):
    service, llm = make({MAIN: "503"}, backup="")
    notices: list[str] = []
    with pytest.raises(ProviderError):
        await collect(service, notices)
    assert llm.calls == [MAIN, MAIN]
    assert notices == [RETRY_NOTICE]


async def test_stream_failing_mid_reply_is_not_restarted(make):
    service, llm = make({MAIN: "break", BACKUP: "ok"})
    received: list[str] = []
    with pytest.raises(ProviderError):
        async for delta in service.llm_stream("conversation", "conversation", system="s", messages=HELLO):
            received.append(delta)
    assert received == ["Bon"]
    assert llm.calls == [MAIN]


async def test_gemini_gets_a_backup_model_by_default_and_off_disables_it(monkeypatch):
    overrides: dict = {}

    async def fake_overrides(db):
        return overrides

    monkeypatch.setattr(runtime_config, "load_overrides", fake_overrides)
    runtime_config.invalidate()
    cfg = await runtime_config.get_ai_config(None)  # type: ignore[arg-type]
    assert cfg.backup_model == BACKUP

    overrides["llm_model_fallback"] = "off"
    runtime_config.invalidate()
    cfg = await runtime_config.get_ai_config(None)  # type: ignore[arg-type]
    assert cfg.backup_model == ""
    assert cfg.llm_fallback_model == "off"
    runtime_config.invalidate()


class ScriptedSTT(GeminiSTT):
    """Gemini STT whose behaviour depends on the model: "ok" | "503" | "hang"."""

    def __init__(self, model: str, script: dict[str, str], calls: list[str]):
        super().__init__(api_key="key", model=model)
        self.script, self.calls = script, calls

    async def transcribe(self, audio, mime, lang, duration_s=0.0):
        self.calls.append(self.model)
        if self.script[self.model] == "503":
            raise busy()
        if self.script[self.model] == "hang":
            await asyncio.sleep(5)
        return STTResult(text="すみません、駅はどこですか", provider="gemini", model=self.model)


def scripted_stt(monkeypatch, script: dict[str, str]) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(ai_mod, "stt_for", lambda cfg, model=None: ScriptedSTT(model, script, calls))
    return calls


async def test_transcription_falls_back_to_the_backup_and_says_so(make, monkeypatch):
    service, _ = make({})
    calls = scripted_stt(monkeypatch, {MAIN: "503", BACKUP: "ok"})
    notices: list[str] = []

    async def on_retry(message: str) -> None:
        notices.append(message)

    result = await service.transcribe(b"audio", "audio/webm", "ja", 2.0, on_retry=on_retry)
    assert result.model == BACKUP and result.text
    assert calls == [MAIN, BACKUP]
    assert notices == [BACKUP_NOTICE]


async def test_slow_transcription_times_out_and_falls_back(make, monkeypatch):
    monkeypatch.setattr(ai_mod, "STT_TIMEOUT", 0.05)
    service, _ = make({})
    calls = scripted_stt(monkeypatch, {MAIN: "hang", BACKUP: "ok"})
    result = await service.transcribe(b"audio", "audio/webm", "ja", 2.0)
    assert result.model == BACKUP
    assert calls == [MAIN, BACKUP]
    assert "longer than" in service.failures[0]


async def test_an_overloaded_reply_model_sends_transcription_to_the_backup_too(make, monkeypatch):
    service, _ = make({MAIN: "503", BACKUP: "ok"})
    await service.llm_text("t", "conversation", system="s", messages=HELLO)  # marks MAIN as overloaded
    calls = scripted_stt(monkeypatch, {MAIN: "ok", BACKUP: "ok"})
    await service.transcribe(b"audio", "audio/webm", "ja", 2.0)
    assert calls == [BACKUP]


def test_course_order_only_drifts_a_few_places():
    from app.services.srs import COURSE_JITTER, loosely_ordered

    items = list(range(20))
    runs = [loosely_ordered(items) for _ in range(200)]
    assert all(sorted(r) == items for r in runs)
    assert all(abs(r.index(i) - i) <= COURSE_JITTER for r in runs for i in items)
    assert any(r != items for r in runs)  # not the same sequence every time
