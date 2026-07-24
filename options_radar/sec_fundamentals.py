from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd
import requests

from .settings import Settings

LOGGER = logging.getLogger(__name__)
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

CONCEPTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "revenue": (
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
        ),
        ("USD",),
    ),
    "net_income": (("NetIncomeLoss", "ProfitLoss"), ("USD",)),
    "eps_diluted": (("EarningsPerShareDiluted",), ("USD/shares", "USD-per-shares")),
    "cash": (
        (
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ),
        ("USD",),
    ),
    "assets": (("Assets",), ("USD",)),
    "liabilities": (("Liabilities", "LiabilitiesCurrent"), ("USD",)),
    "operating_cash_flow": (("NetCashProvidedByUsedInOperatingActivities",), ("USD",)),
}
ALLOWED_FORMS = {"10-Q", "10-K", "20-F", "40-F", "6-K"}


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "User-Agent": settings.sec_user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json",
    }


def _ticker_to_cik(settings: Settings) -> dict[str, str]:
    response = requests.get(SEC_TICKERS, headers=_headers(settings), timeout=25)
    response.raise_for_status()
    result: dict[str, str] = {}
    for item in response.json().values():
        ticker = str(item.get("ticker", "")).upper()
        cik = str(item.get("cik_str", "")).zfill(10)
        if ticker and cik:
            result[ticker] = cik
    return result


def _records(payload: dict[str, Any], concepts: tuple[str, ...], units: tuple[str, ...]) -> list[dict[str, Any]]:
    facts = payload.get("facts", {}).get("us-gaap", {})
    for concept in concepts:
        fact = facts.get(concept)
        if not isinstance(fact, dict):
            continue
        available = fact.get("units", {})
        for unit in units:
            rows = available.get(unit)
            if isinstance(rows, list) and rows:
                return [row for row in rows if str(row.get("form", "")) in ALLOWED_FORMS]
        for rows in available.values():
            if isinstance(rows, list) and rows:
                return [row for row in rows if str(row.get("form", "")) in ALLOWED_FORMS]
    return []


def _latest_metric(payload: dict[str, Any], concepts: tuple[str, ...], units: tuple[str, ...]) -> tuple[float | None, float | None, str]:
    rows = _records(payload, concepts, units)
    if not rows:
        return None, None, ""
    valid = [row for row in rows if isinstance(row.get("val"), (int, float)) and row.get("end")]
    if not valid:
        return None, None, ""
    valid.sort(key=lambda row: (str(row.get("end", "")), str(row.get("filed", ""))), reverse=True)
    latest = valid[0]
    latest_value = float(latest["val"])
    latest_fy = latest.get("fy")
    latest_fp = str(latest.get("fp", ""))
    comparable = None
    if isinstance(latest_fy, int):
        candidates = [
            row for row in valid[1:]
            if row.get("fy") == latest_fy - 1 and str(row.get("fp", "")) == latest_fp
        ]
        if candidates:
            comparable = float(candidates[0]["val"])
    growth = None
    if comparable not in (None, 0):
        growth = latest_value / comparable - 1.0
    period = f"{latest.get('form', '')} {latest.get('end', '')}".strip()
    return latest_value, growth, period


def company_fundamentals(settings: Settings, symbol: str, cik_map: dict[str, str]) -> dict[str, Any]:
    cik = cik_map.get(symbol.upper())
    if not cik:
        return {}
    response = requests.get(
        SEC_COMPANY_FACTS.format(cik=cik),
        headers=_headers(settings),
        timeout=35,
    )
    response.raise_for_status()
    payload = response.json()
    result: dict[str, Any] = {
        "fundamental_source": "SEC Company Facts",
        "fundamental_cik": cik,
        "fundamental_entity": str(payload.get("entityName", "")),
    }
    periods: list[str] = []
    for name, (concepts, units) in CONCEPTS.items():
        value, growth, period = _latest_metric(payload, concepts, units)
        result[name] = value
        result[f"{name}_growth"] = growth
        if period:
            periods.append(period)
    revenue = result.get("revenue")
    net_income = result.get("net_income")
    result["net_margin"] = (
        float(net_income) / float(revenue)
        if isinstance(revenue, (int, float)) and revenue and isinstance(net_income, (int, float))
        else None
    )
    result["fundamental_period"] = periods[0] if periods else ""
    return result


def enrich_stock_fundamentals(frame: pd.DataFrame, settings: Settings, max_symbols: int = 8) -> tuple[pd.DataFrame, dict[str, str]]:
    if frame is None or frame.empty or "symbol" not in frame.columns:
        return frame, {}
    out = frame.copy()
    errors: dict[str, str] = {}
    try:
        cik_map = _ticker_to_cik(settings)
    except Exception as exc:
        return out, {"ticker_map": str(exc)}
    for symbol in out["symbol"].astype(str).head(max_symbols):
        try:
            time.sleep(0.12)
            facts = company_fundamentals(settings, symbol, cik_map)
            if not facts:
                continue
            mask = out["symbol"].astype(str).eq(symbol)
            for key, value in facts.items():
                out.loc[mask, key] = value
        except Exception as exc:
            LOGGER.debug("SEC company facts failed for %s: %s", symbol, exc)
            errors[symbol] = str(exc)
    return out, errors
