"""Text-to-speech adapters: Google Cloud (Chirp 3 HD), OpenAI, a local
OpenAI-compatible server (Kokoro), ElevenLabs and Azure."""

import asyncio
import base64
import time
from xml.sax.saxutils import escape

import httpx

from .base import ProviderError, TTSResult, http_client, raise_for_status

LOCALES = {"fr": "fr-FR", "it": "it-IT", "ja": "ja-JP"}

# Default voices per provider, language and gender. Admins can override any of
# these at runtime; `.env` TTS_VOICE_* override the female (default) voice.
DEFAULT_VOICES: dict[str, dict[str, dict[str, str]]] = {
    "google": {
        lang: {"female": f"{loc}-Chirp3-HD-Aoede", "male": f"{loc}-Chirp3-HD-Charon"}
        for lang, loc in LOCALES.items()
    },
    "openai": {lang: {"female": "nova", "male": "onyx"} for lang in LOCALES},
    "local": {
        "fr": {"female": "ff_siwis", "male": "ff_siwis"},
        "it": {"female": "if_sara", "male": "im_nicola"},
        "ja": {"female": "jf_alpha", "male": "jm_kumo"},
    },
    "elevenlabs": {lang: {"female": "21m00Tcm4TlvDq8ikWAM", "male": "pNInz6obpgDQGcFmaJgB"} for lang in LOCALES},
    "azure": {
        "fr": {"female": "fr-FR-DeniseNeural", "male": "fr-FR-HenriNeural"},
        "it": {"female": "it-IT-ElsaNeural", "male": "it-IT-DiegoNeural"},
        "ja": {"female": "ja-JP-NanamiNeural", "male": "ja-JP-KeitaNeural"},
    },
}

# Chirp 3 HD voices read sentences beautifully but often produce silence or
# garbled sound for a lone kana or a two-kana word. Short Japanese clips use
# these Neural2 voices instead (see services/audio_cache.py).
SHORT_TEXT_VOICES: dict[str, dict[str, dict[str, str]]] = {
    "google": {"ja": {"female": "ja-JP-Neural2-B", "male": "ja-JP-Neural2-C"}},
}

# Extra voices offered in the admin "compare" dropdown (Google Chirp 3 HD).
GOOGLE_CHIRP_VOICES = ["Aoede", "Kore", "Leda", "Zephyr", "Callirrhoe", "Despina", "Charon", "Puck", "Fenrir",
                       "Orus", "Iapetus", "Algenib"]


class TTSProvider:
    name = "base"

    def __init__(self, api_key: str = "", base_url: str = "", region: str = "", credentials_file: str = "",
                 client: httpx.AsyncClient | None = None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.region = region
        self.credentials_file = credentials_file
        self._client = client

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client or http_client()

    async def synthesize(self, text: str, lang: str, voice: str, speed: float = 1.0) -> TTSResult:
        raise NotImplementedError


class GoogleTTS(TTSProvider):
    name = "google"
    URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
    _token: tuple[str, float] | None = None

    async def _auth_headers(self) -> dict[str, str]:
        if self.api_key:
            return {"x-goog-api-key": self.api_key}
        if not self.credentials_file:
            raise ProviderError("Google TTS needs TTS_API_KEY or GOOGLE_APPLICATION_CREDENTIALS")
        cached = GoogleTTS._token
        if cached and cached[1] > time.time() + 60:
            return {"authorization": f"Bearer {cached[0]}"}

        def refresh() -> tuple[str, float]:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_file(
                self.credentials_file, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            creds.refresh(Request())
            expiry = creds.expiry.timestamp() if creds.expiry else time.time() + 3000
            return creds.token, expiry

        GoogleTTS._token = await asyncio.to_thread(refresh)
        return {"authorization": f"Bearer {GoogleTTS._token[0]}"}

    async def synthesize(self, text, lang, voice, speed=1.0):
        locale = voice[:5] if voice[2:3] == "-" else LOCALES.get(lang, lang)
        body = {
            "input": {"text": text},
            "voice": {"languageCode": locale, "name": voice},
            "audioConfig": {"audioEncoding": "MP3", "speakingRate": speed},
        }
        resp = await self.client.post(self.URL, headers=await self._auth_headers(), json=body)
        raise_for_status(resp, "Google TTS")
        audio = base64.b64decode(resp.json()["audioContent"])
        return TTSResult(audio=audio, mime="audio/mpeg", chars=len(text))


class OpenAITTS(TTSProvider):
    name = "openai"
    DEFAULT_BASE = "https://api.openai.com/v1"
    DEFAULT_MODEL = "gpt-4o-mini-tts"

    async def synthesize(self, text, lang, voice, speed=1.0):
        base = self.base_url or self.DEFAULT_BASE
        headers = {"authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        body = {"model": self.DEFAULT_MODEL, "input": text, "voice": voice, "speed": speed, "response_format": "mp3"}
        resp = await self.client.post(f"{base}/audio/speech", headers=headers, json=body)
        raise_for_status(resp, f"{self.name} TTS")
        return TTSResult(audio=resp.content, mime="audio/mpeg", chars=len(text))


class LocalTTS(OpenAITTS):
    """Self-hosted OpenAI-compatible server (e.g. Kokoro-FastAPI) behind the local-ai profile."""

    name = "local"
    DEFAULT_BASE = "http://tts:8880/v1"
    DEFAULT_MODEL = "kokoro"


class ElevenLabsTTS(TTSProvider):
    name = "elevenlabs"

    async def synthesize(self, text, lang, voice, speed=1.0):
        if not self.api_key:
            raise ProviderError("No API key configured for ElevenLabs")
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128"
        body = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "language_code": lang,
            "voice_settings": {"speed": max(0.7, min(1.2, speed))},
        }
        resp = await self.client.post(url, headers={"xi-api-key": self.api_key}, json=body)
        raise_for_status(resp, "ElevenLabs")
        return TTSResult(audio=resp.content, mime="audio/mpeg", chars=len(text))


class AzureTTS(TTSProvider):
    name = "azure"

    async def synthesize(self, text, lang, voice, speed=1.0):
        if not (self.api_key and self.region):
            raise ProviderError("Azure TTS needs an API key and TTS_AZURE_REGION")
        url = f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1"
        locale = LOCALES.get(lang, lang)
        rate = f"{round((speed - 1) * 100):+d}%"
        ssml = (
            f"<speak version='1.0' xml:lang='{locale}'><voice name='{voice}'>"
            f"<prosody rate='{rate}'>{escape(text)}</prosody></voice></speak>"
        )
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
            "User-Agent": "parlo",
        }
        resp = await self.client.post(url, headers=headers, content=ssml.encode())
        raise_for_status(resp, "Azure TTS")
        return TTSResult(audio=resp.content, mime="audio/mpeg", chars=len(text))


TTS_PROVIDERS: dict[str, type[TTSProvider]] = {
    "google": GoogleTTS,
    "openai": OpenAITTS,
    "local": LocalTTS,
    "elevenlabs": ElevenLabsTTS,
    "azure": AzureTTS,
}


def make_tts(provider: str, **kwargs) -> TTSProvider:
    try:
        return TTS_PROVIDERS[provider](**kwargs)
    except KeyError:
        raise ProviderError(f"Unknown TTS provider '{provider}'") from None
