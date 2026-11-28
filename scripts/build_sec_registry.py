"""SEC registrant list with tickers and exchanges (NYSE, NYSE American, Nasdaq, Cboe) for name matching.

Source: https://www.sec.gov/files/company_tickers_exchange.json - SEC.gov content is a U.S. Government
work; the SEC fair-access policy asks automated clients to declare a User-Agent with a contact and to
stay under 10 requests per second. Without SEC_USER_AGENT nothing is fetched (status NOT_ATTEMPTED)
and the previous copy is kept. Standard library only.

Output fields per row: ticker, cik, name, exchange. OTC and blank-exchange rows are dropped. The file
is used by options_radar.fda_events.registry_issuers as the matching layer that covers NYSE and
NYSE American issuers, which the NasdaqTrader file does not.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

URL = "https://www.sec.gov/files/company_tickers_exchange.json"
EXCHANGES = {"NYSE", "Nasdaq", "NYSE American", "NYSE Arca", "CBOE", "Cboe", "BATS"}
TERMS = ("SEC.gov content is a U.S. Government work; automated access must declare a User-Agent with a "
         "contact and stay under 10 requests/second (SEC fair-access policy).")


def build(payload: Any, now: datetime) -> dict[str, Any]:
    fields = payload.get("fields") if isinstance(payload, dict) else None
    rows_in = payload.get("data") if isinstance(payload, dict) else None
    if fields != ["cik", "name", "ticker", "exchange"] or not isinstance(rows_in, list):
        raise ValueError("unexpected SEC file layout")
    rows = [[str(t).upper(), str(c).zfill(10), str(n), str(e)] for c, n, t, e in rows_in
            if e in EXCHANGES and t and n]
    return {"schema": "ghazi.sec_registry.v1", "generated_at": now.isoformat(),
            "source": {"url": URL, "terms": TERMS}, "fields": ["ticker", "cik", "name", "exchange"],
            "counts": {"rows": len(rows), "by_exchange": {x: sum(1 for r in rows if r[3] == x) for x in
                                                         sorted({r[3] for r in rows})}},
            "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    agent = (os.environ.get("SEC_USER_AGENT") or "").strip()
    if not agent or "@" not in agent:
        print("SEC registry: NOT_ATTEMPTED (SEC_USER_AGENT with a contact e-mail is not set); previous copy kept")
        return 0
    request = urllib.request.Request(URL, headers={"User-Agent": agent, "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # fixed https host
            payload = json.loads(response.read().decode("utf-8"))
        result = build(payload, datetime.now(timezone.utc))
    except (OSError, ValueError) as exc:
        print("SEC registry: FAILED", type(exc).__name__, "- previous copy kept")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print("SEC registry:", json.dumps(result["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
