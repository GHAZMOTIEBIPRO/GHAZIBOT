"""Strict offline ticker-to-CIK lookup from SEC company_tickers.json.

This module does not infer an issuer from a ticker spelling or an untrusted source.
"""
from __future__ import annotations

import re

TICKER = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")


def resolve_sec_ticker(payload: object, ticker: str) -> dict | None:
    if not isinstance(payload, dict) or not isinstance(ticker, str):
        return None
    ticker = ticker.strip().upper()
    if not TICKER.fullmatch(ticker):
        return None
    matches = []
    for row in payload.values():
        if not isinstance(row, dict) or row.get("ticker") != ticker:
            continue
        cik = row.get("cik_str")
        if isinstance(cik, bool) or not str(cik).isdigit():
            continue
        number = int(cik)
        if not 0 < number < 10**10:
            continue
        if not isinstance(row.get("title"), str) or not row["title"].strip():
            continue
        matches.append({"ticker": ticker, "cik": number, "company_name": row["title"].strip(),
                        "source": "SEC_COMPANY_TICKERS", "research_only": True})
    return matches[0] if len(matches) == 1 else None
