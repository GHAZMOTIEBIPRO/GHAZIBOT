"""SEC public float for the catalyst watchlist issuers (size classification input).

Reads dei:EntityPublicFloat from the SEC XBRL company-concept API for the
symbols in catalyst_watchlist.json and writes issuer_sizes.json:
{symbols: {SYM: {public_float_usd, public_float_as_of, form, source_url}}}.

- Needs a real contact identity in SEC_USER_AGENT (SEC fair-access policy);
  without it the job writes a SEC_IDENTITY_MISSING report and asks nothing
  else. A 403 or 429 stops the run (no retry loop) and is reported as such.
- Public float is the aggregate market value of shares held by
  non-affiliates on the last business day of the second fiscal quarter, as
  reported on the 10-K cover. It is not market capitalisation and is never
  converted into one here.
- At most 8 requests per second (SEC asks for no more than 10).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from scripts.build_sec_filing_pulse import TICKERS_URL, _get, ticker_cik_map

CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/dei/EntityPublicFloat.json"
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F"}
PAUSE_SECONDS = 0.125
MAX_SYMBOLS = 40


def latest_public_float(concept: dict[str, Any], cik: int) -> dict[str, Any] | None:
    """Newest annual-report public float in USD, with its as-of date and filing link."""
    rows = ((concept.get("units") or {}).get("USD") or []) if isinstance(concept, dict) else []
    usable = [r for r in rows if isinstance(r, dict) and r.get("form") in ANNUAL_FORMS
              and isinstance(r.get("val"), (int, float)) and r["val"] > 0 and r.get("end") and r.get("accn")]
    if not usable:
        return None
    best = max(usable, key=lambda r: (str(r["end"]), str(r.get("filed") or "")))
    accession = str(best["accn"]).replace("-", "")
    return {"public_float_usd": float(best["val"]), "public_float_as_of": str(best["end"])[:10],
            "form": best["form"], "filed": best.get("filed"),
            "source_url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/"}


def build(symbols: list[str], *, agent: str | None, session: Any = requests,
          now: datetime | None = None, pause: float = PAUSE_SECONDS) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    report: dict[str, Any] = {"schema": "ghazi.issuer_sizes.v1", "generated_at": now.isoformat(),
                              "source": "SEC XBRL company concept dei:EntityPublicFloat", "symbols": {},
                              "errors": {}, "research_only": True}
    if not agent:
        return {**report, "status": "SEC_IDENTITY_MISSING"}
    try:
        cik_map = ticker_cik_map(_get(session, TICKERS_URL, agent))
    except Exception as exc:  # noqa: BLE001 - reported, never retried in a loop
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return {**report, "status": f"SEC_REFUSED_HTTP_{status}" if status else "SEC_UNAVAILABLE",
                "errors": {"ticker_map": type(exc).__name__}}
    for symbol in symbols[:MAX_SYMBOLS]:
        if symbol not in cik_map:
            report["errors"][symbol] = "NO_SEC_CIK"
            continue
        cik = cik_map[symbol][0]
        try:
            row = latest_public_float(_get(session, CONCEPT_URL.format(cik=cik), agent), cik)
        except Exception as exc:  # noqa: BLE001
            status = getattr(getattr(exc, "response", None), "status_code", None)
            report["errors"][symbol] = f"HTTP_{status}" if status else type(exc).__name__
            if status in (403, 429):
                break
            continue
        finally:
            time.sleep(pause)
        if row is None:
            report["errors"][symbol] = "NO_ANNUAL_PUBLIC_FLOAT"
        else:
            report["symbols"][symbol] = {**row, "cik": cik}
    report["status"] = "OK" if report["symbols"] else "NO_SIZES"
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchlist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        watch = json.loads(args.watchlist.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        watch = {}
    symbols = [e.get("symbol") for e in watch.get("watchlist") or [] if isinstance(e, dict) and e.get("symbol")]
    report = build(symbols, agent=(os.getenv("SEC_USER_AGENT") or "").strip() or None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Issuer sizes:", report["status"], len(report["symbols"]), "sized;", len(report["errors"]), "errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
