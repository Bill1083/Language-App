"""Speech-to-text adapters: Gemini (audio as multimodal input), OpenAI, Groq,
local faster-whisper (all OpenAI-compatible), Deepgram and Google Cloud STT."""

import base64

import httpx

from .base import STTResult, STTWord, ProviderError, Usage, extract_json, http_client, raise_for_status
from .llm import GeminiLLM

LANG_NAMES = {"fr": "French", "it": "Italian", "ja": "Japanese"}
LOCALES = {"fr": "fr-FR", "it": "it-IT", "ja": "ja-JP"}

VERBATIM_PROMPT = """Transcribe this recording of a {language} learner speaking {language}.
Rules — these matter more than readability:
- Transcribe VERBATIM, exactly what was said. Keep every grammar mistake, wrong word, wrong gender,
  wrong conjugation, missing particle and false start. Do NOT correct or improve anything.
- Write {language} in its normal script{script_note}.
- If a word is unclear or you are guessing, write your best guess followed by [?], e.g. "parlé[?]".
- If the speaker switches to English, transcribe the English words as spoken.
- Output only the transcript text, nothing else. If there is no speech, output an empty string."""

COMBINED_PROMPT = VERBATIM_PROMPT.rsplit("- Output only", 1)[0] + """- Then assess the utterance.
Return JSON: {{"transcript": "<verbatim transcript>", "pronunciation_notes": ["<short note about a sound
the speaker mispronounced, in English>"], "feedback": <feedback object as described in the system instructions>}}"""

DEFAULT_STT_MODELS = {
    "gemini": "gemini-3.8-flash",
    "openai": "gpt-4o-transcribe",
    "groq": "whisper-large-v3-turbo",
    "local": "Systran/faster-whisper-small",
    "deepgram": "nova-3",
    "google_cloud": "latest_long",
}


def _script_note(lang: str) -> str:
    return " (kanji and kana as a native speaker would write it, no romaji)" if lang == "ja" else ""


def audio_ext(mime: str) -> str:
    base = mime.split(";")[0]
    return {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3",
            "audio/wav": "wav", "audio/x-wav": "wav", "audio/aac": "aac"}.get(base, "webm")


class STTProvider:
    name = "base"

    def __init__(self, api_key: str = "", base_url: str = "", model: str = "", client: httpx.AsyncClient | None = None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model or DEFAULT_STT_MODELS.get(self.name, "")
        self._client = client

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client or http_client()

    async def transcribe(self, audio: bytes, mime: str, lang: str, duration_s: float = 0.0) -> STTResult:
        raise NotImplementedError


class GeminiSTT(STTProvider):
    name = "gemini"

    def _llm(self) -> GeminiLLM:
        return GeminiLLM(self.api_key, self.base_url, self._client)

    async def transcribe(self, audio, mime, lang, duration_s=0.0):
        prompt = VERBATIM_PROMPT.format(language=LANG_NAMES.get(lang, lang), script_note=_script_note(lang))
        # Verbatim transcription needs no reasoning; minimal thinking saves 1–3 s per clip.
        result = await self._llm().complete_audio(model=self.model, prompt=prompt, audio=audio, mime=mime,
                                                  thinking="minimal")
        text = result.text.strip().strip('"')
        return STTResult(text=text, provider=self.name, model=self.model, audio_seconds=duration_s, usage=result.usage)

    async def transcribe_with_feedback(self, audio, mime, lang, feedback_instructions: str, duration_s=0.0):
        """Optional combined call: verbatim transcript + feedback JSON + pronunciation notes."""
        prompt = COMBINED_PROMPT.format(language=LANG_NAMES.get(lang, lang), script_note=_script_note(lang))
        result = await self._llm().complete_audio(
            model=self.model, prompt=prompt, audio=audio, mime=mime, json_mode=True, system=feedback_instructions
        )
        data = extract_json(result.text)
        return STTResult(
            text=str(data.get("transcript", "")).strip(), provider=self.name, model=self.model,
            audio_seconds=duration_s, usage=result.usage,
            extra={"feedback": data.get("feedback"), "pronunciation_notes": data.get("pronunciation_notes") or []},
        )


class OpenAISTT(STTProvider):
    name = "openai"
    DEFAULT_BASE = "https://api.openai.com/v1"

    async def transcribe(self, audio, mime, lang, duration_s=0.0):
        base = self.base_url or self.DEFAULT_BASE
        headers = {"authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        verbose = not self.model.startswith("gpt-4o")
        data: dict[str, object] = {
            "model": self.model,
            "language": lang,
            "response_format": "verbose_json" if verbose else "json",
            "prompt": "Verbatim transcription of a language learner. Keep their mistakes; do not correct grammar.",
        }
        if verbose:
            data["timestamp_granularities[]"] = "word"
        files = {"file": (f"speech.{audio_ext(mime)}", audio, mime.split(";")[0])}
        resp = await self.client.post(f"{base}/audio/transcriptions", headers=headers, data=data, files=files)
        raise_for_status(resp, f"{self.name} STT")
        body = resp.json()
        words = None
        if body.get("words"):
            words = [STTWord(word=w.get("word", ""), start=w.get("start"), end=w.get("end")) for w in body["words"]]
        return STTResult(
            text=(body.get("text") or "").strip(), provider=self.name, model=self.model, words=words,
            audio_seconds=float(body.get("duration") or duration_s),
        )


class GroqSTT(OpenAISTT):
    name = "groq"
    DEFAULT_BASE = "https://api.groq.com/openai/v1"


class LocalSTT(OpenAISTT):
    name = "local"
    DEFAULT_BASE = "http://stt:8000/v1"


class DeepgramSTT(STTProvider):
    name = "deepgram"

    async def transcribe(self, audio, mime, lang, duration_s=0.0):
        if not self.api_key:
            raise ProviderError("No API key configured for Deepgram")
        params = {"model": self.model, "language": lang, "punctuate": "true", "smart_format": "false"}
        resp = await self.client.post(
            "https://api.deepgram.com/v1/listen", params=params, content=audio,
            headers={"authorization": f"Token {self.api_key}", "content-type": mime.split(";")[0]},
        )
        raise_for_status(resp, "Deepgram")
        body = resp.json()
        alt = body["results"]["channels"][0]["alternatives"][0]
        words = [STTWord(word=w.get("punctuated_word") or w["word"], start=w.get("start"), end=w.get("end"),
                         confidence=w.get("confidence")) for w in alt.get("words", [])]
        return STTResult(text=alt.get("transcript", "").strip(), provider=self.name, model=self.model, words=words,
                         audio_seconds=float(body.get("metadata", {}).get("duration") or duration_s))


class GoogleCloudSTT(STTProvider):
    name = "google_cloud"

    async def transcribe(self, audio, mime, lang, duration_s=0.0):
        if not self.api_key:
            raise ProviderError("No API key configured for Google Cloud Speech-to-Text")
        base_mime = mime.split(";")[0]
        encoding = {"audio/webm": "WEBM_OPUS", "audio/ogg": "OGG_OPUS"}.get(base_mime, "ENCODING_UNSPECIFIED")
        body = {
            "config": {
                "encoding": encoding, "languageCode": LOCALES.get(lang, lang), "model": self.model,
                "enableWordConfidence": True, "enableWordTimeOffsets": True, "enableAutomaticPunctuation": True,
            },
            "audio": {"content": base64.b64encode(audio).decode()},
        }
        if encoding != "ENCODING_UNSPECIFIED":
            body["config"]["sampleRateHertz"] = 48000
        resp = await self.client.post("https://speech.googleapis.com/v1/speech:recognize",
                                      headers={"x-goog-api-key": self.api_key}, json=body)
        raise_for_status(resp, "Google STT")
        results = resp.json().get("results", [])
        text_parts, words = [], []
        for r in results:
            alt = r["alternatives"][0]
            text_parts.append(alt.get("transcript", ""))
            for w in alt.get("words", []):
                words.append(STTWord(word=w["word"], confidence=w.get("confidence"),
                                     start=float(str(w.get("startTime", "0s")).rstrip("s") or 0),
                                     end=float(str(w.get("endTime", "0s")).rstrip("s") or 0)))
        return STTResult(text=" ".join(text_parts).strip(), provider=self.name, model=self.model, words=words or None,
                         audio_seconds=duration_s, usage=Usage())


STT_PROVIDERS: dict[str, type[STTProvider]] = {
    "gemini": GeminiSTT,
    "openai": OpenAISTT,
    "groq": GroqSTT,
    "local": LocalSTT,
    "deepgram": DeepgramSTT,
    "google_cloud": GoogleCloudSTT,
}


def make_stt(provider: str, **kwargs) -> STTProvider:
    try:
        return STT_PROVIDERS[provider](**kwargs)
    except KeyError:
        raise ProviderError(f"Unknown STT provider '{provider}'") from None
