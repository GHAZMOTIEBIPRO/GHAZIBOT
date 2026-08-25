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
from options_radar.settings import Settings
from options_radar.telegram_transport import send_html_message


STAGE_ORDER = {"WATCH": 0, "DORMANT": 0, "PRESSURE_BUILDING": 1, "PRE_EXPLOSION": 2, "IGNITION": 3, "EXPLOSION": 4, "EXTENDED": 5}
STAGE_AR = {
    "WATCH": "مراقبة",
    "DORMANT": "هادئ",
    "PRESSURE_BUILDING": "ضغط يتكوّن",
    "PRE_EXPLOSION": "قبل الانفجار",
    "IGNITION": "اشتعال مبكر",
    "EXPLOSION": "انفجار سعري",
    "EXTENDED": "ممتد / مطاردة",
}


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


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


def _safe(value: Any, limit: int = 480) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text)


def _payload_age_minutes(payload: dict[str, Any]) -> float | None:
    raw = str(payload.get("generated_at") or payload.get("as_of") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 60.0)


def _verification_badge(evidence: dict[str, Any]) -> str:
    tier = str(evidence.get("source_tier") or "")
    if tier == "A_OFFICIAL":
        return "رسمي A"
    if tier == "B_ISSUER_PRIMARY":
        return "مصدر الشركة B"
    if tier == "B_OFFICIAL_REGISTRY":
        return "سجل رسمي B"
    if tier.startswith("C_"):
        return "تأكيد/مزود ثانوي C"
    return "غير مؤكد"


def _source_line(catalyst: dict[str, Any], evidence: dict[str, Any]) -> str:
    source = _safe(catalyst.get("source") or "مصدر غير مسمى", 120)
    url = str(catalyst.get("url") or "").strip()
    badge = _verification_badge(evidence)
    if url.startswith(("https://", "http://")):
        return f'🔗 <b>المصدر:</b> <a href="{html.escape(url, quote=True)}">{source}</a> | <b>{badge}</b>'
    return f"🔗 <b>المصدر:</b> {source} | <b>{badge}</b>"


def _candidate_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("actionable") if isinstance(payload.get("actionable"), list) else []
    output = [row for row in rows if isinstance(row, dict) and str(row.get("symbol") or "").strip()]
    output.sort(key=lambda row: (_number(row.get("score")), STAGE_ORDER.get(str(row.get("stage") or "WATCH").upper(), 0)), reverse=True)
    return output


def _fingerprint(row: dict[str, Any], catalyst: dict[str, Any]) -> str:
    seed = "|".join(
        [
            str(row.get("symbol") or "").upper(),
            str(row.get("stage") or ""),
            str(round(_number(row.get("score")) / 3) * 3),
            str(catalyst.get("headline") or "")[:180],
            str(catalyst.get("event_date") or ""),
            str(catalyst.get("source") or ""),
        ]
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def _strong_enough(row: dict[str, Any], catalyst: dict[str, Any], evidence: dict[str, Any]) -> bool:
    score = _number(row.get("score"))
    stage = str(row.get("stage") or "WATCH").upper()
    move = _number(row.get("move_pct"))
    turnover = _number(row.get("turnover_pct"))
    volume = _number(row.get("volume"))
    catalyst_score = _number(catalyst.get("score"))
    source_rank = _number(evidence.get("source_rank"))
    attention_only = evidence.get("attention_only") is True
    if attention_only or catalyst_score <= 0:
        return False
    if source_rank >= 86:
        return score >= 62 and STAGE_ORDER.get(stage, 0) >= 1 and (move >= 1.0 or turnover >= 0.3 or volume >= 500_000)
    if source_rank >= 58:
        return score >= 74 and STAGE_ORDER.get(stage, 0) >= 2 and move >= 2.0 and (turnover >= 0.5 or volume >= 1_000_000)
    return False


def _message(row: dict[str, Any], catalyst: dict[str, Any], evidence: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "").upper()
    score = _number(row.get("score"))
    stage = str(row.get("stage") or "WATCH").upper()
    price = _number(row.get("price"))
    move = _number(row.get("move_pct"))
    volume = int(_number(row.get("volume")))
    turnover = _number(row.get("turnover_pct"))
    supply = _number(row.get("supply_score"))
    news_score = _number(row.get("news_score"))
    reasons = [str(value) for value in row.get("reasons", []) if str(value).strip()]
    catalyst_score = _number(catalyst.get("score"))
    confidence = _number(catalyst.get("confidence"))
    freshness = _number(catalyst.get("freshness"))
    source_line = _source_line(catalyst, evidence)
    headline = _safe(catalyst.get("headline") or catalyst.get("category") or "محفز جوهري", 520)
    category = _safe(catalyst.get("category") or "غير مصنف", 180)
    verification = _safe(evidence.get("verification_state") or "UNCONFIRMED", 100)
    proof = " | ".join(reasons[:3]) if reasons else "تزامن حركة السعر والحجم مع المحفز"

    return "\n".join(
        [
            "🚨 <b>بلاك بوكس — خبر قوي + قابلية إعادة تسعير</b>",
            "",
            f"📌 <b>{_safe(symbol)}</b> | السعر <b>${price:,.2f}</b> | اليوم <b>{move:+.1f}%</b>",
            f"🔥 الحالة: <b>{_safe(STAGE_AR.get(stage, stage))}</b> | قوة الحركة <b>{score:.0f}/100</b>",
            f"📰 <b>{headline}</b>",
            f"🧩 النوع: <b>{category}</b> | أثر الخبر <b>{catalyst_score:+.0f}</b> | ثقة المصدر <b>{confidence:.0%}</b> | حداثة <b>{freshness:.0%}</b>",
            source_line,
            f"🛡 حالة التحقق: <b>{verification}</b>",
            "",
            f"💧 الحجم: <b>{volume:,}</b> | دوران السيولة/القيمة السوقية: <b>{turnover:.2f}%</b>",
            f"🧱 ضغط العرض: <b>{supply:.0f}/100</b> | نشاط الخبر السريع: <b>{news_score:.0f}/100</b>",
            f"🔬 لماذا لفت الانتباه: {_safe(proof, 620)}",
            "",
            "⚠️ <i>هذه إشارة خبر + استجابة سوقية مبكرة. لا تعني أن الانفجار سيستمر؛ يلغى الزخم إذا تراجع الحجم أو فشل السعر في الاحتفاظ بإعادة التسعير.</i>",
        ]
    )


def send(payload: dict[str, Any], state: dict[str, Any]) -> int:
    max_age = _number(os.getenv("STOCK_INTEL_MAX_PAYLOAD_AGE_MINUTES", "35"), 35.0)
    age = _payload_age_minutes(payload)
    if age is None or age > max_age:
        state.update({"last_run_at": datetime.now(timezone.utc).isoformat(), "last_sent_count": 0, "blocked_reason": "STALE_FAST_PAYLOAD", "payload_age_minutes": age})
        return 0

    rows = _candidate_rows(payload)
    symbols = [str(row.get("symbol") or "").upper() for row in rows[:30]]
    if not symbols:
        state.update({"last_run_at": datetime.now(timezone.utc).isoformat(), "last_sent_count": 0, "candidate_count": 0})
        return 0

    settings = Settings()
    catalysts = CatalystScanner(settings).scan(symbols, lookback_days=3)
    catalyst_map = best_catalyst_map(catalysts)
    sent_state = state.setdefault("sent", {})
    maximum = max(1, min(5, int(_number(os.getenv("STOCK_INTEL_MAX_ALERTS", "3"), 3))))
    sent = 0

    for row in rows:
        if sent >= maximum:
            break
        symbol = str(row.get("symbol") or "").upper()
        catalyst = catalyst_map.get(symbol)
        if not isinstance(catalyst, dict):
            continue
        evidence = event_source_evidence(catalyst)
        if not _strong_enough(row, catalyst, evidence):
            continue
        fingerprint = _fingerprint(row, catalyst)
        previous = sent_state.get(symbol) if isinstance(sent_state.get(symbol), dict) else {}
        if str(previous.get("fingerprint") or "") == fingerprint:
            continue
        send_html_message(_message(row, catalyst, evidence))
        sent_state[symbol] = {
            "fingerprint": fingerprint,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "score": round(_number(row.get("score")), 2),
            "headline": str(catalyst.get("headline") or "")[:220],
            "source": str(catalyst.get("source") or ""),
            "verification_state": evidence.get("verification_state"),
        }
        sent += 1

    state.update(
        {
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_sent_count": sent,
            "candidate_count": len(rows),
            "payload_age_minutes": round(age, 2),
            "architecture": "standalone_stock_news_explosion_v7",
        }
    )
    state.pop("blocked_reason", None)
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="Send verified BLACK BOX stock catalyst + explosion alerts")
    parser.add_argument("--payload", default="data/live/fast_explosion_scan.json")
    parser.add_argument("--state", default="data/live/stock_intelligence_v7_state.json")
    args = parser.parse_args()
    payload = _load(args.payload, {})
    state = _load(args.state, {"sent": {}})
    if not isinstance(payload, dict):
        payload = {}
    if not isinstance(state, dict):
        state = {"sent": {}}
    try:
        sent = send(payload, state)
    finally:
        _save(args.state, state)
    print(f"Stock intelligence v7: sent={sent} candidates={state.get('candidate_count', 0)} age={state.get('payload_age_minutes')}")


if __name__ == "__main__":
    main()
