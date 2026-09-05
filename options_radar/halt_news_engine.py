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
GLOBENEWSWIRE_PUBLIC_RSS = os.getenv(
    "GLOBENEWSWIRE_PUBLIC_RSS_URL",
    "https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/GlobeNewswire%20-%20News%20about%20Public%20Companies",
)
BUSINESS_WIRE_RSS = os.getenv(
    "BUSINESS_WIRE_RSS_URL",
    "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtRWA==",
)
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
TIMEOUT = 18
SYMBOL_RE = re.compile(r"\b[A-Z][A-Z0-9.-]{0,6}\b")
HALT_REASON_RE = re.compile(r"\b(T1|T2|T5|T6|T8|T12|LUDP|H10|H11|M1|M2|MWC1|MWC2|MWC3)\b", re.I)
EXCHANGE_TICKER_RE = re.compile(
    r"\b(?:NASDAQ|NYSE|NYSE\s+AMERICAN|NYSEAMERICAN|AMEX|CBOE|OTCQX|OTCQB)\s*[:\-]\s*([A-Z][A-Z0-9.\-]{0,6})\b",
    re.I,
)
_BULLISH_NEWS = (
    "approval", "approved", "positive results", "record revenue", "raises guidance",
    "wins contract", "awarded contract", "strategic partnership", "acquisition", "buyback",
    "share repurchase", "dividend increase", "patent granted", "breakthrough",
)
_BEARISH_NEWS = (
    "public offering", "registered direct", "atm offering", "bankruptcy", "delisting",
    "lowers guidance", "cuts guidance", "investigation", "going concern", "reverse split",
    "misses estimates", "trial failed", "clinical hold",
)


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


def _symbols_from_release_text(text: str, known_symbols: set[str] | None = None) -> list[str]:
    known = {str(symbol).upper().strip() for symbol in (known_symbols or set()) if str(symbol).strip()}
    upper = str(text or "").upper()
    output: list[str] = []
    for match in EXCHANGE_TICKER_RE.finditer(upper):
        symbol = match.group(1).upper().strip()
        if symbol and (not known or symbol in known) and symbol not in output:
            output.append(symbol)
    if known:
        # Avoid very short English-word tickers unless the release explicitly
        # labels them with an exchange. This materially reduces false matches.
        for symbol in sorted(known, key=len, reverse=True):
            if len(symbol) < 3 or symbol in output:
                continue
            pattern = rf"(?<![A-Z0-9]){re.escape(symbol)}(?![A-Z0-9])"
            if re.search(pattern, upper):
                output.append(symbol)
    return output


def _headline_sentiment(headline: str) -> float:
    text = str(headline or "").lower()
    bullish = sum(token in text for token in _BULLISH_NEWS)
    bearish = sum(token in text for token in _BEARISH_NEWS)
    if bullish == bearish:
        return 0.0
    return max(-0.6, min(0.6, (bullish - bearish) * 0.22))


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


def _feed_items(root: ET.Element) -> list[ET.Element]:
    items = list(root.findall(".//item"))
    if items:
        return items
    return list(root.findall(".//{*}entry"))


def _feed_text(item: ET.Element, *names: str) -> str:
    for name in names:
        value = item.findtext(name)
        if value:
            return _strip_html(value)
        value = item.findtext(f"{{*}}{name}")
        if value:
            return _strip_html(value)
    return ""


def _feed_link(item: ET.Element) -> str:
    direct = _feed_text(item, "link")
    if direct.startswith("http"):
        return direct
    for node in list(item.findall("link")) + list(item.findall("{*}link")):
        href = str(node.attrib.get("href") or "").strip()
        if href.startswith("http"):
            return href
    return ""


def _feed_categories(item: ET.Element) -> list[str]:
    output: list[str] = []
    for node in list(item.findall("category")) + list(item.findall("{*}category")):
        text = _strip_html(node.text)
        term = _strip_html(node.attrib.get("term"))
        if text:
            output.append(text)
        if term and term not in output:
            output.append(term)
    return output


def _parse_release_feed(
    content: bytes,
    *,
    known_symbols: set[str] | None,
    source: str,
    provider: str,
    maximum: int = 140,
) -> list[NewsEvent]:
    root = ET.fromstring(content)
    events: list[NewsEvent] = []
    for item in _feed_items(root)[:maximum]:
        headline = _feed_text(item, "title")
        if not headline:
            continue
        description = _feed_text(item, "description", "summary", "content")
        published = _feed_text(item, "pubDate", "published", "updated")
        url = _feed_link(item)
        categories = _feed_categories(item)
        category_text = " ".join(categories)
        explicit = _symbols_from_release_text(category_text, known_symbols=known_symbols)
        symbols = explicit or _symbols_from_release_text(
            f"{headline} {description}", known_symbols=known_symbols
        )
        if not symbols:
            continue
        relevance = 0.90 if explicit else 0.72
        sentiment = _headline_sentiment(headline)
        for symbol in symbols:
            events.append(
                NewsEvent(
                    symbol=symbol,
                    headline=headline,
                    source=source,
                    url=url,
                    published=published,
                    relevance=relevance,
                    sentiment=sentiment,
                    provider=provider,
                )
            )
    return events


def _get_rss(url: str, *, params: dict[str, str] | None = None) -> bytes:
    response = requests.get(
        url,
        params=params,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; BLACK-BOX-Omega/NewsMesh; +https://github.com/GHAZMOTIEBIPRO/GHAZIBOT)",
            "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml,*/*",
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.content


def fetch_globenewswire_news(known_symbols: set[str] | None = None) -> list[NewsEvent]:
    content = _get_rss(GLOBENEWSWIRE_PUBLIC_RSS)
    return _parse_release_feed(
        content,
        known_symbols=known_symbols,
        source="GlobeNewswire company release",
        provider="globenewswire_rss",
    )


def fetch_businesswire_news(known_symbols: set[str] | None = None) -> list[NewsEvent]:
    content = _get_rss(BUSINESS_WIRE_RSS)
    return _parse_release_feed(
        content,
        known_symbols=known_symbols,
        source="Business Wire company release",
        provider="businesswire_rss",
    )


def fetch_prnewswire_news(known_symbols: set[str] | None = None) -> list[NewsEvent]:
    # PR Newswire publishes RSS feeds. Google News RSS is used only as a
    # keyless discovery transport here; headlines/links remain attributed to
    # PR Newswire and never become official proof inside the stock path.
    content = _get_rss(
        GOOGLE_NEWS_RSS,
        params={
            "q": "site:prnewswire.com when:1d",
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        },
    )
    return _parse_release_feed(
        content,
        known_symbols=known_symbols,
        source="PR Newswire via Google News RSS",
        provider="prnewswire_google_rss",
        maximum=100,
    )


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
    # Keyless feeds come first so the bot remains multi-source even when no API
    # secrets are configured. Press-release wires are direct-company evidence,
    # not independent confirmation; the deep stock path still requires official
    # SEC/FDA/primary-source evidence before proving a catalyst.
    fetchers = (
        fetch_globenewswire_news,
        fetch_businesswire_news,
        fetch_prnewswire_news,
        fetch_alpha_vantage_news,
        fetch_finnhub_news,
    )
    for fetcher in fetchers:
        try:
            events.extend(fetcher(known_symbols=known_symbols))
        except requests.RequestException as exc:
            print(f"Fast news provider skipped: {fetcher.__name__}: {type(exc).__name__}: {exc}")
        except (ET.ParseError, ValueError) as exc:
            print(f"Fast news parse skipped: {fetcher.__name__}: {type(exc).__name__}: {exc}")
        except Exception as exc:
            print(f"Fast news provider degraded: {fetcher.__name__}: {type(exc).__name__}: {exc}")
    deduped: dict[tuple[str, str], NewsEvent] = {}
    for event in events:
        key = (event.symbol, event.headline.lower()[:180])
        existing = deduped.get(key)
        if existing is None or event.relevance > existing.relevance:
            deduped[key] = event
    return list(deduped.values())
