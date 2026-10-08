"""Bounded SEC EDGAR submissions retrieval; research-only, no trading authority."""
from __future__ import annotations

import json
import re
from urllib.request import Request, urlopen

from options_radar.sec_filing_evidence import parse_recent_filings

CIK_PATTERN = re.compile(r"^[0-9]{1,10}$")


def fetch_sec_filings(cik: str, *, user_agent: str, timeout: float = 10.0, limit: int = 20) -> list[dict]:
    """Fetch one SEC official JSON response. Caller handles cadence and SEC rate limits."""
    if not isinstance(cik, str) or not CIK_PATTERN.fullmatch(cik):
        raise ValueError("Invalid SEC CIK")
    if not isinstance(user_agent, str) or len(user_agent.strip()) < 12 or "@" not in user_agent:
        raise ValueError("SEC requires an identifying User-Agent with contact email")
    if not 0 < timeout <= 30:
        raise ValueError("Timeout out of bounds")
    normalized = str(int(cik)).zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{normalized}.json"
    request = Request(url, headers={
        "User-Agent": user_agent,
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    })
    with urlopen(request, timeout=timeout) as response:
        if response.geturl() != url:
            raise ValueError("SEC redirect not accepted")
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("SEC response exceeds safety limit")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or str(payload.get("cik")) != str(int(cik)):
        raise ValueError("SEC response CIK mismatch")
    return parse_recent_filings(payload, limit=limit)
