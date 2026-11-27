"""What the owner's Alpaca account really returns *now* (runtime entitlement, not key presence).

Prints metadata only - HTTP status, counts, feed, the age of the newest quote/trade timestamp in
seconds, whether greeks/IV are present - never a price, size, strike list or contract symbol.

Checks:
- stocks latest snapshot, feed=iex (real-time single venue on the Basic plan)
- stocks latest snapshot, feed=sip (expected refused on Basic: latest SIP is paid)
- option chain snapshots, feed=indicative, for SPY, QQQ (ETF options) and SPX, NDX (index options)
- put-call parity forward quality for the nearest SPXW / NDXP expiry (options_radar.parity_reference):
  status, strikes, dispersion, spread, quote age, and for SPX the ratio to 10 x SPY - never the level
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import requests

from options_radar import parity_reference as pr
from options_radar.output_policy import decide

BASE = "https://data.alpaca.markets"


def _age(stamp: Any, now: datetime) -> float | None:
    try:
        t = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((now - t).total_seconds(), 1) if t.tzinfo else None


def _get(path: str, params: dict[str, Any], headers: dict[str, str]) -> tuple[int, Any]:
    try:
        r = requests.get(BASE + path, params=params, headers=headers, timeout=20)
    except requests.RequestException as exc:
        return -1, type(exc).__name__
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None


def stocks(feed: str, headers: dict[str, str], now: datetime) -> dict[str, Any]:
    code, body = _get("/v2/stocks/snapshots", {"symbols": "SPY,QQQ,NVDA", "feed": feed}, headers)
    out: dict[str, Any] = {"http": code}
    if code == 200 and isinstance(body, dict):
        quotes = [_age((v.get("latestQuote") or {}).get("t"), now) for v in body.values() if isinstance(v, dict)]
        trades = [_age((v.get("latestTrade") or {}).get("t"), now) for v in body.values() if isinstance(v, dict)]
        out.update(symbols=len(body), newest_quote_age_s=min((a for a in quotes if a is not None), default=None),
                   newest_trade_age_s=min((a for a in trades if a is not None), default=None))
    return out


def chain(underlying: str, headers: dict[str, str], now: datetime) -> dict[str, Any]:
    code, body = _get(f"/v1beta1/options/snapshots/{underlying}", {"feed": "indicative", "limit": 1000}, headers)
    out: dict[str, Any] = {"http": code}
    if code == 200 and isinstance(body, dict):
        snaps = body.get("snapshots") or {}
        ages = [_age((s.get("latestQuote") or {}).get("t"), now) for s in snaps.values() if isinstance(s, dict)]
        roots = sorted({str(k).rstrip("0123456789CP")[:-6] for k in snaps})  # OCC root only (e.g. SPXW), no strikes
        out.update(contracts_first_page=len(snaps), more_pages=bool(body.get("next_page_token")), roots=roots,
                   with_two_sided_quote=sum(1 for s in snaps.values() if (s.get("latestQuote") or {}).get("bp")
                                            and (s.get("latestQuote") or {}).get("ap")),
                   with_greeks=sum(1 for s in snaps.values() if s.get("greeks")),
                   with_iv=sum(1 for s in snaps.values() if s.get("impliedVolatility") is not None),
                   newest_quote_age_s=min((a for a in ages if a is not None), default=None))
    elif isinstance(body, dict):
        out["message"] = str(body.get("message") or "")[:120]
    return out


def _paged_chain(underlying: str, params: dict[str, Any], headers: dict[str, str]) -> tuple[int, dict]:
    snaps: dict = {}
    token = None
    for _ in range(10):
        query = {**params, "feed": "indicative", "limit": 1000, **({"page_token": token} if token else {})}
        code, body = _get(f"/v1beta1/options/snapshots/{underlying}", query, headers)
        if code != 200 or not isinstance(body, dict):
            return code, snaps
        snaps.update(body.get("snapshots") or {})
        token = body.get("next_page_token")
        if not token:
            break
    return 200, snaps


def parity(underlying: str, root: str, headers: dict[str, str], now: datetime, spy_price: float | None) -> dict:
    """Nearest-expiry parity forward; prints quality metrics and, for SPX, the ratio to 10 x SPY only."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    start = now.astimezone(ny).date()
    # which filters does the endpoint honour? counts only (first page)
    diag = {}
    for name, params in (("date_gte", {"expiration_date_gte": start.isoformat()}),
                         ("root", {"root_symbol": root}),
                         ("root_date_gte", {"root_symbol": root, "expiration_date_gte": start.isoformat()})):
        code, body = _get(f"/v1beta1/options/snapshots/{underlying}", {**params, "feed": "indicative", "limit": 1000},
                          headers)
        snaps = (body or {}).get("snapshots") or {} if code == 200 and isinstance(body, dict) else {}
        expiries = sorted({str(p["expiry"]) for p in (pr.parse_occ(k) for k in snaps) if p})
        roots = sorted({p["root"] for p in (pr.parse_occ(k) for k in snaps) if p})
        diag[name] = {"http": code, "contracts": len(snaps), "roots": roots, "first_expiries": expiries[:3]}
    print("chain filter diagnostic", underlying, json.dumps(diag))
    for offset in range(8):
        expiry = start + timedelta(days=offset)
        # root_symbol is not honoured by the endpoint (diagnostic 2026-11-28): filter the date only and pick
        # the root in code (weekly SPXW/NDXP preferred, else the monthly SPX/NDX of that date)
        code, snaps = _paged_chain(underlying, {"expiration_date": expiry.isoformat()}, headers)
        snaps = {k: v for k, v in snaps.items() if (pr.parse_occ(k) or {}).get("expiry") == expiry}
        roots = {(pr.parse_occ(k) or {}).get("root") for k in snaps}
        root = root if root in roots else (underlying if underlying in roots else root)
        if code != 200:
            return {"http": code}
        if snaps:
            close = datetime.combine(expiry, datetime.min.time(), ny).replace(hour=16)
            years = max((close - now).total_seconds(), 0) / (365 * 86400)
            out = pr.implied_forward(snaps, root=root, expiry=expiry, years_to_expiry=years)
            metrics = pr.public_metrics(out)
            if underlying == "SPX" and out.get("forward") and spy_price:
                # sanity only: SPX forward vs 10 x SPY (SPY tracks SPX/10 less fees and dividends)
                metrics["ratio_to_10x_spy_minus_1_pct"] = round((out["forward"] / (10 * spy_price) - 1) * 100, 3)
            metrics["contracts_in_expiry"] = len(snaps)
            return metrics
    return {"status": "NO_EXPIRY_WITHIN_7_DAYS"}


def main() -> int:
    env = os.environ
    if not decide("alpaca_iex", "fetch", env).allowed or not env.get("ALPACA_API_KEY"):
        print("probe: NOT_AUTHORIZED_OR_NO_KEYS")
        return 0
    headers = {"APCA-API-KEY-ID": env["ALPACA_API_KEY"].strip(), "APCA-API-SECRET-KEY": env["ALPACA_SECRET_KEY"].strip()}
    now = datetime.now(timezone.utc)
    code, snap = _get("/v2/stocks/snapshots", {"symbols": "SPY", "feed": "iex"}, headers)
    spy = ((snap or {}).get("SPY") or {}).get("latestTrade", {}).get("p") if code == 200 else None
    result = {"checked_at": now.isoformat(),
              "stocks_iex_latest": stocks("iex", headers, now), "stocks_sip_latest": stocks("sip", headers, now),
              "options_indicative": {u: chain(u, headers, now) for u in ("SPY", "QQQ", "SPX", "NDX")},
              "parity_forward_quality": {"SPXW": parity("SPX", "SPXW", headers, now, spy),
                                         "NDXP": parity("NDX", "NDXP", headers, now, None)}}
    text = json.dumps(result, indent=1)
    print("Realtime entitlement probe (metadata only):", text)
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("## Realtime entitlement probe\n\n```json\n" + text + "\n```\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
