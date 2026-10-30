"""Read-only, account-scoped free-source health audit (never publish quotes).

Providers: Twelve Data Basic, Alpaca IEX and indicative options, Tradier
personal sandbox, official SEC EDGAR. No provider key, raw quote, contract
symbol, derived price level or User-Agent string leaves this process.

The operator must affirm each provider's own permitted use before any request.
Missing credentials or permission results in NO_REQUEST; this file is not an
entitlement-granting or licensed-market-data redistribution mechanism.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

PROVIDER_NAMES = ("twelve_data", "alpaca", "tradier", "sec_edgar")
TRADIER_BASES = ("https://sandbox.tradier.com", "https://api.tradier.com")
MAX_BODY_BYTES = 650_000


def _permitted(env: dict[str, str], variable: str, term: str) -> bool:
    signed = {x.strip().lower() for x in env.get("DATA_TERMS_CONFIRMED", "").split(",")}
    return env.get(variable, "").lower() == "true" and term in signed


def _http(session: Any, url: str, *, headers: dict[str, str] | None = None,
          params: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    """Return status class and bounded JSON only; never log request/errors."""
    try:
        response = session.get(
            url, headers=headers or {}, params=params or {},
            timeout=12, allow_redirects=False)
        status = int(response.status_code)
        if status in (401, 403):
            return "ACCESS_DENIED", {}
        if status == 429:
            return "QUOTA_EXHAUSTED", {}
        if status != 200:
            return "HTTP_UNAVAILABLE", {}
        if len(response.content) > MAX_BODY_BYTES:
            return "RESPONSE_TOO_LARGE", {}
        body = response.json()
        return ("OK", body) if isinstance(body, dict) else ("INVALID_JSON_SHAPE", {})
    except (requests.RequestException, ValueError, TypeError, OverflowError):
        return "NETWORK_OR_RESPONSE_ERROR", {}


def _result(status: str, *, calls: int = 0, scope: str = "private_research",
            data_verified: bool = False, detail: str = "") -> dict[str, Any]:
    return {"status": status, "requests": calls, "data_verified": data_verified,
            "scope": scope, "detail": detail, "execution_grade": False,
            "public_redistribution_allowed": False}


def _positive(value: Any) -> float | None:
    try:
        if isinstance(value, bool):
            return None
        n = float(value)
        return n if math.isfinite(n) and n > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def probe_twelve(env: dict[str, str], session: Any, now: datetime) -> dict[str, Any]:
    if not env.get("TWELVE_DATA_API_KEY"):
        return _result("NO_KEY")
    if not _permitted(env, "TWELVE_DATA_NON_DISPLAY_USE_AUTHORIZED", "twelve_data"):
        return _result("OWNER_TERMS_NOT_CONFIRMED")
    status, payload = _http(
        session, "https://api.twelvedata.com/time_series",
        params={"symbol": "SPY", "interval": "1day", "outputsize": 8,
                "timezone": "America/New_York",
                "apikey": env["TWELVE_DATA_API_KEY"]})
    if status != "OK":
        return _result(status, calls=1)
    if payload.get("status") == "error":
        return _result("QUOTA_OR_API_ERROR" if payload.get("code") == 429
                       else "PROVIDER_REJECTED", calls=1)
    meta, rows = payload.get("meta"), payload.get("values")
    if not isinstance(meta, dict) or meta.get("symbol") != "SPY" or not isinstance(rows, list):
        return _result("INVALID_SOURCE_IDENTITY", calls=1)
    valid = 0
    for row in rows[:8]:
        if not isinstance(row, dict):
            continue
        try:
            stamp = datetime.strptime(str(row["datetime"])[:10], "%Y-%m-%d").date()
            age = (now.date() - stamp).days
        except (KeyError, TypeError, ValueError):
            continue
        o, h, l, c = (_positive(row.get(k)) for k in ("open", "high", "low", "close"))
        if (all(v is not None for v in (o, h, l, c)) and h >= max(o, c, l)
                and l <= min(o, c, h) and 0 <= age <= 14):
            valid += 1
    return _result("INTERNAL_DAILY_BARS_VERIFIED" if valid >= 2 else "INSUFFICIENT_VALID_BARS",
                   calls=1, data_verified=valid >= 2, detail="US_ETF_DAILY_NON_DISPLAY")


def probe_alpaca(env: dict[str, str], session: Any, now: datetime) -> dict[str, Any]:
    if not (env.get("ALPACA_API_KEY") and env.get("ALPACA_SECRET_KEY")):
        return _result("NO_KEY")
    if not _permitted(env, "ALPACA_INTERNAL_DATA_USE_AUTHORIZED", "alpaca"):
        return _result("OWNER_TERMS_NOT_CONFIRMED")
    headers = {"APCA-API-KEY-ID": env["ALPACA_API_KEY"],
               "APCA-API-SECRET-KEY": env["ALPACA_SECRET_KEY"]}
    status, bars = _http(
        session, "https://data.alpaca.markets/v2/stocks/SPY/bars",
        headers=headers, params={"feed": "iex", "timeframe": "1Day",
                                "start": (now - timedelta(days=14)).isoformat(),
                                "end": (now - timedelta(minutes=20)).isoformat(),
                                "limit": 10, "sort": "desc"})
    if status != "OK":
        return _result(status, calls=1)
    rows = bars.get("bars")
    good_stock = isinstance(rows, list) and sum(
        isinstance(r, dict) and all(_positive(r.get(x)) is not None
                                    for x in ("o", "h", "l", "c"))
        for r in (rows[:10] if isinstance(rows, list) else [])
    ) >= 2
    if not good_stock:
        return _result("IEX_DATA_NOT_VERIFIED", calls=1)
    status, options = _http(
        session, "https://data.alpaca.markets/v1beta1/options/snapshots/SPY",
        headers=headers, params={"feed": "indicative", "limit": 10})
    if status != "OK":
        return _result("IEX_VERIFIED_OPTIONS_" + status, calls=2,
                       data_verified=True, detail="IEX_ONLY;OPTIONS_NOT_VERIFIED")
    snapshots = options.get("snapshots")
    observed = isinstance(snapshots, dict) and any(
        isinstance(r, dict) and isinstance(r.get("latest_quote"), dict)
        for r in snapshots.values()
    )
    return _result(
        "IEX_AND_INDICATIVE_OPTIONS_VERIFIED" if observed else "IEX_VERIFIED_OPTIONS_EMPTY",
        calls=2, data_verified=True,
        detail="IEX_PARTIAL_MARKET;INDICATIVE_OPTIONS_NOT_OPRA")


def probe_tradier(env: dict[str, str], session: Any, now: datetime) -> dict[str, Any]:
    if not env.get("TRADIER_TOKEN"):
        return _result("NO_KEY")
    if not _permitted(env, "TRADIER_INTERNAL_DATA_USE_AUTHORIZED", "tradier"):
        return _result("OWNER_TERMS_NOT_CONFIRMED")
    base = env.get("TRADIER_BASE_URL", "https://sandbox.tradier.com").rstrip("/")
    if base not in TRADIER_BASES:
        return _result("INVALID_APPROVED_ENDPOINT")
    headers = {"Authorization": "Bearer " + env["TRADIER_TOKEN"],
               "Accept": "application/json"}
    status, quotes = _http(session, base + "/v1/markets/quotes",
                           headers=headers, params={"symbols": "SPY"})
    if status != "OK":
        return _result(status, calls=1)
    row = quotes.get("quotes", {}).get("quote") if isinstance(quotes.get("quotes"), dict) else None
    if isinstance(row, list):
        row = next((r for r in row if isinstance(r, dict)
                    and r.get("symbol") == "SPY"), None)
    if not isinstance(row, dict) or row.get("symbol") != "SPY":
        return _result("QUOTE_IDENTITY_MISMATCH", calls=1)
    status, body = _http(
        session, base + "/v1/markets/options/expirations",
        headers=headers, params={"symbol": "SPY"})
    if status != "OK":
        return _result("STOCK_VERIFIED_OPTIONS_" + status, calls=2,
                       data_verified=True, detail="SANDBOX_DELAYED_15M" if
                       "sandbox" in base else "BROKERAGE_DATA")
    dates = body.get("expirations", {}).get("date") if isinstance(body.get("expirations"), dict) else None
    if isinstance(dates, str):
        dates = [dates]
    has_expiries = isinstance(dates, list) and any(
        isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)
        for d in dates
    )
    return _result("STOCK_AND_EXPIRIES_VERIFIED" if has_expiries else "STOCK_VERIFIED_OPTIONS_EMPTY",
                   calls=2, data_verified=True, detail=(
                       "SANDBOX_DELAYED_15M_NO_GREEKS" if "sandbox" in base
                       else "BROKERAGE_DATA_OPTIONS_NOT_EXECUTION_VERIFIED"))


def probe_sec(env: dict[str, str], session: Any, now: datetime) -> dict[str, Any]:
    agent = env.get("SEC_USER_AGENT", "").strip()
    if not agent:
        return _result("NO_CONTACT_USER_AGENT", scope="official_public_filings")
    if len(agent) > 256 or not re.search(r"[^@\s]+@[^@\s]+\.[^@\s]+", agent):
        return _result("INVALID_USER_AGENT", scope="official_public_filings")
    status, payload = _http(
        session, "https://data.sec.gov/submissions/CIK0000320193.json",
        headers={"User-Agent": agent, "Accept": "application/json"})
    if status != "OK":
        return _result(status, calls=1, scope="official_public_filings")
    filings = payload.get("filings", {})
    recent = filings.get("recent", {}) if isinstance(filings, dict) else {}
    good = (payload.get("cik") == 320193 and isinstance(recent, dict)
            and isinstance(recent.get("accessionNumber"), list)
            and len(recent["accessionNumber"]) > 0)
    return _result("OFFICIAL_FILINGS_VERIFIED" if good else "INVALID_CIK_OR_FILINGS",
                   calls=1, scope="official_public_filings", data_verified=good,
                   detail="SEC_EDGAR_NO_MARKET_PRICES")


def run(env: dict[str, str], *, now: datetime | None = None,
        session: Any = requests) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    sources = {
        "twelve_data": probe_twelve(env, session, now),
        "alpaca": probe_alpaca(env, session, now),
        "tradier": probe_tradier(env, session, now),
        "sec_edgar": probe_sec(env, session, now),
    }
    return {
        "schema": "ghazi.free_source_owner_health.v1",
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "scope": "RUNNER_PRIVATE_HEALTH_ONLY",
        "providers": sources,
        "real_data_providers_verified": sum(
            bool(v["data_verified"]) for v in sources.values()),
        "raw_prices_present": False,
        "credentials_present_in_output": False,
        "allowed_to_generate_execution_alerts": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(dict(os.environ))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    # JSON has statuses/booleans only: no quotes, ticker-level prices, secrets,
    # source response bodies, or external redistribution.
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as f:
            f.write("\n### GHAZI Independent Free Source Audit (private)\n")
            f.write("| Provider | Status | Verified observations |\n|---|---|---|\n")
            for name, result in report["providers"].items():
                f.write(f"| {name} | {result['status']} | {result['data_verified']} |\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
