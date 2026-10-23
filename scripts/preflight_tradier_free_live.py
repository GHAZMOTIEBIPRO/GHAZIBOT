"""Read-only Tradier access probe; output contains no prices or credentials.

A successful probe proves access and quote structure, never redistribution rights
or trading readiness. Sandbox configuration is preserved exactly.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

BASES = {"https://api.tradier.com": "production", "https://sandbox.tradier.com": "sandbox"}


def _request_json(base: str, path: str, token: str, **params: str) -> dict[str, Any]:
    response = requests.get(
        base + "/v1/markets/" + path,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        params=params, timeout=15, allow_redirects=False,
    )
    if response.status_code != 200:
        raise RuntimeError("HTTP_ACCESS_FAILED")
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError("INVALID_RESPONSE")
    return payload


def quote_quality(row: Any, now: datetime) -> bool:
    if not isinstance(row, dict):
        return False
    try:
        values = [row.get(key) for key in ("bid", "ask", "bid_date", "ask_date")]
        if any(isinstance(v, bool) for v in values):
            return False
        bid, ask, bid_ms, ask_ms = map(float, values)
        return (all(math.isfinite(x) for x in (bid, ask, bid_ms, ask_ms))
                and 0 < bid <= ask
                and all(0 <= now.timestamp() - t / 1000 <= 120 for t in (bid_ms, ask_ms)))
    except (TypeError, ValueError, OverflowError):
        return False


def probe(env: Any, symbol: str = "SPY", *, now: datetime | None = None,
          request: Any = _request_json) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    token = str(env.get("TRADIER_TOKEN") or "").strip()
    base = str(env.get("TRADIER_BASE_URL") or "https://sandbox.tradier.com").rstrip("/")
    report: dict[str, Any] = {
        "schema": "ghazi.tradier_private_access.v1", "generated_at": now.isoformat(),
        "credential_present": bool(token), "mode": BASES.get(base, "invalid"),
        "internal_use_authorized": env.get("TRADIER_INTERNAL_DATA_USE_AUTHORIZED") == "true",
        "status": "BLOCKED", "reason": "MISSING_CREDENTIAL", "checks": {},
        "ready": False, "execution_authority": False, "public_redistribution": False,
    }
    if not token:
        return report
    if base not in BASES:
        report["reason"] = "INVALID_ENDPOINT"
        return report
    if not report["internal_use_authorized"]:
        report["reason"] = "INTERNAL_USE_NOT_CONFIRMED"
        return report
    if not re.fullmatch(r"[A-Z]{1,5}(?:\.[A-Z])?", symbol):
        report["reason"] = "INVALID_SYMBOL"
        return report
    try:
        body = request(base, "quotes", token, symbols=symbol, greeks="false")
        row = body.get("quotes", {}).get("quote")
        if isinstance(row, list):
            row = next((r for r in row if isinstance(r, dict) and r.get("symbol") == symbol), None)
        valid_identity = isinstance(row, dict) and row.get("symbol") == symbol and row.get("type") in {"stock", "etf"}
        report["checks"]["stock_identity_valid"] = valid_identity
        report["checks"]["stock_two_sided_fresh"] = valid_identity and quote_quality(row, now)
        body = request(base, "options/expirations", token, symbol=symbol, includeAllRoots="false")
        dates = body.get("expirations", {}).get("date", [])
        if isinstance(dates, str):
            dates = [dates]
        valid_dates = []
        for item in dates if isinstance(dates, list) else []:
            try:
                expiry = date.fromisoformat(item)
                if expiry >= now.date():
                    valid_dates.append(expiry.isoformat())
            except (TypeError, ValueError):
                pass
        report["checks"]["option_expirations_available"] = bool(valid_dates)
        if valid_dates:
            expiration = min(valid_dates)
            body = request(base, "options/chains", token, symbol=symbol, expiration=expiration, greeks="false")
            rows = body.get("options", {}).get("option", [])
            rows = [rows] if isinstance(rows, dict) else rows
            prefix = symbol + datetime.strptime(expiration, "%Y-%m-%d").strftime("%y%m%d")
            valid = [r for r in rows if isinstance(r, dict)
                     and r.get("type") == "option" and r.get("underlying") == symbol
                     and re.fullmatch(re.escape(prefix) + r"[CP][0-9]{8}", str(r.get("symbol", "")))
                     and r.get("contract_size") == 100] if isinstance(rows, list) else []
            report["checks"]["standard_option_identity_available"] = bool(valid)
            report["checks"]["option_two_sided_fresh"] = any(quote_quality(r, now) for r in valid)
        access = valid_identity and report["checks"].get("standard_option_identity_available", False)
        report["status"] = "ACCESS_VERIFIED" if access else "INCOMPLETE_RESPONSE"
        report["reason"] = "PRIVATE_ACCESS_ONLY" if access else "IDENTITY_OR_CHAIN_MISSING"
        # Never infer licensing, market-open status, spread suitability or quorum.
        return report
    except (requests.RequestException, ValueError, TypeError, AttributeError, RuntimeError, OverflowError):
        report["status"] = "UNAVAILABLE"
        report["reason"] = "REQUEST_OR_RESPONSE_FAILED"
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--output", default="")
    parser.add_argument("--soft-fail", action="store_true")
    args = parser.parse_args()
    report = probe(os.environ, args.symbol.strip().upper())
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(serialized + "\n", encoding="utf-8")
        temporary.replace(path)
    print(serialized)
    return 0 if args.soft_fail or report["status"] == "ACCESS_VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
