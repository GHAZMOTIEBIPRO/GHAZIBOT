"""Read-only SEC access diagnosis: status codes and refusal-page titles only.

Distinguishes an identity (User-Agent) refusal from a network-level block
without printing the configured User-Agent value or any filing content.
"""
from __future__ import annotations

import json
import os
import re
import time

import requests

URLS = (
    "https://www.sec.gov/files/company_tickers.json",
    "https://data.sec.gov/submissions/CIK0000320193.json",
)
DEFAULT_AGENT = "GHAZI Radar Research ghazi-bot@users.noreply.github.com"


def check(agent: str) -> list[dict]:
    out = []
    for url in URLS:
        time.sleep(1.0)
        try:
            response = requests.get(url, timeout=15, headers={
                "User-Agent": agent, "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate"})
            body = response.text[:4000] if response.status_code != 200 else ""
            title = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
            heading = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.IGNORECASE | re.DOTALL)
            out.append({"host": url.split("/")[2], "status": response.status_code,
                        "title": title.group(1).strip()[:100] if title else None,
                        "heading": heading.group(1).strip()[:120] if heading else None})
        except requests.RequestException as exc:
            out.append({"host": url.split("/")[2], "error": type(exc).__name__})
    return out


def main() -> int:
    configured = os.getenv("SEC_USER_AGENT", "").strip()
    report = {
        "secret_configured": bool(os.getenv("SEC_USER_AGENT_SECRET_SET")),
        "configured_agent_has_email": bool(re.search(r"\S+@\S+\.\S+", configured)),
        "configured_agent_is_default": configured == DEFAULT_AGENT,
        "configured": check(configured or DEFAULT_AGENT),
    }
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
