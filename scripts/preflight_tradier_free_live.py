from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import requests

from options_radar.free_autonomy import enforce_free_autonomy_environment


def _quote_payload(body: dict[str, Any]) -> dict[str, Any]:
    quotes = body.get("quotes") if isinstance(body.get("quotes"), dict) else {}
    quote = quotes.get("quote")
    if isinstance(quote, list):
        quote = quote[0] if quote else {}
    return quote if isinstance(quote, dict) else {}


def _request_json(method: str, url: str, token: str, **kwargs: Any) -> dict[str, Any]:
    response = requests.request(
        method,
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        timeout=15,
        **kwargs,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="BLACK BOX Omega free-live Tradier production preflight"
    )
    parser.add_argument("--symbol", default="SPY")
    args = parser.parse_args()

    status = enforce_free_autonomy_environment()
    token = str(os.getenv("TRADIER_TOKEN") or "").strip()
    base_url = str(os.getenv("TRADIER_BASE_URL") or "").rstrip("/")
    symbol = str(args.symbol or "SPY").strip().upper()

    report: dict[str, Any] = {
        "ready": False,
        "symbol": symbol,
        "free_autonomy": status.as_dict(),
        "tradier_base_url": base_url,
        "production_endpoint": bool(base_url and "sandbox" not in base_url.lower()),
        "token_present": bool(token),
        "checks": {},
    }

    if not token:
        report["reason"] = "TRADIER_TOKEN is not configured; free fallbacks remain active."
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    try:
        quote_body = _request_json(
            "GET",
            f"{base_url}/v1/markets/quotes",
            token,
            params={"symbols": symbol, "greeks": "false"},
        )
        quote = _quote_payload(quote_body)
        report["checks"]["quote"] = {
            "ok": bool(quote),
            "symbol": quote.get("symbol"),
            "last": quote.get("last"),
            "bid": quote.get("bid"),
            "ask": quote.get("ask"),
            "trade_date": quote.get("trade_date"),
        }

        expirations_body = _request_json(
            "GET",
            f"{base_url}/v1/markets/options/expirations",
            token,
            params={"symbol": symbol, "includeAllRoots": "true", "strikes": "false"},
        )
        expirations = expirations_body.get("expirations")
        report["checks"]["option_expirations"] = {
            "ok": bool(expirations),
        }

        session_body = _request_json(
            "POST",
            f"{base_url}/v1/markets/events/session",
            token,
        )
        stream = session_body.get("stream") if isinstance(session_body.get("stream"), dict) else {}
        session_id = str(stream.get("sessionid") or session_body.get("sessionid") or "").strip()
        report["checks"]["stream_session"] = {
            "ok": bool(session_id),
            "session_created": bool(session_id),
        }

        report["ready"] = bool(
            report["production_endpoint"]
            and report["checks"]["quote"]["ok"]
            and report["checks"]["option_expirations"]["ok"]
            and report["checks"]["stream_session"]["ok"]
        )
        report["reason"] = (
            "Tradier production quote/options/stream checks passed."
            if report["ready"]
            else "One or more production data checks did not pass."
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ready"] else 1
    except requests.HTTPError as exc:
        response = exc.response
        report["reason"] = "Tradier HTTP preflight failed."
        report["http_status"] = response.status_code if response is not None else None
        # Deliberately do not print Authorization headers, response headers, or token.
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    except Exception as exc:
        report["reason"] = f"Preflight failed: {type(exc).__name__}: {exc}"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
