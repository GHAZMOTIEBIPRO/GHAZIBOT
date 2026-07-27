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
    # Legacy provider switch remains supported for Phase 4 callers.
    provider: str = (os.getenv("OPTIONS_PROVIDER") or "auto").strip().lower()
    marketdata_token: str | None = os.getenv("MARKETDATA_TOKEN") or None
    tradier_token: str | None = os.getenv("TRADIER_TOKEN") or None
    tradier_base_url: str = (
        os.getenv("TRADIER_BASE_URL") or "https://sandbox.tradier.com"
    ).rstrip("/")
    finnhub_api_key: str | None = os.getenv("FINNHUB_API_KEY") or None
    tiingo_api_key: str | None = os.getenv("TIINGO_API_KEY") or None
    alpaca_api_key: str | None = os.getenv("ALPACA_API_KEY") or None
    alpaca_secret_key: str | None = os.getenv("ALPACA_SECRET_KEY") or None
    alpaca_options_feed: str = os.getenv("ALPACA_OPTIONS_FEED") or "indicative"
    alpaca_stock_feed: str = os.getenv("ALPACA_STOCK_FEED") or "iex"

    # Phase 5 deterministic fallback orders.
    stock_provider_order: str = (
        os.getenv("STOCK_PROVIDER_ORDER") or "tiingo,finnhub,yahoo"
    )
    options_provider_order: str = (
        os.getenv("OPTIONS_PROVIDER_ORDER") or "tradier,finnhub,yahoo"
    )

    # Existing optional bar providers remain available to legacy market_bars.py.
    twelve_data_api_key: str | None = os.getenv("TWELVE_DATA_API_KEY") or None
    polygon_api_key: str | None = os.getenv("POLYGON_API_KEY") or None
    alpha_vantage_api_key: str | None = os.getenv("ALPHA_VANTAGE_API_KEY") or None
    fred_api_key: str | None = os.getenv("FRED_API_KEY") or None
    daily_provider_order: str = (
        os.getenv("DAILY_PRICE_PROVIDER_ORDER")
        or "yahoo,tradier,alpaca,twelve_data,polygon,alpha_vantage"
    )
    intraday_provider_order: str = (
        os.getenv("INTRADAY_PRICE_PROVIDER_ORDER")
        or "tradier,alpaca,twelve_data,polygon,yahoo,alpha_vantage"
    )

    sec_user_agent: str = (
        os.getenv("SEC_USER_AGENT")
        or "GHAZI Market Radar (configure SEC_USER_AGENT with contact email)"
    )
    sec_requests_per_second: float = _env_float("SEC_REQUESTS_PER_SECOND", 8.0)
    request_timeout_seconds: int = _env_int("REQUEST_TIMEOUT_SECONDS", 30)
    openfda_api_key: str | None = os.getenv("OPENFDA_API_KEY") or None
    risk_free_rate: float = _env_float("RISK_FREE_RATE", 0.043)

    # Free data is better suited to swing setups than low-latency 0DTE trading.
    free_swing_mode: bool = _env_bool("FREE_SWING_MODE", True)
    min_dte: int = _env_int("MIN_DTE", 14)
    max_dte: int = _env_int("MAX_DTE", 60)
    min_option_volume: int = _env_int("MIN_OPTION_VOLUME", 50)
    min_open_interest: int = _env_int("MIN_OPEN_INTEREST", 100)
    max_spread_pct: float = _env_float("MAX_SPREAD_PCT", 0.15)
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
    model_version: str = os.getenv("MODEL_VERSION") or "2026.07-phase5-hybrid"

    # Market-regime and path-dependency controls.
    vix_risk_off_threshold: float = _env_float("VIX_RISK_OFF_THRESHOLD", 25.0)
    vix_risk_on_threshold: float = _env_float("VIX_RISK_ON_THRESHOLD", 18.0)
    outcome_max_age_days: int = _env_int("OUTCOME_MAX_AGE_DAYS", 60)

    # JSON evidence is persisted by GitHub Actions across isolated runners.
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
        if not 0 < self.max_spread_pct <= 0.15:
            raise ValueError("MAX_SPREAD_PCT must be greater than 0 and no more than 0.15")
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
        if not 0 < self.sec_requests_per_second <= 10:
            raise ValueError("SEC_REQUESTS_PER_SECOND must be between 0 and 10")
        if self.request_timeout_seconds < 5:
            raise ValueError("REQUEST_TIMEOUT_SECONDS must be at least 5")
        if self.outcome_max_age_days < self.max_dte:
            raise ValueError("OUTCOME_MAX_AGE_DAYS must cover MAX_DTE")
        if self.vix_risk_on_threshold >= self.vix_risk_off_threshold:
            raise ValueError("VIX risk-on threshold must be below risk-off threshold")

        phase5_stock = {"tiingo", "finnhub", "yahoo", "yfinance"}
        phase5_options = {"tradier", "finnhub", "yahoo", "yfinance"}
        for field_name, raw, allowed in (
            ("STOCK_PROVIDER_ORDER", self.stock_provider_order, phase5_stock),
            ("OPTIONS_PROVIDER_ORDER", self.options_provider_order, phase5_options),
        ):
            unknown = [
                item.strip().lower()
                for item in raw.split(",")
                if item.strip().lower() not in allowed
            ]
            if unknown:
                raise ValueError(f"{field_name} contains unsupported providers: {unknown}")

        allowed_bar_sources = {
            "yahoo", "tradier", "alpaca", "twelve", "twelvedata", "twelve_data",
            "polygon", "alpha", "alphavantage", "alpha_vantage",
        }
        for field_name, raw in (
            ("DAILY_PRICE_PROVIDER_ORDER", self.daily_provider_order),
            ("INTRADAY_PRICE_PROVIDER_ORDER", self.intraday_provider_order),
        ):
            unknown = [
                item.strip().lower()
                for item in raw.split(",")
                if item.strip().lower() not in allowed_bar_sources
            ]
            if unknown:
                raise ValueError(f"{field_name} contains unsupported providers: {unknown}")
