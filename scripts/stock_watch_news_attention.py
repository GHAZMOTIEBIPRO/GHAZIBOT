"""Safe, bounded research-only issuer-name-matched Google News context.

This module never treats news-search attention as a verified issuer release,
official SEC filing, positive catalyst or direction. It does not fetch URLs.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SYMBOL = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z])?$")
_EXCLUDED = frozenset({"SPX", "NDX", "DJI", "RUT", "VIX", "SPY", "QQQ", "IWM", "DIA"})
MAX_FILE_BYTES = 400_000


def _date(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def load_news_attention(path: Path | None, *, now: datetime) -> dict[str, dict[str, Any]]:
    """Strict schema, age and issuer-name guards; no arbitrary headline ticker search."""
    if now.tzinfo is None or path is None:
        return {}
    now = now.astimezone(timezone.utc)
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return {}
        feed = json.loads(path.read_text(encoding="utf-8"))
        generated = _date(feed.get("generated_at"))
        if (feed.get("schema") != "free_public_intelligence_v1"
                or generated is None or not -300 <= (now - generated).total_seconds() <= 48 * 3600):
            return {}
        rows = feed.get("google_news_attention")
        if not isinstance(rows, list):
            return {}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}

    by_symbol: dict[str, dict[str, Any]] = {}
    for row in rows[:150]:
        if not isinstance(row, dict):
            continue
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol) or symbol in _EXCLUDED:
            continue
        if (row.get("authority") != "NEWS_SEARCH_ATTENTION_ONLY"
                or row.get("source_family") != "unofficial_google_news_search_rss"
                or row.get("issuer_name_in_headline") is not True
                or row.get("issuer_release_authenticated") is not False
                or row.get("positive_catalyst_verified") is not False
                or row.get("market_direction") != "UNKNOWN"):
            continue
        published = _date(row.get("published_at"))
        collected = _date(row.get("first_collected_at"))
        if (published is None or collected is None
                or not 0 <= (now - published).total_seconds() <= 72 * 3600
                or not 0 <= (now - collected).total_seconds() <= 72 * 3600
                or published > collected):
            continue
        previous = by_symbol.get(symbol)
        if previous is None or published.isoformat() > previous["latest_published_at"]:
            by_symbol[symbol] = {
                "symbol": symbol,
                "latest_published_at": published.isoformat(),
                "source_family": "unofficial_google_news_search_rss",
                "authority": "NEWS_SEARCH_ATTENTION_ONLY",
                "official_catalyst_verified": False,
                "research_only": True,
                "news_search_attention": True,
                "headline_direction_inferred": False,
                "live_decision_authority": False,
            }
    return by_symbol


def news_candidates(
    attention: dict[str, dict[str, Any]],
    *,
    fixed: tuple[str, ...],
    radar_choices: tuple[str, ...],
    maximum: int,
) -> tuple[str, ...]:
    """Use unused slots for issuer-matched *attention* after ranked radar stocks.

    News does not promote scores; this merely supplies bounded price-chart
    discovery symbols when official market data is not available.
    """
    if maximum <= 0:
        return ()
    selected = list(dict.fromkeys(radar_choices[:2]))
    ordered_news = sorted(attention.values(), key=lambda x: x["latest_published_at"], reverse=True)
    for item in ordered_news:
        symbol = item["symbol"]
        if (symbol not in fixed and symbol not in _EXCLUDED
                and symbol not in selected and len(selected) < maximum):
            selected.append(symbol)
    for symbol in radar_choices[2:]:
        if symbol not in selected and symbol not in fixed and len(selected) < maximum:
            selected.append(symbol)
    return tuple(selected[:maximum])
