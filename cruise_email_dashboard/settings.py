from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv, set_key

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)


@dataclass
class Settings:
    imap_host: str = os.getenv("IMAP_HOST", "mail.vipcatamaran.com")
    imap_port: int = int(os.getenv("IMAP_PORT", "993"))
    imap_user: str = os.getenv("IMAP_USER", "bookings@vipcatamaran.com")
    imap_password: str = os.getenv("IMAP_PASSWORD", "")
    smtp_host: str = os.getenv("SMTP_HOST", "mail.vipcatamaran.com")
    smtp_port: int = int(os.getenv("SMTP_PORT", "465"))
    smtp_user: str = os.getenv("SMTP_USER", "bookings@vipcatamaran.com")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    poll_interval_minutes: int = int(os.getenv("POLL_INTERVAL_MINUTES", "5"))
    poll_backoff_minutes: int = int(os.getenv("POLL_BACKOFF_MINUTES", "30"))
    mail_timeout_seconds: int = int(os.getenv("MAIL_TIMEOUT_SECONDS", "10"))
    fuzzy_match_threshold: int = int(os.getenv("FUZZY_MATCH_THRESHOLD", "80"))
    secret_key: str = os.getenv("SECRET_KEY", "change-me")
    safe_mode: bool = os.getenv("SAFE_MODE", "true").lower() == "true"
    demo_mode: bool = os.getenv("DEMO_MODE", "false").lower() == "true"
    demo_email: str = os.getenv("DEMO_EMAIL", "")
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{(BASE_DIR / 'cruise_email_dashboard' / 'app.db').as_posix()}")

    @property
    def imap_server(self) -> str:
        return normalize_mail_host(self.imap_host)

    @property
    def smtp_server(self) -> str:
        return normalize_mail_host(self.smtp_host)


def normalize_mail_host(value: str) -> str:
    parsed = urlparse(value)
    if parsed.hostname:
        return parsed.hostname
    return value.strip().rstrip("/")


def reload_settings() -> Settings:
    global settings
    load_dotenv(ENV_PATH, override=True)
    settings = Settings()
    return settings


def update_env(values: dict[str, str]) -> None:
    if not ENV_PATH.exists():
        ENV_PATH.write_text("", encoding="utf-8")
    for key, value in values.items():
        set_key(str(ENV_PATH), key, str(value))
    reload_settings()


settings = Settings()
