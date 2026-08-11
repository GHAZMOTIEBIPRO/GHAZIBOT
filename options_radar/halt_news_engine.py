from __future__ import annotations

import html as html_lib
import math
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

NASDAQ_HALT_RSS = os.getenv("NASDAQ_HALT_RSS_URL", "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts")
ALPHA_VANTAGE_NEWS = "https://www.alphavantage.co/query"
FINNHUB_NEWS = "https://finnhub.io/api/v1/news"
TIMEOUT = 18
SYMBOL_RE = re.compile(r"\b[A-Z][A-Z0-9.-]{0,6}\b")
HALT_REASON_RE = re.compile(r"\b(T1|T2|T5|T6|T8|T12|LUDP|H10|H11|M1|M2|MWC1|MWC2|MWC3)\b", re.I)


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _strip_html(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class HaltEvent:
    symbol: str
    reason: str
    title: str
    description: str
    published: str


@dataclass
class NewsEvent:
    symbol: str
    headline: str
    source: str
    url: str
    published: str
    relevance: float
    sentiment: float
    provider: str


def _symbol_from_text(text: str, known_symbols: set[str] | None = None) -> str:
    known_symbols = known_symbols or set()
    matches = [match.upper() for match in SYMBOL_RE.findall(text.upper())]
    if known_symbols:
        for match in matches:
            if match in known_symbols:
                return match
    ignored = {"NASDAQ", "NYSE", "HALT", "NEWS", "UTC", "EST", "EDT", "ET", "T1", "T2", "T5", "LUDP"}
    for match in matches:
        if match not in ignored and 1 <= len(match) <= 6:
            return match
    return ""


def fetch_nasdaq_halts(known_symbols: set[str] | None = None) -> list[HaltEvent]:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; BLACK-BOX-Omega/1.0)"}
    response = requests.get(NASDAQ_HALT_RSS, headers=headers, timeout=TIMEOUT)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    events: list[HaltEvent] = []
    for item in root.findall(".//item"):
        title = _strip_html(item.findtext("title"))
        description = _strip_html(item.findtext("description"))
        published = _strip_html(item.findtext("pubDate"))
        combined = f"{title} {description}"
        symbol = _symbol_from_text(combined, known_symbols=known_symbols)
        reason_match = HALT_REASON_RE.search(combined)
        reason = reason_match.group(1).upper() if reason_match else "HALT"
        if symbol:
            events.append(HaltEvent(symbol=symbol, reason=reason, title=title, description=description, published=published))
    return events


def fetch_alpha_vantage_news(known_symbols: set[str] | None = None) -> list[NewsEvent]:
    api_key = str(os.getenv("ALPHA_VANTAGE_API_KEY") or "").strip()
    if not api_key:
        return []
    response = requests.get(
        ALPHA_VANTAGE_NEWS,
        params={"function": "NEWS_SENTIMENT", "sort": "LATEST", "limit": "100", "apikey": api_key},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json() or {}
    feed = payload.get("feed") if isinstance(payload, dict) else []
    events: list[NewsEvent] = []
    for article in feed or []:
        if not isinstance(article, dict):
            continue
        headline = str(article.get("title") or "").strip()
        source = str(article.get("source") or "Alpha Vantage").strip()
        url = str(article.get("url") or "").strip()
        published = str(article.get("time_published") or "").strip()
        ticker_rows = article.get("ticker_sentiment") if isinstance(article.get("ticker_sentiment"), list) else []
        for ticker_row in ticker_rows:
            if not isinstance(ticker_row, dict):
                continue
            symbol = str(ticker_row.get("ticker") or "").upper().strip()
            if not symbol or (known_symbols and symbol not in known_symbols):
                continue
            relevance = _number(ticker_row.get("relevance_score"))
            sentiment = _number(ticker_row.get("ticker_sentiment_score"))
            if relevance < 0.25:
                continue
            events.append(
                NewsEvent(
                    symbol=symbol,
                    headline=headline,
                    source=source,
                    url=url,
                    published=published,
                    relevance=relevance,
                    sentiment=sentiment,
                    provider="alpha_vantage",
                )
            )
    return events


def fetch_finnhub_news(known_symbols: set[str] | None = None) -> list[NewsEvent]:
    token = str(os.getenv("FINNHUB_API_KEY") or "").strip()
    if not token:
        return []
    now = datetime.now(timezone.utc)
    response = requests.get(FINNHUB_NEWS, params={"category": "general", "token": token}, timeout=TIMEOUT)
    response.raise_for_status()
    payload = response.json() or []
    events: list[NewsEvent] = []
    for article in payload[:120] if isinstance(payload, list) else []:
        if not isinstance(article, dict):
            continue
        related = str(article.get("related") or "").upper()
        symbols = [token.strip() for token in re.split(r"[,;\s]+", related) if token.strip()]
        for symbol in symbols:
            if known_symbols and symbol not in known_symbols:
                continue
            if not SYMBOL_RE.fullmatch(symbol):
                continue
            published_ts = int(_number(article.get("datetime")))
            published = datetime.fromtimestamp(published_ts, tz=timezone.utc).isoformat() if published_ts > 0 else now.isoformat()
            events.append(
                NewsEvent(
                    symbol=symbol,
                    headline=str(article.get("headline") or "").strip(),
                    source=str(article.get("source") or "Finnhub").strip(),
                    url=str(article.get("url") or "").strip(),
                    published=published,
                    relevance=0.65,
                    sentiment=0.0,
                    provider="finnhub",
                )
            )
    return events


def collect_fast_news(known_symbols: set[str] | None = None) -> list[NewsEvent]:
    events: list[NewsEvent] = []
    for fetcher in (fetch_alpha_vantage_news, fetch_finnhub_news):
        try:
            events.extend(fetcher(known_symbols=known_symbols))
        except requests.RequestException as exc:
            print(f"Fast news provider skipped: {type(exc).__name__}: {exc}")
        except Exception as exc:
            print(f"Fast news parse skipped: {type(exc).__name__}: {exc}")
    deduped: dict[tuple[str, str], NewsEvent] = {}
    for event in events:
        key = (event.symbol, event.headline.lower()[:180])
        existing = deduped.get(key)
        if existing is None or event.relevance > existing.relevance:
            deduped[key] = event
    return list(deduped.values())
