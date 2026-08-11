from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from options_radar.halt_news_engine import NewsEvent, collect_fast_news, fetch_nasdaq_halts

NASDAQ_SCREENER = "https://api.nasdaq.com/api/screener/stocks"
STRUCTURAL_PATH = Path("data/cache/structural_microfloat_candidates.json")
OUTPUT_PATH = Path("data/live/fast_explosion_scan.json")
STATE_PATH = Path("data/live/fast_alert_state.json")
TIMEOUT = 30
SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,6}$")
NON_COMMON_NAME_TOKENS = (
    "preferred",
    "preference",
    "warrant",
    "depositary share",
    "depositary shares",
    "rights",
    "units",
    " unit ",
    "exchange traded fund",
    " etf",
)
STAGE_ORDER = {"WATCH": 0, "PRESSURE_BUILDING": 1, "IGNITION": 2, "EXPLOSION": 3, "EXTENDED": 4}


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_common(symbol: str, name: str) -> bool:
    if not SYMBOL_RE.fullmatch(symbol):
        return False
    if symbol.endswith(("WS", "WT")) or (len(symbol) >= 4 and symbol.endswith(("W", "U", "R"))):
        return False
    normalized = f" {name.lower()} "
    return not any(token in normalized for token in NON_COMMON_NAME_TOKENS)


def _nasdaq_rows() -> list[dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; BLACK-BOX-Omega/Fast-Radar)",
        "Accept": "application/json,text/plain,*/*",
        "Origin": "https://www.nasdaq.com",
        "Referer": "https://www.nasdaq.com/market-activity/stocks/screener",
    }
    response = requests.get(
        NASDAQ_SCREENER,
        params={"tableonly": "true", "limit": "10000", "offset": "0", "download": "true"},
        headers=headers,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json() or {}
    data = payload.get("data") if isinstance(payload, dict) else {}
    rows = (data or {}).get("rows") if isinstance(data, dict) else []
    return [row for row in (rows or []) if isinstance(row, dict)]


def _structural_map() -> dict[str, dict[str, Any]]:
    payload = _load(STRUCTURAL_PATH, {})
    rows = payload.get("candidates") if isinstance(payload, dict) and isinstance(payload.get("candidates"), list) else []
    return {
        str(row.get("symbol") or "").upper(): row
        for row in rows
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    }


def _supply_proxy(market_cap: float, structural: dict[str, Any]) -> float:
    structural_score = _number(structural.get("structural_score"))
    float_shares = _number(structural.get("float_shares"))
    if float_shares > 0:
        if float_shares <= 3_000_000:
            return 100.0
        if float_shares <= 10_000_000:
            return 92.0
        if float_shares <= 25_000_000:
            return 80.0
    if structural_score > 0:
        return max(55.0, structural_score)
    if 0 < market_cap <= 50_000_000:
        return 94.0
    if market_cap <= 150_000_000:
        return 84.0
    if market_cap <= 500_000_000:
        return 68.0
    if market_cap <= 1_000_000_000:
        return 52.0
    if market_cap <= 2_000_000_000:
        return 38.0
    return 18.0


def _turnover_score(turnover_pct: float) -> float:
    if turnover_pct >= 8:
        return 100.0
    if turnover_pct >= 4:
        return 92.0
    if turnover_pct >= 2:
        return 82.0
    if turnover_pct >= 1:
        return 70.0
    if turnover_pct >= 0.5:
        return 58.0
    if turnover_pct >= 0.2:
        return 45.0
    if turnover_pct >= 0.08:
        return 32.0
    return 15.0


def _move_score(move: float) -> float:
    if move < -5:
        return 5.0
    if move < 1:
        return 22.0
    if move <= 3:
        return 45.0
    if move <= 7:
        return 70.0
    if move <= 15:
        return 92.0
    if move <= 25:
        return 100.0
    if move <= 38:
        return 68.0
    return 12.0


def _volume_score(volume: float) -> float:
    if volume >= 10_000_000:
        return 100.0
    if volume >= 5_000_000:
        return 90.0
    if volume >= 1_500_000:
        return 75.0
    if volume >= 500_000:
        return 60.0
    if volume >= 150_000:
        return 45.0
    if volume >= 40_000:
        return 30.0
    return 12.0


def _news_score(events: list[NewsEvent]) -> tuple[float, NewsEvent | None]:
    if not events:
        return 0.0, None
    best = max(events, key=lambda event: (event.relevance, event.sentiment))
    relevance = _clamp(best.relevance * 100.0)
    sentiment_bonus = max(-20.0, min(20.0, best.sentiment * 45.0))
    return _clamp(relevance + sentiment_bonus), best


@dataclass
class FastCandidate:
    symbol: str
    company_name: str
    price: float
    move_pct: float
    volume: float
    market_cap: float
    dollar_volume: float
    turnover_pct: float
    score: float
    stage: str
    supply_score: float
    turnover_score: float
    move_score: float
    volume_score: float
    news_score: float
    structural_score: float
    news_headline: str
    news_source: str
    reasons: list[str]


def _stage(score: float, move: float, turnover: float) -> str:
    if move >= 40:
        return "EXTENDED"
    if (move >= 15 and turnover >= 1.5) or score >= 86:
        return "EXPLOSION"
    if score >= 72 and move >= 2:
        return "IGNITION"
    if score >= 60:
        return "PRESSURE_BUILDING"
    return "WATCH"


def rank_market(rows: list[dict[str, Any]], news_events: list[NewsEvent], structural: dict[str, dict[str, Any]]) -> list[FastCandidate]:
    news_by_symbol: dict[str, list[NewsEvent]] = {}
    for event in news_events:
        news_by_symbol.setdefault(event.symbol, []).append(event)
    ranked: list[FastCandidate] = []
    for row in rows:
        symbol = str(row.get("symbol") or "").upper().strip()
        name = str(row.get("name") or "").strip()
        if not _valid_common(symbol, name):
            continue
        price = _number(row.get("lastsale"))
        market_cap = _number(row.get("marketCap"))
        volume = _number(row.get("volume"))
        move = _number(row.get("pctchange"))
        if price <= 0.25 or price > 500 or market_cap <= 0:
            continue
        dollar_volume = price * volume
        turnover = (dollar_volume / market_cap * 100.0) if market_cap > 0 else 0.0
        structural_row = structural.get(symbol, {})
        supply = _supply_proxy(market_cap, structural_row)
        turnover_component = _turnover_score(turnover)
        move_component = _move_score(move)
        volume_component = _volume_score(volume)
        news_component, best_news = _news_score(news_by_symbol.get(symbol, []))
        structural_score = _number(structural_row.get("structural_score"))
        score = (
            supply * 0.28
            + turnover_component * 0.24
            + move_component * 0.20
            + volume_component * 0.12
            + news_component * 0.11
            + min(100.0, structural_score) * 0.05
        )
        if market_cap > 2_000_000_000 and news_component < 70 and move < 8:
            score -= 10
        if move > 38:
            score -= 22
        score = _clamp(score)
        stage = _stage(score, move, turnover)
        reasons: list[str] = []
        if supply >= 75:
            reasons.append(f"عرض مقيد {supply:.0f}/100")
        if turnover_component >= 70:
            reasons.append(f"دوران سيولة/قيمة سوقية {turnover:.2f}%")
        if 3 <= move <= 25:
            reasons.append(f"السعر بدأ يتحرك {move:+.1f}%")
        if volume_component >= 60:
            reasons.append(f"حجم {volume:,.0f}")
        if best_news:
            reasons.append(f"خبر سريع: {best_news.headline[:130]}")
        ranked.append(
            FastCandidate(
                symbol=symbol,
                company_name=name,
                price=price,
                move_pct=move,
                volume=volume,
                market_cap=market_cap,
                dollar_volume=dollar_volume,
                turnover_pct=turnover,
                score=score,
                stage=stage,
                supply_score=supply,
                turnover_score=turnover_component,
                move_score=move_component,
                volume_score=volume_component,
                news_score=news_component,
                structural_score=structural_score,
                news_headline=best_news.headline if best_news else "",
                news_source=best_news.source if best_news else "",
                reasons=reasons,
            )
        )
    ranked.sort(key=lambda item: (STAGE_ORDER.get(item.stage, 0), item.score, item.turnover_pct), reverse=True)
    return ranked


def _telegram_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _resolve_chat_id(token: str) -> str:
    configured = str(os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if configured:
        return configured
    response = requests.get(_telegram_url(token, "getUpdates"), timeout=18)
    response.raise_for_status()
    body = response.json()
    for update in reversed(body.get("result") or []):
        if not isinstance(update, dict):
            continue
        message = update.get("message") or update.get("edited_message") or update.get("channel_post")
        if isinstance(message, dict) and isinstance(message.get("chat"), dict) and message["chat"].get("id") is not None:
            return str(message["chat"]["id"])
    return ""


def _send(token: str, chat_id: str, text: str) -> None:
    response = requests.post(
        _telegram_url(token, "sendMessage"),
        data={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"},
        timeout=18,
    )
    response.raise_for_status()
    if not response.json().get("ok"):
        raise RuntimeError("Telegram send failed")


def _safe(value: Any, limit: int = 700) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text)


def _candidate_message(candidate: FastCandidate) -> str:
    emoji = "💥" if candidate.stage == "EXPLOSION" else "🔥" if candidate.stage == "IGNITION" else "⚠️"
    reasons = " | ".join(candidate.reasons[:5]) or "تغيّر غير طبيعي في السعر/السيولة"
    news = f"\n📰 {_safe(candidate.news_headline, 500)}" if candidate.news_headline else ""
    return (
        f"{emoji} <b>BLACK BOX Ω — FAST {candidate.stage}</b>\n\n"
        f"<b>{_safe(candidate.symbol)}</b> — ${candidate.price:,.2f}\n"
        f"Fast Score: <b>{candidate.score:.0f}/100</b> <i>(ترتيب، مو احتمال)</i>\n"
        f"اليوم: <b>{candidate.move_pct:+.1f}%</b>\n"
        f"الحجم: <b>{candidate.volume:,.0f}</b>\n"
        f"Turnover/Market Cap: <b>{candidate.turnover_pct:.2f}%</b>\n"
        f"Supply Proxy: <b>{candidate.supply_score:.0f}/100</b>\n\n"
        f"<b>ليش ظهر؟</b>\n{_safe(reasons, 850)}{news}"
    )


def _halt_message(symbol: str, reason: str, title: str, description: str) -> str:
    meaning = {
        "T1": "News Pending — خبر بانتظار النشر",
        "T2": "News Released — الخبر نزل والسوق ينتظر الاستئناف",
        "T5": "Single-stock trading pause / حركة قوية",
        "LUDP": "Limit Up/Limit Down pause",
    }.get(reason, "Trading Halt / Pause")
    return (
        f"⏸🚨 <b>BLACK BOX Ω — HALT SNIPER</b>\n\n"
        f"<b>{_safe(symbol)}</b> — <b>{_safe(reason)}</b>\n"
        f"الحالة: <b>{_safe(meaning)}</b>\n\n"
        f"{_safe(title, 500)}\n{_safe(description, 700)}"
    )


def _should_send_candidate(candidate: FastCandidate, sent_map: dict[str, Any]) -> bool:
    previous = sent_map.get(candidate.symbol) if isinstance(sent_map.get(candidate.symbol), dict) else {}
    if not previous:
        return True
    previous_stage = str(previous.get("stage") or "WATCH")
    previous_score = _number(previous.get("score"))
    return STAGE_ORDER.get(candidate.stage, 0) > STAGE_ORDER.get(previous_stage, 0) or candidate.score >= previous_score + 10


def run(send_telegram: bool = True) -> int:
    structural = _structural_map()
    try:
        rows = _nasdaq_rows()
    except Exception as exc:
        print(f"Fast radar market fetch failed: {type(exc).__name__}: {exc}")
        return 0
    known_symbols = {
        str(row.get("symbol") or "").upper().strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    }
    news_events = collect_fast_news(known_symbols=known_symbols)
    ranked = rank_market(rows, news_events=news_events, structural=structural)
    actionable = [item for item in ranked if item.stage in {"PRESSURE_BUILDING", "IGNITION", "EXPLOSION"}][:30]

    halts = []
    try:
        halts = fetch_nasdaq_halts(known_symbols=known_symbols)
    except Exception as exc:
        print(f"Halt feed skipped: {type(exc).__name__}: {exc}")

    _save(
        OUTPUT_PATH,
        {
            "generated_at": _utc_now(),
            "market_rows_seen": len(rows),
            "news_events_seen": len(news_events),
            "halt_events_seen": len(halts),
            "score_is_probability": False,
            "top": [asdict(item) for item in ranked[:50]],
            "actionable": [asdict(item) for item in actionable],
            "halts": [asdict(item) for item in halts[:100]],
        },
    )

    sent = 0
    if send_telegram:
        token = str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
        chat_id = _resolve_chat_id(token) if token else ""
        if token and chat_id:
            state = _load(STATE_PATH, {"sent": {}, "halts": {}})
            if not isinstance(state, dict):
                state = {"sent": {}, "halts": {}}
            sent_map = state.setdefault("sent", {})
            halt_map = state.setdefault("halts", {})
            max_alerts = max(1, min(5, int(_number(os.getenv("OMEGA_FAST_MAX_ALERTS", "3"), 3))))
            min_score = _number(os.getenv("OMEGA_FAST_MIN_SCORE", "68"), 68.0)
            for candidate in actionable:
                if sent >= max_alerts:
                    break
                if candidate.score < min_score or candidate.stage == "PRESSURE_BUILDING" and candidate.score < 72:
                    continue
                if not _should_send_candidate(candidate, sent_map):
                    continue
                _send(token, chat_id, _candidate_message(candidate))
                sent_map[candidate.symbol] = {"stage": candidate.stage, "score": round(candidate.score, 1), "sent_at": _utc_now()}
                sent += 1

            row_map = {str(row.get("symbol") or "").upper(): row for row in rows if isinstance(row, dict)}
            candidate_map = {candidate.symbol: candidate for candidate in ranked[:250]}
            for halt in halts:
                key = f"{halt.symbol}:{halt.reason}:{halt.published}"
                if key in halt_map:
                    continue
                market_cap = _number((row_map.get(halt.symbol) or {}).get("marketCap"))
                candidate_score = candidate_map.get(halt.symbol).score if halt.symbol in candidate_map else 0.0
                if market_cap > 2_000_000_000 and candidate_score < 55 and halt.symbol not in structural:
                    continue
                _send(token, chat_id, _halt_message(halt.symbol, halt.reason, halt.title, halt.description))
                halt_map[key] = {"sent_at": _utc_now()}
                sent += 1
                if sent >= max_alerts + 2:
                    break
            state["last_run_at"] = _utc_now()
            state["last_sent_count"] = sent
            # Keep state bounded so the repo state file stays tiny.
            if len(halt_map) > 250:
                state["halts"] = dict(list(halt_map.items())[-250:])
            _save(STATE_PATH, state)

    print(f"Fast radar: market={len(rows)} actionable={len(actionable)} news={len(news_events)} halts={len(halts)} sent={sent}")
    if actionable:
        print("Fast leaders:", ", ".join(f"{item.symbol}:{item.stage}:{item.score:.0f}" for item in actionable[:10]))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BLACK BOX Ω full-market fast explosion radar")
    parser.add_argument("--no-telegram", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(send_telegram=not args.no_telegram)


if __name__ == "__main__":
    raise SystemExit(main())
