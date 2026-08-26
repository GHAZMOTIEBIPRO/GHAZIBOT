from __future__ import annotations

import argparse
import hashlib
import html
import os
from datetime import datetime, timezone
from typing import Any

from options_radar.catalyst_selection import best_catalyst_map
from options_radar.catalysts import CatalystScanner
from options_radar.event_source_policy import event_source_evidence
from options_radar.intelligence_grading import grade_alerts, register_alert
from options_radar.settings import Settings
from options_radar.telegram_transport import send_html_message
from options_radar.thesis_engine import UnifiedThesis, build_thesis
from scripts import send_stock_intelligence_v7 as v7


STAGE_AR = {
    "WATCH": "مراقبة",
    "BUILDING": "يتكوّن",
    "CONFIRMED": "مؤكد",
    "EXTENDED": "ممتد / لا تطارد",
    "FAILED": "فشل / تعارض",
}
BIAS_AR = {"BULLISH": "CALL", "BEARISH": "PUT", "NEUTRAL": "WAIT"}


def _current_prices(payload: dict[str, Any]) -> dict[str, float]:
    rows: list[dict[str, Any]] = []
    for key in ("top", "actionable"):
        values = payload.get(key) if isinstance(payload.get(key), list) else []
        rows.extend(row for row in values if isinstance(row, dict))
    prices: dict[str, float] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").upper().strip()
        price = v7._number(row.get("price"))
        if symbol and price > 0:
            prices[symbol] = price
    return prices


def _classical_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for key in ("signals", "waits"):
        values = payload.get(key) if isinstance(payload.get(key), list) else []
        for row in values:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").upper().strip()
            if symbol:
                output[symbol] = row
    return output


def _option_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in (
        "contracts",
        "research_contracts",
        "signals",
        "free_directional_signals",
        "opportunities",
    ):
        values = payload.get(key) if isinstance(payload.get(key), list) else []
        rows.extend(row for row in values if isinstance(row, dict))
    return rows


def _esc(value: Any, limit: int = 500) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text)


def _source_line(thesis: UnifiedThesis) -> str:
    source = _esc(thesis.catalyst_source or "مصدر غير مسمى", 100)
    url = str(thesis.catalyst_url or "").strip()
    if url.startswith(("https://", "http://")):
        return f'📰 <a href="{html.escape(url, quote=True)}">{source}</a> | محفز <b>{thesis.catalyst_grade}</b>'
    return f"📰 {source} | محفز <b>{thesis.catalyst_grade}</b>"


def _fmt_level(value: float | None) -> str:
    return f"${value:,.2f}" if value and value > 0 else "-"


def _message(thesis: UnifiedThesis) -> str:
    stage = STAGE_AR.get(thesis.stage, thesis.stage)
    bias = BIAS_AR.get(thesis.bias, thesis.bias)
    contract = thesis.contract
    why = "؛ ".join(thesis.why_now[:3]) or "الأدلة لم تكتمل بعد"
    blockers = "؛ ".join(thesis.blockers[:2])

    lines = [
        f"🚨 <b>BLACK BOX — {_esc(thesis.symbol)}</b>",
        f"<b>{bias} — {stage}</b> | الدليل <b>{thesis.overall_grade}</b>",
        "",
        f"⚡ <b>لماذا الآن؟</b> {_esc(why, 620)}",
        f"📊 الشارت: 1D <b>{_esc(thesis.daily_direction)}</b> | 1H <b>{_esc(thesis.hourly_direction)}</b> | 15m <b>{_esc(thesis.intraday_direction)}</b>",
        f"🧭 Chart <b>{thesis.chart_grade}</b> | Timing <b>{thesis.timing_grade}</b> | توافق <b>{thesis.chart_agreement_pct}%</b>",
        f"💵 السهم <b>${thesis.price:,.2f}</b> | Trigger <b>{_fmt_level(thesis.trigger)}</b> | إلغاء <b>{_fmt_level(thesis.invalidation)}</b>",
        _source_line(thesis),
        f"🗞 {_esc(thesis.catalyst_headline, 480)}",
    ]

    if contract.available:
        lines.extend(
            [
                "",
                f"🎯 <b>العقد المرشح</b> {_esc(contract.contract_symbol or (contract.option_type.upper() + ' ' + str(contract.strike)), 120)}",
                f"Strike <b>{contract.strike:g}</b> | Exp <b>{_esc(contract.expiration)}</b> | Bid/Ask <b>{contract.bid:.2f}/{contract.ask:.2f}</b>",
                f"Spread <b>{contract.spread_pct:.1%}</b> | Vol <b>{contract.volume:,}</b> | OI <b>{contract.open_interest:,}</b>",
                f"Δ <b>{contract.delta:.2f}</b> | IV <b>{contract.iv:.1%}</b> | Contract <b>{contract.contract_grade}</b> | Flow <b>{contract.flow_grade}</b>",
                f"📡 البيانات <b>{contract.data_confidence}</b> — {_esc(contract.reason, 220)}",
            ]
        )
    else:
        lines.extend(["", "🎯 العقد: <b>غير متاح حاليًا</b> — الفكرة تبقى على السهم ولا تتحول لسعر تنفيذ."])

    lines.append("")
    if thesis.manual_execution_ready:
        lines.append("✅ <b>جاهز للمراجعة اليدوية:</b> طابق السعر الحي في منصة الوسيط قبل التنفيذ.")
    elif thesis.stage == "CONFIRMED":
        lines.append("🟡 <b>الفكرة مؤكدة على السهم، لكن بيانات العقد ليست Execution-grade.</b>")
    elif thesis.stage == "EXTENDED":
        lines.append("🟠 <b>لا تطارد الحركة؛ انتظر إعادة تموضع جديدة.</b>")
    elif thesis.stage == "FAILED":
        lines.append(f"🔴 <b>محجوب:</b> {_esc(blockers or 'الأدلة متعارضة', 300)}")
    else:
        lines.append("🟡 <b>مراقبة فقط:</b> لم تكتمل بوابات التأكيد.")
    lines.append("⚠️ درجة الدليل تصنيف نوعي وليست نسبة نجاح أو أمر شراء.")
    return "\n".join(lines)


def _fingerprint(thesis: UnifiedThesis) -> str:
    contract = thesis.contract
    seed = "|".join(
        [
            thesis.symbol,
            thesis.bias,
            thesis.stage,
            thesis.overall_grade,
            thesis.catalyst_headline[:160],
            contract.contract_symbol,
            contract.data_confidence,
            str(round(thesis.price, 2)),
        ]
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _should_send(thesis: UnifiedThesis, previous: dict[str, Any]) -> bool:
    old_stage = str(previous.get("stage") or "")
    old_grade = str(previous.get("overall_grade") or "")
    if thesis.stage in {"CONFIRMED", "EXTENDED", "FAILED"}:
        return thesis.stage != old_stage or thesis.overall_grade != old_grade
    # BUILDING is useful once; WATCH is retained in state without Telegram noise.
    return thesis.stage == "BUILDING" and old_stage not in {"BUILDING", "CONFIRMED", "EXTENDED"}


def send(
    fast_payload: dict[str, Any],
    classical_payload: dict[str, Any],
    options_payload: dict[str, Any],
    state: dict[str, Any],
) -> int:
    max_age = v7._number(os.getenv("STOCK_INTEL_MAX_PAYLOAD_AGE_MINUTES", "35"), 35.0)
    age = v7._payload_age_minutes(fast_payload)
    if age is None or age > max_age:
        state.update(
            {
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "last_sent_count": 0,
                "blocked_reason": "STALE_FAST_PAYLOAD",
                "payload_age_minutes": age,
            }
        )
        return 0

    scorecard = grade_alerts(state, underlying_prices=_current_prices(fast_payload))
    rows = v7._candidate_rows(fast_payload)
    symbols = [str(row.get("symbol") or "").upper() for row in rows[:30]]
    if not symbols:
        state.update({"last_run_at": datetime.now(timezone.utc).isoformat(), "last_sent_count": 0, "candidate_count": 0})
        return 0

    catalysts = CatalystScanner(Settings()).scan(symbols, lookback_days=3)
    catalyst_map = best_catalyst_map(catalysts)
    classical_map = _classical_map(classical_payload)
    option_rows = _option_rows(options_payload)
    thesis_state = state.setdefault("theses", {})
    maximum = max(1, min(5, int(v7._number(os.getenv("STOCK_INTEL_MAX_ALERTS", "3"), 3))))
    sent = 0
    built = 0

    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        catalyst = catalyst_map.get(symbol)
        if not isinstance(catalyst, dict):
            continue
        evidence = event_source_evidence(catalyst)
        if evidence.get("attention_only") is True:
            continue
        thesis = build_thesis(
            market_row=row,
            catalyst=catalyst,
            source_evidence=evidence,
            classical=classical_map.get(symbol),
            option_rows=option_rows,
        )
        built += 1
        previous = thesis_state.get(symbol) if isinstance(thesis_state.get(symbol), dict) else {}
        fingerprint = _fingerprint(thesis)
        should_send = sent < maximum and _should_send(thesis, previous) and str(previous.get("fingerprint") or "") != fingerprint
        if should_send:
            send_html_message(_message(thesis))
            sent_at = datetime.now(timezone.utc)
            alert_id = hashlib.sha256(f"{symbol}|{fingerprint}|{sent_at.timestamp()}".encode()).hexdigest()[:24]
            register_alert(
                state,
                alert_id=alert_id,
                kind="stock",
                symbol=symbol,
                direction="UP" if thesis.bias == "BULLISH" else "DOWN",
                baseline_underlying=thesis.price,
                score=v7._number(row.get("score")),
                evidence_signature="|".join(
                    [thesis.chart_grade, thesis.catalyst_grade, thesis.timing_grade, thesis.contract_grade, thesis.data_confidence]
                ),
                sent_at=sent_at,
            )
            sent += 1
        thesis_state[symbol] = {
            "fingerprint": fingerprint,
            "stage": thesis.stage,
            "overall_grade": thesis.overall_grade,
            "bias": thesis.bias,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "manual_execution_ready": thesis.manual_execution_ready,
            "data_confidence": thesis.data_confidence,
            "contract": thesis.contract.contract_symbol,
        }

    state.update(
        {
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_sent_count": sent,
            "candidate_count": len(rows),
            "theses_built": built,
            "payload_age_minutes": round(age, 2),
            "self_grading_scorecard": scorecard,
            "architecture": "black_box_v10_unified_mobile_thesis",
        }
    )
    state.pop("blocked_reason", None)
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="Send BLACK BOX V10 unified chart+catalyst+contract thesis cards")
    parser.add_argument("--fast-payload", default="data/live/fast_explosion_scan.json")
    parser.add_argument("--classical-payload", default="public/data/classical_direction_latest.json")
    parser.add_argument("--options-payload", default="public/data/options_latest.json")
    parser.add_argument("--state", default="data/live/stock_intelligence_v10_state.json")
    args = parser.parse_args()

    fast = v7._load(args.fast_payload, {})
    classical = v7._load(args.classical_payload, {})
    options = v7._load(args.options_payload, {})
    state = v7._load(args.state, {"theses": {}, "outcomes": {}})
    if not isinstance(fast, dict):
        fast = {}
    if not isinstance(classical, dict):
        classical = {}
    if not isinstance(options, dict):
        options = {}
    if not isinstance(state, dict):
        state = {"theses": {}, "outcomes": {}}
    try:
        sent = send(fast, classical, options, state)
    finally:
        v7._save(args.state, state)
    print(
        "Stock intelligence v10: "
        f"sent={sent} theses={state.get('theses_built', 0)} "
        f"candidates={state.get('candidate_count', 0)}"
    )


if __name__ == "__main__":
    main()
