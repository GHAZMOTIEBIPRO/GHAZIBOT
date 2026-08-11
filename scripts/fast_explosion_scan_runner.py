from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import fast_explosion_scan as base

LATEST_PATH = Path("public/data/latest.json")
FAST_MARKET_STATE_PATH = Path("data/live/fast_market_state.json")
_original_collect_fast_news = base.collect_fast_news
_original_rank_market = base.rank_market


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


def _load_previous_fast_state() -> tuple[dict[str, dict], float]:
    try:
        payload = json.loads(FAST_MARKET_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, 0.0
    generated = str(payload.get("generated_at") or "")
    try:
        previous_time = datetime.fromisoformat(generated.replace("Z", "+00:00"))
        age_minutes = (datetime.now(timezone.utc) - previous_time.astimezone(timezone.utc)).total_seconds() / 60.0
    except ValueError:
        age_minutes = 9999.0
    rows = payload.get("symbols") if isinstance(payload.get("symbols"), dict) else {}
    if age_minutes < 0 or age_minutes > 90:
        return {}, age_minutes
    return {str(symbol).upper(): row for symbol, row in rows.items() if isinstance(row, dict)}, age_minutes


def _rank_market_with_delta(rows, news_events, structural):
    ranked = _original_rank_market(rows, news_events=news_events, structural=structural)
    previous, age_minutes = _load_previous_fast_state()
    raw_scores = {candidate.symbol: float(candidate.score) for candidate in ranked}
    acceleration_count = 0

    if previous:
        for candidate in ranked:
            prior = previous.get(candidate.symbol)
            if not prior:
                continue
            previous_score = base._number(prior.get("base_score"), base._number(prior.get("score")))
            previous_move = base._number(prior.get("move_pct"))
            previous_volume = base._number(prior.get("volume"))
            previous_turnover = base._number(prior.get("turnover_pct"))
            score_delta = raw_scores[candidate.symbol] - previous_score
            move_delta = candidate.move_pct - previous_move
            turnover_delta = candidate.turnover_pct - previous_turnover
            volume_growth = candidate.volume / previous_volume if previous_volume > 0 else 1.0

            bonus = 0.0
            if score_delta >= 4:
                bonus += min(6.0, score_delta * 0.35)
            if move_delta >= 0.8:
                bonus += min(4.0, move_delta * 0.55)
            if turnover_delta >= 0.15:
                bonus += min(4.0, turnover_delta * 2.5)
            if 1.08 <= volume_growth <= 5.0:
                bonus += min(4.0, (volume_growth - 1.0) * 12.0)
            if candidate.supply_score >= 70 and (score_delta >= 3 or move_delta >= 0.7):
                bonus += 2.0

            if bonus >= 3.0:
                candidate.score = base._clamp(candidate.score + bonus)
                candidate.stage = base._stage(candidate.score, candidate.move_pct, candidate.turnover_pct)
                candidate.reasons.insert(
                    0,
                    f"Fast Delta +{bonus:.1f} | score {previous_score:.0f}→{raw_scores[candidate.symbol]:.0f} | price Δ {move_delta:+.1f}pt",
                )
                acceleration_count += 1

    state = {
        "generated_at": base._utc_now(),
        "source": "full-market compact inter-scan memory",
        "previous_snapshot_age_minutes": round(age_minutes, 2) if previous else None,
        "symbols": {
            candidate.symbol: {
                "base_score": round(raw_scores[candidate.symbol], 2),
                "score": round(float(candidate.score), 2),
                "stage": candidate.stage,
                "move_pct": round(float(candidate.move_pct), 4),
                "volume": round(float(candidate.volume), 2),
                "turnover_pct": round(float(candidate.turnover_pct), 5),
                "supply_score": round(float(candidate.supply_score), 2),
            }
            for candidate in ranked
        },
    }
    base._save(FAST_MARKET_STATE_PATH, state)
    if previous:
        print(f"Fast Delta memory: previous_age={age_minutes:.1f}m accelerated={acceleration_count}/{len(ranked)}")
    else:
        print(f"Fast Delta memory: baseline captured for {len(ranked)} symbols")

    ranked.sort(key=lambda item: (base.STAGE_ORDER.get(item.stage, 0), item.score, item.turnover_pct), reverse=True)
    return ranked


# Patch policy without duplicating the full scanner implementation.
base._valid_common = _valid_common
base.collect_fast_news = _combined_fast_news
base.rank_market = _rank_market_with_delta
rank_market = _rank_market_with_delta
run = base.run


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
