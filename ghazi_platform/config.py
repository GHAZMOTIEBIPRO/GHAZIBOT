"""Runtime settings, read from the environment once per app instance."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    # The whole platform answers 404 unless this is on (feature flag).
    enabled: bool = False
    db_path: str = str(ROOT / "var" / "platform.sqlite3")
    # Published research artifacts the platform may read (never writes).
    public_data_dir: Path = ROOT / "public" / "data"
    source_rights_path: Path = ROOT / "data" / "source_rights.json"
    ui_dir: Path = ROOT / "platform_ui"
    # Cookies carry Secure unless explicitly running on plain-http localhost.
    secure_cookies: bool = True
    session_hours: int = 72
    # Development mode exposes one-time verification / reset tokens in the API
    # response instead of e-mailing them (no mail service is configured).
    dev_mode: bool = False
    # Billing: "disabled" (default) or "sandbox". There is no live mode: real
    # money collection is not implemented and is refused.
    billing_mode: str = "disabled"
    billing_webhook_secret: str = ""
    # E-mails listed here become admins when they register (owner bootstrap).
    admin_emails: frozenset[str] = field(default_factory=frozenset)
    login_max_failures: int = 5
    login_window_seconds: int = 900
    max_upload_bytes: int = 2_000_000

    @classmethod
    def from_env(cls, **overrides: object) -> Config:
        values: dict[str, object] = {
            "enabled": _flag("GHAZI_PLATFORM_ENABLED"),
            "db_path": os.getenv("GHAZI_PLATFORM_DB", cls.db_path),
            "secure_cookies": not _flag("GHAZI_PLATFORM_INSECURE_COOKIES"),
            "dev_mode": _flag("GHAZI_PLATFORM_DEV"),
            "billing_mode": (os.getenv("GHAZI_PLATFORM_BILLING_MODE") or "disabled").strip().lower(),
            "billing_webhook_secret": os.getenv("GHAZI_PLATFORM_BILLING_WEBHOOK_SECRET", ""),
            "admin_emails": frozenset(e.strip().lower() for e in os.getenv("GHAZI_PLATFORM_ADMIN_EMAILS", "").split(",")
                                      if e.strip()),
        }
        values.update(overrides)
        if values["billing_mode"] not in {"disabled", "sandbox"}:
            # "live" or anything unknown fails closed.
            values["billing_mode"] = "disabled"
        return cls(**values)  # type: ignore[arg-type]
