"""Implied forward from put-call parity on one expiry (research; never shown as the cash index).

For European index options (SPX/SPXW, NDX/NDXP) at strike K and expiry T:
    C - P = DF x (F - K)   =>   F = K + (C - P) / DF,   DF = exp(-r x T)
F is the market's FORWARD for that expiry. It differs from the cash index by carry (rates minus
dividends to T) and inherits the quotes' quality. With indicative (non-OPRA) quotes it is a
reference level for research and context only - not SPX, not NDX, not executable.

Quality gates (fail closed):
- both legs two-sided (0 < bid <= ask), relative spread <= MAX_REL_SPREAD of the mid;
- both quotes no older than MAX_AGE_S before the newest quote in the snapshot;
- the strikes used are the N nearest to where |C - P| is smallest (near the money);
- at least MIN_STRIKES strikes, cross-strike dispersion (MAD) reported in basis points; above
  MAX_DISPERSION_BP the estimate is labelled LOW_QUALITY.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from statistics import median
from typing import Any

OCC = re.compile(r"^(?P<root>[A-Z]{1,6})(?P<ymd>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")
MAX_REL_SPREAD = 0.15
MAX_AGE_S = 120.0
NEAREST = 7
MIN_STRIKES = 3
MAX_DISPERSION_BP = 5.0


def parse_occ(symbol: str) -> dict[str, Any] | None:
    m = OCC.match(str(symbol).replace(" ", ""))
    if not m:
        return None
    ymd = m.group("ymd")
    return {"root": m.group("root"), "expiry": date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:])),
            "type": m.group("cp"), "strike": int(m.group("strike")) / 1000}


def _quote(snap: dict[str, Any]) -> tuple[float, float, datetime] | None:
    q = snap.get("latestQuote") or {}
    try:
        bid, ask = float(q["bp"]), float(q["ap"])
        stamp = datetime.fromisoformat(str(q["t"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 < bid <= ask) or stamp.tzinfo is None:
        return None
    mid = (bid + ask) / 2
    return (mid, (ask - bid) / mid, stamp) if mid > 0 else None


def implied_forward(snapshots: dict[str, dict[str, Any]], *, root: str, expiry: date, years_to_expiry: float,
                    rate: float = 0.0) -> dict[str, Any]:
    """Implied forward for one root/expiry from a chain snapshot; statuses explain any refusal."""
    base = {"type": "IMPLIED_FORWARD_FROM_PUT_CALL_PARITY", "is_cash_index": False, "root": root,
            "expiry": expiry.isoformat(), "rate_used": rate}
    legs: dict[float, dict[str, tuple[float, float, datetime]]] = {}
    for symbol, snap in (snapshots or {}).items():
        occ = parse_occ(symbol)
        if not occ or occ["root"] != root or occ["expiry"] != expiry or not isinstance(snap, dict):
            continue
        q = _quote(snap)
        if q:
            legs.setdefault(occ["strike"], {})[occ["type"]] = q
    pairs = {k: v for k, v in legs.items() if "C" in v and "P" in v}
    if not pairs:
        return {**base, "status": "NO_PAIRED_QUOTES", "strikes_used": 0}
    newest = max(q[2] for v in pairs.values() for q in v.values())
    fresh = {k: v for k, v in pairs.items()
             if all((newest - q[2]).total_seconds() <= MAX_AGE_S and q[1] <= MAX_REL_SPREAD for q in v.values())}
    if len(fresh) < MIN_STRIKES:
        return {**base, "status": "TOO_FEW_VALID_STRIKES", "strikes_used": len(fresh), "paired": len(pairs)}
    atm = min(fresh, key=lambda k: abs(fresh[k]["C"][0] - fresh[k]["P"][0]))
    near = sorted(fresh, key=lambda k: abs(k - atm))[:NEAREST]
    df = math.exp(-rate * max(years_to_expiry, 0.0))
    estimates = [k + (fresh[k]["C"][0] - fresh[k]["P"][0]) / df for k in near]
    forward = median(estimates)
    mad = median(abs(e - forward) for e in estimates)
    half_spread = median((fresh[k]["C"][1] * fresh[k]["C"][0] + fresh[k]["P"][1] * fresh[k]["P"][0]) / 2 for k in near)
    dispersion_bp = mad / forward * 1e4
    return {**base, "status": "OK" if dispersion_bp <= MAX_DISPERSION_BP else "LOW_QUALITY",
            "forward": round(forward, 2), "strikes_used": len(near), "paired": len(pairs),
            "dispersion_bp": round(dispersion_bp, 2), "half_spread_bp": round(half_spread / forward * 1e4, 2),
            "quotes_as_of": newest.isoformat(),
            "max_quote_age_s": round(max((newest - q[2]).total_seconds() for k in near for q in fresh[k].values()), 1)}


def public_metrics(result: dict[str, Any]) -> dict[str, Any]:
    """The quality metrics without the level itself (what may appear in a public log)."""
    return {k: v for k, v in result.items() if k != "forward"}
