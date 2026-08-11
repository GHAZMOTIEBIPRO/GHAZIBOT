from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts import fast_explosion_scan as base

LATEST_PATH = Path("public/data/latest.json")
_original_collect_fast_news = base.collect_fast_news


def _valid_common(symbol: str, name: str) -> bool:
    if not base.SYMBOL_RE.fullmatch(symbol):
        return False
    # Only explicit warrant suffixes are rejected by ticker. Single-letter R/W/U
    # can be valid common-stock tickers, so security-name filtering decides those.
    if symbol.endswith(("WS", "WT")):
        return False
    normalized = f" {name.lower()} "
    return not any(token in normalized for token in base.NON_COMMON_NAME_TOKENS)


def _deep_catalyst_news(known_symbols: set[str] | None = None) -> list[base.NewsEvent]:
    try:
        payload = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    omega = payload.get("omega") if isinstance(payload, dict) and isinstance(payload.get("omega"), dict) else {}
    intelligence = omega.get("catalyst_intelligence") if isinstance(omega.get("catalyst_intelligence"), dict) else {}
    by_symbol = intelligence.get("by_symbol") if isinstance(intelligence.get("by_symbol"), dict) else {}
    today = datetime.now(timezone.utc).date()
    events: list[base.NewsEvent] = []
    for raw_symbol, cluster in by_symbol.items():
        if not isinstance(cluster, dict):
            continue
        symbol = str(raw_symbol or "").upper().strip()
        if not symbol or (known_symbols and symbol not in known_symbols):
            continue
        quality = base._number(cluster.get("catalyst_quality"))
        materiality = base._number(cluster.get("materiality"))
        bias = str(cluster.get("directional_bias") or "").lower()
        if max(quality, materiality) < 55 or bias not in {"bullish", "mixed"}:
            continue
        event_date_text = str(cluster.get("event_date") or "")[:10]
        try:
            event_date = datetime.strptime(event_date_text, "%Y-%m-%d").date()
            if (today - event_date).days > 4:
                continue
        except ValueError:
            pass
        headline = str(cluster.get("headline") or cluster.get("title") or cluster.get("event_type") or "").strip()
        if not headline:
            continue
        relevance = min(1.0, max(quality, materiality) / 100.0)
        sentiment = 0.55 if bias == "bullish" else 0.10
        events.append(
            base.NewsEvent(
                symbol=symbol,
                headline=headline,
                source=str(cluster.get("primary_source") or "BLACK BOX Ω Catalyst Intelligence"),
                url=str(cluster.get("primary_url") or ""),
                published=event_date_text,
                relevance=relevance,
                sentiment=sentiment,
                provider="omega_deep_catalyst",
            )
        )
    return events


def _combined_fast_news(known_symbols: set[str] | None = None) -> list[base.NewsEvent]:
    events = _deep_catalyst_news(known_symbols=known_symbols)
    try:
        events.extend(_original_collect_fast_news(known_symbols=known_symbols))
    except Exception as exc:
        print(f"Optional live-news providers skipped: {type(exc).__name__}: {exc}")
    deduped: dict[tuple[str, str], base.NewsEvent] = {}
    for event in events:
        key = (event.symbol, event.headline.lower()[:180])
        previous = deduped.get(key)
        if previous is None or event.relevance > previous.relevance:
            deduped[key] = event
    return list(deduped.values())


# Patch policy without duplicating the full scanner implementation.
base._valid_common = _valid_common
base.collect_fast_news = _combined_fast_news
rank_market = base.rank_market
run = base.run


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
