from __future__ import annotations

import html
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import options_radar.arabic_explosion_notifier as notifier

_ORIGINAL_BUILD = notifier.build_candidates
_ORIGINAL_FORMAT = notifier.format_candidate_message
_OPTION_MAP: dict[str, dict[str, Any]] = {}
_CATALYST_MAP: dict[str, dict[str, Any]] = {}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe(value: Any, limit: int = 500) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text)


def _prepare_maps(payload: dict[str, Any]) -> None:
    global _OPTION_MAP, _CATALYST_MAP
    option_intel = payload.get("option_contract_intelligence") if isinstance(payload.get("option_contract_intelligence"), dict) else {}
    by_symbol = option_intel.get("by_symbol") if isinstance(option_intel.get("by_symbol"), dict) else {}
    _OPTION_MAP = {str(symbol).upper(): row for symbol, row in by_symbol.items() if isinstance(row, dict)}

    omega = payload.get("omega") if isinstance(payload.get("omega"), dict) else {}
    catalyst_intel = omega.get("catalyst_intelligence") if isinstance(omega.get("catalyst_intelligence"), dict) else {}
    catalysts = catalyst_intel.get("by_symbol") if isinstance(catalyst_intel.get("by_symbol"), dict) else {}
    _CATALYST_MAP = {str(symbol).upper(): row for symbol, row in catalysts.items() if isinstance(row, dict)}


def _enforce_causal_semantics(candidate: notifier.UnifiedCandidate) -> None:
    cluster = _CATALYST_MAP.get(candidate.symbol, {})
    cause_eligible = bool(cluster.get("primary_cause_eligible"))
    headline = str(cluster.get("headline") or "").strip()
    status = str(cluster.get("cause_status_ar") or "").strip()
    source = str(cluster.get("primary_source") or "").strip()
    source_url = str(cluster.get("primary_url") or "").strip()

    adjusted: list[notifier.Cause] = []
    for cause in candidate.causes:
        if cause.category == "halt":
            adjusted.append(
                notifier.Cause(
                    78.0,
                    "halt_confirmation",
                    cause.text.replace("إيقاف/استئناف تداول مرصود", "إشارة تأكيد: إيقاف/استئناف تداول مرصود"),
                )
            )
        elif cause.category == "news" and not cause_eligible:
            adjusted.append(
                notifier.Cause(
                    58.0,
                    "unverified_news",
                    "خبر/معلومة متداولة لم ترتقِ بعد إلى سبب أساسي مثبت",
                )
            )
        else:
            adjusted.append(cause)

    if cause_eligible and headline:
        label = status or "سبب أساسي موثق"
        adjusted.append(notifier.Cause(130.0, "verified_primary_cause", f"{label}: {headline}"))
        candidate.primary_source = source or candidate.primary_source
        candidate.source_url = source_url or candidate.source_url
        candidate.headline = headline
    else:
        adjusted.append(
            notifier.Cause(
                130.0,
                "unknown_primary_cause",
                "السبب الأساسي غير مثبت رسميًا حتى الآن؛ المرصود أدناه عوامل تضخيم/تأكيد للحركة وليس تفسيرًا مؤكدًا لها",
            )
        )
        if "لا يوجد سبب رسمي مؤكد حتى الآن" not in candidate.risks:
            candidate.risks.insert(0, "لا يوجد سبب رسمي مؤكد حتى الآن")

    unique: list[notifier.Cause] = []
    seen: set[str] = set()
    for cause in sorted(adjusted, reverse=True):
        key = f"{cause.category}:{cause.text[:160]}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(cause)
    candidate.causes = unique[:7]


def _enhanced_build(payload: dict[str, Any], fast_payload: dict[str, Any], delta_payload: dict[str, Any]):
    _prepare_maps(payload)
    candidates = _ORIGINAL_BUILD(payload, fast_payload, delta_payload)
    for candidate in candidates:
        _enforce_causal_semantics(candidate)
        setattr(candidate, "option_contract_intelligence", _OPTION_MAP.get(candidate.symbol))
    return candidates


def _option_block(candidate: notifier.UnifiedCandidate) -> str:
    item = getattr(candidate, "option_contract_intelligence", None)
    if not isinstance(item, dict):
        return (
            "\n\n🎛 <b>عقد الخيار</b>\n"
            "لا يوجد عقد CALL/PUT اجتاز طبقة الاختيار بجودة كافية في البيانات الحالية."
        )
    primary = item.get("primary") if isinstance(item.get("primary"), dict) else {}
    if not primary:
        return "\n\n🎛 <b>عقد الخيار</b>\nلا يوجد عقد مفضل حاليًا."

    side = str(primary.get("side") or item.get("preferred_side") or "").upper()
    expiration = str(primary.get("expiration") or "غير متوفر")
    dte = primary.get("dte")
    strike = primary.get("strike")
    bid = primary.get("bid")
    ask = primary.get("ask")
    delta = primary.get("delta")
    volume = primary.get("volume")
    oi = primary.get("open_interest")
    vol_oi = _num(primary.get("vol_to_oi_ratio"))
    spread = _num(primary.get("spread_pct"), -1.0)
    rank = _num(primary.get("contract_rank"))

    price_line = ""
    if bid is not None or ask is not None:
        price_line = f"\n💵 Bid/Ask: <b>{_safe(bid)} / {_safe(ask)}</b>"
    spread_text = f" | Spread {spread * 100:.1f}%" if spread >= 0 else ""
    flow_claim = (
        "ضغط شراء/نشاط غير معتاد مرصود، وليس Sweep مؤكدًا"
        if vol_oi >= 1.5
        else "نشاط العقد يحتاج تأكيدًا إضافيًا"
    )
    risks = primary.get("risks_ar") if isinstance(primary.get("risks_ar"), list) else []
    risk_line = ""
    if risks:
        risk_line = "\n⚠️ " + _safe("؛ ".join(str(x) for x in risks[:3]), 600)

    return (
        "\n\n🎛 <b>عقد الخيار المرصود</b>\n"
        f"النوع: <b>{_safe(side)}</b> — {_safe(primary.get('side_reason_ar'), 450)}\n"
        f"الانتهاء: <b>{_safe(expiration)}</b>" + (f" ({_safe(dte)} DTE)" if dte is not None else "") + "\n"
        f"السترايك: <b>${_safe(strike)}</b> — {_safe(primary.get('strike_reason_ar'), 450)}\n"
        f"سبب التاريخ: {_safe(primary.get('expiry_reason_ar'), 500)}\n"
        f"نشاط العقد: {_safe(primary.get('flow_reason_ar'), 500)}\n"
        f"Delta: <b>{_safe(delta)}</b> | Volume: <b>{_safe(volume)}</b> | OI: <b>{_safe(oi)}</b> | Vol/OI: <b>{vol_oi:.2f}×</b>{spread_text}\n"
        f"ترتيب العقد: <b>{rank:.0f}/100</b> <i>(ترتيب جودة وليس احتمال ربح)</i>"
        f"{price_line}\n"
        f"🧾 القراءة: {_safe(flow_claim)}"
        f"{risk_line}"
    )


def _enhanced_format(candidate: notifier.UnifiedCandidate) -> str:
    return _ORIGINAL_FORMAT(candidate) + _option_block(candidate)


def main() -> int:
    notifier.build_candidates = _enhanced_build
    notifier.format_candidate_message = _enhanced_format
    return notifier.main()


if __name__ == "__main__":
    raise SystemExit(main())
