"""Environment configuration.

Everything here comes from `.env` (see `.env.example` at the repo root). Values
an admin can change at runtime (providers, models, voices, keys) are only the
*defaults* here; `services/runtime_config.py` layers the admin overrides stored
in the database on top.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    # --- Core ---
    domain: str = "localhost"
    app_secret: str = "change-me"
    postgres_password: str = "change-me"
    postgres_user: str = "parlo"
    postgres_db: str = "parlo"
    postgres_host: str = "db"
    database_url: str | None = None
    redis_url: str = "redis://redis:6379/0"
    registration_mode: Literal["open", "invite", "closed"] = "invite"
    recording_retention_days: int = 30
    store_recordings: bool = True
    cookie_secure: Literal["auto", "true", "false"] = "auto"
    session_days: int = 30
    data_dir: Path = Path("/data")
    curriculum_dir: Path = Path("/app/curriculum")
    log_level: str = "INFO"

    # --- LLM ---
    llm_provider: str = "gemini"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model_conversation: str = ""
    llm_model_feedback: str = ""
    llm_model_content: str = ""

    # --- TTS ---
    tts_provider_lesson: str = "google"
    tts_provider_conversation: str = "google"
    tts_api_key: str = ""
    tts_base_url: str = ""
    tts_azure_region: str = ""
    google_application_credentials: str = ""
    tts_voice_fr: str = ""
    tts_voice_it: str = ""
    tts_voice_ja: str = ""
    tts_voice_fr_male: str = ""
    tts_voice_it_male: str = ""
    tts_voice_ja_male: str = ""

    # --- STT ---
    stt_provider: str = "gemini"
    stt_api_key: str = ""
    stt_base_url: str = ""
    stt_model: str = ""
    stt_combined_feedback: bool = False

    # --- Optional per-provider keys, used when an admin switches provider at runtime ---
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    groq_api_key: str = ""
    deepgram_api_key: str = ""
    elevenlabs_api_key: str = ""
    azure_speech_key: str = ""

    # --- Limits ---
    daily_ai_budget_usd: float = 2.00
    rate_limit_per_min: int = 30
    max_recording_seconds: int = 60
    max_upload_bytes: int = 4 * 1024 * 1024
    max_text_chars: int = 2000
    pregenerate_ahead: int = 3

    # --- Web push (generated on first boot when empty) ---
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = Field(default="", description="mailto: or https: contact for push services")

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:5432/{self.postgres_db}"
        )

    @property
    def audio_cache_dir(self) -> Path:
        return self.data_dir / "audio_cache"

    @property
    def recordings_dir(self) -> Path:
        return self.data_dir / "recordings"


@lru_cache
def get_settings() -> Settings:
    return Settings()
