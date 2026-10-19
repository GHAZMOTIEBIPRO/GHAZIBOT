"""Historical option-bar observations; absence of bid/ask forbids P&L claims."""
from __future__ import annotations

import math
import re
from typing import Any

OCC = re.compile(r"^O:[A-Z]{1,6}\d{6}[CP]\d{8}$")


def describe_option_path(contract: str, bars: Any, *, entry_date: str,
                         end_date: str) -> dict:
    base = {
        "contract": contract if isinstance(contract, str) and OCC.fullmatch(contract) else None,
        "research_only": True,
        "execution_eligible": False,
        "opra_execution_quotes_verified": False,
        "realized_pnl": None,
        "win_rate": None,
        "fill_price": None,
        "bid_ask_spread_verified": False,
        "sample_days": 0,
        "observed_close_change_pct": None,
        "status": "UNAVAILABLE",
    }
    if base["contract"] is None or not isinstance(bars, list):
        return base
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry_date or ""):
        return base
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end_date or "") or end_date <= entry_date:
        return base
    eligible = []
    for row in bars:
        if not isinstance(row, dict):
            continue
        day,close=row.get("date"),row.get("close")
        if (isinstance(day, str) and entry_date <= day <= end_date
                and type(close) in (int, float) and math.isfinite(close) and close > 0):
            eligible.append((day, float(close)))
    selected = sorted(dict(eligible).items())
    if (len(selected) < 2 or selected[0][0] != entry_date
            or selected[-1][0] != end_date):
        return base
    # Only day-end comparisons. OHLC trade bars do not supply execution NBBO.
    result = round((selected[-1][1] / selected[0][1] - 1) * 100, 2)
    return {**base, "status": "HISTORICAL_CLOSE_OBSERVATION",
            "sample_days": len(selected),
            "observed_close_change_pct": result}
