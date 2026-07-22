from __future__ import annotations

import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from .settings import Settings

LOGGER = logging.getLogger(__name__)
SEC_BASE = "https://www.sec.gov"
SEC_TICKERS = f"{SEC_BASE}/files/company_tickers.json"
SEC_FEED = f"{SEC_BASE}/cgi-bin/browse-edgar"
NASDAQ_MOVERS = "https://api.nasdaq.com/api/marketmovers"
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,6}$")
_PLACEHOLDERS = {"SYMBOL", "TICKER", "N/A", "NA", "NONE", "NULL"}


def _valid_symbol(value: str) -> bool:
    symbol = str(value or "").strip().upper()
    if not _SYMBOL.fullmatch(symbol) or symbol in _PLACEHOLDERS:
        return False
    return not any(token in symbol for token in ("/", "^", "$"))


def _valid_mover_symbol(value: str) -> bool:
    """Exclude common warrant/right/unit suffixes from Nasdaq discovery only."""

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


def _sec_ticker_map(settings: Settings) -> dict[str, str]:
    cache = Path("data/cache/sec_company_tickers.json")
    cache.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {}
    try:
        response = requests.get(SEC_TICKERS, headers=_sec_headers(settings), timeout=20)
        response.raise_for_status()
        payload = response.json()
        cache.write_text(response.text, encoding="utf-8")
    except Exception as exc:
        LOGGER.warning("Dynamic universe SEC ticker map unavailable: %s", exc)
        if cache.exists():
            try:
                payload = json.loads(cache.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
    result: dict[str, str] = {}
    for item in payload.values():
        cik = str(item.get("cik_str", "")).zfill(10)
        ticker = str(item.get("ticker", "")).upper()
        if cik and _valid_symbol(ticker):
            result[cik] = ticker
    return result


def sec_event_symbols(settings: Settings, max_per_form: int = 40) -> list[str]:
    """Discover symbols with fresh material SEC forms before ranking stocks."""

    cik_map = _sec_ticker_map(settings)
    if not cik_map:
        return []
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    forms = ("8-K", "6-K", "SC 13D", "SC 13D/A", "4", "S-1", "S-3", "424B5")
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
            if _valid_symbol(ticker):
                symbols.append(ticker)
    return list(dict.fromkeys(symbols))


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


def nasdaq_mover_symbols(limit: int = 60) -> list[str]:
    """Best-effort discovery from Nasdaq's public market-movers response."""

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GHAZI-Market-Radar/2.0)",
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


def build_dynamic_universe(
    base_symbols: list[str],
    settings: Settings,
    *,
    maximum: int | None = None,
) -> tuple[list[str], dict[str, int]]:
    maximum = maximum or settings.max_universe_size
    base = [str(symbol).strip().upper() for symbol in base_symbols if _valid_symbol(symbol)]
    sec = sec_event_symbols(settings)
    movers = nasdaq_mover_symbols()
    aliases = _load_alias_symbols()
    ordered = list(dict.fromkeys(base + sec + movers + aliases))[:maximum]
    return ordered, {
        "base": len(set(base)),
        "sec_events": len(set(sec)),
        "nasdaq_movers": len(set(movers)),
        "aliases": len(set(aliases)),
        "total": len(ordered),
    }
