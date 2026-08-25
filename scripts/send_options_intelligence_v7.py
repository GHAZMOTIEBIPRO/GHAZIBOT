from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from options_radar.catalyst_selection import best_catalyst_map
from options_radar.catalysts import CatalystScanner
from options_radar.event_source_policy import event_source_evidence
from options_radar.intrinio_flow import enrich_with_intrinio_flow
from options_radar.settings import Settings
from options_radar.telegram_transport import send_html_message


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _safe(value: Any, limit: int = 480) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text)


def _load(path: str | Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save(path: str | Path, payload: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)


def _payload_age_minutes(payload: dict[str, Any]) -> float | None:
    raw = str(payload.get("generated_at") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 60.0)


def _direction(row: dict[str, Any]) -> str:
    value = str(row.get("direction_label") or row.get("direction") or row.get("option_type") or "").upper()
    if value in {"CALL", "PUT"}:
        return value
    option_type = str(row.get("option_type") or "").upper()
    return option_type if option_type in {"CALL", "PUT"} else ""


def _signals(payload: dict[str, Any]) -> list[dict[str, Any]]:
    readiness = payload.get("provider_readiness") if isinstance(payload.get("provider_readiness"), dict) else {}
    if readiness.get("production_quote_ready") is True:
        rows = payload.get("production_directional_signals") or payload.get("directional_signals") or []
    else:
        rows = payload.get("free_directional_signals") or payload.get("directional_signals") or []
    output = [dict(row) for row in rows if isinstance(row, dict)]
    output.sort(
        key=lambda row: (
            _number(row.get("strict_score") or row.get("score")),
            _number(row.get("side_consensus_score")),
            _number(row.get("flow_momentum_score")),
        ),
        reverse=True,
    )
    return output


def _contract_key(row: dict[str, Any]) -> str:
    contract = str(row.get("contract_symbol") or "").upper().strip()
    if contract:
        return contract
    return "|".join(
        [
            str(row.get("symbol") or "").upper(),
            _direction(row),
            str(row.get("expiration") or "")[:10],
            str(row.get("strike") or ""),
        ]
    )


def _catalyst_alignment(direction: str, catalyst: dict[str, Any] | None) -> tuple[bool, str]:
    if not catalyst:
        return False, "لا يوجد محفز خبري موثق مسيطر"
    score = _number(catalyst.get("score"))
    aligned = (direction == "CALL" and score > 0) or (direction == "PUT" and score < 0)
    return aligned, "متوافق مع جهة العقد" if aligned else "المحفز لا يتوافق بوضوح مع جهة العقد"


def _flow_assessment(row: dict[str, Any]) -> dict[str, Any]:
    direction = _direction(row)
    verified = row.get("verified_trade_flow") is True
    sentiment = str(row.get("verified_unusual_sentiment") or "").lower()
    unusual_type = str(row.get("verified_unusual_type") or "").lower()
    aligned_sentiment = (direction == "CALL" and sentiment == "bullish") or (direction == "PUT" and sentiment == "bearish")
    premium = _number(row.get("verified_unusual_total_value"))
    prints = int(_number(row.get("verified_unusual_print_count")))
    volume = int(_number(row.get("volume")))
    oi = int(_number(row.get("open_interest")))
    vol_oi = _number(row.get("vol_to_oi_ratio") or row.get("vol_oi"))
    flow_score = _number(row.get("flow_momentum_score"))
    evidence = row.get("flow_evidence") if isinstance(row.get("flow_evidence"), dict) else {}
    proxy = str(evidence.get("execution_pressure_proxy") or row.get("aggressor_proxy") or "unknown").lower()

    if verified and aligned_sentiment and unusual_type in {"sweep", "block", "large"}:
        strength = 96 if unusual_type == "sweep" and premium >= 250_000 else 92 if premium >= 100_000 else 86
        label = f"فلو {unusual_type.upper()} موثق عند التنفيذ — {sentiment}"
        return {"tier": "VERIFIED", "score": strength, "label": label, "premium": premium, "prints": prints, "verified": True}

    proxy_aligned = (direction == "CALL" and proxy == "ask") or (direction == "PUT" and proxy == "ask")
    if proxy_aligned and vol_oi >= 1.5 and volume >= 200:
        return {
            "tier": "SNAPSHOT_PROXY",
            "score": min(84.0, 58.0 + min(18.0, vol_oi * 6.0) + min(8.0, flow_score / 12.0)),
            "label": "ضغط شراء مرجح من Snapshot + نشاط Volume/OI — غير مؤكد كـBuy-to-Open",
            "premium": 0.0,
            "prints": 0,
            "verified": False,
        }

    if vol_oi >= 2.0 and volume >= 300:
        return {
            "tier": "ACTIVITY_ONLY",
            "score": min(72.0, 48.0 + vol_oi * 6.0),
            "label": "نشاط غير طبيعي في Volume/OI — لا يثبت جهة المشتري",
            "premium": 0.0,
            "prints": 0,
            "verified": False,
        }

    return {"tier": "WEAK", "score": 35.0, "label": "لا يوجد فلو قوي كافٍ", "premium": 0.0, "prints": 0, "verified": False}


def _source_line(catalyst: dict[str, Any] | None) -> str:
    if not catalyst:
        return "🔗 <b>المصدر:</b> لا يوجد محفز رسمي/أولي مطابق حتى الآن"
    evidence = event_source_evidence(catalyst)
    source = _safe(catalyst.get("source") or "مصدر غير مسمى", 120)
    url = str(catalyst.get("url") or "").strip()
    tier = _safe(evidence.get("source_tier") or "UNVERIFIED", 80)
    if url.startswith(("https://", "http://")):
        return f'🔗 <b>المصدر:</b> <a href="{html.escape(url, quote=True)}">{source}</a> | {tier}'
    return f"🔗 <b>المصدر:</b> {source} | {tier}"


def _estimated_premium(row: dict[str, Any]) -> float:
    verified = _number(row.get("verified_unusual_total_value"))
    if verified > 0:
        return verified
    volume = _number(row.get("volume"))
    mid = _number(row.get("mid"))
    if mid <= 0:
        bid = _number(row.get("bid"))
        ask = _number(row.get("ask"))
        mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else 0.0
    return volume * mid * 100.0


def _eligible(row: dict[str, Any], catalyst: dict[str, Any] | None, flow: dict[str, Any]) -> bool:
    strict = _number(row.get("strict_score") or row.get("score"))
    grade = str(row.get("signal_grade") or row.get("strict_grade") or "")
    direction = _direction(row)
    aligned, _ = _catalyst_alignment(direction, catalyst)
    catalyst_score = abs(_number((catalyst or {}).get("score")))
    minimum = _number(os.getenv("OPTIONS_INTEL_MIN_SCORE", "85"), 85.0)
    if strict < minimum or (grade and grade not in {"A", "A+"}):
        return False
    if flow["tier"] == "VERIFIED" and flow["score"] >= 86:
        return aligned or catalyst is None or catalyst_score < 8
    if flow["tier"] == "SNAPSHOT_PROXY":
        return aligned and catalyst_score >= 8
    return False


def _fingerprint(row: dict[str, Any], catalyst: dict[str, Any] | None, flow: dict[str, Any]) -> str:
    seed = "|".join(
        [
            _contract_key(row),
            str(round(_number(row.get("strict_score") or row.get("score")) / 3) * 3),
            flow["tier"],
            str(round(_number(flow.get("premium")) / 50_000) * 50_000),
            str((catalyst or {}).get("headline") or "")[:160],
        ]
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def _message(row: dict[str, Any], catalyst: dict[str, Any] | None, flow: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "").upper()
    direction = _direction(row)
    side_ar = "كول" if direction == "CALL" else "بوت"
    emoji = "🟢" if direction == "CALL" else "🔴"
    strike = _number(row.get("strike"))
    expiration = str(row.get("expiration") or "")[:10]
    dte = int(_number(row.get("dte")))
    strict = _number(row.get("strict_score") or row.get("score"))
    grade = str(row.get("signal_grade") or row.get("strict_grade") or "")
    bid = _number(row.get("bid"))
    ask = _number(row.get("ask"))
    spread = _number(row.get("spread_pct"))
    volume = int(_number(row.get("volume")))
    oi = int(_number(row.get("open_interest")))
    vol_oi = _number(row.get("vol_to_oi_ratio") or row.get("vol_oi"))
    delta = _number(row.get("delta"))
    iv = _number(row.get("iv"))
    premium = _estimated_premium(row)
    premium_label = "موثق من UOA" if flow.get("verified") else "تقديري = Volume × Mid × 100"
    aligned, alignment_text = _catalyst_alignment(direction, catalyst)
    headline = _safe((catalyst or {}).get("headline") or "لا يوجد خبر رسمي/أولي مطابق حتى الآن", 520)
    category = _safe((catalyst or {}).get("category") or "لا يوجد", 160)
    source_line = _source_line(catalyst)
    reasons = [str(value) for value in row.get("strict_reasons", []) if str(value).strip()]

    lines = [
        f"{emoji} <b>بلاك بوكس — عقد {side_ar} غير طبيعي + محفز</b>",
        "",
        f"📌 <b>{_safe(symbol)}</b> | {strike:g} {direction} | انتهاء <b>{expiration}</b> | <b>{dte}D</b>",
        f"⭐ الجودة: <b>{strict:.0f}/100 {grade}</b> | B/A <b>${bid:.2f}/${ask:.2f}</b> | Spread <b>{spread * 100:.1f}%</b>",
        f"💧 Volume <b>{volume:,}</b> | OI السابق <b>{oi:,}</b> | V/OI <b>{vol_oi:.2f}×</b>",
        f"💸 <b>التدفق:</b> {_safe(flow.get('label'), 520)}",
        f"💰 Premium: <b>${premium:,.0f}</b> <i>({premium_label})</i>",
        f"📐 Delta <b>{delta:+.2f}</b> | IV <b>{iv:.0%}</b>",
        "",
        f"📰 <b>المحفز:</b> {headline}",
        f"🧩 النوع: <b>{category}</b> | الربط بالاتجاه: <b>{_safe(alignment_text)}</b>",
        source_line,
        "",
        "🧾 <b>ملاحظة OI:</b> OI المعروض ناتج عن تسوية الجلسة السابقة. إذا ارتفع OI في الجلسة التالية سيصلك تنبيه متابعة مستقل يدعم بقاء جزء من النشاط كمراكز مفتوحة؛ لا يحدد هوية المشتري.",
    ]
    if reasons:
        lines.append(f"✅ {_safe(' | '.join(reasons[:2]), 620)}")
    lines.append("⚠️ <i>Volume/OI أو التنفيذ قرب الـAsk لا يثبت Buy-to-Open وحده. الفلو الموثق يرفع جودة الدليل لكنه لا يضمن اتجاه السعر.</i>")
    return "\n".join(lines)


def _find_contract(payload: dict[str, Any], contract_key: str) -> dict[str, Any] | None:
    rows = payload.get("contracts") if isinstance(payload.get("contracts"), list) else []
    for row in rows:
        if isinstance(row, dict) and _contract_key(row) == contract_key:
            return row
    return None


def _send_oi_followups(payload: dict[str, Any], state: dict[str, Any]) -> int:
    registry = state.setdefault("contracts", {})
    today = datetime.now(timezone.utc).date().isoformat()
    sent = 0
    for key, record in list(registry.items()):
        if not isinstance(record, dict) or record.get("oi_followup_sent") is True:
            continue
        sent_date = str(record.get("sent_date") or "")
        if not sent_date or sent_date >= today:
            continue
        current = _find_contract(payload, key)
        if current is None:
            continue
        baseline = int(_number(record.get("baseline_oi")))
        baseline_volume = int(_number(record.get("baseline_volume")))
        current_oi = int(_number(current.get("open_interest")))
        increase = current_oi - baseline
        threshold = max(50, int(max(baseline * 0.10, baseline_volume * 0.10)))
        if increase < threshold:
            continue
        symbol = str(record.get("symbol") or current.get("symbol") or "").upper()
        direction = str(record.get("direction") or _direction(current))
        side_ar = "كول" if direction == "CALL" else "بوت"
        text = "\n".join(
            [
                "🔁 <b>بلاك بوكس — متابعة OI بعد التنبيه</b>",
                f"📌 <b>{_safe(symbol)}</b> | عقد {side_ar} | {_safe(key, 120)}",
                f"OI السابق: <b>{baseline:,}</b> → OI بعد التسوية: <b>{current_oi:,}</b> | الزيادة <b>+{increase:,}</b>",
                "🧠 الزيادة تدعم أن جزءًا من نشاط الجلسة السابقة بقي كمراكز مفتوحة بعد التسوية، لكنها لا تثبت هوية المتداول ولا أن جميع العقود كانت Buy-to-Open.",
            ]
        )
        send_html_message(text)
        record["oi_followup_sent"] = True
        record["oi_followup_sent_at"] = datetime.now(timezone.utc).isoformat()
        record["confirmed_oi"] = current_oi
        sent += 1
    return sent


def send(payload: dict[str, Any], state: dict[str, Any]) -> tuple[int, int]:
    age = _payload_age_minutes(payload)
    max_age = _number(os.getenv("OPTIONS_INTEL_MAX_PAYLOAD_AGE_MINUTES", "45"), 45.0)
    if age is None or age > max_age:
        state.update({"last_run_at": datetime.now(timezone.utc).isoformat(), "last_sent_count": 0, "blocked_reason": "STALE_OPTIONS_PAYLOAD", "payload_age_minutes": age})
        return 0, 0

    followups = _send_oi_followups(payload, state)
    signals = _signals(payload)
    symbols = list(dict.fromkeys(str(row.get("symbol") or "").upper() for row in signals[:20] if str(row.get("symbol") or "").strip()))
    settings = Settings()
    catalysts = CatalystScanner(settings).scan(symbols, lookback_days=3) if symbols else None
    catalyst_map = best_catalyst_map(catalysts) if catalysts is not None else {}

    enriched, flow_errors = enrich_with_intrinio_flow(
        signals,
        max_symbols=max(1, min(25, int(_number(os.getenv("INTRINIO_FLOW_MAX_SYMBOLS", "12"), 12)))),
    )
    sent_map = state.setdefault("sent", {})
    contract_registry = state.setdefault("contracts", {})
    maximum = max(1, min(5, int(_number(os.getenv("OPTIONS_INTEL_MAX_ALERTS", "3"), 3))))
    sent = 0

    for row in enriched:
        if sent >= maximum:
            break
        symbol = str(row.get("symbol") or "").upper()
        direction = _direction(row)
        if not symbol or direction not in {"CALL", "PUT"}:
            continue
        catalyst = catalyst_map.get(symbol)
        flow = _flow_assessment(row)
        if not _eligible(row, catalyst, flow):
            continue
        key = _contract_key(row)
        fp = _fingerprint(row, catalyst, flow)
        previous = sent_map.get(key) if isinstance(sent_map.get(key), dict) else {}
        if str(previous.get("fingerprint") or "") == fp:
            continue
        send_html_message(_message(row, catalyst, flow))
        now = datetime.now(timezone.utc)
        sent_map[key] = {
            "fingerprint": fp,
            "sent_at": now.isoformat(),
            "symbol": symbol,
            "direction": direction,
            "flow_tier": flow["tier"],
            "strict_score": round(_number(row.get("strict_score") or row.get("score")), 2),
        }
        contract_registry[key] = {
            "symbol": symbol,
            "direction": direction,
            "sent_date": now.date().isoformat(),
            "baseline_oi": int(_number(row.get("open_interest"))),
            "baseline_volume": int(_number(row.get("volume"))),
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
            "architecture": "standalone_options_flow_catalyst_v7",
        }
    )
    state.pop("blocked_reason", None)
    return sent, followups


def main() -> None:
    parser = argparse.ArgumentParser(description="Send BLACK BOX options flow + catalyst intelligence alerts")
    parser.add_argument("--payload", required=True)
    parser.add_argument("--state", default="data/live/options_intelligence_v7_state.json")
    args = parser.parse_args()
    payload = _load(args.payload, {})
    state = _load(args.state, {"sent": {}, "contracts": {}})
    if not isinstance(payload, dict) or payload.get("path") != "options":
        raise RuntimeError("Expected independent options payload")
    if not isinstance(state, dict):
        state = {"sent": {}, "contracts": {}}
    try:
        sent, followups = send(payload, state)
    finally:
        _save(args.state, state)
    print(f"Options intelligence v7: sent={sent} oi_followups={followups} age={state.get('payload_age_minutes')}")


if __name__ == "__main__":
    main()
