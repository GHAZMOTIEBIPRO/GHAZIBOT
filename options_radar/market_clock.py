from __future__ import annotations

# Canonical implementation lives outside the options_radar package so lightweight
# workflows (for example Telegram gating) can use it without triggering the
# package's heavy initialization side effects.
from market_runtime_clock import MarketClockState, market_clock_state

__all__ = ["MarketClockState", "market_clock_state"]
