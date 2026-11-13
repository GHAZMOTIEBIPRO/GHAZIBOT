"""Runtime settings, read from the environment once per app instance."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENVIRONMENTS = ("production", "development")


class ConfigError(RuntimeError):
    """The settings are unsafe for the declared environment; the app refuses to start."""


def _flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    # The whole platform answers 404 unless this is on (feature flag).
    enabled: bool = False
    # "production" unless explicitly declared "development" (fail closed).
    environment: str = "production"
    db_path: str = str(ROOT / "var" / "platform.sqlite3")
    # Published research artifacts the platform may read (never writes).
    public_data_dir: Path = ROOT / "public" / "data"
    source_rights_path: Path = ROOT / "data" / "source_rights.json"
    ui_dir: Path = ROOT / "platform_ui"
    # Cookies carry Secure (and the __Host- prefix) unless explicitly running on
    # plain-http localhost in development.
    secure_cookies: bool = True
    session_hours: int = 72
    # A session unused for this long is dead even before its absolute expiry.
    session_idle_hours: int = 24
    # Development mode exposes one-time verification / reset tokens in the API
    # response instead of e-mailing them (no mail service is configured).
    # Refused outside environment="development".
    dev_mode: bool = False
    # Billing: "disabled" (default) or "sandbox". There is no live mode: real
    # money collection is not implemented and is refused.
    billing_mode: str = "disabled"
    billing_webhook_secret: str = ""
    login_max_failures: int = 5
    login_window_seconds: int = 900
    # Rate limits for unauthenticated endpoints: (max events, window seconds).
    register_per_ip: tuple[int, int] = (5, 3600)
    reset_per_email: tuple[int, int] = (3, 3600)
    reset_per_ip: tuple[int, int] = (10, 3600)
    token_attempts_per_ip: tuple[int, int] = (20, 900)
    max_upload_bytes: int = 2_000_000

    def validate(self) -> Config:
        if self.environment not in ENVIRONMENTS:
            raise ConfigError(f"unknown environment {self.environment!r}")
        if self.environment != "development":
            if self.dev_mode:
                raise ConfigError("GHAZI_PLATFORM_DEV is only allowed with GHAZI_PLATFORM_ENV=development")
            if not self.secure_cookies:
                raise ConfigError("insecure cookies are only allowed with GHAZI_PLATFORM_ENV=development")
        if self.billing_mode not in ("disabled", "sandbox"):
            raise ConfigError("billing_mode must be 'disabled' or 'sandbox'; there is no live mode")
        if self.billing_mode == "sandbox" and len(self.billing_webhook_secret) < 16:
            raise ConfigError("sandbox billing needs a webhook secret of at least 16 characters")
        return self

    @classmethod
    def from_env(cls, **overrides: object) -> Config:
        values: dict[str, object] = {
            "enabled": _flag("GHAZI_PLATFORM_ENABLED"),
            "environment": (os.getenv("GHAZI_PLATFORM_ENV") or "production").strip().lower(),
            "db_path": os.getenv("GHAZI_PLATFORM_DB", cls.db_path),
            "secure_cookies": not _flag("GHAZI_PLATFORM_INSECURE_COOKIES"),
            "dev_mode": _flag("GHAZI_PLATFORM_DEV"),
            "billing_mode": (os.getenv("GHAZI_PLATFORM_BILLING_MODE") or "disabled").strip().lower(),
            "billing_webhook_secret": os.getenv("GHAZI_PLATFORM_BILLING_WEBHOOK_SECRET", ""),
        }
        values.update(overrides)
        if values["billing_mode"] not in {"disabled", "sandbox"}:
            # "live" or anything unknown fails closed.
            values["billing_mode"] = "disabled"
        return cls(**values).validate()  # type: ignore[arg-type]
