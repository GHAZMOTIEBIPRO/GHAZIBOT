"""One-off check of the SEC latest-filings feed and of COGT/BBIO first-source timing (public SEC data).

Uses SEC_USER_AGENT when set, else the repository's declared research agent (scripts/probe_free_sources.py),
one request per form plus the registrant list and two submissions files - far under SEC fair access.
Prints: entries per form, newest acceptance time and its age, filer rows resolved to a ticker, and for
COGT and BBIO the latest 8-K filings with EDGAR acceptance times and item codes (the first official source).
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone

from options_radar import sec_current_feed as scf
from scripts.probe_free_sources import DEFAULT_SEC_AGENT


def _get(url: str, agent: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": agent, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=30) as r:  # fixed SEC hosts
        return r.read()


def main() -> int:
    agent = (os.environ.get("SEC_USER_AGENT") or "").strip() or DEFAULT_SEC_AGENT
    now = datetime.now(timezone.utc)
    reg = json.loads(_get("https://www.sec.gov/files/company_tickers_exchange.json", agent))
    rows = [[t, str(c).zfill(10), n, e] for c, n, t, e in reg["data"] if e and t]
    registry = {"fields": ["ticker", "cik", "name", "exchange"], "rows": rows}
    mapping = scf.cik_map(registry)
    report: dict = {"registry_rows": len(rows), "forms": {}}
    for form in scf.FORMS:
        xml = _get(scf.FEED.format(form=form.replace(" ", "+")), agent).decode("utf-8", "replace")
        events = scf.parse(xml, mapping, now)
        newest = max((e["published"] for e in events if e["published"]), default=None)
        report["forms"][form] = {"filer_rows_with_ticker": len(events), "newest_published": newest,
                                 "newest_age_min": round((now - datetime.fromisoformat(newest)).total_seconds() / 60, 1)
                                 if newest else None}
    for symbol in ("COGT", "BBIO"):
        cik = next((r[1] for r in rows if r[0] == symbol), None)
        if not cik:
            report[symbol] = "not in SEC registrant list"
            continue
        sub = json.loads(_get(f"https://data.sec.gov/submissions/CIK{cik}.json", agent))
        recent = sub["filings"]["recent"]
        eightk = [{"form": f, "accepted": a, "items": i} for f, a, i in
                  zip(recent["form"], recent["acceptanceDateTime"], recent.get("items", [""] * len(recent["form"])),
                      strict=False) if f in ("8-K", "6-K")][:6]
        report[symbol] = {"cik": cik, "name": sub.get("name"), "latest_8k": eightk}
    print("SEC current probe:", json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
