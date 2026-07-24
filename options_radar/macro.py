from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import requests

from .settings import Settings

LOGGER = logging.getLogger(__name__)
TREASURY_XML = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
FRED_OBSERVATIONS = "https://api.stlouisfed.org/fred/series/observations"

TREASURY_FIELDS = {
    "BC_3MONTH": "treasury_3m",
    "BC_2YEAR": "treasury_2y",
    "BC_10YEAR": "treasury_10y",
    "BC_30YEAR": "treasury_30y",
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def fetch_treasury_curve(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    response = requests.get(
        TREASURY_XML,
        params={"data": "daily_treasury_yield_curve", "field_tdr_date_value": now.year},
        timeout=30,
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)
    rows: list[dict[str, Any]] = []
    for entry in root.iter():
        if _local(entry.tag) != "properties":
            continue
        row: dict[str, Any] = {}
        for child in entry:
            key = _local(child.tag)
            text = (child.text or "").strip()
            if not text:
                continue
            if key == "NEW_DATE":
                row["date"] = text
            elif key in TREASURY_FIELDS:
                try:
                    row[TREASURY_FIELDS[key]] = float(text)
                except ValueError:
                    pass
        if row.get("date"):
            rows.append(row)
    if not rows:
        raise RuntimeError("Treasury XML feed returned no yield-curve rows")
    rows.sort(key=lambda row: str(row.get("date", "")))
    latest = rows[-1]
    two = latest.get("treasury_2y")
    ten = latest.get("treasury_10y")
    three_month = latest.get("treasury_3m")
    latest["curve_10y_2y"] = round(float(ten) - float(two), 4) if ten is not None and two is not None else None
    latest["curve_10y_3m"] = round(float(ten) - float(three_month), 4) if ten is not None and three_month is not None else None
    slope = latest.get("curve_10y_2y")
    latest["curve_state"] = "inverted" if isinstance(slope, (int, float)) and slope < 0 else "normal"
    latest["source"] = "U.S. Treasury Daily Interest Rate XML Feed"
    return latest


def fetch_fred_latest(settings: Settings, series_id: str) -> dict[str, Any]:
    if not settings.fred_api_key:
        return {}
    response = requests.get(
        FRED_OBSERVATIONS,
        params={
            "series_id": series_id,
            "api_key": settings.fred_api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 10,
        },
        timeout=30,
    )
    response.raise_for_status()
    for observation in response.json().get("observations", []):
        value = observation.get("value")
        if value in (None, "."):
            continue
        return {
            "series_id": series_id,
            "date": observation.get("date"),
            "value": float(value),
            "source": "FRED",
        }
    return {}


def build_macro_context(settings: Settings) -> tuple[dict[str, Any], dict[str, str]]:
    context: dict[str, Any] = {}
    errors: dict[str, str] = {}
    try:
        context["treasury"] = fetch_treasury_curve()
    except Exception as exc:
        errors["treasury"] = str(exc)
        LOGGER.debug("Treasury macro feed failed: %s", exc)
    if settings.fred_api_key:
        for series in ("VIXCLS", "DFF"):
            try:
                value = fetch_fred_latest(settings, series)
                if value:
                    context[series.lower()] = value
            except Exception as exc:
                errors[f"fred:{series}"] = str(exc)
                LOGGER.debug("FRED series %s failed: %s", series, exc)
    return context, errors
