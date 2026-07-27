from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .market_bars import configured_bar_sources
from .settings import Settings

SEC_EFTS_STATUS = Path("data/cache/sec_efts_status.json")


@dataclass(frozen=True)
class ServiceStatus:
    name: str
    configured: bool
    required_fields: tuple[str, ...]
    note: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_fields"] = list(self.required_fields)
        return payload


def _read_sec_efts_status() -> dict[str, Any]:
    if not SEC_EFTS_STATUS.exists():
        return {
            "available": False,
            "event_count": 0,
            "message": "No SEC full-text health check has been published yet.",
        }
    try:
        payload = json.loads(SEC_EFTS_STATUS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "available": False,
            "event_count": 0,
            "message": f"SEC full-text status file is invalid: {exc}",
        }
    return payload if isinstance(payload, dict) else {}


def build_operational_status(settings: Settings) -> dict[str, Any]:
    """Return a public, credential-free status report for the dashboard workflow."""

    provider = settings.provider
    provider_ready = True
    provider_note = "Yahoo fallback is available; option data may be delayed or unofficial."
    provider_required: tuple[str, ...] = ()
    if provider == "marketdata":
        provider_ready = bool(settings.marketdata_token)
        provider_required = ("MARKETDATA_TOKEN",)
        provider_note = "MarketData.app token is required for the selected provider."
    elif provider == "tradier":
        provider_ready = bool(settings.tradier_token)
        provider_required = ("TRADIER_TOKEN", "TRADIER_BASE_URL")
        provider_note = "Tradier credentials are required; sandbox data is delayed."
    elif provider == "auto":
        provider_note = (
            "Auto mode merges configured Tradier and MarketData option chains and fills "
            "missing fields from Yahoo; Alpaca can enrich quotes and Greeks."
        )

    sec_ready = "configure SEC_USER_AGENT" not in settings.sec_user_agent
    sec_fulltext = _read_sec_efts_status()
    sec_fulltext_ready = bool(sec_fulltext.get("available"))
    sec_fulltext_note = (
        f"SEC EFTS reachable; {int(sec_fulltext.get('event_count', 0) or 0)} matched events cached "
        f"for {sec_fulltext.get('start_date', '—')} to {sec_fulltext.get('end_date', '—')}."
        if sec_fulltext_ready
        else "SEC EFTS unavailable on the current runner; latest-form and cached evidence remain active. "
        + str(sec_fulltext.get("message", ""))[:300]
    )
    bars = configured_bar_sources(settings)
    configured_official_bars = [
        item["name"] for item in bars
        if item["configured"] and item["name"] != "yahoo"
    ]
    services = [
        ServiceStatus(
            name="options_data",
            configured=provider_ready,
            required_fields=provider_required,
            note=provider_note,
        ),
        ServiceStatus(
            name="hybrid_price_bars",
            configured=True,
            required_fields=(),
            note=(
                "Configured official/free-account bar sources: "
                + (", ".join(configured_official_bars) if configured_official_bars else "none; Yahoo fallback active")
                + ". Intraday path tracking uses the first successful provider."
            ),
        ),
        ServiceStatus(
            name="path_order_tracking",
            configured=True,
            required_fields=(),
            note=(
                "Five-minute underlying OHLC bars record target-first, stop-first, or "
                "ambiguous same-bar outcomes."
            ),
        ),
        ServiceStatus(
            name="sec_full_text_search",
            configured=sec_fulltext_ready,
            required_fields=(),
            note=sec_fulltext_note,
        ),
        ServiceStatus(
            name="sec_identity",
            configured=sec_ready,
            required_fields=("SEC_USER_AGENT",),
            note="SEC automated access uses a descriptive User-Agent and fair-access limits.",
        ),
        ServiceStatus(
            name="sec_company_facts",
            configured=sec_ready,
            required_fields=("SEC_USER_AGENT",),
            note=(
                "Official SEC XBRL Company Facts are attempted first; an explicitly labelled "
                "unofficial financial-statement fallback is used when the runner is blocked."
            ),
        ),
        ServiceStatus(
            name="treasury_yield_curve",
            configured=True,
            required_fields=(),
            note="Official U.S. Treasury XML feed supplies 3m, 2y, 10y and 30y yields without an API key.",
        ),
        ServiceStatus(
            name="fred_macro",
            configured=bool(settings.fred_api_key),
            required_fields=("FRED_API_KEY",),
            note=(
                "FRED VIX close and effective federal funds rate are enabled."
                if settings.fred_api_key
                else "Optional free FRED key not configured; Treasury macro data remains active."
            ),
        ),
        ServiceStatus(
            name="openfda",
            configured=True,
            required_fields=(),
            note=(
                "openFDA works without a key within the public limit; a free key is optional."
                if not settings.openfda_api_key
                else "openFDA free API key configured."
            ),
        ),
        ServiceStatus(
            name="evidence_journal",
            configured=True,
            required_fields=(),
            note="Signals, observations and calibration evidence are persisted by GitHub Actions.",
        ),
    ]

    return {
        "dashboard_only": True,
        "ready_for_paper_tracking": provider_ready and sec_ready,
        "external_notifications_enabled": False,
        "bar_sources": bars,
        "daily_provider_order": settings.daily_provider_order,
        "intraday_provider_order": settings.intraday_provider_order,
        "services": [item.to_dict() for item in services],
        "sec_fulltext_status": sec_fulltext,
        "configuration_warnings": [
            field
            for item in services
            if not item.configured and item.name not in {"fred_macro", "sec_full_text_search"}
            for field in item.required_fields
        ],
        "operation_note": (
            "The project publishes only to the dashboard and GitHub evidence journal. "
            "External message delivery and automated order execution are disabled."
        ),
    }
