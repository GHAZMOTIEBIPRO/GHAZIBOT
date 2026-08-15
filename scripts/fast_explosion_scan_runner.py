from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from options_radar.institutional_radar import assess_candidate, should_promote
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


def _rank_market_with_institutional_engine(rows, news_events, structural):
    ranked = _original_rank_market(rows, news_events=news_events, structural=structural)
    previous, age_minutes = _load_previous_fast_state()
    raw_scores = {candidate.symbol: float(candidate.score) for candidate in ranked}
    promoted_count = 0

    for candidate in ranked:
        prior = previous.get(candidate.symbol)
        assessment = assess_candidate(candidate, prior)

        candidate.score = assessment.score
        candidate.stage = assessment.stage
        candidate.institutional_confidence = assessment.confidence
        candidate.institutional_earlyness = assessment.earlyness
        candidate.institutional_anomaly = assessment.anomaly
        candidate.institutional_acceleration = assessment.acceleration
        candidate.institutional_risk_penalty = assessment.risk_penalty
        candidate.institutional_priority = assessment.send_priority

        summary = (
            f"Ω Institutional {assessment.score:.0f}/100 | "
            f"ثقة {assessment.confidence} | مبكر {assessment.earlyness:.0f} | "
            f"شذوذ {assessment.anomaly:.0f} | تسارع {assessment.acceleration:.0f}"
        )
        candidate.reasons.insert(0, summary)
        for reason in reversed(assessment.reasons[:4]):
            candidate.reasons.insert(1, reason)
        for blocker in assessment.blockers[:2]:
            candidate.reasons.append(f"حاجز: {blocker}")

        if prior:
            prior_stage = str(prior.get("stage") or "WATCH")
            prior_score = base._number(prior.get("score"))
            if should_promote(prior_stage, assessment.stage, assessment.score - prior_score):
                promoted_count += 1

    state = {
        "generated_at": base._utc_now(),
        "source": "BLACK BOX Omega institutional-style full-market state memory",
        "score_is_probability": False,
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
                "confidence": str(getattr(candidate, "institutional_confidence", "D")),
                "earlyness": round(float(getattr(candidate, "institutional_earlyness", 0.0)), 2),
                "anomaly": round(float(getattr(candidate, "institutional_anomaly", 0.0)), 2),
                "acceleration": round(float(getattr(candidate, "institutional_acceleration", 0.0)), 2),
                "risk_penalty": round(float(getattr(candidate, "institutional_risk_penalty", 0.0)), 2),
                "send_priority": round(float(getattr(candidate, "institutional_priority", 0.0)), 2),
            }
            for candidate in ranked
        },
    }
    base._save(FAST_MARKET_STATE_PATH, state)

    if previous:
        print(
            f"Institutional memory: previous_age={age_minutes:.1f}m "
            f"promoted={promoted_count}/{len(ranked)}"
        )
    else:
        print(f"Institutional memory: baseline captured for {len(ranked)} symbols")

    ranked.sort(
        key=lambda item: (
            base.STAGE_ORDER.get(item.stage, 0),
            float(getattr(item, "institutional_priority", 0.0)),
            item.score,
            item.turnover_pct,
        ),
        reverse=True,
    )
    return ranked


def _institutional_message(candidate) -> str:
    stage_ar = {
        "PRESSURE_BUILDING": "تجميع ضغط / مراقبة مبكرة",
        "IGNITION": "بداية اشتعال",
        "EXPLOSION": "تأكيد حركة قوية",
        "EXTENDED": "ممتد — لا مطاردة",
    }.get(candidate.stage, "مراقبة")
    confidence = str(getattr(candidate, "institutional_confidence", "D"))
    earlyness = float(getattr(candidate, "institutional_earlyness", 0.0))
    anomaly = float(getattr(candidate, "institutional_anomaly", 0.0))
    acceleration = float(getattr(candidate, "institutional_acceleration", 0.0))
    risk = float(getattr(candidate, "institutional_risk_penalty", 0.0))
    reasons = "\n• ".join(candidate.reasons[:6]) or "تغيّر غير طبيعي قيد المتابعة"
    news = f"\n\n📰 {base._safe(candidate.news_headline, 500)}" if candidate.news_headline else ""
    emoji = "💥" if candidate.stage == "EXPLOSION" else "🔥" if candidate.stage == "IGNITION" else "🟡"

    return (
        f"{emoji} <b>BLACK BOX Ω — {base._safe(stage_ar)}</b>\n\n"
        f"<b>{base._safe(candidate.symbol)}</b> — ${candidate.price:,.2f}\n"
        f"Ω Score: <b>{candidate.score:.0f}/100</b> — الثقة <b>{base._safe(confidence)}</b>\n"
        f"مبكّر: <b>{earlyness:.0f}/100</b> | شذوذ: <b>{anomaly:.0f}/100</b> | "
        f"تسارع: <b>{acceleration:.0f}/100</b>\n"
        f"الحركة اليوم: <b>{candidate.move_pct:+.1f}%</b> | "
        f"Turnover: <b>{candidate.turnover_pct:.2f}%</b>\n"
        f"خصم المخاطر: <b>{risk:.0f}</b>\n\n"
        f"<b>ليش ظهر الآن؟</b>\n• {base._safe(reasons, 1200)}{news}\n\n"
        f"<i>الدرجة ترتيب احتمالي للأولوية وليست نسبة نجاح أو توصية تنفيذ.</i>"
    )


def _institutional_should_send(candidate, sent_map) -> bool:
    if candidate.stage in {"WATCH", "EXTENDED"}:
        return False
    previous = sent_map.get(candidate.symbol) if isinstance(sent_map.get(candidate.symbol), dict) else {}
    if not previous:
        return float(getattr(candidate, "institutional_priority", candidate.score)) >= 68.0
    previous_stage = str(previous.get("stage") or "WATCH")
    previous_score = base._number(previous.get("score"))
    return should_promote(previous_stage, candidate.stage, candidate.score - previous_score)


# Patch policy without duplicating the full scanner implementation.
base._valid_common = _valid_common
base.collect_fast_news = _combined_fast_news
base.rank_market = _rank_market_with_institutional_engine
base._candidate_message = _institutional_message
base._should_send_candidate = _institutional_should_send
rank_market = _rank_market_with_institutional_engine
run = base.run


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
