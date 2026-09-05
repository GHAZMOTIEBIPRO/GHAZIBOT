from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import MutableMapping


TRADIER_LIVE_BASE_URL = "https://api.tradier.com"


@dataclass(frozen=True)
class FreeAutonomyStatus:
    enabled: bool
    paid_market_data_allowed: bool
    user_intervention_required: bool
    stock_stream_feed: str
    option_stream_feed: str
    option_stream_grade: str
    persistent_host_required: bool
    execution_model: str
    overrides: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["overrides"] = list(self.overrides)
        return payload


def _truthy(value: object, default: bool = True) -> bool:
    text = str(value if value is not None else "").strip().lower()
    if not text:
        return default
    return text not in {"0", "false", "no", "off"}


def enforce_free_autonomy_environment(
    env: MutableMapping[str, str] | None = None,
) -> FreeAutonomyStatus:
    """Force the autonomous runtime onto zero-cost market-data paths.

    Alpaca Basic remains the no-account fallback (IEX equities + indicative
    options). When a Tradier Brokerage production token is available, zero-cost
    mode prefers Tradier's production endpoint instead of the delayed sandbox.
    This never enables paid SIP/OPRA entitlements and existing provider-readiness
    gates still decide whether any quote is suitable for a production alert.

    Set ``TRADIER_LIVE_FREE_ENABLED=false`` to keep an explicitly configured
    Tradier sandbox endpoint for testing.
    """

    target = env if env is not None else os.environ
    enabled = _truthy(target.get("FREE_AUTONOMY_MODE"), default=True)
    overrides: list[str] = []

    if enabled:
        forced = {
            "FREE_AUTONOMY_MODE": "true",
            "PAID_MARKET_DATA_ALLOWED": "false",
            # Alpaca Basic: free equity stream is IEX; do not silently select SIP.
            "ALPACA_STOCK_FEED": "iex",
            # Alpaca Basic options are indicative. OPRA remains entitlement
            # dependent and must never be required by the autonomous free path.
            "ALPACA_OPTIONS_FEED": "indicative",
        }
        for key, value in forced.items():
            previous = str(target.get(key) or "").strip().lower()
            if previous != value:
                overrides.append(f"{key}:{previous or '<unset>'}->{value}")
            target[key] = value

        # Tradier's sandbox is delayed. A Brokerage production token can use the
        # real-time production endpoint without turning on a paid market-data
        # entitlement. The token itself is never inspected or logged.
        tradier_token = str(target.get("TRADIER_TOKEN") or "").strip()
        tradier_live_enabled = _truthy(
            target.get("TRADIER_LIVE_FREE_ENABLED"),
            default=True,
        )
        if tradier_token and tradier_live_enabled:
            previous_url = str(target.get("TRADIER_BASE_URL") or "").strip()
            if not previous_url or "sandbox.tradier.com" in previous_url.lower():
                if previous_url != TRADIER_LIVE_BASE_URL:
                    overrides.append(
                        "TRADIER_BASE_URL:"
                        f"{previous_url or '<unset>'}->{TRADIER_LIVE_BASE_URL}"
                    )
                target["TRADIER_BASE_URL"] = TRADIER_LIVE_BASE_URL

    stock_feed = str(target.get("ALPACA_STOCK_FEED") or "iex").strip().lower()
    option_feed = str(target.get("ALPACA_OPTIONS_FEED") or "indicative").strip().lower()
    tradier_token = str(target.get("TRADIER_TOKEN") or "").strip()
    tradier_base_url = str(target.get("TRADIER_BASE_URL") or "").strip().lower()
    tradier_live = bool(
        enabled
        and tradier_token
        and "api.tradier.com" in tradier_base_url
        and "sandbox" not in tradier_base_url
    )

    return FreeAutonomyStatus(
        enabled=enabled,
        paid_market_data_allowed=(
            _truthy(target.get("PAID_MARKET_DATA_ALLOWED"), default=False)
            if not enabled
            else False
        ),
        user_intervention_required=False,
        stock_stream_feed=stock_feed,
        option_stream_feed=option_feed,
        option_stream_grade=(
            "tradier_realtime_available"
            if tradier_live
            else ("context_only" if option_feed == "indicative" else "entitlement_dependent")
        ),
        persistent_host_required=False,
        execution_model=(
            "tradier_realtime_first_with_free_fallbacks"
            if tradier_live
            else "scheduled_repository_automation_with_automatic_fallbacks"
        ),
        overrides=tuple(overrides),
    )


def free_autonomy_enabled(env: MutableMapping[str, str] | None = None) -> bool:
    target = env if env is not None else os.environ
    return _truthy(target.get("FREE_AUTONOMY_MODE"), default=True)
