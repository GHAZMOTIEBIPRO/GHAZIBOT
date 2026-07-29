from __future__ import annotations

import csv
import io
import logging
import math
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger(__name__)

OCC_VOLUME_QUERY_URL = "https://marketdata.theocc.com/volume-query"
OCC_REPORT_TYPES = {"daily": "D", "weekly": "W", "monthly": "M"}
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


def _normalise_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text:
        return 0.0
    try:
        number = float(text)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _latest_business_dates(reference: date | None = None, lookback_days: int = 8) -> list[date]:
    current = reference or datetime.now(timezone.utc).date()
    dates: list[date] = []
    for offset in range(max(lookback_days, 1)):
        candidate = current - timedelta(days=offset)
        if candidate.weekday() < 5:
            dates.append(candidate)
    return dates


def _row_value(row: dict[str, Any], aliases: set[str]) -> Any:
    for key, value in row.items():
        if _normalise_key(key) in aliases:
            return value
    return None


def _contains_value(row: dict[str, Any], required: tuple[str, ...]) -> Any:
    for key, value in row.items():
        normalised = _normalise_key(key)
        if all(token in normalised for token in required):
            return value
    return None


def parse_occ_volume_csv(text: str) -> dict[str, Any]:
    """Parse OCC volume-query CSV across known aggregate and side-row layouts.

    OCC has changed report layouts over time. The parser therefore supports both
    aggregate columns (Call Volume / Put Volume) and row-oriented layouts where a
    P/C field accompanies a generic Volume field. Unknown layouts fail closed and
    are reported in the audit rather than silently inventing values.
    """

    clean = str(text or "").lstrip("\ufeff").strip()
    if not clean or clean.startswith("<"):
        raise ValueError("OCC response is empty or HTML instead of CSV")

    try:
        dialect = csv.Sniffer().sniff(clean[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(clean), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("OCC CSV has no header row")

    rows = [dict(row) for row in reader if row and any(str(value or "").strip() for value in row.values())]
    if not rows:
        raise ValueError("OCC CSV contains no data rows")

    call_aliases = {
        "call", "calls", "callvolume", "callvol", "callquantity",
        "callcontractvolume", "callsvolume", "cvolume",
    }
    put_aliases = {
        "put", "puts", "putvolume", "putvol", "putquantity",
        "putcontractvolume", "putsvolume", "pvolume",
    }
    side_aliases = {"porc", "putcall", "callput", "optiontype", "type", "side", "cp"}
    volume_aliases = {
        "volume", "totalvolume", "contractvolume", "quantity", "contracts",
        "clearedvolume", "tradevolume",
    }

    call_volume = 0.0
    put_volume = 0.0
    parsed_rows = 0

    for row in rows:
        direct_call = _row_value(row, call_aliases)
        direct_put = _row_value(row, put_aliases)
        if direct_call is None:
            direct_call = _contains_value(row, ("call", "vol"))
        if direct_put is None:
            direct_put = _contains_value(row, ("put", "vol"))

        used = False
        if direct_call is not None or direct_put is not None:
            call_volume += _number(direct_call)
            put_volume += _number(direct_put)
            used = True
        else:
            side = str(_row_value(row, side_aliases) or "").strip().upper()
            volume = _row_value(row, volume_aliases)
            if volume is None:
                volume = _contains_value(row, ("vol",))
            numeric_volume = _number(volume)
            if side in {"C", "CALL", "CALLS"}:
                call_volume += numeric_volume
                used = True
            elif side in {"P", "PUT", "PUTS"}:
                put_volume += numeric_volume
                used = True
        if used:
            parsed_rows += 1

    if parsed_rows == 0:
        raise ValueError(f"Unsupported OCC CSV layout: {reader.fieldnames}")

    total = call_volume + put_volume
    return {
        "call_volume": int(round(call_volume)),
        "put_volume": int(round(put_volume)),
        "total_volume": int(round(total)),
        "put_call_ratio": round(put_volume / call_volume, 4) if call_volume > 0 else None,
        "rows": len(rows),
        "parsed_rows": parsed_rows,
    }


class OccFreeVolumeClient:
    """No-key OCC volume-query client used as official market context only."""

    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        timeout: int = 25,
        min_interval_seconds: float = 0.20,
        user_agent: str | None = None,
    ) -> None:
        self.session = session or requests.Session()
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            status=2,
            backoff_factor=0.6,
            status_forcelist=sorted(_TRANSIENT_STATUS),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update(
            {
                "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.1",
                "User-Agent": user_agent
                or os.getenv("SEC_USER_AGENT")
                or "GHAZI Market Radar 207104176+GHAZMOTIEBIPRO@users.noreply.github.com",
            }
        )
        self.timeout = timeout
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self._last_request_at = 0.0

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.min_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def fetch_report(
        self,
        symbol: str,
        report_key: str,
        *,
        reference_date: date | None = None,
    ) -> dict[str, Any]:
        report_type = OCC_REPORT_TYPES[report_key]
        attempts: list[dict[str, Any]] = []
        for report_date in _latest_business_dates(reference_date):
            compact = report_date.strftime("%Y%m%d")
            params = {
                "reportDate": compact,
                "format": "csv",
                "volumeQueryType": "O",
                "symbolType": "U",
                "symbol": symbol.upper(),
                "reportType": report_type,
                "accountType": "ALL",
                "productKind": "ALL",
                "porc": "BOTH",
                "contractDt": compact,
            }
            self._wait()
            started = time.monotonic()
            try:
                response = self.session.get(OCC_VOLUME_QUERY_URL, params=params, timeout=self.timeout)
                elapsed_ms = int((time.monotonic() - started) * 1000)
                attempts.append(
                    {
                        "report_date": compact,
                        "status_code": response.status_code,
                        "elapsed_ms": elapsed_ms,
                    }
                )
                if response.status_code in {204, 404}:
                    continue
                response.raise_for_status()
                parsed = parse_occ_volume_csv(response.text)
                return {
                    "success": True,
                    "source": "OCC Volume Query",
                    "official": True,
                    "free_no_key": True,
                    "report_key": report_key,
                    "report_type": report_type,
                    "report_date": compact,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "context_only": True,
                    "not_live_quote": True,
                    "not_options_flow": True,
                    "attempts": attempts,
                    **parsed,
                }
            except (requests.RequestException, ValueError, csv.Error) as exc:
                attempts[-1]["error"] = f"{type(exc).__name__}: {exc}"
                LOGGER.warning("OCC %s report failed for %s on %s: %s", report_key, symbol, compact, exc)
                continue

        return {
            "success": False,
            "source": "OCC Volume Query",
            "official": True,
            "free_no_key": True,
            "report_key": report_key,
            "report_type": report_type,
            "context_only": True,
            "not_live_quote": True,
            "not_options_flow": True,
            "attempts": attempts,
            "error": "No parseable OCC report was available in the lookback window",
        }

    def fetch_symbol(self, symbol: str, *, reference_date: date | None = None) -> dict[str, Any]:
        reports = {
            key: self.fetch_report(symbol, key, reference_date=reference_date)
            for key in OCC_REPORT_TYPES
        }
        successful = sum(1 for item in reports.values() if item.get("success"))
        return {
            "symbol": symbol.upper(),
            "source": "OCC",
            "official": True,
            "free_no_key": True,
            "context_only": True,
            "successful_reports": successful,
            "reports": reports,
        }


def fetch_occ_contexts(
    symbols: list[str],
    *,
    client: OccFreeVolumeClient | None = None,
    enabled: bool | None = None,
) -> dict[str, dict[str, Any]]:
    if enabled is None:
        enabled = os.getenv("OCC_FREE_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
    if not enabled:
        return {}
    active_client = client or OccFreeVolumeClient()
    output: dict[str, dict[str, Any]] = {}
    for symbol in dict.fromkeys(str(value).upper() for value in symbols if value):
        output[symbol] = active_client.fetch_symbol(symbol)
    return output
