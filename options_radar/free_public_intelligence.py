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
}

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
WATCH_DEFAULT = ("MU", "NVDA", "RGC", "BNAI", "RKLB", "AMD")
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


def google_issuer_attention(
    symbols: list[str], *, session: Any = requests, now: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Six bounded issuer-name RSS searches; source is NOT an official API.

    RSS may change or block hosted runners. Only headlines explicitly naming
    the *queried* issuer qualify; Google matching/translation is not evidence.
    """
    current = now or datetime.now(UTC)
    preference = ("RGC", "BNAI", "RKLB", "IONQ", "SOUN", "ASTS",
                  "RGTI", "MU", "NVDA", "AMD", "AAPL", "TSLA", "PLTR")
    requested = {str(s).upper().strip() for s in symbols}
    selected = [s for s in preference if s in requested and s in ISSUER_NAMES][:GOOGLE_NEWS_MAX_ISSUERS]
    events: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for symbol in selected:
        name = ISSUER_NAMES[symbol][0]
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
                aliases = ISSUER_NAMES[symbol]
                if not any(re.search(r"(?<![A-Za-z0-9])" + re.escape(alias) +
                                     r"(?![A-Za-z0-9])", title, re.IGNORECASE)
                           for alias in aliases):
                    continue
                events.append({
                    "symbol": symbol, "headline": title, "url": link,
                    "published_at": published.isoformat(),
                    "source": "google_news_rss",
                    "source_family": "unofficial_google_news_search_rss",
                    "authority": "NEWS_SEARCH_ATTENTION_ONLY",
                    "issuer_name_in_headline": True,
                    "issuer_release_authenticated": False,
                    "official_sec_filing": False,
                    "positive_catalyst_verified": False,
                    "market_direction": "UNKNOWN",
                    "price_or_option_quote": False,
                })
        except requests.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            errors[symbol] = f"HTTP_{status}" if isinstance(status, int) else "HTTP_ERROR"
            # Google 403/429 are host-wide fair-use refusals. Stop immediately:
            # querying the remaining symbols would turn one failure into
            # a costly burst and does not improve evidence quality.
            if status in (403, 429):
                break
        except (requests.RequestException, ValueError, TypeError) as exc:
            errors[symbol] = type(exc).__name__
    # Publisher articles can repeat across searches; keep issuer+article
    # identity and first observed publication time intact.
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in events:
        unique.setdefault((item["symbol"], item["url"]), item)
    return sorted(unique.values(), key=lambda x: x["published_at"], reverse=True)[:36], errors


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


def build_context(*, symbols: list[str], now: datetime | None = None, session: Any = requests) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    pieces: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, fn, opts in (
        ("gdelt_attention", gdelt_attention, {"symbols": symbols}),
        ("fed_monetary", fed_monetary_updates, {}),
        ("bls_upcoming", bls_upcoming, {}),
    ):
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
    press_items, press_errors = press_wire_attention(symbols, session=session, now=current)
    pieces["press_wire_attention"] = press_items
    errors.update({"press_wire_" + k: v for k, v in press_errors.items()})
    google_items, google_errors = google_issuer_attention(symbols, session=session, now=current)
    pieces["google_news_attention"] = google_items
    errors.update({"google_news_" + key: value for key, value in google_errors.items()})
    pieces["alpaca_iex"] = alpaca_iex_health(session=session, now=current)
    return {
        "schema": "free_public_intelligence_v1",
        "generated_at": current.isoformat(),
        "status": "READY" if not errors else "DEGRADED",
        "source_errors": errors,
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Keyless GDELT/Fed/BLS research context + optional Alpaca IEX health")
    parser.add_argument("--output", default="public/data/free_public_intelligence.json")
    parser.add_argument("--symbols", default=",".join(WATCH_DEFAULT))
    args = parser.parse_args()
    symbols = [x.strip().upper() for x in args.symbols.split(",") if x.strip()]
    payload = build_context(symbols=symbols)
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
