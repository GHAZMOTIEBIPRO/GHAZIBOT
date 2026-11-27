"""What the owner's Alpaca account really returns *now* (runtime entitlement, not key presence).

Prints metadata only - HTTP status, counts, feed, the age of the newest quote/trade timestamp in
seconds, whether greeks/IV are present - never a price, size, strike list or contract symbol.

Checks:
- stocks latest snapshot, feed=iex (real-time single venue on the Basic plan)
- stocks latest snapshot, feed=sip (expected refused on Basic: latest SIP is paid)
- option chain snapshots, feed=indicative, for SPY, QQQ (ETF options) and SPX, NDX (index options)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import requests

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


def main() -> int:
    env = os.environ
    if not decide("alpaca_iex", "fetch", env).allowed or not env.get("ALPACA_API_KEY"):
        print("probe: NOT_AUTHORIZED_OR_NO_KEYS")
        return 0
    headers = {"APCA-API-KEY-ID": env["ALPACA_API_KEY"].strip(), "APCA-API-SECRET-KEY": env["ALPACA_SECRET_KEY"].strip()}
    now = datetime.now(timezone.utc)
    result = {"checked_at": now.isoformat(),
              "stocks_iex_latest": stocks("iex", headers, now), "stocks_sip_latest": stocks("sip", headers, now),
              "options_indicative": {u: chain(u, headers, now) for u in ("SPY", "QQQ", "SPX", "NDX")}}
    text = json.dumps(result, indent=1)
    print("Realtime entitlement probe (metadata only):", text)
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("## Realtime entitlement probe\n\n```json\n" + text + "\n```\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
