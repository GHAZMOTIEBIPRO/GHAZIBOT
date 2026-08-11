from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

API_TIMEOUT_SECONDS = 20
DEFAULT_HISTORY_PATH = Path("data/live/delta_history.json")
DEFAULT_SIGNAL_PATH = Path("data/live/delta_signals.json")
DEFAULT_ALERT_STATE_PATH = Path("data/live/delta_alert_state.json")
DEFAULT_STRUCTURAL_PATH = Path("data/cache/structural_microfloat_candidates.json")
STAGE_ORDER = {
    "DORMANT": 0,
    "PRESSURE_BUILDING": 1,
    "PRE_EXPLOSION": 2,
    "IGNITION": 3,
    "EXPLOSION": 4,
    "EXTENDED": 5,
}


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _pct(value: Any) -> float:
    number = _number(value)
    if 0 < number <= 1:
        number *= 100.0
    return number


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first_number(row: dict[str, Any], keys: tuple[str, ...]) -> float:
    for key in keys:
        if row.get(key) is None:
            continue
        value = _number(row.get(key), float("nan"))
        if math.isfinite(value):
            return value
    return 0.0


def _float_shares(row: dict[str, Any]) -> float:
    return _first_number(row, ("effective_float_estimate", "public_float_shares", "float_shares", "public_float", "float"))


def _shares_outstanding(row: dict[str, Any]) -> float:
    return _first_number(row, ("shares_outstanding", "outstanding_shares", "shares"))


def _insider_pct(row: dict[str, Any]) -> float:
    for key in ("insider_ownership_pct", "insider_ownership", "insider_owned_pct", "insider_pct"):
        if row.get(key) is not None:
            return _pct(row.get(key))
    return 0.0


def _rvol(row: dict[str, Any]) -> float:
    return max(
        _number(row.get("finviz_relative_volume")),
        _number(row.get("relative_volume")),
        _number(row.get("rvol")),
    )


def _volume(row: dict[str, Any]) -> float:
    return _first_number(row, ("volume", "regular_market_volume", "current_volume", "finviz_volume"))


def _day_move(row: dict[str, Any]) -> float:
    return _first_number(row, ("performance_day", "change_pct", "price_change_pct", "day_change_pct", "gap_pct"))


def _week_move(row: dict[str, Any]) -> float:
    return _first_number(row, ("performance_week", "week_change_pct", "change_5d_pct"))


def _price(row: dict[str, Any]) -> float:
    return _first_number(row, ("price", "current_price", "regular_market_price", "last"))


def _social_score(row: dict[str, Any]) -> float:
    evidence = row.get("external_evidence") if isinstance(row.get("external_evidence"), dict) else {}
    return max(_number(row.get("social_score")), _number(evidence.get("social_score")))


def _catalyst_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    omega = payload.get("omega") if isinstance(payload.get("omega"), dict) else {}
    intelligence = omega.get("catalyst_intelligence") if isinstance(omega.get("catalyst_intelligence"), dict) else {}
    by_symbol = intelligence.get("by_symbol") if isinstance(intelligence.get("by_symbol"), dict) else {}
    return {str(symbol).upper(): row for symbol, row in by_symbol.items() if isinstance(row, dict)}


def _structural_map(path: Path) -> dict[str, dict[str, Any]]:
    payload = _load_json(path, {})
    rows = payload.get("candidates") if isinstance(payload, dict) and isinstance(payload.get("candidates"), list) else []
    return {
        str(row.get("symbol") or "").upper(): row
        for row in rows
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    }


def _merge_supply_inputs(stock: dict[str, Any], structural: dict[str, Any]) -> dict[str, Any]:
    merged = dict(structural)
    for key, value in stock.items():
        if value not in (None, "", 0, 0.0):
            merged[key] = value
    return merged


@dataclass
class EffectiveFloatMetrics:
    reported_float: float
    shares_outstanding: float
    insider_pct: float
    affiliate_adjusted_float: float
    effective_float_estimate: float
    dilution_risk: float
    supply_overhang_estimate: float
    supply_vacuum_score: float
    confidence: float
    reasons: list[str]


def effective_float_metrics(
    stock: dict[str, Any],
    structural: dict[str, Any] | None = None,
    catalyst: dict[str, Any] | None = None,
) -> EffectiveFloatMetrics:
    structural = structural or {}
    catalyst = catalyst or {}
    merged = _merge_supply_inputs(stock, structural)
    reported = _float_shares(merged)
    shares = _shares_outstanding(merged)
    insider = _insider_pct(merged)
    dilution = _clamp(_number(catalyst.get("dilution_risk")))

    affiliate_adjusted = 0.0
    if shares > 0 and 0 < insider < 100:
        affiliate_adjusted = shares * max(0.0, 1.0 - insider / 100.0)

    candidates = [value for value in (reported, affiliate_adjusted) if value > 0]
    effective = min(candidates) if candidates else 0.0
    # This is a stress estimate, not a legal/accounting float figure. Dilution risk
    # expands potential tradable supply instead of pretending dilution already occurred.
    supply_overhang = effective * (1.0 + 0.65 * dilution / 100.0) if effective > 0 else 0.0

    score = 20.0
    reasons: list[str] = []
    if effective > 0:
        if effective <= 2_000_000:
            score = 100.0
            reasons.append(f"effective float ≈ {effective/1_000_000:.2f}M")
        elif effective <= 5_000_000:
            score = 94.0
            reasons.append(f"effective float ≈ {effective/1_000_000:.1f}M")
        elif effective <= 10_000_000:
            score = 86.0
            reasons.append(f"effective float ≈ {effective/1_000_000:.1f}M")
        elif effective <= 25_000_000:
            score = 72.0
        elif effective <= 50_000_000:
            score = 56.0
        else:
            score = 35.0
    if shares > 0 and effective > 0:
        lock_ratio = 1.0 - min(1.0, effective / shares)
        if lock_ratio >= 0.80:
            score += 10.0
            reasons.append(f"locked/non-float estimate ≈ {lock_ratio:.0%}")
        elif lock_ratio >= 0.60:
            score += 6.0
    if insider >= 60:
        score += 5.0
        reasons.append(f"insider ownership ≈ {insider:.0f}%")
    if dilution >= 70:
        score -= 32.0
        reasons.append(f"dilution overhang مرتفع {dilution:.0f}/100")
    elif dilution >= 45:
        score -= 16.0
        reasons.append(f"dilution overhang متوسط {dilution:.0f}/100")

    known = sum(value > 0 for value in (reported, shares, insider))
    confidence = 45.0 + known * 15.0
    if reported > 0 and affiliate_adjusted > 0:
        confidence += 10.0
    if structural:
        confidence += 5.0

    return EffectiveFloatMetrics(
        reported_float=reported,
        shares_outstanding=shares,
        insider_pct=insider,
        affiliate_adjusted_float=affiliate_adjusted,
        effective_float_estimate=effective,
        dilution_risk=dilution,
        supply_overhang_estimate=supply_overhang,
        supply_vacuum_score=_clamp(score),
        confidence=_clamp(confidence),
        reasons=reasons,
    )


def _catalyst_features(cluster: dict[str, Any]) -> tuple[float, str]:
    if not cluster:
        return 0.0, ""
    quality = _number(cluster.get("catalyst_quality"))
    materiality = _number(cluster.get("materiality"))
    confidence = _number(cluster.get("confidence"))
    if 0 < confidence <= 1:
        confidence *= 100.0
    score = quality * 0.48 + materiality * 0.34 + confidence * 0.18
    bias = str(cluster.get("directional_bias") or "").lower()
    if bias not in {"bullish", "mixed"}:
        score *= 0.45
    dilution = _number(cluster.get("dilution_risk"))
    if dilution >= 70:
        score -= 30
    headline = str(cluster.get("headline") or cluster.get("title") or cluster.get("event_type") or "").strip()
    event_date = str(cluster.get("event_date") or "").strip()
    fingerprint = hashlib.sha1(f"{headline}|{event_date}|{bias}".encode("utf-8")).hexdigest()[:12] if headline else ""
    return _clamp(score), fingerprint


def _feature_row(
    symbol: str,
    stock: dict[str, Any],
    structural: dict[str, Any],
    cluster: dict[str, Any],
) -> dict[str, Any]:
    effective = effective_float_metrics(stock, structural=structural, catalyst=cluster)
    catalyst_score, catalyst_key = _catalyst_features(cluster)
    return {
        "symbol": symbol,
        "ts": _utc_now(),
        "price": _price(stock),
        "day_move": _day_move(stock),
        "week_move": _week_move(stock),
        "gap_pct": _number(stock.get("gap_pct")),
        "rvol": _rvol(stock),
        "volume": _volume(stock),
        "avg_dollar_volume": _number(stock.get("avg_dollar_volume")),
        "social_score": _social_score(stock),
        "catalyst_score": catalyst_score,
        "catalyst_key": catalyst_key,
        "catalyst_headline": str(cluster.get("headline") or cluster.get("title") or ""),
        "effective_float": asdict(effective),
    }


def _recent(history: list[dict[str, Any]], count: int = 4) -> list[dict[str, Any]]:
    return [row for row in history[-count:] if isinstance(row, dict)]


def _volume_acceleration(current: dict[str, Any], prior: list[dict[str, Any]]) -> tuple[float, float]:
    if not prior:
        return 0.0, 0.0
    current_volume = _number(current.get("volume"))
    previous_volume = _number(prior[-1].get("volume"))
    current_increment = max(0.0, current_volume - previous_volume)
    if len(prior) < 2:
        return current_increment, 0.0
    older_volume = _number(prior[-2].get("volume"))
    previous_increment = max(0.0, previous_volume - older_volume)
    if previous_increment <= 0:
        ratio = 2.0 if current_increment > 0 else 0.0
    else:
        ratio = current_increment / previous_increment
    return current_increment, ratio


def _delta_score(current: dict[str, Any], prior: list[dict[str, Any]]) -> tuple[float, dict[str, float], list[str]]:
    previous = prior[-1] if prior else {}
    rvol = _number(current.get("rvol"))
    previous_rvol = _number(previous.get("rvol"))
    rvol_delta = rvol - previous_rvol
    day = _number(current.get("day_move"))
    previous_day = _number(previous.get("day_move"))
    day_delta = day - previous_day
    social = _number(current.get("social_score"))
    social_delta = social - _number(previous.get("social_score"))
    catalyst = _number(current.get("catalyst_score"))
    new_information = bool(current.get("catalyst_key")) and current.get("catalyst_key") != previous.get("catalyst_key")
    supply = _number((current.get("effective_float") or {}).get("supply_vacuum_score"))
    _, volume_accel_ratio = _volume_acceleration(current, prior)

    rvol_component = _clamp(28.0 + rvol * 17.0 + max(0.0, rvol_delta) * 25.0)
    volume_component = _clamp(25.0 + max(0.0, volume_accel_ratio - 0.8) * 42.0)
    info_component = _clamp(catalyst + (18.0 if new_information else 0.0))
    social_component = _clamp(social + max(0.0, social_delta) * 0.7)

    # Reward the exact pattern we want: demand/volume wakes up while price is still lagging.
    price_lag = 35.0
    if rvol >= 1.25 and rvol_delta > 0 and -2 <= day <= 8:
        price_lag = 100.0
    elif 2 <= day <= 15 and (rvol >= 1.5 or volume_accel_ratio >= 1.25):
        price_lag = 78.0
    elif day > 30:
        price_lag = 5.0

    score = (
        supply * 0.24
        + rvol_component * 0.20
        + volume_component * 0.19
        + info_component * 0.17
        + price_lag * 0.14
        + social_component * 0.06
    )
    if day_delta > 4 and rvol_delta > 0:
        score += min(8.0, day_delta * 0.7)

    reasons: list[str] = []
    if supply >= 75:
        reasons.append(f"Supply Vacuum {supply:.0f}/100")
    if rvol_delta >= 0.35:
        reasons.append(f"RVOL يتسارع {previous_rvol:.2f}→{rvol:.2f}")
    if volume_accel_ratio >= 1.35:
        reasons.append(f"تسارع حجم ×{volume_accel_ratio:.1f}")
    if new_information:
        reasons.append("Information Change جديد")
    if price_lag >= 90:
        reasons.append("الحجم سبق السعر — Price Lag")
    if social_delta >= 12:
        reasons.append("Social acceleration")

    components = {
        "supply": round(supply, 2),
        "rvol": round(rvol_component, 2),
        "volume_acceleration": round(volume_component, 2),
        "information_change": round(info_component, 2),
        "price_lag": round(price_lag, 2),
        "social_acceleration": round(social_component, 2),
        "raw_rvol_delta": round(rvol_delta, 4),
        "raw_volume_accel_ratio": round(volume_accel_ratio, 4),
        "raw_day_delta": round(day_delta, 4),
    }
    return _clamp(score), components, reasons


def _stage(score: float, row: dict[str, Any]) -> str:
    day = _number(row.get("day_move"))
    week = _number(row.get("week_move"))
    gap = abs(_number(row.get("gap_pct")))
    rvol = _number(row.get("rvol"))
    if day >= 38 or week >= 95 or gap >= 28:
        return "EXTENDED"
    if (day >= 18 and rvol >= 2.2) or score >= 90:
        return "EXPLOSION"
    if score >= 73 and (rvol >= 1.35 or day >= 3):
        return "IGNITION"
    if score >= 63:
        return "PRE_EXPLOSION"
    if score >= 50:
        return "PRESSURE_BUILDING"
    return "DORMANT"


@dataclass
class DeltaSignal:
    symbol: str
    score: float
    stage: str
    previous_stage: str
    stage_changed: bool
    price: float
    day_move: float
    rvol: float
    effective_float: float
    supply_vacuum_score: float
    catalyst_score: float
    catalyst_headline: str
    components: dict[str, float]
    reasons: list[str]


def build_delta_signals(
    payload: dict[str, Any],
    history_payload: dict[str, Any] | None = None,
    structural_payload: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[DeltaSignal], dict[str, Any]]:
    history_payload = history_payload if isinstance(history_payload, dict) else {"symbols": {}}
    symbols_history = history_payload.get("symbols") if isinstance(history_payload.get("symbols"), dict) else {}
    structural_payload = structural_payload or {}
    catalysts = _catalyst_map(payload)
    stocks = payload.get("stocks") if isinstance(payload.get("stocks"), list) else []
    signals: list[DeltaSignal] = []
    max_history = max(6, min(48, int(_number(os.getenv("OMEGA_DELTA_HISTORY_LENGTH", "24"), 24))))

    for stock in stocks:
        if not isinstance(stock, dict):
            continue
        symbol = str(stock.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        row = _feature_row(symbol, stock, structural_payload.get(symbol, {}), catalysts.get(symbol, {}))
        prior = _recent(symbols_history.get(symbol, []) if isinstance(symbols_history.get(symbol), list) else [], 4)
        score, components, reasons = _delta_score(row, prior)
        stage = _stage(score, row)
        previous_stage = str(prior[-1].get("stage") or "DORMANT") if prior else "DORMANT"
        row["delta_score"] = round(score, 2)
        row["stage"] = stage
        row["components"] = components
        row["reasons"] = reasons

        effective = row.get("effective_float") if isinstance(row.get("effective_float"), dict) else {}
        signals.append(
            DeltaSignal(
                symbol=symbol,
                score=score,
                stage=stage,
                previous_stage=previous_stage,
                stage_changed=stage != previous_stage,
                price=_number(row.get("price")),
                day_move=_number(row.get("day_move")),
                rvol=_number(row.get("rvol")),
                effective_float=_number(effective.get("effective_float_estimate")),
                supply_vacuum_score=_number(effective.get("supply_vacuum_score")),
                catalyst_score=_number(row.get("catalyst_score")),
                catalyst_headline=str(row.get("catalyst_headline") or ""),
                components=components,
                reasons=reasons,
            )
        )
        existing = symbols_history.get(symbol) if isinstance(symbols_history.get(symbol), list) else []
        symbols_history[symbol] = (existing + [row])[-max_history:]

    signals.sort(key=lambda item: (STAGE_ORDER.get(item.stage, 0), item.score, item.supply_vacuum_score), reverse=True)
    updated_history = {
        "updated_at": _utc_now(),
        "history_length": max_history,
        "symbols": symbols_history,
    }
    return signals, updated_history


def _telegram_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _resolve_chat_id(token: str) -> str:
    configured = str(os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if configured:
        return configured
    response = requests.get(_telegram_url(token, "getUpdates"), timeout=API_TIMEOUT_SECONDS)
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
        timeout=API_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError("Telegram sendMessage failed")


def _safe(value: Any, limit: int = 700) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text)


def _format_signal(signal: DeltaSignal) -> str:
    stage_emoji = {
        "PRESSURE_BUILDING": "⚠️",
        "PRE_EXPLOSION": "🚨",
        "IGNITION": "🔥",
        "EXPLOSION": "💥",
        "EXTENDED": "⛔",
    }.get(signal.stage, "🔎")
    reasons = " | ".join(signal.reasons[:5]) or "تجمع تدريجي في طبقات Ω"
    float_text = f"{signal.effective_float/1_000_000:.2f}M" if signal.effective_float > 0 else "غير متوفر"
    headline = _safe(signal.catalyst_headline, 500) if signal.catalyst_headline else "ما فيه خبر لازم؛ ممكن تكون الحركة Supply-driven"
    return (
        f"{stage_emoji} <b>BLACK BOX Ω — {signal.stage}</b>\n\n"
        f"<b>{_safe(signal.symbol)}</b> — ${signal.price:,.2f}\n"
        f"Delta Pressure: <b>{signal.score:.0f}/100</b> <i>(ترتيب، مو احتمال)</i>\n"
        f"انتقال الحالة: <b>{_safe(signal.previous_stage)} → {_safe(signal.stage)}</b>\n\n"
        f"📈 اليوم: <b>{signal.day_move:+.1f}%</b> | RVOL: <b>{signal.rvol:.2f}</b>\n"
        f"🧩 Effective Float: <b>{float_text}</b>\n"
        f"🌪 Supply Vacuum: <b>{signal.supply_vacuum_score:.0f}/100</b>\n"
        f"⚡ Catalyst: <b>{signal.catalyst_score:.0f}/100</b>\n\n"
        f"<b>وش تغير؟</b>\n{_safe(reasons, 850)}\n\n"
        f"📰 {_safe(headline, 600)}"
    )


def send_transition_alerts(signals: list[DeltaSignal], alert_state_path: Path = DEFAULT_ALERT_STATE_PATH) -> int:
    token = str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        return 0
    chat_id = _resolve_chat_id(token)
    if not chat_id:
        print("Delta: Telegram chat id unavailable; skipped alert send")
        return 0
    state = _load_json(alert_state_path, {"sent": {}})
    if not isinstance(state, dict):
        state = {"sent": {}}
    sent_map = state.setdefault("sent", {})
    min_score = _number(os.getenv("OMEGA_DELTA_ALERT_MIN_SCORE", "52"), 52.0)
    max_alerts = max(1, min(5, int(_number(os.getenv("OMEGA_DELTA_MAX_ALERTS", "3"), 3))))
    sent = 0

    for signal in signals:
        if sent >= max_alerts:
            break
        if signal.stage in {"DORMANT", "EXTENDED"} or signal.score < min_score:
            continue
        previous = sent_map.get(signal.symbol) if isinstance(sent_map.get(signal.symbol), dict) else {}
        previous_stage = str(previous.get("stage") or "DORMANT")
        previous_score = _number(previous.get("score"))
        upgraded = STAGE_ORDER.get(signal.stage, 0) > STAGE_ORDER.get(previous_stage, 0)
        materially_stronger = signal.score >= previous_score + 12.0
        if not upgraded and not materially_stronger:
            continue
        _send(token, chat_id, _format_signal(signal))
        sent_map[signal.symbol] = {"stage": signal.stage, "score": round(signal.score, 1), "sent_at": _utc_now()}
        sent += 1

    state["last_run_at"] = _utc_now()
    state["last_sent_count"] = sent
    _write_json(alert_state_path, state)
    return sent


def run(
    payload_path: Path,
    history_path: Path = DEFAULT_HISTORY_PATH,
    signal_path: Path = DEFAULT_SIGNAL_PATH,
    structural_path: Path = DEFAULT_STRUCTURAL_PATH,
    send_telegram: bool = False,
) -> int:
    payload = _load_json(payload_path, {})
    if not isinstance(payload, dict) or not payload:
        print("Delta: payload unavailable")
        return 0
    history = _load_json(history_path, {"symbols": {}})
    structural = _structural_map(structural_path)
    signals, updated_history = build_delta_signals(payload, history_payload=history, structural_payload=structural)
    _write_json(history_path, updated_history)
    _write_json(
        signal_path,
        {
            "generated_at": _utc_now(),
            "method": "state-delta: supply + RVOL acceleration + volume acceleration + information change + price lag + social acceleration",
            "score_is_probability": False,
            "signals": [asdict(item) for item in signals],
            "top_pressure": [asdict(item) for item in signals if item.stage not in {"DORMANT", "EXTENDED"}][:25],
        },
    )
    sent = send_transition_alerts(signals) if send_telegram else 0
    counts: dict[str, int] = {}
    for signal in signals:
        counts[signal.stage] = counts.get(signal.stage, 0) + 1
    print(f"Delta: symbols={len(signals)} stages={counts} telegram_sent={sent}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BLACK BOX Ω delta/effective-float explosion intelligence")
    parser.add_argument("--payload", default="public/data/latest.json")
    parser.add_argument("--history", default=str(DEFAULT_HISTORY_PATH))
    parser.add_argument("--signals", default=str(DEFAULT_SIGNAL_PATH))
    parser.add_argument("--structural", default=str(DEFAULT_STRUCTURAL_PATH))
    parser.add_argument("--send-telegram", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(
        Path(args.payload),
        history_path=Path(args.history),
        signal_path=Path(args.signals),
        structural_path=Path(args.structural),
        send_telegram=args.send_telegram,
    )


if __name__ == "__main__":
    raise SystemExit(main())
