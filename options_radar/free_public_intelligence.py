"""Keyless public news and economic calendar: context only, never signal authority.

News redistributors GDELT are attention, not proof of catalysts. BLS dates
are scheduled releases, not the published economic value. Fed RSS is official
publication context, not an upcoming FOMC schedule.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import feedparser
import requests

from options_radar.github_listing_discovery import (
    resolve_public_issuers,
    symbols_from_brief,
)

GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"
BLS_ICS = "https://www.bls.gov/schedule/news_release/bls.ics"
FED_MONETARY = "https://www.federalreserve.gov/feeds/press_monetary.xml"
ALPACA_LATEST = "https://data.alpaca.markets/v2/stocks/SPY/bars/latest"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
GOOGLE_NEWS_MAX_ISSUERS = 6
PRESS_WIRE_RSS = {
    "prnewswire": "https://www.prnewswire.com/rss/news-releases-list.rss",
    "globenewswire": "https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/GlobeNewswire%20-%20News%20about%20Public%20Companies",
}
# A source's generic release title is only issuer-related when the specific
# company name OR a strict exchange-qualified ticker appears in that headline.
# Do NOT associate bare RGC, MU, AI, etc with unrelated companies.
ISSUER_NAMES = {
    "RGC": ("Regencell Bioscience", "Regencell"),
    "BNAI": ("Brand Engagement Network",),
    "RKLB": ("Rocket Lab",),
    "IONQ": ("IonQ",),
    "RGTI": ("Rigetti Computing", "Rigetti"),
    "ASTS": ("AST SpaceMobile",),
    "SOUN": ("SoundHound AI",),
    "MU": ("Micron Technology",),
    "NVDA": ("NVIDIA Corporation", "NVIDIA"),
    "AMD": ("Advanced Micro Devices",),
    "AAPL": ("Apple Inc.",),
    "TSLA": ("Tesla Inc.", "Tesla, Inc.",),
    "PLTR": ("Palantir Technologies",),
    "SHOP": ("Shopify Inc.",),
    "GILD": ("Gilead Sciences",),
    "SOFI": ("SoFi Technologies",),
    "MSFT": ("Microsoft Corporation", "Microsoft"),
    "AVGO": ("Broadcom Inc.", "Broadcom"),
}

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
WATCH_DEFAULT = ("MU", "NVDA", "RGC", "BNAI", "RKLB", "AMD")
_COOLDOWN_HOURS = {"HTTP_429": 12, "HTTP_403": 24, "HTTP_404": 48}
_COOLDOWN_SOURCES = frozenset((
    "gdelt_attention", "press_wire_prnewswire",
    "press_wire_globenewswire", "google_news_attention",
))
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{1,6}$")
_ICS_DT_RE = re.compile(r"^(?P<key>DTSTART)(?:;TZID=(?P<tz>[^:]+)|;VALUE=DATE)?:(?P<value>.+)$")


def _iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d%H%M%S"):
        try:
            point = datetime.strptime(raw, fmt)
            return point.replace(tzinfo=UTC)
        except ValueError:
            pass
    try:
        value_dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return value_dt.astimezone(UTC) if value_dt.tzinfo else None
    except ValueError:
        pass
    try:
        value_dt = parsedate_to_datetime(raw)
        return value_dt.astimezone(UTC) if value_dt.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _https(url: Any, allowed_domains: tuple[str, ...] = ()) -> str:
    value = str(url or "").strip()
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host or parsed.username or parsed.password:
            return ""
        if allowed_domains and host not in allowed_domains:
            return ""
    except ValueError:
        return ""
    return value[:1200]


def _get(
    url: str, *,
    session: requests.Session | Any = requests,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    response = session.get(
        url, params=params,
        headers={"User-Agent": "GHAZIBOT-Free-Research/1.0", **(headers or {})},
        timeout=15,
    )
    response.raise_for_status()
    if len(response.content) > 1_500_000:
        raise ValueError("oversized public feed")
    return response


def gdelt_attention(
    symbols: list[str], *,
    session: Any = requests, now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Match only exchange-ticker/$ticker mentions, not ambiguous bare words."""
    current = now or datetime.now(UTC)
    watch = list(dict.fromkeys(str(s).strip().upper() for s in symbols))
    watch = [s for s in watch if _SYMBOL_RE.fullmatch(s)][:12]
    if not watch:
        return []
    # One bounded query; free public API may throttle/return partial coverage.
    terms = " OR ".join(f'"{s}"' for s in watch)
    response = _get(
        GDELT_DOC, session=session,
        params={
            "query": f"({terms}) (stock OR shares OR NASDAQ OR NYSE)",
            "mode": "artlist", "format": "json", "timespan": "24h",
            "maxrecords": 75, "sort": "datedesc",
        },
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError("GDELT returned invalid JSON")
    articles = payload.get("articles", [])
    if not isinstance(articles, list):
        raise TypeError("GDELT article schema invalid")
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in articles[:75]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()[:250]
        url = _https(row.get("url"))
        observed = _iso(row.get("seendate"))
        if not title or not url or observed is None:
            continue
        age = current - observed
        if age < timedelta(minutes=-3) or age > timedelta(hours=26):
            continue
        # Ticker alone is not evidence. A finance-context headline with an
        # explicit stock suffix is valid *attention* but not company identity.
        for symbol in watch:
            mentioned = bool(re.search(
                rf"(?<![A-Z0-9])(?:\${re.escape(symbol)}|(?:NASDAQ|NYSE|AMEX)\s*:\s*{re.escape(symbol)})(?![A-Z0-9])",
                title, flags=re.IGNORECASE,
            ))
            if not mentioned or (symbol, url) in seen:
                continue
            seen.add((symbol, url))
            output.append({
                "symbol": symbol, "headline": title, "url": url,
                "observed_at": observed.isoformat(),
                "source": "gdelt_doc_v2", "source_family": "gdelt_news_aggregation",
                "authority": "ATTENTION_ONLY", "official_confirmed": False,
                "independent_confirmation": False, "market_direction": "UNKNOWN",
                "price_or_option_quote": False,
            })
    return output[:40]


def press_wire_attention(
    symbols: list[str], *, session: Any = requests, now: datetime | None = None,
    skip_publishers: frozenset[str] = frozenset(),
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Bounded two-feed wire RSS discovery; does NOT verify issuer/impact.

    The free feeds are intended for RSS readers. Do not fetch release bodies,
    bypass controls, store copyrighted article content, or imply official
    issuer attribution. Avoid ambiguous bare ticker matches.
    """
    current = now or datetime.now(UTC)
    watch = [
        x for x in dict.fromkeys(str(s).upper().strip() for s in symbols)
        if x in ISSUER_NAMES
    ][:16]
    output: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    seen: set[tuple[str, str]] = set()
    for publisher, url in PRESS_WIRE_RSS.items():
        if publisher in skip_publishers:
            errors[publisher] = "COOLDOWN_ACTIVE"
            continue
        try:
            response = _get(
                url, session=session, headers={"Accept": "application/rss+xml, application/xml"},
            )
            feed = feedparser.parse(response.content)
            if feed.bozo and not feed.entries:
                raise ValueError("Invalid publisher RSS XML")
            if not feed.entries and b"<rss" not in response.content[:1000].lower():
                raise ValueError("Publisher RSS missing expected format")
            entries = list(feed.entries)[:110]
            allowed_hosts = (
                ("www.prnewswire.com", "prnewswire.com")
                if publisher == "prnewswire" else
                ("www.globenewswire.com", "globenewswire.com")
            )
            for item in entries:
                title = str(item.get("title") or "").strip()[:250]
                link = _https(item.get("link"), allowed_hosts)
                published = _iso(item.get("published") or item.get("updated"))
                if not title or not link or published is None:
                    continue
                age = current - published
                if age < timedelta(minutes=-3) or age > timedelta(days=7):
                    continue
                for symbol in watch:
                    aliases = ISSUER_NAMES[symbol]
                    company_mention = any(
                        re.search(r"(?<![A-Za-z0-9])" + re.escape(alias) +
                                  r"(?![A-Za-z0-9])", title, re.IGNORECASE)
                        for alias in aliases
                    )
                    exchange_mention = bool(re.search(
                        rf"(?<![A-Z0-9])(?:\${re.escape(symbol)}|"
                        rf"(?:NASDAQ|NYSE|AMEX)\s*:\s*{re.escape(symbol)})(?![A-Z0-9])",
                        title, re.IGNORECASE,
                    ))
                    if not (company_mention or exchange_mention):
                        continue
                    if (symbol, link) in seen:
                        continue
                    seen.add((symbol, link))
                    output.append({
                        "symbol": symbol, "headline": title, "url": link,
                        "published_at": published.isoformat(),
                        "source": publisher,
                        "source_family": "press_wire_syndication",
                        "authority": "PRESS_RELEASE_DISCOVERY_ONLY",
                        "company_mentioned_in_headline": True,
                        "issuer_release_authenticated": False,
                        "positive_catalyst_verified": False,
                        "official_sec_filing": False,
                        "market_direction": "UNKNOWN",
                        "price_or_option_quote": False,
                    })
        except requests.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            errors[publisher] = f"HTTP_{status}" if isinstance(status, int) else "HTTP_ERROR"
        except (requests.RequestException, ValueError, TypeError) as exc:
            errors[publisher] = type(exc).__name__
    output.sort(key=lambda item: item["published_at"], reverse=True)
    return output[:40], errors


_GENERIC_STOCK_PAGE = re.compile(
    r"(?:stock price[, ]+news[, ]+quote|stock price (?:today|forecast)|"
    r"quote\s*(?:&|and)\s*history|buy,\s*sell,?\s*or\s*hold|"
    r"price predictions?|stock forecasts?|latest stock quote)",
    re.IGNORECASE,
)
_NEWS_EVENT_TERMS = re.compile(
    r"\b(?:announce[ds]?|announcing|contract(?:s)?|agreement(?:s)?|"
    r"partnership|deal|award(?:s)?|launch(?:es|ed)?|delay(?:ed|s)?|"
    r"mission|approval|approved|FDA|clinical trial|phase [123]|"
    r"acquisition|merger|spectrum purchase|offering|dilution|"
    r"filing|filed|reports?|results?|earnings|revenue|loss(?:es)?|"
    r"guidance|funding|financing|debt|lawsuit|settlement|"
    r"investigation|bankruptcy|share buyback|dividend|"
    r"quarterly|annual loss|annual results)\b",
    re.IGNORECASE,
)
_RISK_NEWS_TERMS = re.compile(
    r"\b(?:loss(?:es)?|delay(?:ed|s)?|offering|dilution|"
    r"bankruptcy|debt|lawsuit|investigation|"
    r"negative guidance|share sale|shelf registration)\b",
    re.IGNORECASE,
)
_FINANCIAL_NEWS_TERMS = re.compile(
    r"\b(?:quarterly|annual results|annual loss|reports?|results?|"
    r"earnings|revenue|guidance)\b",
    re.IGNORECASE,
)


def classify_issuer_news_headline(title: str) -> str | None:
    """Precision-first *topic*, never publisher verification or prediction."""
    if _GENERIC_STOCK_PAGE.search(title) or not _NEWS_EVENT_TERMS.search(title):
        return None
    if _RISK_NEWS_TERMS.search(title):
        return "RISK_OR_ADVERSE_EVENT_MENTION"
    if _FINANCIAL_NEWS_TERMS.search(title):
        return "FINANCIAL_REPORT_MENTION"
    return "CORPORATE_EVENT_MENTION"


def google_issuer_attention(
    symbols: list[str], *, session: Any = requests, now: datetime | None = None,
    dynamic_names: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Six bounded issuer-name RSS searches; source is NOT an official API.

    RSS may change or block hosted runners. Only headlines explicitly naming
    the *queried* issuer qualify; Google matching/translation is not evidence.
    """
    current = now or datetime.now(UTC)
    preference = ("RGC", "BNAI", "RKLB", "IONQ", "SOUN", "ASTS",
                  "RGTI", "SOFI", "MU", "NVDA", "AMD", "AAPL",
                  "TSLA", "PLTR", "MSFT", "AVGO")
    requested = {str(s).upper().strip() for s in symbols}
    directory = {s: (name,) for s, name in (dynamic_names or {}).items()
                 if s not in ISSUER_NAMES and _SYMBOL_RE.fullmatch(s)
                 and isinstance(name, str) and len(name) >= 6}
    names = {**ISSUER_NAMES, **directory}
    # Same maximum six RSS calls; unlisted dynamic candidates never get
    # searched by ambiguous bare ticker.
    eligible = [s for s in preference if s in requested and s in names]
    dynamic = sorted(s for s in directory if s in requested)
    # Reserve up to two slots per hourly rotation for new discoveries, while
    # preserving the six-request hard cap and coverage of curated names.
    if dynamic:
        hour = int(current.timestamp() // 3600)
        curated_slots = 4
        curated_batches = max(1, (len(eligible) + curated_slots - 1)//curated_slots)
        extra_batches = max(1, (len(dynamic) + 1)//2)
        start_curated = (hour % curated_batches)*curated_slots
        start_dynamic = (hour % extra_batches)*2
        selected = eligible[start_curated:start_curated+curated_slots]
        selected += dynamic[start_dynamic:start_dynamic+2]
    elif len(eligible) > GOOGLE_NEWS_MAX_ISSUERS:
        shift = int(current.timestamp() // 3600) % (
            (len(eligible)+GOOGLE_NEWS_MAX_ISSUERS-1)//GOOGLE_NEWS_MAX_ISSUERS
        )
        selected = eligible[shift*GOOGLE_NEWS_MAX_ISSUERS:
                            (shift+1)*GOOGLE_NEWS_MAX_ISSUERS]
    else:
        selected = eligible
    events: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for symbol in selected:
        name = names[symbol][0]
        # Do not rely on fuzzy ticker matching: retrieve by issuer's precise
        # name, then verify the title. No article body or scraping.
        query = f'"{name}" stock when:7d'
        try:
            response = _get(
                GOOGLE_NEWS_RSS, session=session,
                params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
                headers={"Accept": "application/rss+xml, application/xml"},
            )
            parsed = feedparser.parse(response.content)
            if parsed.bozo and not parsed.entries:
                raise ValueError("Google RSS could not be parsed")
            if not parsed.entries and b"<rss" not in response.content[:1000].lower():
                raise ValueError("Google RSS missing expected feed")
            for item in list(parsed.entries)[:20]:
                title = str(item.get("title") or "").strip()[:250]
                link = _https(item.get("link"), ("news.google.com",))
                published = _iso(item.get("published") or item.get("updated"))
                if not title or not link or published is None:
                    continue
                age = current - published
                if not timedelta(minutes=-3) <= age <= timedelta(days=7):
                    continue
                # The title must match the precise company, never a bare
                # ticker like AI/MU/RGC. Require first full name or a curated
                # unambiguous alternate issuer name.
                aliases = names[symbol]
                if not any(re.search(r"(?<![A-Za-z0-9])" + re.escape(alias) +
                                     r"(?![A-Za-z0-9])", title, re.IGNORECASE)
                           for alias in aliases):
                    continue
                topic = classify_issuer_news_headline(title)
                if topic is None:
                    continue  # Price portal, generic opinion, or no named event.
                events.append({
                    "event_topic": topic,
                    "symbol": symbol, "headline": title, "url": link,
                    "published_at": published.isoformat(),
                    "source": "google_news_rss",
                    "source_family": "unofficial_google_news_search_rss",
                    "authority": "NEWS_SEARCH_ATTENTION_ONLY",
                    "issuer_name_in_headline": True,
                    "issuer_name_source": ("github_public_listing_mirrors" if symbol in directory
                                           else "curated_static_issuer_names"),
                    "issuer_release_authenticated": False,
                    "official_sec_filing": False,
                    "positive_catalyst_verified": False,
                    "market_direction": "UNKNOWN",
                    "price_or_option_quote": False,
                })
        except requests.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            errors[symbol] = f"HTTP_{status}" if isinstance(status, int) else "HTTP_ERROR"
            # A provider-wide refusal must stop this run, not produce an
            # unnecessary burst across all six requested issuer searches.
            if status in (403, 429):
                break
        except (requests.RequestException, ValueError, TypeError) as exc:
            errors[symbol] = type(exc).__name__
    # Publisher articles can repeat across searches; keep issuer+article
    # identity and first observed publication time intact.
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in events:
        unique.setdefault((item["symbol"], item["url"]), item)
    # Balance coverage across issuers; a high-profile stock cannot take
    # every public slot by filling an entire RSS page with near duplicates.
    balanced: list[dict[str, Any]] = []
    per_symbol: dict[str, int] = {}
    for item in sorted(unique.values(), key=lambda x: x["published_at"], reverse=True):
        symbol = item["symbol"]
        if per_symbol.get(symbol, 0) >= 4:
            continue
        balanced.append(item)
        per_symbol[symbol] = per_symbol.get(symbol, 0) + 1
    return balanced[:24], errors


def fed_monetary_updates(
    *, session: Any = requests, now: datetime | None = None,
) -> list[dict[str, Any]]:
    current = now or datetime.now(UTC)
    response = _get(FED_MONETARY, session=session)
    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        raise ValueError("Federal Reserve RSS parse failed")
    events = []
    for item in list(parsed.entries)[:30]:
        url = _https(item.get("link"), ("www.federalreserve.gov", "federalreserve.gov"))
        # publication timestamp belongs to publisher, not local generated_at
        published = _iso(item.get("published") or item.get("updated"))
        if not published or not url or not str(item.get("title") or "").strip():
            continue
        age = current - published
        if not timedelta(minutes=-3) <= age <= timedelta(days=7):
            continue
        events.append({
            "title": str(item.title).strip()[:250],
            "published_at": published.isoformat(),
            "url": url, "source": "federal_reserve_monetary_rss",
            "authority": "OFFICIAL_PUBLICATION", "event_type": "RELEASED_NEWS",
            "price_direction": "UNKNOWN",
        })
    return events


def _unfold_ics(content: str) -> list[str]:
    out: list[str] = []
    for line in content.replace("\r\n", "\n").split("\n"):
        if line.startswith((" ", "\t")) and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def parse_bls_calendar(
    content: str, *, now: datetime | None = None,
    horizon_days: int = 14,
) -> list[dict[str, Any]]:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("now requires timezone")
    if "BEGIN:VCALENDAR" not in content or "BEGIN:VEVENT" not in content:
        raise ValueError("BLS iCalendar invalid")
    limit = current + timedelta(days=min(30, max(1, horizon_days)))
    events: list[dict[str, Any]] = []
    item: dict[str, str] | None = None
    for line in _unfold_ics(content):
        if line == "BEGIN:VEVENT":
            item = {}
        elif line == "END:VEVENT":
            if item:
                name = item.get("SUMMARY", "").replace("\\,", ",").strip()
                key = name.casefold()
                # Only high-impact or material U.S. macro calendar entries.
                if any(term in key for term in (
                    "consumer price index", "producer price index",
                    "employment situation", "job openings and labor turnover",
                    "employment cost index",
                )):
                    raw_date = item.get("_DT", "")
                    zone = item.get("_TZ", "America/New_York")
                    dt = None
                    try:
                        if re.fullmatch(r"\d{8}T\d{6}Z", raw_date):
                            dt = datetime.strptime(raw_date, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
                        elif re.fullmatch(r"\d{8}T\d{6}", raw_date):
                            tz = NY if zone in ("", "America/New_York", "US/Eastern", "US-Eastern") else ZoneInfo(zone)
                            dt = datetime.strptime(raw_date, "%Y%m%dT%H%M%S").replace(tzinfo=tz).astimezone(UTC)
                    except (ValueError, KeyError):
                        dt = None
                    if dt is not None and current <= dt <= limit:
                        events.append({
                            "title": name[:160], "scheduled_at": dt.isoformat(),
                            "source": "bls_official_ical",
                            "url": "https://www.bls.gov/schedule/news_release/bls.ics",
                            "authority": "OFFICIAL_SCHEDULE",
                            "event_type": "UPCOMING_RELEASE",
                            "economic_result_available": False,
                            "price_direction": "UNKNOWN",
                        })
            item = None
        elif item is not None:
            m = _ICS_DT_RE.match(line)
            if m:
                item["_DT"] = m.group("value")
                item["_TZ"] = m.group("tz") or ("UTC" if m.group("value").endswith("Z") else "America/New_York")
            elif ":" in line:
                k, v = line.split(":", 1)
                if k in {"SUMMARY", "UID"}:
                    item[k] = v.strip()
    return sorted({(x["title"], x["scheduled_at"]): x for x in events}.values(), key=lambda x: x["scheduled_at"])


def bls_upcoming(*, session: Any = requests, now: datetime | None = None) -> list[dict[str, Any]]:
    response = _get(BLS_ICS, session=session, headers={"Accept": "text/calendar,text/plain"})
    return parse_bls_calendar(response.text, now=now)


def alpaca_iex_health(
    *, session: Any = requests, now: datetime | None = None,
    key: str = "", secret: str = "",
) -> dict[str, Any]:
    key = key or os.getenv("ALPACA_API_KEY", "")
    secret = secret or os.getenv("ALPACA_SECRET_KEY", "")
    base = {
        "provider": "alpaca_iex", "feed": "iex", "source_family": "alpaca_iex",
        "execution_grade": False, "opra_options": False,
        "quote_freshness_verified": False, "stock_bar_only": True,
    }
    if not key or not secret:
        return {**base, "status": "NOT_CONFIGURED"}
    try:
        response = _get(
            ALPACA_LATEST, session=session, params={"feed": "iex"},
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
        )
        body = response.json()
        point = (body.get("bar") if isinstance(body, dict) else None) or {}
        stamp = _iso(point.get("t"))
        if stamp is None or not isinstance(point, dict):
            raise ValueError("Alpaca IEX bar lacks provider timestamp")
        current = now or datetime.now(UTC)
        delta = current - stamp
        if delta < timedelta(minutes=-3):
            raise ValueError("Alpaca bar timestamp in the future")
        return {
            **base, "status": "AVAILABLE_RESEARCH" if delta <= timedelta(days=4) else "STALE",
            "bar_timestamp": stamp.isoformat(), "bar_age_minutes": round(delta.total_seconds() / 60, 1),
            "note": "IEX single exchange minute bar; not full SIP/OPRA or live quote entitlement.",
        }
    except (requests.RequestException, ValueError, TypeError) as exc:
        return {**base, "status": "UNAVAILABLE", "error": type(exc).__name__}


def valid_source_cooldowns(previous: dict, *, now: datetime) -> dict[str, dict]:
    """Honor only bounded source refusals from a recent first-party report."""
    if not isinstance(previous, dict) or previous.get("schema") != "free_public_intelligence_v1":
        return {}
    report_time = _iso(previous.get("generated_at"))
    if report_time is None or not timedelta(0) <= now - report_time <= timedelta(days=7):
        return {}
    raw = previous.get("source_cooldowns")
    if not isinstance(raw, dict):
        return {}
    active = {}
    for key in _COOLDOWN_SOURCES:
        item = raw.get(key)
        if not isinstance(item, dict) or item.get("last_error") not in _COOLDOWN_HOURS:
            continue
        until = _iso(item.get("retry_after"))
        if until is not None and timedelta(0) < until - now <= timedelta(hours=48):
            active[key] = {"last_error": item["last_error"],
                           "retry_after": until.isoformat()}
    return active


def update_source_cooldowns(existing: dict, errors: dict, *, now: datetime) -> dict:
    """Bounded circuit breaker; original 403/404/429 remain explicit."""
    active = dict(existing)
    for key in _COOLDOWN_SOURCES:
        error = errors.get(key)
        if key == "google_news_attention" and error is None:
            error = next((v for k, v in errors.items()
                          if k.startswith("google_news_") and v in _COOLDOWN_HOURS), None)
        if error in _COOLDOWN_HOURS:
            active[key] = {
                "last_error": error,
                "retry_after": (now + timedelta(hours=_COOLDOWN_HOURS[error])).isoformat(),
            }
    return active


def build_context(*, symbols: list[str], now: datetime | None = None,
                  session: Any = requests, prior_cooldowns: dict | None = None,
                  dynamic_names: dict[str, str] | None = None) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    cooldowns = prior_cooldowns or {}
    pieces: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, fn, opts in (
        ("gdelt_attention", gdelt_attention, {"symbols": symbols}),
        ("fed_monetary", fed_monetary_updates, {}),
        ("bls_upcoming", bls_upcoming, {}),
    ):
        if key in cooldowns:
            pieces[key] = []
            errors[key] = "COOLDOWN_ACTIVE"
            continue
        try:
            pieces[key] = fn(session=session, now=current, **opts)
        except requests.HTTPError as exc:
            pieces[key] = []
            code = getattr(getattr(exc, "response", None), "status_code", None)
            # The upstream may reject shared runners (e.g. GDELT HTTP 429).
            # Never retry a 429 aggressively or manufacture fallback articles.
            errors[key] = f"HTTP_{code}" if isinstance(code, int) else "HTTP_ERROR"
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            pieces[key] = []
            errors[key] = type(exc).__name__
    # Press-wire RSS operates independently from GDELT 429 and SEC 403.
    # These are publisher-distributed titles, not SEC or issuer confirmation.
    skipped = frozenset(
        key.removeprefix("press_wire_") for key in cooldowns
        if key.startswith("press_wire_")
    )
    press_items, press_errors = press_wire_attention(
        symbols, session=session, now=current, skip_publishers=skipped,
    )
    pieces["press_wire_attention"] = press_items
    errors.update({"press_wire_" + k: v for k, v in press_errors.items()})
    if "google_news_attention" in cooldowns:
        google_items, google_errors = [], {}
        errors["google_news_attention"] = "COOLDOWN_ACTIVE"
    else:
        google_items, google_errors = google_issuer_attention(
            symbols, session=session, now=current, dynamic_names=dynamic_names,
        )
    pieces["google_news_attention"] = google_items
    errors.update({"google_news_" + key: value for key, value in google_errors.items()})
    pieces["alpaca_iex"] = alpaca_iex_health(session=session, now=current)
    updated_cooldowns = update_source_cooldowns(cooldowns, errors, now=current)
    return {
        "schema": "free_public_intelligence_v1",
        "generated_at": current.isoformat(),
        "status": "READY" if not errors else "DEGRADED",
        "source_errors": errors,
        "source_cooldowns": updated_cooldowns,
        "decision_authority": False, "live_alert_weights_changed": False,
        "is_independent_executable_market_data": False,
        "policy": {
            "gdelt_attention_not_official_confirmation": True,
            "press_wire_is_discovery_not_issuer_or_bullish_confirmation": True,
            "google_news_rss_is_unofficial_search_not_official_confirmation": True,
            "bls_calendar_is_schedule_not_release_result": True,
            "fed_rss_publication_is_not_upcoming_fomc_calendar": True,
            "alpaca_iex_not_national_market_or_opra": True,
            "no_quote_or_freshness_fabrication": True,
        },
        **pieces,
    }


def retain_verified_news_context(
    current: dict, previous: dict, *, now: datetime,
    dynamic_names: dict[str, str] | None = None,
) -> dict:
    """Preserve historical *published* RSS headlines across rotated batches.

    Retention is not a provider refresh: original publication time stays
    unchanged, and previous collection timestamp is retained separately.
    Filter stale or unverified/unmatched stories to fail closed.
    """
    names = {**ISSUER_NAMES, **{
        s: (name,) for s, name in (dynamic_names or {}).items()
        if s not in ISSUER_NAMES and _SYMBOL_RE.fullmatch(s)
        and isinstance(name, str) and len(name) >= 6
    }}
    valid = []
    current_urls = {(x.get("symbol"),x.get("url")) for x in
                    current.get("google_news_attention",[]) if isinstance(x,dict)}
    for item in (current.get("google_news_attention") or []) + (
            previous.get("google_news_attention") or []):
        if not isinstance(item, dict):
            continue
        published = _iso(item.get("published_at"))
        if published is None or not timedelta(minutes=-3) <= now-published <= timedelta(days=7):
            continue
        symbol = str(item.get("symbol") or "")
        url = _https(item.get("url"), ("news.google.com",))
        headline = str(item.get("headline") or "")
        if (symbol not in names or not url or
                item.get("authority") != "NEWS_SEARCH_ATTENTION_ONLY" or
                item.get("positive_catalyst_verified") is not False or
                item.get("issuer_release_authenticated") is not False or
                item.get("market_direction") != "UNKNOWN" or
                classify_issuer_news_headline(headline) is None):
            continue
        aliases = names[symbol]
        if not any(re.search(r"(?<![A-Za-z0-9])" + re.escape(alias) +
                             r"(?![A-Za-z0-9])", headline, re.IGNORECASE)
                   for alias in aliases):
            continue
        safe = dict(item)
        safe["first_collected_at"] = str(item.get("first_collected_at") or (
            current.get("generated_at") if (symbol,url) in current_urls
            else previous.get("generated_at") or current.get("generated_at")) )
        safe["published_at"] = published.isoformat()
        valid.append(safe)
    by_identity = {}
    for item in valid:
        by_identity.setdefault((item["symbol"], item["url"]), item)
    balanced = []
    per_symbol = {}
    for item in sorted(by_identity.values(), key=lambda x:x["published_at"],reverse=True):
        symbol=item["symbol"]
        if per_symbol.get(symbol,0)>=4:
            continue
        per_symbol[symbol]=per_symbol.get(symbol,0)+1
        balanced.append(item)
    current["google_news_attention"] = balanced[:48]
    current["google_news_retention"] = {
        "historical_stories_preserved": sum(
            (x["symbol"],x["url"]) not in current_urls
            for x in balanced
        ),
        "note": "Older stories keep publication timestamps; not refreshed quotes",
    }
    current.pop("_new_stories",None)
    return current


def main() -> None:
    parser = argparse.ArgumentParser(description="Keyless GDELT/Fed/BLS research context + optional Alpaca IEX health")
    parser.add_argument("--output", default="public/data/free_public_intelligence.json")
    parser.add_argument("--symbols", default=",".join(WATCH_DEFAULT))
    parser.add_argument("--previous", type=Path, default=None)
    parser.add_argument("--discovery-brief", type=Path, default=None)
    args = parser.parse_args()
    symbols = [x.strip().upper() for x in args.symbols.split(",") if x.strip()]
    current = datetime.now(UTC)
    previous = {}
    if (args.previous and args.previous.is_file()
            and args.previous.stat().st_size <= 200_000):
        try:
            previous = json.loads(args.previous.read_text(encoding="utf-8"))
        except (ValueError, TypeError, OSError):
            previous = {}
    cooldowns = valid_source_cooldowns(previous, now=current)
    scanned = symbols_from_brief(args.discovery_brief, now=current)
    extra = [s for s in scanned if s not in ISSUER_NAMES and s not in symbols][:24]
    directory = resolve_public_issuers(
        extra, now=current, previous=previous, session=requests,
    ) if extra else {
        "source_family": "github_public_listing_mirrors",
        "status": "NO_NEW_ISSUERS", "issuers": {}, "research_only": True,
    }
    dynamic_names = directory.get("issuers", {})
    symbols.extend(s for s in extra if s in dynamic_names)
    payload = build_context(
        symbols=symbols, now=current, prior_cooldowns=cooldowns,
        dynamic_names=dynamic_names,
    )
    payload["issuer_directory"] = directory
    if (isinstance(previous, dict)
            and previous.get("schema") == "free_public_intelligence_v1"
            and _iso(previous.get("generated_at")) is not None):
        payload["_new_stories"] = list(payload.get("google_news_attention") or [])
        payload = retain_verified_news_context(
            payload, previous, now=current, dynamic_names=dynamic_names,
        )
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(dest)
    print(
        "Free public context:"
        f" status={payload['status']}"
        f" gdelt={len(payload['gdelt_attention'])}"
        f" presswire={len(payload['press_wire_attention'])}"
        f" gnews={len(payload['google_news_attention'])}"
        f" fed={len(payload['fed_monetary'])}"
        f" bls={len(payload['bls_upcoming'])}"
        f" alpaca={payload['alpaca_iex']['status']}"
        f" degraded_sources={','.join(payload['source_errors']) or 'none'}"
    )


if __name__ == "__main__":
    main()
