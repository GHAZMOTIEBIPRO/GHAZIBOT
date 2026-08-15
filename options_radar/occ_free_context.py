from __future__ import annotations

import csv
import io
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

OCC_VOLUME_QUERY_URL = "https://marketdata.theocc.com/volume-query"


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _number(value: Any) -> float:
    text = str(value or "").strip().replace(",", "").replace("$", "")
    try:
        number = float(text)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _value(row: dict[str, Any], aliases: set[str]) -> Any:
    for name, value in row.items():
        if _key(name) in aliases:
            return value
    return None


def parse_occ_volume_csv(text: str) -> dict[str, Any]:
    clean = str(text or "").lstrip("\ufeff").strip()
    if not clean or clean.startswith("<"):
        raise ValueError("OCC response is empty or HTML")
    try:
        dialect = csv.Sniffer().sniff(clean[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(clean), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("OCC CSV has no header")
    rows = [dict(row) for row in reader if row and any(str(value or "").strip() for value in row.values())]
    if not rows:
        raise ValueError("OCC CSV has no data rows")

    call_aliases = {"call", "calls", "callvolume", "callvol", "callcontractvolume", "cvolume"}
    put_aliases = {"put", "puts", "putvolume", "putvol", "putcontractvolume", "pvolume"}
    side_aliases = {"porc", "putcall", "callput", "optiontype", "type", "side", "cp", "pc"}
    volume_aliases = {"volume", "totalvolume", "contractvolume", "quantity", "contracts", "tradevolume"}

    calls = puts = 0.0
    parsed = 0
    for row in rows:
        direct_call = _value(row, call_aliases)
        direct_put = _value(row, put_aliases)
        used = False
        if direct_call is not None or direct_put is not None:
            calls += _number(direct_call)
            puts += _number(direct_put)
            used = True
        else:
            side = str(_value(row, side_aliases) or "").strip().upper()
            volume = _number(_value(row, volume_aliases))
            if side in {"C", "CALL", "CALLS"}:
                calls += volume
                used = True
            elif side in {"P", "PUT", "PUTS"}:
                puts += volume
                used = True
        parsed += int(used)
    if parsed == 0:
        raise ValueError(f"Unsupported OCC CSV layout: {reader.fieldnames}")
    total = calls + puts
    return {
        "call_volume": int(round(calls)),
        "put_volume": int(round(puts)),
        "total_volume": int(round(total)),
        "put_call_ratio": round(puts / calls, 4) if calls > 0 else None,
        "parsed_rows": parsed,
    }


def _business_dates(reference: date | None = None, limit: int = 6) -> list[date]:
    current = reference or datetime.now(timezone.utc).date()
    output: list[date] = []
    offset = 0
    while len(output) < limit and offset < 14:
        candidate = current - timedelta(days=offset)
        if candidate.weekday() < 5:
            output.append(candidate)
        offset += 1
    return output


class OccDailyVolumeClient:
    """Official no-key OCC aggregate CALL/PUT volume; context only, never flow proof."""

    def __init__(self, timeout: int = 20, session: requests.Session | None = None) -> None:
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.1",
                "User-Agent": "GHAZI BLACK BOX Omega options research",
            }
        )

    def fetch(self, symbol: str, reference_date: date | None = None) -> dict[str, Any]:
        attempts: list[dict[str, Any]] = []
        for report_date in _business_dates(reference_date):
            compact = report_date.strftime("%Y%m%d")
            params = {
                "reportDate": compact,
                "format": "csv",
                "volumeQueryType": "O",
                "symbolType": "U",
                "symbol": symbol.upper(),
                "reportType": "D",
                "accountType": "ALL",
                "productKind": "ALL",
                "porc": "BOTH",
                "contractDt": compact,
            }
            try:
                response = self.session.get(OCC_VOLUME_QUERY_URL, params=params, timeout=self.timeout)
                attempts.append({"report_date": compact, "status_code": response.status_code})
                if response.status_code in {204, 404}:
                    continue
                response.raise_for_status()
                parsed = parse_occ_volume_csv(response.text)
                return {
                    "success": True,
                    "official": True,
                    "free_no_key": True,
                    "source": "OCC Volume Query",
                    "report_date": compact,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "context_only": True,
                    "not_live_quote": True,
                    "not_transaction_flow": True,
                    "attempts": attempts,
                    **parsed,
                }
            except (requests.RequestException, ValueError, csv.Error) as exc:
                if attempts:
                    attempts[-1]["error"] = f"{type(exc).__name__}: {exc}"
        return {
            "success": False,
            "official": True,
            "free_no_key": True,
            "source": "OCC Volume Query",
            "context_only": True,
            "attempts": attempts,
            "error": "No parseable OCC daily report in lookback window",
        }


def side_alignment(context: dict[str, Any], side: str) -> dict[str, Any]:
    if not context.get("success"):
        return {"available": False, "aligned": None, "dominance_ratio": None, "bonus": 0.0}
    calls = _number(context.get("call_volume"))
    puts = _number(context.get("put_volume"))
    current = calls if side.lower() == "call" else puts
    opposite = puts if side.lower() == "call" else calls
    ratio = current / opposite if opposite > 0 else (99.0 if current > 0 else 1.0)
    aligned = ratio >= 1.08
    opposed = ratio <= 0.92
    bonus = min(3.0, max(0.0, (ratio - 1.0) * 3.0)) if aligned else (-2.0 if opposed else 0.0)
    return {
        "available": True,
        "aligned": aligned,
        "opposed": opposed,
        "dominance_ratio": round(ratio, 4),
        "bonus": round(bonus, 2),
        "call_volume": int(calls),
        "put_volume": int(puts),
        "report_date": context.get("report_date"),
        "source": "OCC Volume Query",
        "context_only": True,
    }
