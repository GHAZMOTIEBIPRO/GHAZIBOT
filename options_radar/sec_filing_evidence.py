"""Offline, research-only SEC submissions evidence parser.

Consumes SEC submissions JSON already obtained by a separate compliant fetcher.
A filing is evidence of a filing, not evidence of a bullish catalyst.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import quote

ACCESSION = re.compile(r"^\\d{10}-\\d{2}-\\d{6}$")
DOCUMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,200}$")


def parse_recent_filings(payload: dict, *, limit: int = 20) -> list[dict]:
    if not isinstance(payload, dict) or not 1 <= limit <= 100:
        return []
    cik = payload.get("cik")
    if isinstance(cik, bool) or not str(cik).isdigit():
        return []
    cik_number = int(cik)
    if not 0 < cik_number < 10**10:
        return []
    recent = payload.get("filings", {}).get("recent", {})
    if not isinstance(recent, dict):
        return []
    required = ("accessionNumber", "form", "filingDate", "primaryDocument")
    if not all(isinstance(recent.get(key), list) for key in required):
        return []
    length = min(len(recent[key]) for key in required)
    results = []
    for index in range(length):
        accession, form, filed, document = (recent[key][index] for key in required)
        if not all(isinstance(v, str) for v in (accession, form, filed, document)):
            continue
        if not ACCESSION.fullmatch(accession) or not DOCUMENT.fullmatch(document):
            continue
        if form not in {"8-K", "6-K", "10-Q", "10-K", "S-3", "424B5"}:
            continue
        try:
            if date.fromisoformat(filed).isoformat() != filed:
                continue
        except ValueError:
            continue
        results.append({
            "cik": cik_number,
            "accession": accession,
            "form": form,
            "filed_at": filed,
            "official_catalyst_url": (
                f"https://www.sec.gov/Archives/edgar/data/{cik_number}/"
                f"{accession.replace('-', '')}/{quote(document, safe='')}"
            ),
            "evidence_type": "SEC_FILING_EXISTS",
            "bullish_catalyst_verified": False,
            "research_only": True,
        })
        if len(results) >= limit:
            break
    return results
