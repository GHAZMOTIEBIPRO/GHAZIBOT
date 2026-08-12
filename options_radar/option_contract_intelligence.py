from __future__ import annotations

import math
from typing import Any

_INDEX_ROOTS = {"SPX", "SPXW", "NDX", "XND", "SPY", "QQQ"}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _contracts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    radar = payload.get("expiry_radar") if isinstance(payload.get("expiry_radar"), dict) else {}
    tabs = radar.get("tabs") if isinstance(radar.get("tabs"), dict) else {}
    all_exp = tabs.get("all_expirations") if isinstance(tabs.get("all_expirations"), dict) else {}
    rows: list[dict[str, Any]] = []
    for side in ("calls", "puts"):
        source_rows = all_exp.get(side, []) if isinstance(all_exp.get(side), list) else []
        rows.extend(dict(row) for row in source_rows if isinstance(row, dict))
    return rows


def _stock_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("symbol") or "").upper(): row
        for row in payload.get("stocks", []) or []
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    }


def _opportunity_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    omega = payload.get("omega") if isinstance(payload.get("omega"), dict) else {}
    rows = omega.get("opportunities") if isinstance(omega.get("opportunities"), list) else []
    return {
        str(row.get("symbol") or "").upper(): row
        for row in rows
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    }


def _catalyst_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    omega = payload.get("omega") if isinstance(payload.get("omega"), dict) else {}
    intelligence = omega.get("catalyst_intelligence") if isinstance(omega.get("catalyst_intelligence"), dict) else {}
    by_symbol = intelligence.get("by_symbol") if isinstance(intelligence.get("by_symbol"), dict) else {}
    return {str(symbol).upper(): row for symbol, row in by_symbol.items() if isinstance(row, dict)}


def _preferred_side(
    stock: dict[str, Any],
    opportunity: dict[str, Any],
    catalyst: dict[str, Any],
) -> tuple[str | None, str]:
    bias = str(catalyst.get("directional_bias") or "").lower()
    official = bool(catalyst.get("official_confirmed"))
    cause_eligible = bool(catalyst.get("primary_cause_eligible"))
    if cause_eligible and bias == "bullish":
        return "call", "المحفز الأساسي يميل للصعود" + (" ومؤكد رسميًا" if official else "")
    if cause_eligible and bias == "bearish":
        return "put", "المحفز الأساسي يميل للهبوط" + (" ومؤكد رسميًا" if official else "")

    direction = str(opportunity.get("direction") or "").upper()
    if direction in {"UPSIDE", "LONG", "CALL"}:
        return "call", "اتجاه فرصة Ω صاعد"
    if direction in {"DOWNSIDE", "SHORT", "PUT"}:
        return "put", "اتجاه فرصة Ω هابط"

    setup = str(stock.get("setup_side") or "").lower()
    if setup in {"call", "put"}:
        return setup, f"الاتجاه الفني للسهم يفضل {setup.upper()}"
    technical = str(stock.get("technical_direction") or "").lower()
    if technical == "bullish":
        return "call", "الاتجاه الفني صاعد"
    if technical == "bearish":
        return "put", "الاتجاه الفني هابط"
    return None, "الاتجاه غير محسوم؛ لا يوجد عقد مفضل"


def _target_dte(catalyst: dict[str, Any], opportunity: dict[str, Any]) -> tuple[float, str]:
    official = bool(catalyst.get("official_confirmed"))
    materiality = _number(catalyst.get("materiality"))
    reaction = str(catalyst.get("reaction_state") or "").upper()
    horizon = str(opportunity.get("horizon") or opportunity.get("timeframe") or "").upper()

    if "SWING" in horizon:
        return 30.0, "مدة أقرب إلى شهر لأن السيناريو Swing"
    if official and materiality >= 75 and reaction in {"NOT_YET_REPRICED", "REPRICING", "UNKNOWN"}:
        return 14.0, "نحو أسبوعين لموازنة سرعة المحفز مع تقليل خطر Theta مقارنة بالعقود شديدة القصر"
    return 21.0, "نحو 3 أسابيع كحل متوازن بين الوقت والسيولة وحساسية العقد"


def _dte_window(target: float, symbol: str) -> tuple[float, float]:
    """Hard horizon guard so flow strength cannot select a wildly distant expiry."""

    if symbol in _INDEX_ROOTS:
        if target <= 14:
            return 0.0, 35.0
        if target <= 21:
            return 0.0, 45.0
        return 0.0, 70.0
    if target <= 14:
        return 4.0, 35.0
    if target <= 21:
        return 7.0, 45.0
    return 10.0, 70.0


def _dte_score(dte: float, target: float, symbol: str) -> tuple[float, str, list[str]]:
    risks: list[str] = []
    low, high = _dte_window(target, symbol)
    if dte < low or dte > high:
        return -1.0, f"DTE={int(dte)} خارج نافذة {int(low)}–{int(high)} يوم", ["تاريخ الانتهاء لا يناسب أفق الصفقة"]
    if dte <= 1 and symbol not in _INDEX_ROOTS:
        risks.append("العقد شديد القصر؛ Theta/Gamma risk مرتفعان")
    width = max(target - low, high - target, 10.0)
    fit = max(0.0, 1.0 - abs(dte - target) / width)
    score = 100.0 * fit
    if dte <= 2:
        score -= 18.0
    elif dte <= 5:
        score -= 6.0
    return max(0.0, min(100.0, score)), f"DTE={int(dte)} مقابل هدف تقريبي {int(target)} يوم", risks


def _contract_score(
    row: dict[str, Any],
    *,
    symbol: str,
    preferred_side: str,
    target_dte: float,
    official_catalyst: bool,
) -> tuple[float, dict[str, Any]]:
    side = str(row.get("option_type") or "").lower()
    if side != preferred_side:
        return -1.0, {}

    rank = _number(row.get("rank_score"))
    dte = _number(row.get("dte"), -1.0)
    dte_fit, dte_note, risks = _dte_score(dte, target_dte, symbol)
    if dte_fit < 0:
        return -1.0, {}

    delta = abs(_number(row.get("delta"), -1.0))
    delta_fit = max(0.0, 1.0 - abs(delta - 0.45) / 0.25) if delta >= 0 else 0.0
    spread = _number(row.get("spread_pct"), 1.0)
    spread_fit = max(0.0, 1.0 - spread / 0.25) if spread >= 0 else 0.0
    vol_oi = _number(row.get("vol_to_oi_ratio"))
    flow_fit = min(1.0, vol_oi / 2.0)
    oi = _number(row.get("open_interest"))
    volume = _number(row.get("volume"))
    liquidity_fit = 0.5 * min(1.0, oi / 500.0) + 0.5 * min(1.0, volume / 500.0)
    tier = str(row.get("opportunity_tier") or "C").upper()
    tier_bonus = {"A": 8.0, "B": 3.0}.get(tier, 0.0)
    source_bonus = 5.0 if row.get("primary_or_licensed_quote") else 0.0
    flow_sources = row.get("flow_sources") if isinstance(row.get("flow_sources"), list) else []
    flow_source_bonus = 5.0 if flow_sources else 0.0

    occ = row.get("occ_official_context") if isinstance(row.get("occ_official_context"), dict) else {}
    occ_available = bool(occ.get("available"))
    occ_aligned = bool(occ.get("aligned_with_contract_side"))
    occ_bonus = 4.0 if occ_aligned else 0.0

    score = (
        0.34 * rank
        + 0.22 * dte_fit
        + 14.0 * delta_fit
        + 10.0 * spread_fit
        + 8.0 * flow_fit
        + 7.0 * liquidity_fit
        + tier_bonus
        + source_bonus
        + flow_source_bonus
        + occ_bonus
        + (3.0 if official_catalyst else 0.0)
    )
    score = max(0.0, min(100.0, score))

    moneyness = _number(row.get("moneyness_pct"), float("nan"))
    if math.isfinite(moneyness):
        strike_note = f"السترايك قريب من السعر الفوري بفارق {moneyness * 100:+.1f}% وDelta≈{delta:.2f}"
    else:
        strike_note = f"Delta≈{delta:.2f} ضمن النطاق المفضل للعقد المتوازن"

    flow_note = (
        f"Volume/OI={vol_oi:.2f}× مع مصدر Flow إضافي ({', '.join(str(x) for x in flow_sources[:2])})"
        if flow_sources
        else f"Volume/OI={vol_oi:.2f}×؛ لا يوجد إثبات trade-level مستقل لاتجاه المنفذ"
    )
    if occ_available:
        call_volume = int(_number(occ.get("call_volume")))
        put_volume = int(_number(occ.get("put_volume")))
        dominance = _number(occ.get("side_dominance_ratio"))
        if occ_aligned:
            flow_note += f"؛ OCC الرسمي يدعم الجهة إجماليًا (CALL {call_volume:,} / PUT {put_volume:,}، تفوق {dominance:.2f}×)"
        else:
            flow_note += f"؛ OCC الرسمي CALL {call_volume:,} / PUT {put_volume:,} دون تفوق واضح لنفس الجهة"

    if vol_oi < 1.0:
        risks.append("Volume/OI غير مرتفع؛ نشاط العقد ليس استثنائيًا بعد")
    if spread > 0.15:
        risks.append(f"السبريد واسع نسبيًا ({spread * 100:.1f}%)")
    if tier == "C":
        risks.append("جودة العقد C؛ مراقبة فقط")
    if not row.get("primary_or_licensed_quote"):
        risks.append("الـQuote الحالي غير مرخّص/أساسي؛ لا يرقى العقد إلى ثقة تنفيذية عالية")

    return score, {
        "score": round(score, 1),
        "dte_note": dte_note,
        "strike_note": strike_note,
        "flow_note": flow_note,
        "risks": list(dict.fromkeys(risks)),
    }


def build_option_contract_intelligence(payload: dict[str, Any]) -> dict[str, Any]:
    contracts = _contracts(payload)
    stocks = _stock_map(payload)
    opportunities = _opportunity_map(payload)
    catalysts = _catalyst_map(payload)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in contracts:
        symbol = str(row.get("symbol") or row.get("root_symbol") or "").upper().strip()
        if symbol:
            grouped.setdefault(symbol, []).append(row)

    by_symbol: dict[str, dict[str, Any]] = {}
    rejected_for_horizon: dict[str, int] = {}
    for symbol, rows in grouped.items():
        stock = stocks.get(symbol, {})
        opportunity = opportunities.get(symbol, {})
        catalyst = catalysts.get(symbol, {})
        side, side_reason = _preferred_side(stock, opportunity, catalyst)
        if side is None:
            continue
        target_dte, expiry_reason = _target_dte(catalyst, opportunity)

        ranked: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
        eligible_side = 0
        for row in rows:
            if str(row.get("option_type") or "").lower() == side:
                eligible_side += 1
            score, detail = _contract_score(
                row,
                symbol=symbol,
                preferred_side=side,
                target_dte=target_dte,
                official_catalyst=bool(catalyst.get("official_confirmed")),
            )
            if score >= 0:
                ranked.append((score, row, detail))
        ranked.sort(key=lambda item: item[0], reverse=True)
        rejected_for_horizon[symbol] = max(0, eligible_side - len(ranked))
        if not ranked:
            continue

        choices: list[dict[str, Any]] = []
        for score, row, detail in ranked[:3]:
            choices.append(
                {
                    "symbol": symbol,
                    "contract_symbol": row.get("contract_symbol"),
                    "side": side.upper(),
                    "expiration": str(row.get("expiration_date") or row.get("expiration") or "")[:10],
                    "dte": int(_number(row.get("dte"), 0)),
                    "strike": row.get("strike"),
                    "bid": row.get("bid"),
                    "ask": row.get("ask"),
                    "mid": row.get("mid"),
                    "delta": row.get("delta"),
                    "gamma": row.get("gamma"),
                    "theta": row.get("theta"),
                    "vega": row.get("vega"),
                    "iv": row.get("iv"),
                    "volume": row.get("volume"),
                    "open_interest": row.get("open_interest"),
                    "vol_to_oi_ratio": row.get("vol_to_oi_ratio"),
                    "spread_pct": row.get("spread_pct"),
                    "source": row.get("source"),
                    "flow_sources": row.get("flow_sources") or [],
                    "occ_official_context": row.get("occ_official_context") or {},
                    "liquidity_grade": row.get("liquidity_grade"),
                    "opportunity_tier": row.get("opportunity_tier"),
                    "contract_rank": round(score, 1),
                    "side_reason_ar": side_reason,
                    "expiry_reason_ar": expiry_reason + "; " + detail["dte_note"],
                    "strike_reason_ar": detail["strike_note"],
                    "flow_reason_ar": detail["flow_note"],
                    "risks_ar": detail["risks"],
                    "flow_claim": "BUYING_PRESSURE_PROXY_NOT_SWEEP_PROOF",
                    "occ_is_context_only": True,
                    "automatic_execution": False,
                    "research_only": True,
                }
            )

        by_symbol[symbol] = {
            "symbol": symbol,
            "preferred_side": side.upper(),
            "side_reason_ar": side_reason,
            "target_dte": target_dte,
            "allowed_dte_window": list(_dte_window(target_dte, symbol)),
            "catalyst_verification": catalyst.get("verification_state") or "NO_OFFICIAL_CAUSE",
            "catalyst_cause_status_ar": catalyst.get("cause_status_ar") or "السبب الأساسي غير مثبت رسميًا",
            "primary": choices[0],
            "alternatives": choices[1:],
            "contract_count_considered": len(ranked),
            "contracts_rejected_for_horizon": rejected_for_horizon[symbol],
        }

    return {
        "version": "2026.08-option-contract-rationale-v3",
        "policy": {
            "side_requires_direction_alignment": True,
            "strike_not_selected_by_volume_alone": True,
            "expiry_uses_dte_liquidity_and_catalyst_horizon": True,
            "hard_dte_horizon_guard": True,
            "volume_oi_is_activity_signal_not_direction_proof": True,
            "occ_is_official_aggregate_context_only": True,
            "sweep_claim_requires_trade_quote_level_evidence": True,
            "automatic_execution": False,
            "research_only": True,
        },
        "contracts_seen": len(contracts),
        "symbols_with_contract_choice": len(by_symbol),
        "rejected_for_horizon": rejected_for_horizon,
        "by_symbol": by_symbol,
    }


def apply_option_contract_intelligence(payload: dict[str, Any]) -> dict[str, Any]:
    intelligence = build_option_contract_intelligence(payload)
    payload["option_contract_intelligence"] = intelligence
    summary = payload.setdefault("summary", {})
    summary["option_contract_choices"] = intelligence["symbols_with_contract_choice"]
    return payload
