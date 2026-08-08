from __future__ import annotations

import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .sec_efts import sec_fulltext_symbols
from .settings import Settings

LOGGER = logging.getLogger(__name__)
SEC_BASE = "https://www.sec.gov"
SEC_TICKERS = f"{SEC_BASE}/files/company_tickers.json"
SEC_TICKERS_EXCHANGE = f"{SEC_BASE}/files/company_tickers_exchange.json"
SEC_FEED = f"{SEC_BASE}/cgi-bin/browse-edgar"
NASDAQ_MOVERS = "https://api.nasdaq.com/api/marketmovers"
ALPHA_VANTAGE = "https://www.alphavantage.co/query"
LOCAL_CIK_MAP = Path("data/sec_cik_map.json")
LOCAL_US_UNIVERSE = Path("data/cache/us_listed_universe.json")
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,6}$")
_PLACEHOLDERS = {"SYMBOL", "TICKER", "N/A", "NA", "NONE", "NULL"}
_LAST_SEC_COUNTS = {"sec_fulltext": 0, "sec_latest_forms": 0}


def _valid_symbol(value: str) -> bool:
    symbol = str(value or "").strip().upper()
    if not _SYMBOL.fullmatch(symbol) or symbol in _PLACEHOLDERS:
        return False
    return not any(token in symbol for token in ("/", "^", "$"))


def _valid_mover_symbol(value: str) -> bool:
    """Exclude common warrant/right/unit suffixes from broad discovery."""

    symbol = str(value or "").strip().upper()
    if not _valid_symbol(symbol):
        return False
    if symbol.endswith(("WS", "WT")):
        return False
    if len(symbol) >= 4 and symbol.endswith(("W", "U", "R")):
        return False
    return True


def _load_alias_symbols(path: str | Path = "data/company_aliases.json") -> list[str]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [str(symbol).upper() for symbol in payload if _valid_symbol(str(symbol))]


def _sec_headers(settings: Settings) -> dict[str, str]:
    return {
        "User-Agent": settings.sec_user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/atom+xml,application/json,text/html;q=0.9,*/*;q=0.8",
    }


def _load_persistent_cik_map(path: Path = LOCAL_CIK_MAP) -> dict[str, str]:
    """Return CIK-to-ticker mappings from the checked-in official snapshot."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    result: dict[str, str] = {}
    for ticker, cik in payload.items():
        symbol = str(ticker).upper()
        cik_value = str(cik).zfill(10)
        if _valid_symbol(symbol) and cik_value.strip("0"):
            result[cik_value] = symbol
    return result


def _sec_ticker_map(settings: Settings) -> dict[str, str]:
    cache = Path("data/cache/sec_company_tickers.json")
    cache.parent.mkdir(parents=True, exist_ok=True)
    result = _load_persistent_cik_map()
    payload: dict = {}
    try:
        response = requests.get(SEC_TICKERS, headers=_sec_headers(settings), timeout=20)
        response.raise_for_status()
        payload = response.json()
        cache.write_text(response.text, encoding="utf-8")
    except Exception as exc:
        LOGGER.warning(
            "Dynamic universe SEC ticker map unavailable; using %d persistent mappings: %s",
            len(result),
            exc,
        )
        if cache.exists():
            try:
                payload = json.loads(cache.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
    for item in payload.values():
        cik = str(item.get("cik_str", "")).zfill(10)
        ticker = str(item.get("ticker", "")).upper()
        if cik and _valid_symbol(ticker):
            result[cik] = ticker
    return result


def _is_us_exchange(exchange: str) -> bool:
    normalized = str(exchange or "").strip().lower()
    if not normalized:
        return False
    return any(token in normalized for token in ("nasdaq", "nyse", "cboe"))


def us_listed_symbols(settings: Settings) -> list[str]:
    """Load the broad US exchange universe from the SEC official exchange file.

    This is the coverage universe. We do not run expensive option/history requests
    on every name. Event and price-shock sources nominate a smaller deep-scan set.
    """

    LOCAL_US_UNIVERSE.parent.mkdir(parents=True, exist_ok=True)
    rows: list = []
    try:
        response = requests.get(
            SEC_TICKERS_EXCHANGE,
            headers=_sec_headers(settings),
            timeout=max(20, int(settings.request_timeout_seconds)),
        )
        response.raise_for_status()
        payload = response.json()
        fields = [str(field) for field in payload.get("fields", [])]
        data = payload.get("data", [])
        for raw in data:
            if not isinstance(raw, list):
                continue
            item = dict(zip(fields, raw))
            ticker = str(item.get("ticker") or "").upper()
            exchange = str(item.get("exchange") or "")
            if _valid_mover_symbol(ticker) and _is_us_exchange(exchange):
                rows.append(
                    {
                        "ticker": ticker,
                        "exchange": exchange,
                        "name": str(item.get("name") or ""),
                        "cik": item.get("cik"),
                    }
                )
        snapshot = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "SEC company_tickers_exchange.json",
            "count": len(rows),
            "rows": rows,
        }
        LOCAL_US_UNIVERSE.write_text(
            json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:
        LOGGER.warning("SEC US exchange universe unavailable; trying cache: %s", exc)
        try:
            snapshot = json.loads(LOCAL_US_UNIVERSE.read_text(encoding="utf-8"))
            rows = snapshot.get("rows", []) if isinstance(snapshot, dict) else []
        except Exception:
            rows = []

    return list(
        dict.fromkeys(
            str(row.get("ticker") or "").upper()
            for row in rows
            if isinstance(row, dict) and _valid_mover_symbol(str(row.get("ticker") or ""))
        )
    )


def _sec_latest_form_symbols(settings: Settings, max_per_form: int = 80) -> list[str]:
    """Discover symbols from newest market-moving forms across the whole market."""

    cik_map = _sec_ticker_map(settings)
    if not cik_map:
        return []
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    forms = (
        "8-K",
        "6-K",
        "SC 13D",
        "SC 13D/A",
        "4",
        "S-1",
        "S-3",
        "424B5",
        "SC TO",
        "DEFM14A",
    )
    symbols: list[str] = []
    for form in forms:
        params = {
            "action": "getcurrent",
            "type": form,
            "company": "",
            "dateb": "",
            "owner": "include",
            "start": 0,
            "count": max_per_form,
            "output": "atom",
        }
        try:
            time.sleep(0.12)
            response = requests.get(
                SEC_FEED,
                params=params,
                headers=_sec_headers(settings),
                timeout=25,
            )
            response.raise_for_status()
            root = ET.fromstring(response.content)
        except Exception as exc:
            LOGGER.debug("Dynamic SEC feed unavailable for %s: %s", form, exc)
            continue
        for entry in root.findall("atom:entry", namespace):
            title = entry.findtext("atom:title", default="", namespaces=namespace)
            summary = entry.findtext("atom:summary", default="", namespaces=namespace)
            match = re.search(r"\((\d{6,10})\)", title) or re.search(
                r"CIK[:=\s]+(\d{6,10})", summary, flags=re.I
            )
            if not match:
                continue
            ticker = cik_map.get(match.group(1).zfill(10), "")
            if _valid_mover_symbol(ticker):
                symbols.append(ticker)
    return list(dict.fromkeys(symbols))


def sec_event_symbols(settings: Settings, max_per_form: int = 80) -> list[str]:
    """Combine full-text event discovery with the latest-form feed."""

    fulltext = [
        symbol
        for symbol in sec_fulltext_symbols(settings, lookback_days=14)
        if _valid_mover_symbol(symbol)
    ]
    latest = _sec_latest_form_symbols(settings, max_per_form=max_per_form)
    _LAST_SEC_COUNTS["sec_fulltext"] = len(set(fulltext))
    _LAST_SEC_COUNTS["sec_latest_forms"] = len(set(latest))
    return list(dict.fromkeys(fulltext + latest))


def _walk_symbols(payload: object) -> list[str]:
    symbols: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower() == "symbol" and _valid_mover_symbol(str(value)):
                symbols.append(str(value).upper())
            else:
                symbols.extend(_walk_symbols(value))
    elif isinstance(payload, list):
        for item in payload:
            symbols.extend(_walk_symbols(item))
    return symbols


def nasdaq_mover_symbols(limit: int = 160) -> list[str]:
    """Best-effort discovery from Nasdaq's public market-movers response."""

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GHAZI-Market-Radar/5.0)",
        "Accept": "application/json,text/plain,*/*",
        "Origin": "https://www.nasdaq.com",
        "Referer": "https://www.nasdaq.com/market-activity/most-active",
    }
    try:
        response = requests.get(
            NASDAQ_MOVERS,
            params={"assetclass": "stocks"},
            headers=headers,
            timeout=20,
        )
        response.raise_for_status()
        symbols = _walk_symbols(response.json())
        return list(dict.fromkeys(symbols))[:limit]
    except Exception as exc:
        LOGGER.debug("Nasdaq market movers unavailable: %s", exc)
        return []


def alpha_vantage_news_symbols(settings: Settings, limit: int = 1000) -> list[str]:
    """Pull broad market news once and extract mentioned US equity tickers."""

    key = str(settings.alpha_vantage_api_key or "").strip()
    if not key:
        return []
    lookback_hours = max(6, int(os.getenv("EXPLOSION_NEWS_LOOKBACK_HOURS", "48")))
    time_from = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).strftime(
        "%Y%m%dT%H%M"
    )
    try:
        response = requests.get(
            ALPHA_VANTAGE,
            params={
                "function": "NEWS_SENTIMENT",
                "sort": "LATEST",
                "limit": min(1000, max(50, limit)),
                "time_from": time_from,
                "apikey": key,
            },
            timeout=max(20, int(settings.request_timeout_seconds)),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        LOGGER.debug("Alpha Vantage broad news unavailable: %s", exc)
        return []

    symbols: list[str] = []
    for article in payload.get("feed", []) if isinstance(payload, dict) else []:
        if not isinstance(article, dict):
            continue
        for row in article.get("ticker_sentiment", []) or []:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or "").upper()
            relevance = 0.0
            try:
                relevance = float(row.get("relevance_score") or 0.0)
            except (TypeError, ValueError):
                relevance = 0.0
            if relevance >= 0.08 and _valid_mover_symbol(ticker):
                symbols.append(ticker)
    return list(dict.fromkeys(symbols))


def alpha_vantage_gainer_symbols(settings: Settings) -> list[str]:
    """Use Alpha Vantage's US top-gainer feed as a second price-shock source."""

    key = str(settings.alpha_vantage_api_key or "").strip()
    if not key:
        return []
    try:
        response = requests.get(
            ALPHA_VANTAGE,
            params={"function": "TOP_GAINERS_LOSERS", "apikey": key},
            timeout=max(20, int(settings.request_timeout_seconds)),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        LOGGER.debug("Alpha Vantage gainers unavailable: %s", exc)
        return []

    symbols: list[str] = []
    if isinstance(payload, dict):
        for row in payload.get("top_gainers", []) or []:
            if isinstance(row, dict):
                ticker = str(row.get("ticker") or "").upper()
                if _valid_mover_symbol(ticker):
                    symbols.append(ticker)
        for row in payload.get("most_actively_traded", []) or []:
            if isinstance(row, dict):
                ticker = str(row.get("ticker") or "").upper()
                if _valid_mover_symbol(ticker):
                    symbols.append(ticker)
    return list(dict.fromkeys(symbols))


def build_dynamic_universe(
    base_symbols: list[str],
    settings: Settings,
    *,
    maximum: int | None = None,
) -> tuple[list[str], dict[str, int | str]]:
    """Build the deep-scan shortlist from full-US-market discovery sources.

    Coverage is broad: the SEC exchange directory defines the US-listed universe.
    Expensive OHLCV/options work is performed only on symbols nominated by a new
    filing, broad-market news, or abnormal market-mover feed. This is deliberate:
    it maximizes explosion/news coverage without making thousands of per-symbol
    API calls every run.
    """

    full_market_mode = str(os.getenv("FULL_US_MARKET_MODE", "true")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    if maximum is None:
        maximum = (
            max(100, int(os.getenv("EXPLOSION_SHORTLIST_MAX", "350")))
            if full_market_mode
            else settings.max_universe_size
        )

    base = [
        str(symbol).strip().upper()
        for symbol in base_symbols
        if _valid_mover_symbol(str(symbol))
    ]
    listed = us_listed_symbols(settings) if full_market_mode else []
    listed_set = set(listed)
    sec = sec_event_symbols(settings)
    alpha_news = alpha_vantage_news_symbols(settings)
    alpha_gainers = alpha_vantage_gainer_symbols(settings)
    movers = nasdaq_mover_symbols()
    aliases = _load_alias_symbols()

    def allowed(symbol: str) -> bool:
        if not _valid_mover_symbol(symbol):
            return False
        if not listed_set:
            return True
        return symbol in listed_set

    # Priority is intentional: official filings first, then fresh broad news,
    # then explicit gainers/abnormal activity, then legacy/manual discovery.
    nominated = [
        symbol
        for symbol in (sec + alpha_news + alpha_gainers + movers + base + aliases)
        if allowed(symbol)
    ]
    ordered = list(dict.fromkeys(nominated))[:maximum]

    # If every live source fails, preserve legacy operation instead of publishing
    # an empty radar. The fallback remains exchange-filtered when possible.
    if not ordered:
        fallback = [symbol for symbol in (base + aliases) if allowed(symbol)]
        ordered = list(dict.fromkeys(fallback))[:maximum]

    return ordered, {
        "mode": "full_us_event_driven" if full_market_mode else "legacy_dynamic",
        "us_listed_coverage": len(listed),
        "sec_fulltext": int(_LAST_SEC_COUNTS.get("sec_fulltext", 0)),
        "sec_latest_forms": int(_LAST_SEC_COUNTS.get("sec_latest_forms", 0)),
        "sec_events": len(set(sec)),
        "alpha_vantage_news": len(set(alpha_news)),
        "alpha_vantage_gainers_active": len(set(alpha_gainers)),
        "nasdaq_movers": len(set(movers)),
        "base": len(set(base)),
        "aliases": len(set(aliases)),
        "deep_scan_total": len(ordered),
        "total": len(ordered),
    }
