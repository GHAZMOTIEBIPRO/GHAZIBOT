"""Alpaca option-chain snapshots -> contract rows for the existing scorers (options_radar.option_explosion).

Feed honesty: the owner's Basic plan returns the INDICATIVE feed - a free derivative of OPRA whose quotes
are not OPRA quotes and whose trades are delayed 15 minutes (Alpaca docs). Every row says so
(`feed = "indicative"`, `execution_grade = False`). Open interest comes from the Trading API contract
list and is the prior session's figure (`open_interest_date`); Vol/OI is context, never proof of opening
trades. Greeks/IV are Alpaca's own when present; when absent (index options) they stay None - nothing is
filled in. Snapshot volume is the day's indicative volume so far.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from options_radar.option_explosion import score_option_explosion
from options_radar.parity_reference import parse_occ

DTE_BUCKETS = (("0DTE", 0, 0), ("1DTE", 1, 1), ("2-7", 2, 7), ("8-30", 8, 30), ("31-60", 31, 60))
MAX_SPREAD = 0.25


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def rows(snapshots: dict[str, dict[str, Any]], *, today: date, open_interest: dict[str, dict[str, Any]] | None = None,
         underlying_price: float | None = None, rejects: dict[str, int] | None = None) -> list[dict[str, Any]]:
    out = []
    rejects = rejects if rejects is not None else {}

    def reject(reason: str) -> None:
        rejects[reason] = rejects.get(reason, 0) + 1

    for symbol, snap in (snapshots or {}).items():
        occ = parse_occ(symbol)
        if not occ or not isinstance(snap, dict):
            reject("unparsed_symbol")
            continue
        q, bar, g = snap.get("latestQuote") or {}, snap.get("dailyBar") or {}, snap.get("greeks") or {}
        bid, ask = _f(q.get("bp")), _f(q.get("ap"))
        if bid is None or ask is None:
            reject("no_quote")
            continue
        if bid <= 0:
            reject("zero_bid")
            continue
        if bid > ask:
            reject("crossed")
            continue
        mid = (bid + ask) / 2
        spread = (ask - bid) / mid
        oi_row = (open_interest or {}).get(symbol) or {}
        oi = _f(oi_row.get("open_interest"))
        volume = _f(bar.get("v")) or 0.0
        dte = (occ["expiry"] - today).days
        out.append({
            "contract": symbol, "root": occ["root"], "expiry": occ["expiry"].isoformat(), "dte": dte,
            "type": "CALL" if occ["type"] == "C" else "PUT", "strike": occ["strike"], "multiplier": 100,
            "bid": bid, "ask": ask, "mid": round(mid, 4), "spread_pct": round(spread, 4),
            "quote_time": q.get("t"), "volume": volume, "open_interest": oi,
            "open_interest_date": oi_row.get("open_interest_date"),
            "vol_to_oi_ratio": round(volume / oi, 3) if oi else None,
            "iv": _f(snap.get("impliedVolatility")), "delta": _f(g.get("delta")), "gamma": _f(g.get("gamma")),
            "theta": _f(g.get("theta")), "vega": _f(g.get("vega")),
            "moneyness": round(occ["strike"] / underlying_price - 1, 4) if underlying_price else None,
            "prev_close": _f((snap.get("prevDailyBar") or {}).get("c")),
            "feed": "indicative", "execution_grade": False,
        })
    return out


def strike_cluster(contract_rows: list[dict[str, Any]]) -> None:
    """Share of the same root/expiry/side volume traded at this strike and its two neighbours (0-100), in place."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in contract_rows:
        groups.setdefault((r["root"], r["expiry"], r["type"]), []).append(r)
    for group in groups.values():
        group.sort(key=lambda r: r["strike"])
        total = sum(r["volume"] for r in group) or 0.0
        for i, r in enumerate(group):
            near = sum(x["volume"] for x in group[max(0, i - 1):i + 2])
            r["strike_cluster_score"] = round(100 * near / total, 1) if total else 0.0


def bucket(dte: int) -> str | None:
    return next((name for name, lo, hi in DTE_BUCKETS if lo <= dte <= hi), None)


def rank(contract_rows: list[dict[str, Any]], *, per_bucket: int = 5, min_volume: float = 50) -> dict[str, list]:
    """Score with the existing option_explosion model; liquid two-sided contracts only, best per DTE bucket."""
    strike_cluster(contract_rows)
    ranked: dict[str, list[dict[str, Any]]] = {name: [] for name, _, _ in DTE_BUCKETS}
    for r in contract_rows:
        b = bucket(r["dte"])
        if b is None or r["volume"] < min_volume or r["spread_pct"] > MAX_SPREAD:
            continue
        scored = score_option_explosion(r)
        ranked[b].append({**r, "score": scored.get("score"), "profile": scored.get("profile"),
                          "label": scored.get("label"), "blockers": scored.get("blockers"),
                          "unavailable_inputs": scored.get("unavailable_inputs"),
                          "components": scored.get("components")})
    return {b: sorted(items, key=lambda r: -(r["score"] or 0))[:per_bucket] for b, items in ranked.items()}


def freshness(contract_rows: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """How old the newest quote is (seconds) - an indicative quote from the close is not 'live'."""
    stamps = []
    for r in contract_rows:
        try:
            stamps.append(datetime.fromisoformat(str(r["quote_time"]).replace("Z", "+00:00")))
        except ValueError:
            continue
    newest = max(stamps) if stamps else None
    return {"newest_quote": newest.isoformat() if newest else None,
            "age_s": round((now - newest).total_seconds(), 1) if newest else None}


CLASS_AR = {"EARLY_WATCH": "مراقبة مبكرة", "UNUSUAL_ACTIVITY": "نشاط غير اعتيادي",
            "CONFIRMED_BY_AVAILABLE_DATA": "مؤكد بالبيانات المتاحة", "EXTENDED": "ممتد (متأخر)", "REJECTED": "مرفوض"}


def classify(r: dict[str, Any], *, bucket_median_volume: float, underlying_change_pct: float | None,
             quote_age_s: float | None, in_session: bool) -> tuple[str, list[str]]:
    """One class per contract with its reasons. Observed activity only: buyer/seller intent is unknown."""
    reasons: list[str] = []
    if r["spread_pct"] > MAX_SPREAD:
        return "REJECTED", ["spread above 25 % of mid"]
    if in_session and (quote_age_s is None or quote_age_s > 900):
        return "REJECTED", ["quote older than 15 minutes in session"]
    if r.get("prev_close") and r["mid"] >= 2 * r["prev_close"]:
        return "EXTENDED", ["mid already >= 2x the prior close: the move has happened"]
    rel = r["volume"] / bucket_median_volume if bucket_median_volume else 0.0
    voi = r.get("vol_to_oi_ratio")
    unusual = (voi is not None and voi >= 1.5) or rel >= 5
    if unusual:
        reasons.append(f"Vol/OI {voi}" if voi is not None and voi >= 1.5 else f"volume {rel:.1f}x bucket median")
        direction = 1 if r["type"] == "CALL" else -1
        if (underlying_change_pct is not None and direction * underlying_change_pct > 0.3
                and r["spread_pct"] <= 0.10):
            return "CONFIRMED_BY_AVAILABLE_DATA", [*reasons, f"underlying {underlying_change_pct:+.2f}% in the same direction"]
        return "UNUSUAL_ACTIVITY", reasons
    if (voi is not None and voi >= 0.5) or rel >= 2:
        return "EARLY_WATCH", [f"Vol/OI {voi}" if voi is not None and voi >= 0.5 else f"volume {rel:.1f}x bucket median"]
    return "REJECTED", ["activity not above the bucket's normal level"]


def coverage(snapshots_by_underlying: dict[str, dict[str, Any]], kept: list[dict[str, Any]],
             rejects: dict[str, int], pages: dict[str, int]) -> dict[str, Any]:
    """What the scan really covered: unique contracts, roots, expiries, pages, two-sided share, rejects."""
    total = sum(len(v) for v in snapshots_by_underlying.values())
    return {"contracts_seen": total, "unique_two_sided": len({r["contract"] for r in kept}),
            "two_sided_share": round(len(kept) / total, 3) if total else None,
            "roots": sorted({r["root"] for r in kept}), "expiries": len({(r["root"], r["expiry"]) for r in kept}),
            "pages": pages, "rejects": dict(sorted(rejects.items())),
            "with_open_interest": sum(1 for r in kept if r.get("open_interest") is not None),
            "with_volume": sum(1 for r in kept if r["volume"] > 0)}
