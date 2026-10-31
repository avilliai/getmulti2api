"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(get_project_root() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Service Configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    RELOAD: bool = False
    LOG_LEVEL: str = "INFO"
    API_KEY: str = "changeme"

    # Multi AI & Firebase
    MULTI_BASE_URL: str = "https://web.getmulti.ai"
    FIREBASE_API_KEY: str = "AIzaSyDJ_v8StAeaFVcStQHiuXEWIBVk_3mAvB0"
    FIREBASE_PROJECT_ID: str = "get-multi"

    # Account Pool & Health
    ACCOUNT_FILE: str = "data/accounts.json"
    ACCOUNT_FAILURE_LIMIT: int = 3
    ACCOUNT_COOLDOWN_SECONDS: int = 180
    AUTO_REGISTER_ON_EMPTY: bool = True
    MIN_ACTIVE_ACCOUNTS: int = 2
    FREE_MODE: bool = True
    DEFAULT_MODEL: str = "google/gemma-4-26b-a4b-it:free"

    # Cloudflare Temp Email
    WORKER_DOMAIN: str = ""
    EMAIL_DOMAIN: str = ""
    ADMIN_PASSWORD: str = ""

    # Outlook Email Pool
    OUTLOOK_ACCOUNT_FILE: str = "data/outlook_valid_accounts.txt"
    OUTLOOK_TOKEN_URL: str = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    OUTLOOK_IMAP_HOSTS: str = "outlook.office365.com,outlook.live.com"
    OUTLOOK_IMAP_PORT: int = 993
    OUTLOOK_IMAP_TIMEOUT: int = 20

    # Network & Timeout
    REQUEST_TIMEOUT: int = 120
    PROXY: Optional[str] = None

    @field_validator("PROXY", mode="before")
    @classmethod
    def normalize_proxy(cls, v: Any) -> Optional[str]:
        if not v or not str(v).strip():
            return None
        return str(v).strip()


def resolve_project_path(path: str | Path) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return get_project_root() / p


settings = Settings()
