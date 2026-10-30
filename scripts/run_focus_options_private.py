"""Opt-in, private Alpaca Basic research collector for GHAZI CORE Ω.

Default: no network calls, no public price output, no Telegram price sharing.
Owner-supplied Alpaca account keys and acknowledged provider terms required.
Fetches IEX completed 5m/daily, indicative option chain and dated contract OI.
Only *non-price* health metadata is written; observations remain in process RAM.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from options_radar.core_options_strategy import evaluate, number
from options_radar.focus_universe import FOCUS_STOCKS

NY = ZoneInfo("America/New_York")
FOCUS = ("SPY", "QQQ", *FOCUS_STOCKS)
MARKET = "https://data.alpaca.markets"
TRADING = "https://paper-api.alpaca.markets"
NO_DATA = "BLOCKED_NO_INTERNAL_ENTITLEMENT"


def _authorized() -> bool:
    consent = os.getenv("DATA_TERMS_CONFIRMED", "")
    return (os.getenv("ALPACA_INTERNAL_DATA_USE_AUTHORIZED") == "true"
            and "alpaca" in {x.strip().lower() for x in consent.split(",")}
            and bool(os.getenv("ALPACA_API_KEY"))
            and bool(os.getenv("ALPACA_SECRET_KEY")))


def _request(session: Any, host: str, endpoint: str, *,
             query: dict[str, Any], key: str, secret: str) -> dict:
    """Strictly bounded single-page request; never print provider response."""
    try:
        result = session.get(
            host + endpoint, params=query,
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            timeout=15,
        )
        if result.status_code != 200 or len(result.content) > 2_500_000:
            return {}
        payload = result.json()
        if not isinstance(payload, dict):
            return {}
        # Incomplete pagination must never be treated as whole-chain evidence.
        if payload.get("next_page_token") or payload.get("page_token"):
            return {}
        return payload
    except (requests.RequestException, ValueError, TypeError):
        return {}


def _bars(session: Any, symbol: str, *, minute: bool, now: datetime,
          key: str, secret: str) -> list[dict]:
    days = 6 if minute else 35
    latest = now - timedelta(minutes=20)
    result = _request(
        session, MARKET, f"/v2/stocks/{symbol}/bars",
        query={"timeframe": "5Min" if minute else "1Day",
               "start": (now - timedelta(days=days)).isoformat(),
               "end": latest.isoformat(),
               "feed": "iex", "adjustment": "raw", "sort": "asc", "limit": 10000},
        key=key, secret=secret)
    data = result.get("bars", [])
    return data if isinstance(data, list) else []


def _chain(session: Any, symbol: str, *, spot: float, now: datetime,
           key: str, secret: str) -> list[dict]:
    # Only search a defined strike/DTE neighborhood; no chain-exhaustiveness claim.
    today = now.astimezone(NY).date()
    expiry_end = today + timedelta(days=7 if symbol in ("SPY", "QQQ") else 21)
    query = {"feed": "indicative", "expiration_date_gte": (today + timedelta(days=1)).isoformat(),
             "expiration_date_lte": expiry_end.isoformat(),
             "strike_price_gte": round(spot * .88, 2),
             "strike_price_lte": round(spot * 1.12, 2), "limit": 1000}
    snapshots = _request(session, MARKET, f"/v1beta1/options/snapshots/{symbol}",
                         query=query, key=key, secret=secret)
    listings = _request(session, TRADING, "/v2/options/contracts",
                        query={"underlying_symbols": symbol, "status": "active",
                               "expiration_date_gte": query["expiration_date_gte"],
                               "expiration_date_lte": query["expiration_date_lte"],
                               "strike_price_gte": query["strike_price_gte"],
                               "strike_price_lte": query["strike_price_lte"],
                               "limit": 1000}, key=key, secret=secret)
    snapshot_rows = snapshots.get("snapshots", {})
    contracts = listings.get("option_contracts", [])
    if not isinstance(snapshot_rows, dict) or not isinstance(contracts, list):
        return []
    by_code = {str(c.get("symbol")): c for c in contracts if isinstance(c, dict)}
    combined = []
    for contract, snapshot in snapshot_rows.items():
        if not isinstance(snapshot, dict) or contract not in by_code:
            continue
        meta = by_code[contract]
        g = snapshot.get("greeks") if isinstance(snapshot.get("greeks"), dict) else {}
        combined.append({
            "symbol": contract, "type": meta.get("type"),
            "strike": number(meta.get("strike_price")),
            "expiration": meta.get("expiration_date"),
            "open_interest": number(meta.get("open_interest")),
            "open_interest_date": meta.get("open_interest_date"),
            "delta": number(g.get("delta")), "gamma": number(g.get("gamma")),
            "implied_volatility": number(snapshot.get("implied_volatility")),
            "latest_quote": snapshot.get("latest_quote"),
            # Latest trade size is NOT daily contract volume.
            "volume": None,
        })
    return combined


def run(*, now: datetime | None = None, session: Any = requests) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    stamp = now.astimezone(timezone.utc).isoformat()
    result: dict[str, Any] = {
        "schema": "ghazi.focus_private_probe.v1", "generated_at": stamp,
        "status": NO_DATA, "source_family": "alpaca",
        "source_feeds": ["IEX_PARTIAL_EXCHANGE", "INDICATIVE_MODIFIED_OPTION_QUOTES"],
        "public_redistribution_allowed": False, "execution_authority": False,
        "index_cash_supported": False, "etf_proxies": {"SPX": "SPY", "NDX": "QQQ"},
        "symbols_requested": list(FOCUS), "completed": 0, "research_watches": 0,
        "eligible_execution_signals": 0, "no_data": 0, "by_symbol": {},
        "no_prices_or_keys_in_output": True,
    }
    if not _authorized():
        return result
    result["status"] = "PRIVATE_RESEARCH_SCAN"
    key, secret = os.getenv("ALPACA_API_KEY", ""), os.getenv("ALPACA_SECRET_KEY", "")
    for symbol in FOCUS:
        daily = _bars(session, symbol, minute=False, now=now, key=key, secret=secret)
        intraday = _bars(session, symbol, minute=True, now=now, key=key, secret=secret)
        # Extract latest completed IEX spot only for bounded strike discovery.
        # 5-min bar start is not an executable quote.
        spot = (number(intraday[-1].get("c")) if intraday else None)
        chain = (_chain(session, symbol, spot=spot, now=now, key=key, secret=secret)
                 if spot is not None and spot > 0 else [])
        plan = evaluate(symbol, daily=daily, bars5=intraday,
                        chain=chain, now=now, feed="indicative")
        technical = plan["technical"]
        entry = {"technical_status": technical["status"],
                 "technical_decision": technical["decision"],
                 "contracts_observed": len(chain),
                 "gamma_coverage": plan["gamma"].get("joint_coverage", 0),
                 "gamma_status": plan["gamma"]["status"],
                 "option_status": plan["option"]["status"],
                 "eligible_execution_signals": 0}
        result["by_symbol"][symbol] = entry
        result["completed"] += int(technical["status"] == "RESEARCH_ONLY_IEX")
        result["research_watches"] += int(
            plan["signal_type"] == "WATCH_RESEARCH_ONLY"
            and bool(plan["option"]["candidates"]))
        result["no_data"] += int(technical["status"] != "RESEARCH_ONLY_IEX")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=Path("data/live/focus_private_strategy_health.json"))
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # This is metadata only; never save raw OHLC, chain or option quote.
    temp = args.output.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False),
                    encoding="utf-8")
    temp.replace(args.output)
    print("GHAZI CORE Omega private scan:", result["status"],
          "completed=", result["completed"],
          "research_watches=", result["research_watches"],
          "execution_signals=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
