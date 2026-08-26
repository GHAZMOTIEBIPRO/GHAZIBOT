from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable


BULLISH = "BULLISH"
BEARISH = "BEARISH"
NEUTRAL = "NEUTRAL"


STAGE_ORDER = {
    "WATCH": 0,
    "BUILDING": 1,
    "CONFIRMED": 2,
    "EXTENDED": 3,
    "FAILED": -1,
}


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _text(value: Any) -> str:
    return str(value or "").strip()


def _side_for_bias(bias: str) -> str:
    return "call" if bias == BULLISH else "put" if bias == BEARISH else ""


def _bias_from_catalyst(catalyst: dict[str, Any] | None) -> str:
    score = _number((catalyst or {}).get("score"))
    if score > 0:
        return BULLISH
    if score < 0:
        return BEARISH
    return NEUTRAL


def _classical_direction(classical: dict[str, Any] | None) -> str:
    decision = _text((classical or {}).get("decision")).upper()
    if decision == "CALL":
        return BULLISH
    if decision == "PUT":
        return BEARISH
    return NEUTRAL


def _source_grade(evidence: dict[str, Any] | None) -> str:
    rank = _number((evidence or {}).get("source_rank"))
    if rank >= 98:
        return "A+"
    if rank >= 86:
        return "A"
    if rank >= 74:
        return "B+"
    if rank >= 58:
        return "B"
    return "C"


def _chart_grade(classical: dict[str, Any] | None, bias: str) -> str:
    if not isinstance(classical, dict):
        return "N/A"
    direction = _classical_direction(classical)
    agreement = int(round(_number(classical.get("agreement_pct"))))
    if direction != NEUTRAL and direction != bias:
        return "F"
    if direction == bias and agreement >= 90:
        return "A+"
    if direction == bias and agreement >= 75:
        return "A"
    if direction == bias and agreement >= 60:
        return "B"
    return "C"


@dataclass(frozen=True)
class CatalystReaction:
    state: str
    grade: str
    move_pct: float
    relative_volume: float
    stage_hint: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_catalyst_reaction(
    market_row: dict[str, Any],
    bias: str,
) -> CatalystReaction:
    """Classify price response without pretending we have a tick at the news timestamp.

    The fast scanner may only provide current move/stage/volume context. When an
    explicit event-price response is present we use it; otherwise the result is a
    conservative reaction proxy and is labelled by its reason.
    """

    stage = _text(market_row.get("stage") or market_row.get("setup_status") or "WATCH").upper()
    move = _number(
        market_row.get("move_since_catalyst_pct"),
        _number(market_row.get("move_pct"), _number(market_row.get("change_pct"))),
    )
    aligned_move = move if bias == BULLISH else -move if bias == BEARISH else 0.0
    rel_volume = _number(
        market_row.get("relative_volume"),
        _number(market_row.get("relative_volume20"), _number(market_row.get("volume_ratio"))),
    )

    explicit = market_row.get("move_since_catalyst_pct") is not None
    prefix = "استجابة مقاسة منذ المحفز" if explicit else "استجابة سوقية تقريبية من لقطة الرادار"

    if stage in {"EXTENDED", "EXPLOSION"} and aligned_move >= 8.0:
        return CatalystReaction("EXTENDED", "C", move, rel_volume, stage, f"{prefix}: الحركة أصبحت ممتدة")
    if aligned_move <= -1.0:
        return CatalystReaction("DIVERGING", "F", move, rel_volume, stage, f"{prefix}: السعر يتحرك عكس المحفز")
    if stage in {"IGNITION", "PRE_EXPLOSION", "EXPLOSION"} and aligned_move >= 1.0:
        grade = "A" if rel_volume >= 1.5 else "B+"
        return CatalystReaction("CONFIRMING", grade, move, rel_volume, stage, f"{prefix}: السعر والحالة يؤكدان إعادة التسعير")
    if aligned_move >= 0.25 or stage in {"PRESSURE_BUILDING", "PRE_EXPLOSION"}:
        return CatalystReaction("BUILDING", "B", move, rel_volume, stage, f"{prefix}: الاستجابة تتكوّن ولم تكتمل")
    return CatalystReaction("LAGGING", "C", move, rel_volume, stage, f"{prefix}: المحفز لم يظهر استجابة سعرية كافية بعد")


@dataclass(frozen=True)
class ContractEvidence:
    available: bool
    contract_symbol: str
    option_type: str
    strike: float
    expiration: str
    bid: float
    ask: float
    spread_pct: float
    volume: int
    open_interest: int
    delta: float
    iv: float
    data_confidence: str
    contract_grade: str
    flow_grade: str
    execution_ready: bool
    source: str
    freshness: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def data_confidence(row: dict[str, Any]) -> str:
    text = " ".join(
        _text(row.get(key)).lower()
        for key in (
            "source",
            "freshness_label",
            "fabric_source_tier",
            "provider",
            "data_mode",
        )
    )
    delayed = any(token in text for token in ("delayed", "indicative", "sandbox", "unofficial", "yahoo", "24h"))
    live = any(token in text for token in ("opra", "realtime", "real-time", "licensed", "brokerage feed"))
    account = any(token in text for token in ("account entitlement", "account feed"))
    if live and not delayed:
        return "LIVE"
    if account and not delayed:
        return "ACCOUNT"
    if delayed or text.strip():
        return "RESEARCH"
    return "UNAVAILABLE"


def _contract_grade(row: dict[str, Any]) -> str:
    bid = _number(row.get("bid"))
    ask = _number(row.get("ask"))
    spread = _number(row.get("spread_pct"), (ask - bid) / ask if ask > 0 and bid > 0 else 99.0)
    volume = int(_number(row.get("volume")))
    oi = int(_number(row.get("open_interest")))
    delta = abs(_number(row.get("delta")))
    if bid <= 0 or ask <= bid or spread > 0.15:
        return "F"
    if spread <= 0.06 and volume >= 1000 and oi >= 500 and 0.30 <= delta <= 0.60:
        return "A"
    if spread <= 0.10 and volume >= 300 and oi >= 100 and 0.25 <= delta <= 0.65:
        return "B"
    return "C"


def select_contract_evidence(
    rows: Iterable[dict[str, Any]],
    *,
    symbol: str,
    bias: str,
) -> ContractEvidence:
    wanted = _side_for_bias(bias)
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _text(row.get("symbol")).upper() != symbol.upper():
            continue
        side = _text(row.get("option_type") or row.get("direction")).lower()
        if wanted and side not in {wanted, wanted.upper().lower()}:
            continue
        candidates.append(row)

    if not candidates:
        return ContractEvidence(
            False, "", wanted, 0.0, "", 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0,
            "UNAVAILABLE", "N/A", "N/A", False, "", "", "لا توجد بيانات عقد متوافقة مع اتجاه الفكرة",
        )

    def rank(row: dict[str, Any]) -> tuple[int, float, float, float]:
        grade = _contract_grade(row)
        grade_rank = {"A": 4, "B": 3, "C": 2, "F": 0}.get(grade, 1)
        score = _number(row.get("score"))
        volume = _number(row.get("volume"))
        spread = _number(row.get("spread_pct"), 1.0)
        return grade_rank, score, volume, -spread

    row = max(candidates, key=rank)
    bid = _number(row.get("bid"))
    ask = _number(row.get("ask"))
    spread = _number(row.get("spread_pct"), (ask - bid) / ask if ask > 0 and bid > 0 else 0.0)
    confidence = data_confidence(row)
    grade = _contract_grade(row)
    flow_grade = _text(row.get("evidence_grade") or row.get("flow_evidence_grade") or "N/A").upper()
    execution_ready = confidence in {"LIVE", "ACCOUNT"} and grade in {"A", "B"}
    reason = (
        "سعر عقد صالح للتنفيذ اليدوي بعد التحقق من منصة الوسيط"
        if execution_ready
        else "العقد بحثي/متأخر أو جودته غير كافية؛ لا يستخدم كسعر تنفيذ"
    )
    return ContractEvidence(
        True,
        _text(row.get("contract_symbol")),
        wanted,
        _number(row.get("strike")),
        _text(row.get("expiration"))[:10],
        bid,
        ask,
        spread,
        int(_number(row.get("volume"))),
        int(_number(row.get("open_interest"))),
        _number(row.get("delta")),
        _number(row.get("iv")),
        confidence,
        grade,
        flow_grade,
        execution_ready,
        _text(row.get("source") or row.get("provider")),
        _text(row.get("freshness_label")),
        reason,
    )


@dataclass(frozen=True)
class UnifiedThesis:
    symbol: str
    bias: str
    stage: str
    overall_grade: str
    chart_grade: str
    catalyst_grade: str
    timing_grade: str
    contract_grade: str
    flow_grade: str
    data_confidence: str
    manual_execution_ready: bool
    trigger: float | None
    invalidation: float | None
    price: float
    catalyst_headline: str
    catalyst_source: str
    catalyst_url: str
    chart_decision: str
    chart_agreement_pct: int
    daily_direction: str
    hourly_direction: str
    intraday_direction: str
    reaction: CatalystReaction
    contract: ContractEvidence
    why_now: tuple[str, ...]
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reaction"] = self.reaction.as_dict()
        payload["contract"] = self.contract.as_dict()
        return payload


def build_thesis(
    *,
    market_row: dict[str, Any],
    catalyst: dict[str, Any],
    source_evidence: dict[str, Any],
    classical: dict[str, Any] | None,
    option_rows: Iterable[dict[str, Any]] = (),
) -> UnifiedThesis:
    symbol = _text(market_row.get("symbol")).upper()
    bias = _bias_from_catalyst(catalyst)
    chart_direction = _classical_direction(classical)
    chart_grade = _chart_grade(classical, bias)
    catalyst_grade = _source_grade(source_evidence)
    reaction = classify_catalyst_reaction(market_row, bias)
    contract = select_contract_evidence(option_rows, symbol=symbol, bias=bias)

    blockers: list[str] = []
    why: list[str] = []
    if bias == NEUTRAL:
        blockers.append("المحفز بلا اتجاه واضح")
    if chart_direction != NEUTRAL and chart_direction != bias:
        blockers.append("التحليل متعدد الفريمات يعارض المحفز")
    if chart_direction == NEUTRAL:
        blockers.append("التحليل متعدد الفريمات لم يكتمل بعد")
    if reaction.state == "DIVERGING":
        blockers.append("السعر يتحرك عكس المحفز")
    if source_evidence.get("attention_only") is True:
        blockers.append("المصدر Attention-only ولا يثبت سبب الحركة")

    if chart_direction == bias:
        why.append(f"توافق 1D/1H/15m بنسبة {int(_number((classical or {}).get('agreement_pct')))}%")
    why.append(reaction.reason)
    why.append(f"المحفز بدرجة مصدر {catalyst_grade}")
    if contract.available:
        why.append(f"جودة العقد {contract.contract_grade} وبيانات {contract.data_confidence}")

    if blockers and any("يعارض" in item or "عكس" in item or "Attention" in item for item in blockers):
        stage = "FAILED"
    elif reaction.state == "EXTENDED":
        stage = "EXTENDED"
    elif chart_direction == bias and chart_grade in {"A+", "A", "B"} and catalyst_grade in {"A+", "A", "B+", "B"} and reaction.state == "CONFIRMING":
        stage = "CONFIRMED"
    elif chart_direction == bias or reaction.state in {"BUILDING", "CONFIRMING"}:
        stage = "BUILDING"
    else:
        stage = "WATCH"

    # Evidence grade is categorical, not a probability. Execution readiness is separate.
    if stage == "CONFIRMED" and chart_grade in {"A+", "A"} and catalyst_grade in {"A+", "A"} and reaction.grade in {"A", "B+"}:
        overall = "A+" if contract.contract_grade == "A" and contract.data_confidence in {"LIVE", "ACCOUNT"} else "A"
    elif stage == "CONFIRMED":
        overall = "B+"
    elif stage == "BUILDING":
        overall = "B"
    elif stage == "FAILED":
        overall = "F"
    else:
        overall = "C"

    manual_ready = stage == "CONFIRMED" and contract.execution_ready and overall in {"A+", "A", "B+"}
    trigger = _number((classical or {}).get("confirmation_level")) or None
    invalidation = _number((classical or {}).get("invalidation_level")) or _number(market_row.get("invalidation")) or None
    daily = _text(((classical or {}).get("daily") or {}).get("direction") or "N/A")
    hourly = _text(((classical or {}).get("hourly") or {}).get("direction") or "N/A")
    intraday = _text(((classical or {}).get("intraday") or {}).get("direction") or "N/A")

    return UnifiedThesis(
        symbol=symbol,
        bias=bias,
        stage=stage,
        overall_grade=overall,
        chart_grade=chart_grade,
        catalyst_grade=catalyst_grade,
        timing_grade=reaction.grade,
        contract_grade=contract.contract_grade,
        flow_grade=contract.flow_grade,
        data_confidence=contract.data_confidence,
        manual_execution_ready=manual_ready,
        trigger=trigger,
        invalidation=invalidation,
        price=_number(market_row.get("price")),
        catalyst_headline=_text(catalyst.get("headline") or catalyst.get("category")),
        catalyst_source=_text(catalyst.get("source")),
        catalyst_url=_text(catalyst.get("url")),
        chart_decision=_text((classical or {}).get("decision") or "WAIT"),
        chart_agreement_pct=int(round(_number((classical or {}).get("agreement_pct")))),
        daily_direction=daily,
        hourly_direction=hourly,
        intraday_direction=intraday,
        reaction=reaction,
        contract=contract,
        why_now=tuple(why[:5]),
        blockers=tuple(blockers[:5]),
    )
