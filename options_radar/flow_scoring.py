from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd

from . import scoring

_ORIGINAL_SCORE_CHAIN = scoring.score_chain
_INSTALLED = False


def score_chain_with_ask_spread(
    chain: pd.DataFrame,
    technical: Any,
    regime: str,
    settings: Any,
    external_catalyst: dict | None = None,
) -> pd.DataFrame:
    """Run legacy scoring while preserving the Phase 5 ask-based spread gate.

    Legacy scoring uses spread/mid internally. For a configured ask-based limit r,
    the mathematically equivalent mid-based limit is 2r/(2-r). The returned public
    field is then restored to the required (ask-bid)/ask definition.
    """
    ask_limit = float(getattr(settings, "max_spread_pct", 0.15))
    raw_mid_equivalent = (2.0 * ask_limit) / max(2.0 - ask_limit, 1e-9)
    # Move by one representable float only. This admits the exact mathematical
    # boundary without widening the economic 15% ask-based threshold.
    mid_equivalent = float(np.nextafter(raw_mid_equivalent, np.inf))
    scoring_settings = replace(settings, max_spread_pct=mid_equivalent)
    result = _ORIGINAL_SCORE_CHAIN(
        chain,
        technical,
        regime,
        scoring_settings,
        external_catalyst,
    )
    if result is None or result.empty:
        return result
    out = result.copy()
    bid = pd.to_numeric(out.get("bid"), errors="coerce")
    ask = pd.to_numeric(out.get("ask"), errors="coerce")
    out["spread_pct"] = (
        (ask - bid) / ask.replace(0, np.nan)
    ).replace([np.inf, -np.inf], np.nan)
    return out


def install_ask_spread_scoring() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    scoring.score_chain = score_chain_with_ask_spread
    _INSTALLED = True
