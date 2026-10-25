"""SEC size evidence for the catalyst watchlist issuers, kept as separate fields.

Writes issuer_sizes.json (schema ghazi.issuer_sizes.v2). Each symbol carries
independent fields, never merged into one "size":

- public_float_value: dei:EntityPublicFloat, the USD value of shares held by
  non-affiliates on the last business day of the second fiscal quarter, as
  reported on the annual-report cover. It is a dollar value, not a share
  count, and not market capitalisation.
- shares_outstanding: dei:EntityCommonStockSharesOutstanding (shares, cover
  page of the latest 10-K/10-Q), with its as-of date. Shares outstanding is
  not the float.
- sec_filer_status: the filer category on the SEC submissions record
  (large accelerated / accelerated / non-accelerated, smaller reporting
  company, emerging growth company) and the listed exchanges. It is a
  disclosure regime, not a market-cap class.
- market_cap: always UNVERIFIED here; it needs a current price from a source
  whose terms allow the use, and none is configured.
- float_shares: UNAVAILABLE; no permitted source for a share float.

Needs a real contact identity in SEC_USER_AGENT (SEC fair-access policy);
without it the job writes SEC_IDENTITY_MISSING. A 403 or 429 stops the run
(no retry loop). At most 8 requests per second (SEC asks for at most 10).
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
SHARES_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/dei/EntityCommonStockSharesOutstanding.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F"}
COVER_FORMS = ANNUAL_FORMS | {"10-Q", "10-Q/A"}
PAUSE_SECONDS = 0.125
MAX_SYMBOLS = 40
MARKET_CAP = {"status": "UNVERIFIED", "reason": "needs a current price from a permitted source; none configured"}
FLOAT_SHARES = {"status": "UNAVAILABLE", "reason": "no permitted source for share float"}


def _filing_url(cik: int, accn: Any) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{str(accn).replace('-', '')}/"


def _latest(concept: Any, unit: str, forms: set[str]) -> dict[str, Any] | None:
    rows = ((concept.get("units") or {}).get(unit) or []) if isinstance(concept, dict) else []
    usable = [r for r in rows if isinstance(r, dict) and r.get("form") in forms and not isinstance(r.get("val"), bool)
              and isinstance(r.get("val"), (int, float)) and r["val"] > 0 and r.get("end") and r.get("accn")]
    return max(usable, key=lambda r: (str(r["end"]), str(r.get("filed") or ""))) if usable else None


def latest_public_float(concept: dict[str, Any], cik: int) -> dict[str, Any] | None:
    """Newest annual-report public float in USD, with its as-of date and filing link."""
    best = _latest(concept, "USD", ANNUAL_FORMS)
    if best is None:
        return None
    return {"usd": float(best["val"]), "as_of": str(best["end"])[:10], "form": best["form"],
            "filed": best.get("filed"), "source_url": _filing_url(cik, best["accn"])}


def latest_shares_outstanding(concept: dict[str, Any], cik: int) -> dict[str, Any] | None:
    best = _latest(concept, "shares", COVER_FORMS)
    if best is None:
        return None
    return {"shares": int(best["val"]), "as_of": str(best["end"])[:10], "form": best["form"],
            "filed": best.get("filed"), "source_url": _filing_url(cik, best["accn"])}


def filer_status(submissions: dict[str, Any], cik: int) -> dict[str, Any] | None:
    category = str(submissions.get("category") or "").strip() if isinstance(submissions, dict) else ""
    if not category:
        return None
    parts = [p.strip() for p in category.replace("<br/>", "<br>").split("<br>") if p.strip()]
    exchanges = [str(x) for x in submissions.get("exchanges") or [] if x]
    return {"category": parts[0], "flags": parts[1:],
            "smaller_reporting_company": any(p.lower() == "smaller reporting company" for p in parts),
            "emerging_growth_company": any(p.lower() == "emerging growth company" for p in parts),
            "exchanges": exchanges,
            "source_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"}


def build(symbols: list[str], *, agent: str | None, session: Any = requests,
          now: datetime | None = None, pause: float = PAUSE_SECONDS) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    report: dict[str, Any] = {"schema": "ghazi.issuer_sizes.v2", "generated_at": now.isoformat(),
                              "source": "SEC XBRL company concepts (dei) + SEC submissions", "symbols": {},
                              "errors": {}, "research_only": True,
                              "fields": {"public_float_value": "USD held by non-affiliates; not market cap",
                                         "shares_outstanding": "cover-page shares; not float",
                                         "sec_filer_status": "SEC filing regime; not a market-cap class",
                                         "market_cap": MARKET_CAP, "float_shares": FLOAT_SHARES}}
    if not agent:
        return {**report, "status": "SEC_IDENTITY_MISSING"}
    try:
        cik_map = ticker_cik_map(_get(session, TICKERS_URL, agent))
    except Exception as exc:  # noqa: BLE001 - reported, never retried in a loop
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return {**report, "status": f"SEC_REFUSED_HTTP_{status}" if status else "SEC_UNAVAILABLE",
                "errors": {"ticker_map": type(exc).__name__}}
    stopped = False
    for symbol in symbols[:MAX_SYMBOLS]:
        if stopped:
            break
        if symbol not in cik_map:
            report["errors"][symbol] = "NO_SEC_CIK"
            continue
        cik = cik_map[symbol][0]
        row: dict[str, Any] = {"cik": cik, "public_float_value": None, "shares_outstanding": None,
                               "sec_filer_status": None, "market_cap": MARKET_CAP, "float_shares": FLOAT_SHARES}
        problems = []
        for field, url, parse in (("public_float_value", CONCEPT_URL, latest_public_float),
                                  ("shares_outstanding", SHARES_URL, latest_shares_outstanding),
                                  ("sec_filer_status", SUBMISSIONS_URL, filer_status)):
            try:
                row[field] = parse(_get(session, url.format(cik=cik), agent), cik)
            except Exception as exc:  # noqa: BLE001
                status = getattr(getattr(exc, "response", None), "status_code", None)
                problems.append(f"{field}:HTTP_{status}" if status else f"{field}:{type(exc).__name__}")
                if status in (403, 429):
                    stopped = True
                    break
            finally:
                time.sleep(pause)
        if problems:
            report["errors"][symbol] = ";".join(problems)
        if any(row[f] for f in ("public_float_value", "shares_outstanding", "sec_filer_status")):
            report["symbols"][symbol] = row
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
    agent = (os.getenv("SEC_USER_AGENT") or "").strip() or None
    # Only booleans and counts are logged; the identity itself never is.
    print("SEC identity configured:", bool(agent))
    report = build(symbols, agent=agent)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Issuer sizes:", report["status"], len(report["symbols"]), "issuers;", len(report["errors"]), "errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
