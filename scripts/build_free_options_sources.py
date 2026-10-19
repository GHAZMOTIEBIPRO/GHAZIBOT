"""Free, provenance-aware options and filings source pulse.

- FilingPulse health is public/no-key. Private free-key event queries are
  scoped to a small, fixed issuer set (CIK not ticker-name inference).
- OCC's market-wide Daily Open Interest report dates the latest OI
  publication; OCC Series Search gives per-series OI for a few symbols
  (undated, labelled as a retrieval snapshot). Bounded bytes, fail-closed
  schema, adjusted series excluded. OCC is never a live quote.
- Tradier is already integrated elsewhere, requires the account token and
  personal-use permissions. This script never uses its trading endpoints.

No order/trading routes. A third-party filing feed is NOT a verified
independent SEC live API response, even if it cites an authentic SEC URL.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

FILINGPULSE = "https://api.filingpulse.io"
OCC = "https://marketdata.theocc.com/daily-open-interest"
OCC_SERIES = "https://marketdata.theocc.com/series-search"
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


def _occ_count(value: Any) -> int | None:
    text = str(value or "").strip().replace(",", "")
    return int(text) if re.fullmatch(r"\d{1,12}", text) else None


def _schema_names(lines: list[str]) -> list[str]:
    """Normalized header *names* only, never series values or counts."""
    names: list[str] = []
    for line in lines[:6]:
        for cell in re.split(r"[,\t]", line)[:15]:
            key = re.sub(r"[^a-z]", "", cell.lower())
            if key and len(key) <= 40 and key not in names:
                names.append(key)
    return names[:20]


def parse_occ_market_oi(raw: str) -> dict:
    """OCC Daily Open Interest: a *market-wide* monthly report.

    Verified layout (runner probe, Oct 2026): a title line, a two-row
    category header (Equity / Index/Other / Debt / Futures / OCC Total,
    then Calls / Puts / Total) and one dated row per business day. It has
    no per-symbol rows, so it can only date OCC's latest OI publication.
    """
    if not isinstance(raw, str) or not raw.strip() or raw.lstrip().startswith("<"):
        return {"status": "UNPARSEABLE_CSV"}
    lines = [line for line in raw.lstrip("\ufeff").splitlines() if line.strip()]
    rows = list(csv.reader(lines[:80]))
    top = next((i for i, row in enumerate(rows[:10])
                if row and row[0].strip().lower() == "date"
                and any(c.strip().lower() == "equity" for c in row)
                and any(c.strip().lower() == "occ total" for c in row)), None)
    if top is None or top + 1 >= len(rows):
        return {"status": "UNKNOWN_LAYOUT",
                "safe_schema_column_names": _schema_names(lines)}
    sub = [c.strip().lower() for c in rows[top + 1]]
    if sub[1:4] != ["calls", "puts", "total"]:
        return {"status": "UNKNOWN_LAYOUT",
                "safe_schema_column_names": _schema_names(lines)}
    occ_total = next(i for i, c in enumerate(rows[top]) if c.strip().lower() == "occ total")
    latest = None
    for row in rows[top + 2:]:
        try:
            day = datetime.strptime(row[0].strip(), "%m/%d/%Y").replace(
                tzinfo=timezone.utc).date()
        except (ValueError, IndexError):
            return {"status": "INVALID_ROW"}
        values = [_occ_count(row[i]) if i < len(row) else None
                  for i in (1, 2, 3, occ_total)]
        if any(v is None for v in values) or values[0] + values[1] != values[2]:
            return {"status": "INVALID_ROW"}
        if latest is None or day > latest[0]:
            latest = (day, values)
    if latest is None:
        return {"status": "NO_DATED_ROWS"}
    day, (calls, puts, total, overall) = latest
    return {
        "status": "MARKET_WIDE_DAILY_TOTALS",
        "report_date": day.isoformat(),
        "equity_call_oi": calls, "equity_put_oi": puts,
        "equity_total_oi": total, "occ_total_oi": overall,
    }


def parse_occ_series_oi(raw: str, *, symbol: str) -> dict:
    """OCC Series Search: per-series call/put open interest for one underlying.

    Verified layout: title lines, a header row ``ProductSymbol year Month
    Day Integer Dec C/P Call Put Position Limit`` and tab-separated rows
    with an empty cell after the product symbol. The response carries no
    as-of date. Adjusted/non-standard products (e.g. ``2AAPL``) are
    counted as excluded, never merged into the standard symbol's totals.
    """
    if not isinstance(raw, str) or not raw.strip() or raw.lstrip().startswith("<"):
        return {"status": "UNPARSEABLE_TEXT"}
    lines = raw.lstrip("\ufeff").splitlines()
    header = next((i for i, line in enumerate(lines[:20])
                   if [c.strip().lower() for c in line.split("\t")][:9] ==
                   ["productsymbol", "year", "month", "day", "integer", "dec",
                    "c/p", "call", "put"]), None)
    if header is None:
        return {"status": "UNKNOWN_LAYOUT",
                "safe_schema_column_names": _schema_names(lines[3:])}
    calls = puts = standard = excluded = 0
    for count, line in enumerate(lines[header + 1:]):
        if count > 50_000:
            return {"status": "TOO_MANY_ROWS"}
        if not line.strip():
            continue
        cells = [c.strip() for c in line.split("\t")]
        if len(cells) < 10 or cells[1] != "":
            return {"status": "INVALID_ROW"}
        product, year, month, day, strike, dec, side, call_oi, put_oi = (
            cells[0], *cells[2:10])
        valid = (re.fullmatch(r"\d?[A-Z]{1,6}\d?", product)
                 and re.fullmatch(r"20\d\d", year)
                 and re.fullmatch(r"\d{1,2}", month) and 1 <= int(month) <= 12
                 and re.fullmatch(r"\d{1,2}", day) and 1 <= int(day) <= 31
                 and re.fullmatch(r"\d{1,6}", strike) and re.fullmatch(r"\d{1,3}", dec)
                 and side in ("C", "P", "C P"))
        call_n, put_n = _occ_count(call_oi), _occ_count(put_oi)
        if not valid or call_n is None or put_n is None:
            return {"status": "INVALID_ROW"}
        if product != symbol:
            excluded += 1
            continue
        standard += 1
        calls += call_n if "C" in side else 0
        puts += put_n if "P" in side else 0
    if not standard:
        return {"status": "NO_STANDARD_SERIES", "nonstandard_series_excluded": excluded}
    return {
        "status": "SERIES_OPEN_INTEREST",
        "call_oi": calls, "put_oi": puts, "total_oi": calls + puts,
        "put_call_oi_ratio": round(puts / calls, 4) if calls else None,
        "standard_series": standard, "nonstandard_series_excluded": excluded,
    }


def _occ_text(session: Any, url: str, params: dict) -> tuple[str | None, str]:
    try:
        response = session.get(
            url, params=params, timeout=18, stream=True,
            headers={"Accept": "text/csv,text/plain;q=0.9"},
        )
        if response.status_code != 200:
            return None, f"HTTP_{response.status_code}"
        chunks, size = [], 0
        for chunk in response.iter_content(chunk_size=65536):
            size += len(chunk)
            if size > MAX_OCC_BYTES:
                return None, "BULK_TOO_LARGE"
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8-sig"), "OK"
    except (requests.RequestException, ValueError, UnicodeError):
        return None, "REQUEST_OR_FORMAT_ERROR"


def occ_open_interest_snapshot(*, now: datetime, session: Any,
                               enabled: bool, pause: float = 1.5) -> dict:
    base = {"source": "OCC_DAILY_OPEN_INTEREST",
            "status": "DISABLED", "context_only": True,
            "not_live_quote": True, "not_trade_flow": True,
            "open_interest": None, "report_date": None}
    if not enabled:
        return base
    # The market-wide report is the only OCC response that states an OI
    # date; it is requested once with the previous calendar weekday.
    day = now.date() - timedelta(days=1)
    while day.weekday() > 4:
        day -= timedelta(days=1)
    text, fetch = _occ_text(session, OCC, {
        "reportDate": day.strftime("%m/%d/%Y"),
        "action": "download", "format": "csv"})
    market = parse_occ_market_oi(text) if text is not None else {"status": fetch}
    if market["status"] != "MARKET_WIDE_DAILY_TOTALS":
        return {**base, "status": market["status"],
                "safe_schema_column_names": market.get("safe_schema_column_names", [])}
    age = (now.date() - date.fromisoformat(market["report_date"])).days
    if not 0 <= age <= 7:
        return {**base, "status": "STALE_MARKET_REPORT",
                "market_wide": market}
    per_symbol: dict[str, dict] = {}
    for index, symbol in enumerate(SYMBOLS):
        if index and pause:
            time.sleep(pause)
        text, fetch = _occ_text(session, OCC_SERIES,
                                {"symbolType": "U", "symbol": symbol})
        parsed = (parse_occ_series_oi(text, symbol=symbol)
                  if text is not None else {"status": fetch})
        per_symbol[symbol] = parsed
        if fetch.startswith("HTTP_4"):
            break
    totals = {sym: item["total_oi"] for sym, item in per_symbol.items()
              if item["status"] == "SERIES_OPEN_INTEREST"}
    return {
        **base,
        "source": "OCC_PUBLIC_MARKET_DATA",
        "status": "HISTORICAL_DAILY_AGGREGATE" if totals else "MARKET_WIDE_ONLY",
        # report_date dates OCC's market-wide publication. Series search
        # responses carry no as-of date; their totals are a snapshot taken
        # at per_symbol_retrieved_at and are never relabelled as dated.
        "report_date": market["report_date"],
        "report_date_scope": "OCC_MARKET_WIDE_DAILY_REPORT",
        "market_wide": market,
        "open_interest": totals or None,
        "per_symbol": per_symbol,
        "per_symbol_as_of_verified": False,
        "per_symbol_retrieved_at": now.astimezone(timezone.utc).isoformat(),
        "adjusted_series_excluded": True,
    }


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
