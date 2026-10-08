"""Run one bounded SEC filing lookup for an explicit ticker (research only)."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

from options_radar.sec_submissions_client import fetch_sec_filings
from options_radar.sec_ticker_resolver import resolve_sec_ticker


def probe(ticker: str, *, user_agent: str) -> dict:
    url = "https://www.sec.gov/files/company_tickers.json"
    request = Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    with urlopen(request, timeout=10) as response:
        if response.geturl() != url:
            raise ValueError("SEC mapping redirect")
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("SEC mapping too large")
    identity = resolve_sec_ticker(json.loads(raw), ticker)
    if identity is None:
        return {"status": "NO_UNAMBIGUOUS_SEC_MATCH", "ticker": ticker, "research_only": True}
    filings = fetch_sec_filings(str(identity["cik"]), user_agent=user_agent, limit=10)
    return {"status": "SEC_RESEARCH_OK", "identity": identity, "filings": filings,
            "filing_count": len(filings), "research_only": True, "telegram_enabled": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--output", default="data/live/sec_research_probe.json")
    args = parser.parse_args()
    user_agent = os.environ.get("SEC_USER_AGENT", "")
    if len(user_agent) < 12 or "@" not in user_agent:
        print("SEC_USER_AGENT must identify an operator and contact email")
        return 2
    try:
        result = probe(args.ticker, user_agent=user_agent)
    except (OSError, ValueError, TimeoutError) as exc:
        result = {"status": "SEC_UNAVAILABLE", "reason": type(exc).__name__,
                  "research_only": True, "telegram_enabled": False}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SEC probe: {result['status']}")
    return 0 if result["status"] == "SEC_RESEARCH_OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
