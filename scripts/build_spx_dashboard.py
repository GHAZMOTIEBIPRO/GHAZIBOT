"""SPX dashboard snapshot (moved out of the workflow's inline script).

The snapshot's only price input is Yahoo's ^GSPC/^VIX bars and its gamma
input is the community GEX feeds; both are behind source permission gates.
With a gate closed the file becomes an explicit blocked report, so the SPX
page shows why it has no data instead of an old spot price.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from options_radar.source_permissions import allowed, block_record, require


def blocked_snapshot(now: datetime) -> dict:
    block = block_record("yahoo")
    return {
        "generated_at": now.isoformat(),
        **block,
        "spot": None,
        "price_source": None,
        "gamma_source": None,
        "research_only": True,
        "trade_map": {"version": "SPX_TRADE_MAP_V1", "state": "DATA_UNAVAILABLE",
                      "reason_ar": block["reason_ar"]},
    }


def live_snapshot(now: datetime) -> dict:
    require("yahoo")
    import pandas as pd
    import yfinance as yf

    from options_radar.spx_decision import build_spx_trade_map
    from options_radar.spx_external_gamma import build_spx_external_context

    idx = yf.download("^GSPC", period="1d", interval="5m", progress=False, auto_adjust=False, prepost=False)
    if idx.empty:
        raise SystemExit("SPX price unavailable")
    if isinstance(idx.columns, pd.MultiIndex):
        idx.columns = idx.columns.get_level_values(0)
    idx = idx.dropna(subset=["Close"])
    close = idx["Close"].astype(float)
    vol = idx.get("Volume", pd.Series(index=idx.index, dtype=float)).fillna(0).astype(float)
    opening = idx.head(min(6, len(idx)))
    opening_high = float(opening["High"].astype(float).max()) if "High" in opening and not opening.empty else None
    opening_low = float(opening["Low"].astype(float).min()) if "Low" in opening and not opening.empty else None
    vwap = float((close * vol).sum() / vol.sum()) if vol.sum() > 0 else None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    raw_rsi = 100 - (100 / (1 + gain / loss.replace(0, float("nan"))))
    rsi = float(raw_rsi.iloc[-1]) if math.isfinite(float(raw_rsi.iloc[-1])) else None
    spot, prev = float(close.iloc[-1]), float(close.iloc[0])
    gamma = (build_spx_external_context().get("daily_gamma") or {}) if allowed("community_gex") else {}
    bar_time = close.index[-1]
    if getattr(bar_time, "tzinfo", None) is None:
        raise SystemExit("SPX bar timezone unavailable")
    payload = {
        "generated_at": now.isoformat(), "spot": spot, "change_pct": (spot / prev - 1) * 100 if prev else None,
        "vwap": vwap, "vwap_method": "provider_volume_weighted_close" if vwap is not None else "unavailable",
        "research_only": True, "rsi": rsi, "vix": None, "price_source": "yahoo/yfinance ^GSPC",
        "gamma_source": gamma.get("source"), "zero_gamma_flip": gamma.get("zero_gamma_flip"),
        "call_wall": gamma.get("call_wall"), "put_wall": gamma.get("put_wall"),
        "net_gex_dollars": gamma.get("net_gex_dollars"), "gamma_regime": gamma.get("gamma_regime"),
        "opening_range_high": opening_high, "opening_range_low": opening_low,
        "age_minutes": (now - bar_time.to_pydatetime()).total_seconds() / 60,
        "market_bar_time": bar_time.isoformat(),
    }
    vix = yf.download("^VIX", period="1d", interval="5m", progress=False, auto_adjust=False, prepost=False)
    if not vix.empty:
        if isinstance(vix.columns, pd.MultiIndex):
            vix.columns = vix.columns.get_level_values(0)
        payload["vix"] = float(vix["Close"].dropna().iloc[-1])
    payload["trade_map"] = build_spx_trade_map(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    payload = live_snapshot(now) if allowed("yahoo") else blocked_snapshot(now)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("SPX dashboard:", payload.get("status") or "PUBLISHED", payload.get("generated_at"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
