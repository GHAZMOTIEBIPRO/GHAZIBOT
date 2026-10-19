"""Free, provenance-aware options and filings source pulse.

- FilingPulse health is public/no-key. Private free-key event queries are
  scoped to a small, fixed issuer set (CIK not ticker-name inference).
- OCC's official daily open-interest CSV is tried at most once per run,
  with bounded bytes and fail-closed schema. OCC is never a live quote.
- Tradier is already integrated elsewhere, requires the account token and
  personal-use permissions. This script never uses its trading endpoints.

No order/trading routes. A third-party filing feed is NOT a verified
independent SEC live API response, even if it cites an authentic SEC URL.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

FILINGPULSE = "https://api.filingpulse.io"
OCC = "https://marketdata.theocc.com/daily-open-interest"
SYMBOLS = ("AAPL", "NVDA", "TSLA", "SOFI")
ACC = re.compile(r"^\d{10}-\d{2}-\d{6}$")
SAFE_CIK = re.compile(r"^\d{1,10}$")
MAX_RESPONSE = 1_000_000
MAX_OCC_BYTES = 25_000_000
MAX_API_CALLS = 12


def _json_get(session: Any, url: str, *, params: dict | None = None,
              headers: dict | None = None) -> tuple[dict | None, int | None]:
    try:
        response = session.get(url, params=params, headers=headers or {},
                               timeout=14)
        code = response.status_code
        if code != 200 or len(response.content) > MAX_RESPONSE:
            return None, code
        result = response.json()
        return (result if isinstance(result, dict) else None), code
    except (requests.RequestException, ValueError, TypeError):
        return None, None


def _date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    original = value.strip()
    if re.fullmatch(r"\d{8}", original):
        original = f"{original[:4]}-{original[4:6]}-{original[6:]}"
    try:
        return date.fromisoformat(original).isoformat()
    except ValueError:
        return None


def _official_sec_link(link: Any) -> str | None:
    if not isinstance(link, str) or len(link) > 350:
        return None
    from urllib.parse import urlparse

    p = urlparse(link)
    if (p.scheme == "https" and p.netloc.lower() in {"www.sec.gov", "sec.gov"}
            and p.path.startswith("/Archives/edgar/data/")
            and not p.username and not p.password and not p.query and not p.fragment):
        return link
    return None


def _issuer_records(response: Any, *, symbol: str, cik: int,
                    kind: str, since: date, until: date) -> list[dict]:
    if not isinstance(response, dict) or not isinstance(response.get("data"), list):
        return []
    if len(response["data"]) > 50:
        return []
    output = []
    for row in response["data"]:
        if not isinstance(row, dict):
            continue
        issuer = row.get("issuer")
        if not isinstance(issuer, dict):
            continue
        try:
            matched = int(issuer.get("cik", -1)) == cik
        except (ValueError, TypeError):
            matched = False
        if not matched:
            continue
        if kind == "insider":
            reported_symbol = issuer.get("ticker")
            if not isinstance(reported_symbol, str) or reported_symbol.upper() != symbol:
                continue
        filed = _date(row.get("filed_date"))
        acc = row.get("accession")
        if (filed is None or not since.isoformat() <= filed <= until.isoformat()
                or not isinstance(acc, str) or not ACC.fullmatch(acc)):
            continue
        link = _official_sec_link(row.get("source_url"))
        if kind != "insider" and link is None:
            continue
        items = row.get("items")
        codes = []
        if kind == "event" and isinstance(items, list):
            for item in items[:20]:
                code = item.get("code") if isinstance(item, dict) else None
                if (isinstance(code, str) and
                        re.fullmatch(r"\d{1,2}\.\d{2}", code) and
                        code not in codes):
                    codes.append(code)
        form = row.get("form_type")
        form = form if isinstance(form, str) and len(form) <= 12 else "UNKNOWN"
        if kind == "event" and form not in {"8-K", "8-K/A"}:
            continue
        if kind == "registration" and form not in {
            "S-1", "S-1/A", "F-1", "F-1/A", "EFFECT", "424B1", "424B4",
        }:
            continue
        if kind == "insider" and form not in {"3", "3/A", "4", "4/A", "5", "5/A"}:
            continue
        output.append({
            "symbol": symbol, "cik": cik,
            "filed_date": filed, "form": form,
            "accession": acc, "source_url": link,
            "item_codes": codes, "kind": kind,
            "third_party_source": "FILINGPULSE_SEC_DERIVED",
            "official_sec_api_response_verified": False,
            "original_filing_live_confirmed": False,
            "positive_catalyst_verified": False,
            "option_execution_eligible": False,
        })
    return output[:30]


def _read_ciks(path: Path) -> dict[str, int]:
    try:
        if path.stat().st_size > 30_000:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    result = {}
    for sym in SYMBOLS:
        raw = data.get(sym)
        if isinstance(raw, str) and SAFE_CIK.fullmatch(raw):
            result[sym] = int(raw)
    return result


def filingpulse_snapshot(*, key: str, ciks: dict[str, int], now: datetime,
                         session: Any) -> dict:
    body = {
        "provider": "FilingPulse",
        "source_role": "THIRD_PARTY_SEC_DERIVED_NOT_OFFICIAL_LIVE_SEC",
        "free_tier": True, "requests_max_per_run": MAX_API_CALLS,
        "health_reachable": False, "events": [],
        "status": "UNAVAILABLE", "api_calls_attempted": 0,
        "quota_exhausted": False, "research_only": True,
    }
    health, status = _json_get(session, FILINGPULSE + "/v1/health")
    body["health_reachable"] = bool(status == 200 and health)
    if not key:
        body["status"] = "NO_API_KEY_HEALTH_ONLY" if body["health_reachable"] else "NO_API_KEY"
        return body
    if not ciks:
        body["status"] = "NO_VERIFIED_CIK_CANDIDATES"
        return body
    since = now.date() - timedelta(days=5)
    until = now.date()
    records = {}
    headers = {"X-API-Key": key, "Accept": "application/json"}
    for symbol, cik in ciks.items():
        for kind, endpoint in [
            ("event", "/v1/events"),
            ("registration", "/v1/registrations"),
            ("insider", "/v1/insider-trades"),
        ]:
            if body["api_calls_attempted"] >= MAX_API_CALLS:
                break
            body["api_calls_attempted"] += 1
            data, code = _json_get(
                session, FILINGPULSE + endpoint,
                params={"cik": str(cik), "since": since.isoformat(),
                        "until": until.isoformat(), "limit": 30},
                headers=headers,
            )
            if code == 429:
                body["quota_exhausted"] = True
                body["status"] = "RATE_LIMIT_OR_QUOTA_EXHAUSTED"
                body["events"] = list(records.values())[:45]
                return body
            if code in (401, 403):
                body["status"] = "ACCOUNT_PERMISSION_OR_KEY_FAILURE"
                return body
            for row in _issuer_records(
                data, symbol=symbol, cik=cik,
                kind=kind, since=since, until=until,
            ):
                records.setdefault((row["accession"], row["kind"]), row)
    body["events"] = sorted(
        records.values(), key=lambda x: x["filed_date"], reverse=True
    )[:45]
    body["status"] = "THIRD_PARTY_RESEARCH_ONLY" if records else "NO_VERIFIED_RECENT_METADATA"
    return body


def parse_occ_oi_csv(raw: str, *, watched: set[str]) -> dict:
    """Strictly names underlying and dated contract; no inferred OI or flows.

    Large/unrecognized OCC layouts return UNAVAILABLE, not guessed columns.
    """
    if not isinstance(raw, str) or not raw.strip() or raw.lstrip().startswith("<"):
        return {"status": "UNPARSEABLE_CSV", "matched": 0}
    rows = csv.DictReader(io.StringIO(raw))
    if not rows.fieldnames:
        return {"status": "UNKNOWN_LAYOUT", "matched": 0}
    mapping = {re.sub(r"[^a-z0-9]", "", key.lower()): key
               for key in rows.fieldnames if isinstance(key, str)}
    def col(*keys: str) -> str | None:
        return next((mapping[k] for k in keys if k in mapping), None)
    symkey = col("underlyingsymbol", "underlying", "underlier", "symbol")
    oikey = col("openinterest", "openint", "oi")
    if not symkey or not oikey:
        return {"status": "UNKNOWN_LAYOUT", "matched": 0}
    totals = {}
    count = 0
    for row in rows:
        if count > 500_000:
            return {"status": "TOO_MANY_ROWS", "matched": 0}
        count += 1
        sym = str(row.get(symkey) or "").strip().upper()
        if sym not in watched:
            continue
        rawoi = str(row.get(oikey) or "").strip().replace(",", "")
        if not re.fullmatch(r"\d{1,11}", rawoi):
            return {"status": "INVALID_OI", "matched": 0}
        totals[sym] = totals.get(sym, 0) + int(rawoi)
    return {
        "status": "HISTORICAL_DAILY_AGGREGATE" if totals else "NO_WATCHED_SYMBOLS",
        "matched": len(totals),
        "watched_oi": totals,
        "not_live_quote": True, "not_trade_flow": True,
        "contract_specific_executable": False,
    }


def occ_open_interest_snapshot(*, now: datetime, session: Any,
                               enabled: bool) -> dict:
    base = {"source": "OCC_DAILY_OPEN_INTEREST",
            "status": "DISABLED", "context_only": True,
            "not_live_quote": True, "not_trade_flow": True,
            "open_interest": None, "report_date": None}
    if not enabled:
        return base
    # Once per job, previous calendar weekday only. No loops on 403.
    day = now.date() - timedelta(days=1)
    while day.weekday() > 4:
        day -= timedelta(days=1)
    try:
        response = session.get(
            OCC,
            params={"dailyDate": day.strftime("%m/%d/%Y"),
                    "action": "download", "format": "csv"},
            timeout=18, stream=True,
            headers={"Accept": "text/csv,text/plain;q=0.9"},
        )
        if response.status_code != 200:
            return {**base, "status": f"HTTP_{response.status_code}"}
        chunks, size = [], 0
        for chunk in response.iter_content(chunk_size=65536):
            size += len(chunk)
            if size > MAX_OCC_BYTES:
                return {**base, "status": "BULK_TOO_LARGE"}
            chunks.append(chunk)
        content = b"".join(chunks)
        parsed = parse_occ_oi_csv(
            content.decode("utf-8-sig"),
            watched=set(SYMBOLS),
        )
        if parsed["status"] != "HISTORICAL_DAILY_AGGREGATE":
            return {**base, "status": parsed["status"]}
        return {
            **base, "status": parsed["status"],
            "open_interest": parsed["watched_oi"],
            "report_date": day.isoformat(),
        }
    except (requests.RequestException, ValueError, UnicodeError):
        return {**base, "status": "REQUEST_OR_FORMAT_ERROR"}


def collect(*, now: datetime, key: str = "", ciks: dict | None = None,
            occ_enabled: bool = False, session: Any = requests) -> dict:
    if now.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    pulse = filingpulse_snapshot(
        key=key, ciks=ciks or {}, now=now, session=session,
    )
    oi = occ_open_interest_snapshot(
        now=now, session=session, enabled=occ_enabled,
    )
    return {
        "schema": "ghazi.free_options_source_pulse.v1",
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "research_only": True, "trading_authority": False,
        "option_execution_eligible": False,
        "filingpulse": pulse, "occ_open_interest": oi,
        "tradier": {
            "integration": "EXISTING_TRADIER_OPTIONS_PROVIDER",
            "public_api_reuse_permitted": False,
            "account_permission_required": True,
            "source_quotes_published": False,
            "status": "ACCOUNT_ENTITLEMENT_NOT_ASSERTED",
        },
        "policy": {
            "no_real_time_opra_claim": True,
            "third_party_filings_not_official_sec_confirmation": True,
            "no_automatic_options_orders": True,
            "no_licensed_quote_redistribution": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cik-map", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = collect(
        now=datetime.now(timezone.utc),
        key=os.getenv("FILINGPULSE_API_KEY", ""),
        ciks=_read_ciks(args.cik_map),
        occ_enabled=os.getenv("OCC_DAILY_OI_ENABLED") == "true",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    dest = args.output.with_suffix(".tmp")
    dest.write_text(
        json.dumps(result, separators=(",", ":"), ensure_ascii=False,
                   allow_nan=False) + "\n", encoding="utf-8",
    )
    dest.replace(args.output)
    print("FilingPulse", result["filingpulse"]["status"],
          "OCC OI", result["occ_open_interest"]["status"],
          "Tradier account needed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
