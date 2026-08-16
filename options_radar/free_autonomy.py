from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import MutableMapping


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
    """Force the bot's autonomous runtime onto zero-cost data feeds.

    This guard intentionally does not pretend that free indicative option data is
    OPRA or execution-grade.  Existing provider-readiness gates remain responsible
    for deciding whether a contract may be promoted to a production alert.

    The guard is deliberately environment-level so it runs *before* Settings and
    data clients are created.  A stale repository secret that says SIP/OPRA cannot
    silently turn the autonomous path into a paid dependency.
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
            # Alpaca Basic options are indicative.  OPRA remains a paid upgrade
            # and must never be required by the autonomous free path.
            "ALPACA_OPTIONS_FEED": "indicative",
        }
        for key, value in forced.items():
            previous = str(target.get(key) or "").strip().lower()
            if previous != value:
                overrides.append(f"{key}:{previous or '<unset>'}->{value}")
            target[key] = value

    stock_feed = str(target.get("ALPACA_STOCK_FEED") or "iex").strip().lower()
    option_feed = str(target.get("ALPACA_OPTIONS_FEED") or "indicative").strip().lower()

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
        option_stream_grade=("context_only" if option_feed == "indicative" else "entitlement_dependent"),
        persistent_host_required=False,
        execution_model="scheduled_repository_automation_with_automatic_fallbacks",
        overrides=tuple(overrides),
    )


def free_autonomy_enabled(env: MutableMapping[str, str] | None = None) -> bool:
    target = env if env is not None else os.environ
    return _truthy(target.get("FREE_AUTONOMY_MODE"), default=True)
