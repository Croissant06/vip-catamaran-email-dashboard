from __future__ import annotations

from dataclasses import dataclass, field, fields
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv, set_key

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)


def _env_bool(name: str, default: str = "false") -> bool:
    raw = os.getenv(name, default)
    return str(raw).strip().strip("\"'").lower() == "true"


REQUIRED_SETTING_ENV_VARS = (
    "IMAP_HOST",
    "IMAP_USER",
    "IMAP_PASSWORD",
    "SMTP_HOST",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SECRET_KEY",
)


def _required_env(name: str) -> str:
    return os.getenv(name, "")


def _validate_required_settings(settings: "Settings") -> None:
    missing = [
        env_name
        for env_name, value in (
            ("IMAP_HOST", settings.imap_host),
            ("IMAP_USER", settings.imap_user),
            ("IMAP_PASSWORD", settings.imap_password),
            ("SMTP_HOST", settings.smtp_host),
            ("SMTP_USER", settings.smtp_user),
            ("SMTP_PASSWORD", settings.smtp_password),
            ("SECRET_KEY", settings.secret_key),
        )
        if not str(value or "").strip()
    ]
    if missing:
        raise RuntimeError(
            "Missing required settings: "
            + ", ".join(missing)
            + ". Set them in the environment or .env before starting the app."
        )


@dataclass
class Settings:
    imap_host: str = field(default_factory=lambda: _required_env("IMAP_HOST"))
    imap_port: int = field(default_factory=lambda: int(os.getenv("IMAP_PORT", "993")))
    imap_user: str = field(default_factory=lambda: _required_env("IMAP_USER"))
    imap_password: str = field(default_factory=lambda: _required_env("IMAP_PASSWORD"))
    smtp_host: str = field(default_factory=lambda: _required_env("SMTP_HOST"))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "465")))
    smtp_use_starttls: bool = field(default_factory=lambda: _env_bool("SMTP_USE_STARTTLS", "false"))
    smtp_user: str = field(default_factory=lambda: _required_env("SMTP_USER"))
    smtp_password: str = field(default_factory=lambda: _required_env("SMTP_PASSWORD"))
    poll_interval_minutes: int = field(default_factory=lambda: int(os.getenv("POLL_INTERVAL_MINUTES", "5")))
    poll_backoff_minutes: int = field(default_factory=lambda: int(os.getenv("POLL_BACKOFF_MINUTES", "30")))
    mail_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("MAIL_TIMEOUT_SECONDS", "10")))
    fuzzy_match_threshold: int = field(default_factory=lambda: int(os.getenv("FUZZY_MATCH_THRESHOLD", "80")))
    secret_key: str = field(default_factory=lambda: _required_env("SECRET_KEY"))
    safe_mode: bool = field(default_factory=lambda: _env_bool("SAFE_MODE", "true"))
    demo_mode: bool = field(default_factory=lambda: _env_bool("DEMO_MODE", "false"))
    demo_email: str = field(default_factory=lambda: os.getenv("DEMO_EMAIL", ""))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", f"sqlite:///{(BASE_DIR / 'cruise_email_dashboard' / 'app.db').as_posix()}"))

    def __post_init__(self) -> None:
        _validate_required_settings(self)

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
    refreshed = Settings()
    if "settings" in globals():
        for item in fields(Settings):
            setattr(settings, item.name, getattr(refreshed, item.name))
        return settings
    settings = refreshed
    return settings


def update_env(values: dict[str, str]) -> None:
    if not ENV_PATH.exists():
        ENV_PATH.write_text("", encoding="utf-8")
    for key, value in values.items():
        set_key(str(ENV_PATH), key, str(value))
    reload_settings()


settings = Settings()
