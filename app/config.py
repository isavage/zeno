from typing import List, Optional, Dict, Any
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator, AliasChoices
import os
from pathlib import Path
from dotenv import load_dotenv

# Load local .env if present (Doppler provides env vars directly in production)
load_dotenv(override=False)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Server
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    APP_SECRET_KEY: str = Field(default="zeno-insecure-secret-key-change-in-production-12345")
    VAULT_DATA_DIR: str = Field(default="./data/vault")

    # Encryption Master Key (32 url-safe base64 / Fernet key)
    ZENOS_ENCRYPTION_KEY: Optional[str] = None

    # LLM API Keys
    OPENAI_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    MOONSHOT_API_KEY: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None

    DEFAULT_FAST_MODEL: str = "z-ai/glm-5.2:free"
    DEFAULT_REASONING_MODEL: str = "gpt-5.4-mini"
    DEFAULT_FALLBACK_MODEL: str = "minimax/minimax-m3:free"
    ALLOWED_HOSTS: str = "localhost,127.0.0.1"  # comma‑separated list of hostnames allowed by TrustedHostMiddleware
    ADMIN_EMAILS: str = Field(
        default="",
        validation_alias=AliasChoices("ADMIN_EMAILS", "admin_emails"),
    )  # comma‑separated list of admin user emails

    @property
    def allowed_hosts(self) -> List[str]:
        """Return a list of hostnames (lower‑cased) for TrustedHostMiddleware."""
        if not self.ALLOWED_HOSTS:
            return []
        return [h.strip().lower() for h in self.ALLOWED_HOSTS.split(",") if h.strip()]




    @property
    def admin_emails(self) -> List[str]:
        """Return a list of lower‑cased admin emails from the env var."""
        if not self.ADMIN_EMAILS:
            return []
        return [e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()]

    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_ALLOWED_USER_IDS: str = ""
    ENABLE_TELEGRAM_VOICE_REPLIES: bool = True

    # Web UI Auth
    AUTHORIZED_EMAILS: str = ""

    # Google OAuth
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_PATH: str = "/auth/google/callback"

    # Microsoft OAuth
    MICROSOFT_CLIENT_ID: Optional[str] = None
    MICROSOFT_CLIENT_SECRET: Optional[str] = None
    MICROSOFT_TENANT_ID: str = "common"
    MICROSOFT_REDIRECT_PATH: str = "/auth/microsoft/callback"

    # Voice Engine
    WHISPER_MODEL_SIZE: str = "small.en"
    KOKORO_VOICE: str = "af_heart"
    # Primary TTS provider: "edge" uses free edge‑tts wrapper, "kokoro" forces Kokoro only
    TTS_PROVIDER: str = "edge"
    # Edge TTS voice selection (default female)
    EDGE_TTS_VOICE: str = "en-US-AriaNeural"

    @property
    def allowed_telegram_ids(self) -> List[int]:
        if not self.TELEGRAM_ALLOWED_USER_IDS:
            return []
        ids = []
        for raw in self.TELEGRAM_ALLOWED_USER_IDS.split(","):
            raw = raw.strip()
            if raw.isdigit():
                ids.append(int(raw))
        return ids

    @property
    def authorized_emails_list(self) -> List[str]:
        if not self.AUTHORIZED_EMAILS:
            return []
        return [e.strip().lower() for e in self.AUTHORIZED_EMAILS.split(",") if e.strip()]

    @property
    def vault_path(self) -> Path:
        p = Path(self.VAULT_DATA_DIR)
        p.mkdir(parents=True, exist_ok=True)
        return p

settings = Settings()
