from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

from . import phase61_intelligence
from .settings import Settings


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _collect_finra_reg_sho(
    client: requests.Session,
    settings: Settings,
    symbols: list[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    audit = {
        "provider": "finra_reg_sho",
        "configured": True,
        "success": False,
        "records": 0,
        "error": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    endpoint = "https://api.finra.org/data/group/OTCMarket/name/regShoDaily"
    output: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    end_date = date.today()
    start_date = end_date - timedelta(days=21)

    for symbol in symbols[:20]:
        try:
            response = client.post(
                endpoint,
                json={
                    "limit": 250,
                    "fields": [
                        "tradeReportDate",
                        "securitiesInformationProcessorSymbolIdentifier",
                        "shortParQuantity",
                        "shortExemptParQuantity",
                        "totalParQuantity",
                        "marketCode",
                        "reportingFacilityCode",
                    ],
                    "dateRangeFilters": [
                        {
                            "fieldName": "tradeReportDate",
                            "startDate": start_date.isoformat(),
                            "endDate": end_date.isoformat(),
                        }
                    ],
                    "compareFilters": [
                        {
                            "compareType": "equal",
                            "fieldName": "securitiesInformationProcessorSymbolIdentifier",
                            "fieldValue": symbol,
                        }
                    ],
                },
                headers={"Accept": "application/json"},
                timeout=settings.request_timeout_seconds,
            )
            response.raise_for_status()
            rows = response.json() or []
            if isinstance(rows, dict):
                rows = rows.get("data") or rows.get("results") or []
            valid = [row for row in rows if isinstance(row, dict) and row.get("tradeReportDate")]
            if not valid:
                continue

            latest_date = max(str(row.get("tradeReportDate")) for row in valid)
            latest_rows = [row for row in valid if str(row.get("tradeReportDate")) == latest_date]
            short_volume = sum(_number(row.get("shortParQuantity")) for row in latest_rows)
            short_exempt = sum(_number(row.get("shortExemptParQuantity")) for row in latest_rows)
            total_volume = sum(_number(row.get("totalParQuantity")) for row in latest_rows)
            facilities = sorted(
                {
                    str(row.get("reportingFacilityCode") or "").strip()
                    for row in latest_rows
                    if str(row.get("reportingFacilityCode") or "").strip()
                }
            )
            markets = sorted(
                {
                    str(row.get("marketCode") or "").strip()
                    for row in latest_rows
                    if str(row.get("marketCode") or "").strip()
                }
            )
            output[symbol] = {
                "source": "FINRA Reg SHO Daily Short Sale Volume",
                "trade_date": latest_date,
                "short_volume": round(short_volume, 2),
                "short_exempt_volume": round(short_exempt, 2),
                "total_volume": round(total_volume, 2),
                "short_volume_ratio": round(short_volume / total_volume, 4) if total_volume > 0 else None,
                "reporting_facilities": facilities,
                "market_codes": markets,
                "rows_aggregated": len(latest_rows),
                "context_only": True,
                "interpretation_note": "Daily short-sale volume is market context, not short interest and not a directional signal by itself.",
            }
        except Exception as exc:
            errors.append(f"{symbol}: {type(exc).__name__}: {exc}")

    audit["records"] = len(output)
    audit["success"] = bool(output)
    audit["date_window_start"] = start_date.isoformat()
    audit["date_window_end"] = end_date.isoformat()
    if errors:
        audit["error"] = " | ".join(errors[:5])
    elif not output:
        audit["error"] = "FINRA returned no matching Reg SHO records in the recent date window"
    return output, audit


def install_finra_reg_sho_fix() -> None:
    phase61_intelligence._collect_finra = _collect_finra_reg_sho
