from __future__ import annotations

import argparse
import hashlib
import html
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from options_radar.catalyst_selection import best_catalyst_map
from options_radar.catalysts import CatalystScanner
from options_radar.event_source_policy import event_source_evidence
from options_radar.flow_memory import (
    attach_strike_clusters,
    contract_key,
    option_mid,
    update_flow_memory,
)
from options_radar.intelligence_grading import grade_alerts, register_alert
from options_radar.intrinio_flow import enrich_with_intrinio_flow
from options_radar.settings import Settings
from options_radar.telegram_transport import send_html_message
from scripts import send_options_intelligence_v7 as v7


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _safe(value: Any, limit: int = 520) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text)


def _current_maps(payload: dict[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    rows = payload.get("contracts") if isinstance(payload.get("contracts"), list) else []
    underlying: dict[str, float] = {}
    instruments: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper().strip()
        spot = _num(row.get("underlying_price"))
        if symbol and spot > 0:
            underlying[symbol] = spot
        key = contract_key(row)
        mid = option_mid(row)
        if key and mid > 0:
            instruments[key] = mid
    return underlying, instruments


def _evidence_signature(row: dict[str, Any], catalyst: dict[str, Any] | None, flow: dict[str, Any]) -> str:
    pieces = [flow.get("tier", "WEAK")]
    if row.get("repeat_flow_confirmed") is True:
        pieces.append("repeat")
    if row.get("flow_acceleration_strong") is True:
        pieces.append("acceleration")
    if row.get("strike_cluster_confirmed") is True:
        pieces.append("cluster")
    if catalyst:
        pieces.append(str(catalyst.get("category") or "catalyst"))
    return "+".join(str(value) for value in pieces)


def _enhanced_strength(row: dict[str, Any], flow: dict[str, Any]) -> float:
    strict = _num(row.get("strict_score") or row.get("score"))
    repeat = min(10.0, _num(row.get("repeat_flow_hits")) * 2.5)
    acceleration = 7.0 if row.get("flow_acceleration_strong") is True else 0.0
    cluster = min(8.0, _num(row.get("strike_cluster_score")) * 0.08)
    verified = 5.0 if flow.get("tier") == "VERIFIED" else 0.0
    # This is a ranking score, not a probability. The original strict gate remains authoritative.
    return min(100.0, strict * 0.78 + _num(flow.get("score")) * 0.12 + repeat + acceleration + cluster + verified)


def _eligible_v8(row: dict[str, Any], catalyst: dict[str, Any] | None, flow: dict[str, Any]) -> bool:
    if v7._eligible(row, catalyst, flow):
        return True
    strict = _num(row.get("strict_score") or row.get("score"))
    grade = str(row.get("signal_grade") or row.get("strict_grade") or "")
    direction = v7._direction(row)
    aligned, _ = v7._catalyst_alignment(direction, catalyst)
    catalyst_score = abs(_num((catalyst or {}).get("score")))
    repeat = row.get("repeat_flow_confirmed") is True
    accel = row.get("flow_acceleration_strong") is True
    cluster = row.get("strike_cluster_confirmed") is True
    min_score = _num(os.getenv("OPTIONS_INTEL_MIN_SCORE", "85"), 85.0)
    if strict < min_score or (grade and grade not in {"A", "A+"}) or not aligned or catalyst_score < 8:
        return False
    # Snapshot evidence may graduate only when activity repeats/accelerates or appears
    # across a strike ladder. Activity-only data never becomes "verified flow".
    if flow.get("tier") in {"VERIFIED", "SNAPSHOT_PROXY"}:
        return (repeat and accel) or (cluster and (repeat or accel))
    if flow.get("tier") == "ACTIVITY_ONLY":
        return repeat and accel and cluster and _num(row.get("vol_to_oi_ratio") or row.get("vol_oi")) >= 2.5
    return False


def _fingerprint_v8(row: dict[str, Any], catalyst: dict[str, Any] | None, flow: dict[str, Any]) -> str:
    seed = "|".join(
        [
            contract_key(row),
            str(round(_enhanced_strength(row, flow) / 3) * 3),
            str(min(5, int(_num(row.get("repeat_flow_hits"))))),
            "A" if row.get("flow_acceleration_strong") is True else "N",
            str(min(6, int(_num(row.get("strike_cluster_count"))))),
            str((catalyst or {}).get("headline") or "")[:160],
        ]
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def _flow_memory_lines(row: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    repeats = int(_num(row.get("repeat_flow_hits")))
    delta_volume = int(_num(row.get("flow_volume_delta")))
    proxy_delta = _num(row.get("flow_notional_delta_proxy"))
    verified_delta = _num(row.get("verified_premium_delta"))
    velocity = _num(row.get("verified_premium_velocity_per_min")) or _num(row.get("flow_notional_velocity_per_min"))
    if repeats > 0:
        lines.append(f"🔁 تكرار النشاط: <b>{repeats}</b> دفعات ذات زيادة فعلية بين الفحوص")
    if delta_volume > 0:
        label = "Premium موثق جديد" if verified_delta > 0 else "Notional proxy جديد"
        amount = verified_delta if verified_delta > 0 else proxy_delta
        lines.append(f"⚡ منذ الفحص السابق: <b>+{delta_volume:,}</b> عقد | {label}: <b>${amount:,.0f}</b> | السرعة ≈ <b>${velocity:,.0f}/دقيقة</b>")
    cluster_count = int(_num(row.get("strike_cluster_count")))
    if cluster_count >= 2:
        strikes = row.get("strike_cluster_strikes") if isinstance(row.get("strike_cluster_strikes"), list) else []
        display = ", ".join(f"{_num(value):g}" for value in strikes[:6])
        lines.append(
            f"🧱 تركّز الاستحقاق: <b>{cluster_count}</b> Strikes متجاورة"
            + (f" ({_safe(display, 120)})" if display else "")
            + f" | حجم مجمع <b>{int(_num(row.get('strike_cluster_volume'))):,}</b>"
        )
    move = _num(row.get("underlying_move_since_observation_pct"))
    if (row.get("flow_acceleration_strong") is True or repeats >= 2) and abs(move) < 0.20:
        lines.append("👀 السعر لم يتحرك كثيرًا منذ الفحص السابق رغم تسارع نشاط العقد؛ حالة Price/Flow lag للمراقبة وليست إشارة اتجاه مستقلة.")
    return lines


def _message_v8(row: dict[str, Any], catalyst: dict[str, Any] | None, flow: dict[str, Any]) -> str:
    base = v7._message(row, catalyst, flow).splitlines()
    # Replace the heading and quality line while preserving the carefully worded v7 evidence policy.
    direction = v7._direction(row)
    side_ar = "كول" if direction == "CALL" else "بوت"
    emoji = "🟢" if direction == "CALL" else "🔴"
    strength = _enhanced_strength(row, flow)
    grade = str(row.get("signal_grade") or row.get("strict_grade") or "")
    if base:
        base[0] = f"{emoji} <b>بلاك بوكس — عقد {side_ar}: فلو متكرر + محفز</b>"
    for idx, line in enumerate(base):
        if line.startswith("⭐ الجودة:"):
            base[idx] = f"⭐ قوة الرصد المركبة: <b>{strength:.0f}/100 {grade}</b> <i>(ترتيب داخلي، ليست نسبة نجاح)</i>"
            break
    memory_lines = _flow_memory_lines(row)
    insert_at = 0
    for idx, line in enumerate(base):
        if line.startswith("📐 Delta"):
            insert_at = idx + 1
            break
    if memory_lines:
        base[insert_at:insert_at] = memory_lines
    return "\n".join(base)


def send(payload: dict[str, Any], state: dict[str, Any]) -> tuple[int, int]:
    age = v7._payload_age_minutes(payload)
    max_age = _num(os.getenv("OPTIONS_INTEL_MAX_PAYLOAD_AGE_MINUTES", "45"), 45.0)
    if age is None or age > max_age:
        state.update(
            {
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "last_sent_count": 0,
                "blocked_reason": "STALE_OPTIONS_PAYLOAD",
                "payload_age_minutes": age,
            }
        )
        return 0, 0

    now = datetime.now(timezone.utc)
    underlying_prices, instrument_prices = _current_maps(payload)
    scorecard = grade_alerts(
        state,
        underlying_prices=underlying_prices,
        instrument_prices=instrument_prices,
        now=now,
    )
    followups = v7._send_oi_followups(payload, state)
    signals = v7._signals(payload)
    symbols = list(
        dict.fromkeys(
            str(row.get("symbol") or "").upper()
            for row in signals[:25]
            if str(row.get("symbol") or "").strip()
        )
    )
    settings = Settings()
    catalysts = CatalystScanner(settings).scan(symbols, lookback_days=3) if symbols else None
    catalyst_map = best_catalyst_map(catalysts) if catalysts is not None else {}

    enriched, flow_errors = enrich_with_intrinio_flow(
        signals,
        max_symbols=max(1, min(25, int(_num(os.getenv("INTRINIO_FLOW_MAX_SYMBOLS", "12"), 12)))),
    )
    universe_contracts = [row for row in (payload.get("contracts") or []) if isinstance(row, dict)]
    enriched = attach_strike_clusters(enriched, universe_contracts)
    enriched = update_flow_memory(state, enriched, now=now)
    enriched.sort(
        key=lambda row: (
            row.get("repeat_flow_confirmed") is True,
            row.get("flow_acceleration_strong") is True,
            row.get("strike_cluster_confirmed") is True,
            _num(row.get("strict_score") or row.get("score")),
        ),
        reverse=True,
    )

    sent_map = state.setdefault("sent", {})
    contract_registry = state.setdefault("contracts", {})
    maximum = max(1, min(5, int(_num(os.getenv("OPTIONS_INTEL_MAX_ALERTS", "3"), 3))))
    sent = 0

    for row in enriched:
        if sent >= maximum:
            break
        symbol = str(row.get("symbol") or "").upper().strip()
        direction = v7._direction(row)
        if not symbol or direction not in {"CALL", "PUT"}:
            continue
        catalyst = catalyst_map.get(symbol)
        flow = v7._flow_assessment(row)
        if not _eligible_v8(row, catalyst, flow):
            continue
        key = contract_key(row)
        fp = _fingerprint_v8(row, catalyst, flow)
        previous = sent_map.get(key) if isinstance(sent_map.get(key), dict) else {}
        if str(previous.get("fingerprint") or "") == fp:
            continue

        send_html_message(_message_v8(row, catalyst, flow))
        sent_at = datetime.now(timezone.utc)
        strength = _enhanced_strength(row, flow)
        signature = _evidence_signature(row, catalyst, flow)
        alert_id = f"{key}:{int(sent_at.timestamp())}"
        register_alert(
            state,
            alert_id=alert_id,
            kind="options",
            symbol=symbol,
            direction=direction,
            baseline_underlying=_num(row.get("underlying_price")),
            baseline_instrument=option_mid(row),
            instrument_key=key,
            score=strength,
            evidence_signature=signature,
            sent_at=sent_at,
        )
        sent_map[key] = {
            "fingerprint": fp,
            "sent_at": sent_at.isoformat(),
            "symbol": symbol,
            "direction": direction,
            "flow_tier": flow.get("tier"),
            "repeat_flow_hits": int(_num(row.get("repeat_flow_hits"))),
            "strike_cluster_count": int(_num(row.get("strike_cluster_count"))),
            "strength": round(strength, 2),
            "alert_id": alert_id,
        }
        contract_registry[key] = {
            "symbol": symbol,
            "direction": direction,
            "sent_date": sent_at.date().isoformat(),
            "baseline_oi": int(_num(row.get("open_interest"))),
            "baseline_volume": int(_num(row.get("volume"))),
            "oi_followup_sent": False,
        }
        sent += 1

    state.update(
        {
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_sent_count": sent,
            "last_oi_followups": followups,
            "payload_age_minutes": round(age, 2),
            "flow_enrichment_errors": flow_errors,
            "self_grading_scorecard": scorecard,
            "architecture": "standalone_options_repeatflow_catalyst_v8",
        }
    )
    state.pop("blocked_reason", None)
    return sent, followups


def main() -> None:
    parser = argparse.ArgumentParser(description="Send BLACK BOX V8 repeat-flow + premium acceleration + catalyst alerts")
    parser.add_argument("--payload", required=True)
    parser.add_argument("--state", default="data/live/options_intelligence_v8_state.json")
    args = parser.parse_args()
    payload = v7._load(args.payload, {})
    state = v7._load(args.state, {"sent": {}, "contracts": {}, "flow_memory": {}, "outcomes": {}})
    if not isinstance(payload, dict) or payload.get("path") != "options":
        raise RuntimeError("Expected independent options payload")
    if not isinstance(state, dict):
        state = {"sent": {}, "contracts": {}, "flow_memory": {}, "outcomes": {}}
    try:
        sent, followups = send(payload, state)
    finally:
        v7._save(args.state, state)
    print(
        "Options intelligence v8: "
        f"sent={sent} oi_followups={followups} "
        f"outcomes={state.get('self_grading_scorecard', {}).get('alert_records', 0)}"
    )


if __name__ == "__main__":
    main()
