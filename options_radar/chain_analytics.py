"""Derived analytics from Cboe's public delayed option chain JSON.

Only derived values are published (expected move, ATM IV, skew, term
structure, open-interest concentration, liquidity screen). Raw bid/ask/last
prices are not republished. Every value carries its data class:
- DELAYED_QUOTE: from delayed bid/ask (expected move, spread %)
- PROVIDER_MODEL: Cboe's own IV / delta (delayed)
- HISTORICAL: open interest (prior session)
Nothing here is executable, and nothing is a probability.
"""
from __future__ import annotations

import json
import math
import urllib.request
from datetime import date, datetime, timezone
from typing import Any

from .ghazi_gex_multi import parse_occ

CBOE_CHAIN = "https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json"
INDEX_ROOTS = {"SPX": "_SPX", "NDX": "_NDX", "RUT": "_RUT", "VIX": "_VIX"}
UA = "GHAZI-Black-Box/1.0"
MAX_SPREAD_PCT = 10.0
MIN_OI = 100


def fetch_chain(symbol: str, timeout: int = 20) -> dict[str, Any]:
    code = INDEX_ROOTS.get(symbol.upper(), symbol.upper())
    req = urllib.request.Request(CBOE_CHAIN.format(symbol=code), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _f(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rows(payload: dict[str, Any], today: date) -> tuple[float | None, list[dict[str, Any]]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None, []
    spot = _f(data.get("current_price"))
    rows = []
    for x in data.get("options") or []:
        if not isinstance(x, dict):
            continue
        occ = parse_occ(x.get("option"))
        if not occ:
            continue
        expiry = date.fromisoformat(occ["expiry"])
        if expiry < today:
            continue
        bid, ask = _f(x.get("bid")), _f(x.get("ask"))
        two_sided = bid is not None and ask is not None and bid > 0 and ask >= bid
        mid = (bid + ask) / 2 if two_sided else None
        iv = _f(x.get("iv"))
        rows.append({
            "root": occ["root"], "expiry": occ["expiry"], "dte": (expiry - today).days,
            "type": occ["type"], "strike": occ["strike"], "mid": mid,
            "spread_pct": round((ask - bid) / mid * 100, 2) if mid else None,
            "iv": iv if iv and iv > 0 else None, "delta": _f(x.get("delta")),
            "oi": _f(x.get("open_interest")) or 0.0, "volume": _f(x.get("volume")) or 0.0,
        })
    return spot, rows


def _atm(rows: list[dict[str, Any]], spot: float, expiry: str) -> tuple[dict | None, dict | None]:
    same = [r for r in rows if r["expiry"] == expiry]
    if not same:
        return None, None
    strike = min({r["strike"] for r in same}, key=lambda k: abs(k - spot))
    call = next((r for r in same if r["strike"] == strike and r["type"] == "call"), None)
    put = next((r for r in same if r["strike"] == strike and r["type"] == "put"), None)
    return call, put


def _nearest_delta(rows: list[dict[str, Any]], expiry: str, target: float) -> dict | None:
    pool = [r for r in rows if r["expiry"] == expiry and r["delta"] is not None and r["iv"]]
    return min(pool, key=lambda r: abs(r["delta"] - target), default=None)


def analyze(symbol: str, payload: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    today = now.astimezone(timezone.utc).date()
    spot, rows = _rows(payload, today)
    base = {"symbol": symbol, "source": "Cboe delayed public option chain",
            "provider_snapshot_time": payload.get("timestamp") if isinstance(payload, dict) else None,
            "execution_grade": False, "probability": None}
    if not spot or spot <= 0 or not rows:
        return {**base, "status": "DATA_UNAVAILABLE"}
    expiries = sorted({r["expiry"] for r in rows})
    front = next((e for e in expiries
                  if all(x is not None and x["mid"] for x in _atm(rows, spot, e))), None)
    expected = None
    if front:
        call, put = _atm(rows, spot, front)
        move = call["mid"] + put["mid"]
        expected = {"expiry": front, "dte": call["dte"], "atm_strike": call["strike"],
                    "move_abs": round(move, 2), "move_pct": round(move / spot * 100, 2),
                    "range_low": round(spot - move, 2), "range_high": round(spot + move, 2),
                    "data_class": "DELAYED_QUOTE", "method": "ATM straddle mid"}
    term = []
    for expiry in expiries[:6]:
        call, put = _atm(rows, spot, expiry)
        ivs = [x["iv"] for x in (call, put) if x and x["iv"]]
        if ivs:
            term.append({"expiry": expiry, "atm_iv": round(sum(ivs) / len(ivs), 4)})
    skew = None
    if front:
        p25, c25 = _nearest_delta(rows, front, -0.25), _nearest_delta(rows, front, 0.25)
        if p25 and c25:
            skew = {"expiry": front, "put25_iv": round(p25["iv"], 4), "call25_iv": round(c25["iv"], 4),
                    "put_minus_call": round(p25["iv"] - c25["iv"], 4), "data_class": "PROVIDER_MODEL"}
    window = [r for r in rows if r["expiry"] in expiries[:4]]
    oi_levels = {
        side: [{"strike": k, "oi": int(v)} for k, v in sorted(
            _sum_by_strike(window, side).items(), key=lambda kv: kv[1], reverse=True)[:3]]
        for side in ("call", "put")}
    call_vol = sum(r["volume"] for r in window if r["type"] == "call")
    put_vol = sum(r["volume"] for r in window if r["type"] == "put")
    screen = {side: [
        {"expiry": r["expiry"], "dte": r["dte"], "strike": r["strike"], "delta": round(r["delta"], 2),
         "spread_pct": r["spread_pct"], "oi": int(r["oi"]), "volume": int(r["volume"])}
        for r in sorted((r for r in rows if r["type"] == side and r["delta"] is not None
                         and 0.30 <= abs(r["delta"]) <= 0.60 and 1 <= r["dte"] <= 45
                         and r["spread_pct"] is not None and r["spread_pct"] <= MAX_SPREAD_PCT
                         and r["oi"] >= MIN_OI and r["volume"] > 0),
                        key=lambda r: (r["spread_pct"], -r["oi"]))[:3]]
        for side in ("call", "put")}
    return {
        **base, "status": "OK", "spot_delayed": spot,
        "expected_move": expected, "atm_iv_term": term, "skew_25d": skew,
        "oi_concentration": {**oi_levels, "data_class": "HISTORICAL", "expirations": expiries[:4]},
        "put_call_volume_ratio": round(put_vol / call_vol, 3) if call_vol else None,
        "liquid_contract_screen": {**screen, "rule": f"|delta| 0.30-0.60, 1-45 DTE, spread <= {MAX_SPREAD_PCT}%, "
                                   f"OI >= {MIN_OI}, volume > 0; delayed quotes, not executable"},
        "contracts_seen": len(rows),
    }


def _sum_by_strike(rows: list[dict[str, Any]], side: str) -> dict[float, float]:
    out: dict[float, float] = {}
    for r in rows:
        if r["type"] == side:
            out[r["strike"]] = out.get(r["strike"], 0.0) + r["oi"]
    return out
