from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric, got {raw!r}") from exc


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean, got {raw!r}")


@dataclass(frozen=True)
class Settings:
    provider: str = (os.getenv("OPTIONS_PROVIDER") or "auto").strip().lower()
    marketdata_token: str | None = os.getenv("MARKETDATA_TOKEN") or None
    tradier_token: str | None = os.getenv("TRADIER_TOKEN") or None
    tradier_base_url: str = (
        os.getenv("TRADIER_BASE_URL") or "https://sandbox.tradier.com"
    ).rstrip("/")
    alpaca_api_key: str | None = os.getenv("ALPACA_API_KEY") or None
    alpaca_secret_key: str | None = os.getenv("ALPACA_SECRET_KEY") or None
    alpaca_options_feed: str = os.getenv("ALPACA_OPTIONS_FEED") or "indicative"
    telegram_bot_token: str | None = os.getenv("TELEGRAM_BOT_TOKEN") or None
    telegram_chat_id: str | None = os.getenv("TELEGRAM_CHAT_ID") or None
    discord_webhook_url: str | None = os.getenv("DISCORD_WEBHOOK_URL") or None
    sec_user_agent: str = (
        os.getenv("SEC_USER_AGENT")
        or "GHAZI Options Radar (configure SEC_USER_AGENT)"
    )
    openfda_api_key: str | None = os.getenv("OPENFDA_API_KEY") or None
    smtp_host: str = os.getenv("SMTP_HOST") or "smtp.gmail.com"
    smtp_port: int = _env_int("SMTP_PORT", 587)
    smtp_user: str | None = os.getenv("SMTP_USER") or None
    smtp_password: str | None = os.getenv("SMTP_PASSWORD") or None
    report_email_to: str | None = os.getenv("REPORT_EMAIL_TO") or None
    risk_free_rate: float = _env_float("RISK_FREE_RATE", 0.043)

    # Free data is better suited to swing setups than low-latency 0DTE trading.
    free_swing_mode: bool = _env_bool("FREE_SWING_MODE", True)
    min_dte: int = _env_int("MIN_DTE", 14)
    max_dte: int = _env_int("MAX_DTE", 60)
    min_option_volume: int = _env_int("MIN_OPTION_VOLUME", 50)
    min_open_interest: int = _env_int("MIN_OPEN_INTEREST", 100)
    max_spread_pct: float = _env_float("MAX_SPREAD_PCT", 0.20)
    min_abs_delta: float = _env_float("MIN_ABS_DELTA", 0.30)
    max_abs_delta: float = _env_float("MAX_ABS_DELTA", 0.60)
    min_option_price: float = _env_float("MIN_OPTION_PRICE", 0.25)
    max_option_price: float = _env_float("MAX_OPTION_PRICE", 30.0)
    min_data_quality: float = _env_float("MIN_DATA_QUALITY", 0.50)
    max_last_trade_age_minutes: int = _env_int(
        "MAX_LAST_TRADE_AGE_MINUTES", 7 * 24 * 60
    )

    min_score: float = _env_float("MIN_SCORE", 65.0)
    alert_score: float = _env_float("ALERT_SCORE", 76.0)
    alert_vol_oi: float = _env_float("ALERT_VOL_OI", 2.0)
    max_workers: int = _env_int("MAX_WORKERS", 4)
    max_universe_size: int = _env_int("MAX_UNIVERSE_SIZE", 150)
    calibration_minimum_sample: int = _env_int("CALIBRATION_MINIMUM_SAMPLE", 100)
    model_version: str = os.getenv("MODEL_VERSION") or "2026.07-phase2"

    # JSON is persisted by GitHub Actions across isolated runners.
    database_path: Path = Path(
        os.getenv("DATABASE_PATH", "data/live/alert_state.json")
    )
    signal_journal_path: Path = Path(
        os.getenv("SIGNAL_JOURNAL_PATH", "data/live/signals.jsonl")
    )
    outcome_path: Path = Path(
        os.getenv("OUTCOME_PATH", "data/live/outcomes.json")
    )
    calibration_path: Path = Path(
        os.getenv("CALIBRATION_PATH", "data/live/calibration.json")
    )

    def validate(self) -> None:
        if self.provider not in {"auto", "yahoo", "marketdata", "tradier"}:
            raise ValueError(
                "OPTIONS_PROVIDER must be one of auto, yahoo, marketdata, tradier"
            )
        if self.min_dte < 0 or self.max_dte < self.min_dte:
            raise ValueError("Invalid DTE range")
        if not 0 < self.max_spread_pct <= 1:
            raise ValueError("MAX_SPREAD_PCT must be between 0 and 1")
        if not 0 <= self.min_abs_delta <= self.max_abs_delta <= 1:
            raise ValueError("Invalid delta range")
        if not 0 <= self.min_data_quality <= 1:
            raise ValueError("MIN_DATA_QUALITY must be between 0 and 1")
        if self.min_option_price <= 0 or self.max_option_price <= self.min_option_price:
            raise ValueError("Invalid option price range")
        if self.max_last_trade_age_minutes <= 0:
            raise ValueError("MAX_LAST_TRADE_AGE_MINUTES must be positive")
        if self.max_universe_size < 20:
            raise ValueError("MAX_UNIVERSE_SIZE must be at least 20")
        if self.calibration_minimum_sample < 30:
            raise ValueError("CALIBRATION_MINIMUM_SAMPLE must be at least 30")
