from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yfinance as yf

from .settings import Settings

LOGGER = logging.getLogger(__name__)
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
LOCAL_CIK_MAP = Path("data/sec_cik_map.json")

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
YAHOO_LABELS: dict[str, tuple[str, ...]] = {
    "revenue": ("Total Revenue", "Operating Revenue"),
    "net_income": ("Net Income", "Net Income Common Stockholders"),
    "eps_diluted": ("Diluted EPS", "Basic EPS"),
    "cash": (
        "Cash Cash Equivalents And Short Term Investments",
        "Cash And Cash Equivalents",
        "Cash Financial",
    ),
    "assets": ("Total Assets",),
    "liabilities": (
        "Total Liabilities Net Minority Interest",
        "Total Liabilities",
    ),
    "operating_cash_flow": ("Operating Cash Flow", "Total Cash From Operating Activities"),
}
ALLOWED_FORMS = {"10-Q", "10-K", "20-F", "40-F", "6-K"}


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "User-Agent": settings.sec_user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json",
    }


def _load_local_cik_map(path: Path = LOCAL_CIK_MAP) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Local SEC CIK map unavailable: %s", exc)
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(ticker).upper(): str(cik).zfill(10)
        for ticker, cik in payload.items()
        if str(ticker).strip() and str(cik).strip()
    }


def _ticker_to_cik(settings: Settings) -> dict[str, str]:
    """Return a resilient ticker map using the official endpoint when reachable."""

    result = _load_local_cik_map()
    try:
        response = requests.get(SEC_TICKERS, headers=_headers(settings), timeout=25)
        response.raise_for_status()
        for item in response.json().values():
            ticker = str(item.get("ticker", "")).upper()
            cik = str(item.get("cik_str", "")).zfill(10)
            if ticker and cik:
                result[ticker] = cik
    except Exception as exc:
        LOGGER.warning(
            "Live SEC ticker map unavailable; using %d local mappings: %s",
            len(result),
            exc,
        )
    if not result:
        raise RuntimeError("No SEC ticker-to-CIK mappings are available")
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
        "fundamental_confidence": 0.95,
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


def _statement_metric(frame: pd.DataFrame, labels: tuple[str, ...]) -> tuple[float | None, float | None, str]:
    if frame is None or frame.empty:
        return None, None, ""
    for label in labels:
        if label not in frame.index:
            continue
        series = pd.to_numeric(frame.loc[label], errors="coerce").dropna()
        if series.empty:
            continue
        try:
            series = series.reindex(
                sorted(series.index, key=lambda value: pd.Timestamp(value), reverse=True)
            )
        except Exception:
            pass
        latest = float(series.iloc[0])
        # Quarterly statements normally contain five columns. Compare the same
        # quarter one year earlier; use the prior period only when YoY is unavailable.
        comparison_index = 4 if len(series) >= 5 else 1
        comparable = float(series.iloc[comparison_index]) if len(series) > comparison_index else None
        growth = latest / comparable - 1.0 if comparable not in (None, 0) else None
        period_value = series.index[0]
        period = pd.Timestamp(period_value).date().isoformat() if not pd.isna(period_value) else ""
        return latest, growth, period
    return None, None, ""


def yahoo_fundamentals(symbol: str, sec_error: str = "") -> dict[str, Any]:
    """Use free Yahoo statements as a clearly labelled, unofficial fallback."""

    ticker = yf.Ticker(symbol)
    income = ticker.quarterly_income_stmt
    balance = ticker.quarterly_balance_sheet
    cashflow = ticker.quarterly_cashflow
    frames = {
        "revenue": income,
        "net_income": income,
        "eps_diluted": income,
        "cash": balance,
        "assets": balance,
        "liabilities": balance,
        "operating_cash_flow": cashflow,
    }
    result: dict[str, Any] = {
        "fundamental_source": "Yahoo/yfinance statements",
        "fundamental_confidence": 0.45,
        "fundamental_note": (
            "unofficial fallback; SEC Company Facts unavailable on the runner"
            + (f" ({sec_error[:120]})" if sec_error else "")
        ),
    }
    periods: list[str] = []
    populated = 0
    for name, labels in YAHOO_LABELS.items():
        value, growth, period = _statement_metric(frames[name], labels)
        result[name] = value
        result[f"{name}_growth"] = growth
        if value is not None:
            populated += 1
        if period:
            periods.append(period)
    if populated == 0:
        return {}
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
        cik_map = {}
        LOGGER.warning("SEC ticker map unavailable; Yahoo statement fallback remains active: %s", exc)
    for symbol in out["symbol"].astype(str).head(max_symbols):
        facts: dict[str, Any] = {}
        sec_error = ""
        if symbol.upper() in cik_map:
            try:
                time.sleep(0.12)
                facts = company_fundamentals(settings, symbol, cik_map)
            except Exception as exc:
                sec_error = str(exc)
                LOGGER.debug("SEC Company Facts failed for %s: %s", symbol, exc)
        if not facts:
            try:
                facts = yahoo_fundamentals(symbol, sec_error=sec_error)
            except Exception as exc:
                LOGGER.debug("Yahoo statements failed for %s: %s", symbol, exc)
                if sec_error:
                    errors[symbol] = f"SEC: {sec_error}; Yahoo: {exc}"
                else:
                    errors[symbol] = str(exc)
        if not facts:
            continue
        mask = out["symbol"].astype(str).eq(symbol)
        for key, value in facts.items():
            out.loc[mask, key] = value
    return out, errors
