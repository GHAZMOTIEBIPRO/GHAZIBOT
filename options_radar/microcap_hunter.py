from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

_DILUTION_TERMS = (
    "at-the-market",
    "atm offering",
    "registered direct",
    "public offering",
    "underwritten offering",
    "shelf",
    "s-3",
    "s-1",
    "424b5",
    "424b3",
    "effect",
    "warrant",
    "convertible",
)
_REVERSE_SPLIT_TERMS = ("reverse split", "reverse stock split")
_PROPOSED_SALE_TERMS = (
    "form 144",
    "proposed affiliate sale",
    "proposed sale notice",
)
_MATERIAL_CATALYST_TERMS = (
    "fda",
    "approval",
    "approved",
    "positive results",
    "phase 2",
    "phase 3",
    "contract",
    "award",
    "acquisition",
    "merger",
    "patent",
    "raised guidance",
    "raises guidance",
    "strategic partnership",
)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _official_sec_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in {"sec.gov", "www.sec.gov"}
        and parsed.username is None
        and parsed.password is None
        and parsed.port in (None, 443)
        and parsed.path.startswith(("/Archives/", "/ixviewer/"))
    )


def _text(row: dict[str, Any]) -> str:
    values = (
        row.get("news_headline"),
        row.get("catalyst_headline"),
        row.get("catalyst_event_type"),
        row.get("entry_cause_status"),
        row.get("cause_category"),
    )
    return re.sub(r"\s+", " ", " ".join(str(value or "") for value in values).lower()).strip()


def _float_score(float_shares: float) -> float:
    if float_shares <= 0:
        return 20.0
    if float_shares <= 1_000_000:
        return 100.0
    if float_shares <= 3_000_000:
        return 96.0
    if float_shares <= 10_000_000:
        return 86.0
    if float_shares <= 25_000_000:
        return 58.0
    return 15.0


def _rvol_score(rvol: float) -> float:
    if rvol <= 0:
        return 10.0
    if rvol >= 8:
        return 100.0
    if rvol >= 5:
        return 92.0
    if rvol >= 3:
        return 80.0
    if rvol >= 2:
        return 66.0
    if rvol >= 1.3:
        return 48.0
    return 20.0


def _liquidity_score(dollar_volume: float) -> float:
    if dollar_volume >= 10_000_000:
        return 100.0
    if dollar_volume >= 5_000_000:
        return 92.0
    if dollar_volume >= 1_000_000:
        return 78.0
    if dollar_volume >= 250_000:
        return 60.0
    if dollar_volume >= 100_000:
        return 38.0
    return 12.0


def _market_cap_score(market_cap: float) -> float:
    if market_cap <= 0:
        return 30.0
    if market_cap <= 30_000_000:
        return 100.0
    if market_cap <= 100_000_000:
        return 90.0
    if market_cap <= 300_000_000:
        return 76.0
    if market_cap <= 1_000_000_000:
        return 58.0
    if market_cap <= 2_000_000_000:
        return 35.0
    return 10.0


def _earlyness_score(day_move_pct: float) -> float:
    if day_move_pct < -8:
        return 8.0
    if day_move_pct < -2:
        return 28.0
    if day_move_pct < 1:
        return 58.0
    if day_move_pct <= 6:
        return 100.0
    if day_move_pct <= 12:
        return 88.0
    if day_move_pct <= 20:
        return 66.0
    if day_move_pct <= 35:
        return 32.0
    return 5.0


@dataclass(frozen=True)
class MicrocapAssessment:
    symbol: str
    score: float
    stage: str
    risk_penalty: float
    float_score: float
    rvol_score: float
    liquidity_score: float
    market_cap_score: float
    earlyness_score: float
    supply_score: float
    catalyst_score: float
    dilution_context: bool
    reverse_split_context: bool
    official_sec_catalyst: bool
    flags: tuple[str, ...]
    reasons: tuple[str, ...]
    research_only: bool = True
    decision_authority: bool = False
    score_is_probability: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["flags"] = list(self.flags)
        payload["reasons"] = list(self.reasons)
        return payload


def assess_microcap_candidate(row: dict[str, Any]) -> MicrocapAssessment:
    """Rank small-cap explosion evidence without promoting it to trading authority.

    This is an independent implementation inspired by public MIT-licensed
    micro-cap scanners and SEC dilution tools. It uses existing GHAZIBOT
    evidence and deliberately avoids third-party float/news scraping.
    """

    symbol = str(row.get("symbol") or "").upper().strip()
    price = _number(row.get("price"))
    market_cap = _number(row.get("market_cap"))
    float_shares = _number(row.get("float_shares"))
    rvol = _number(row.get("rvol"))
    dollar_volume = _number(row.get("dollar_volume"))
    move = _number(row.get("day_move_pct"), _number(row.get("move_pct")))
    supply = _clamp(_number(row.get("supply_score"), 45.0))
    catalyst = _clamp(
        _number(row.get("catalyst_score"), _number(row.get("news_score"), 0.0))
    )
    sec_dilution = (
        row.get("sec_dilution_v2")
        if isinstance(row.get("sec_dilution_v2"), dict)
        else {}
    )
    sec_dilution_risk = _clamp(_number(sec_dilution.get("risk_score")))
    dilution_risk = max(
        _clamp(_number(row.get("dilution_risk"))),
        sec_dilution_risk,
    )
    official_sec = _official_sec_url(row.get("official_catalyst_url"))

    text = _text(row)
    dilution_context = dilution_risk >= 45 or any(term in text for term in _DILUTION_TERMS)
    reverse_split_context = any(term in text for term in _REVERSE_SPLIT_TERMS)
    proposed_sale_context = any(term in text for term in _PROPOSED_SALE_TERMS)
    material_text = any(term in text for term in _MATERIAL_CATALYST_TERMS)

    float_component = _float_score(float_shares)
    rvol_component = _rvol_score(rvol)
    liquidity_component = _liquidity_score(dollar_volume)
    market_cap_component = _market_cap_score(market_cap)
    early_component = _earlyness_score(move)

    risk_penalty = 0.0
    flags: list[str] = []
    reasons: list[str] = []

    if price <= 0 or price > 30:
        flags.append("PRICE_OUTSIDE_MICROCAP_PROFILE")
        risk_penalty += 10.0

    if float_shares <= 0:
        flags.append("FLOAT_UNVERIFIED")
        risk_penalty += 8.0
    elif float_shares > 25_000_000:
        flags.append("FLOAT_TOO_LARGE_FOR_MICROCAP_HUNTER")
        risk_penalty += 20.0
    elif float_shares <= 10_000_000:
        reasons.append(f"float {float_shares / 1_000_000:.2f}M")

    if rvol < 2.0:
        flags.append("RVOL_BELOW_2")
    else:
        reasons.append(f"RVOL {rvol:.2f}x")

    if dollar_volume < 250_000:
        flags.append("DOLLAR_LIQUIDITY_BELOW_250K")
        risk_penalty += 10.0
    else:
        reasons.append(f"dollar volume USD {dollar_volume:,.0f}")

    if market_cap > 1_000_000_000:
        flags.append("MARKET_CAP_ABOVE_1B")
        risk_penalty += 12.0
    elif 0 < market_cap <= 300_000_000:
        reasons.append(f"market cap USD {market_cap / 1_000_000:.1f}M")

    if move >= 35:
        flags.append("CHASE_RISK")
        risk_penalty += min(28.0, 8.0 + (move - 35.0) * 0.9)
    elif -2 <= move <= 12:
        reasons.append("price still in early-move window")

    if reverse_split_context:
        flags.append("REVERSE_SPLIT_CONTEXT")
        risk_penalty += 12.0

    if proposed_sale_context:
        flags.append("FORM144_PROPOSED_SALE_CONTEXT")
        risk_penalty += 8.0
        reasons.append("SEC Form 144 proposed sale adds supply-risk context; execution not assumed")

    if dilution_context:
        flags.append("DILUTION_REVIEW")
        risk_penalty += 16.0
        if sec_dilution_risk >= 45:
            flags.append("SEC_DILUTION_V2_ELEVATED")
            reasons.extend(
                str(reason)
                for reason in (sec_dilution.get("reasons") or [])[:3]
                if str(reason).strip()
            )
        if dilution_risk >= 70:
            flags.append("HIGH_DILUTION_RISK")
            if sec_dilution_risk >= 70:
                flags.append("SEC_DILUTION_V2_HIGH")
            risk_penalty += 18.0

    if official_sec:
        reasons.append("official SEC catalyst provenance")
    if material_text:
        reasons.append("material catalyst language detected")

    raw_score = (
        float_component * 0.22
        + rvol_component * 0.20
        + liquidity_component * 0.15
        + early_component * 0.15
        + market_cap_component * 0.10
        + supply * 0.10
        + catalyst * 0.08
    )
    score = _clamp(raw_score - risk_penalty)

    hard_risk = "HIGH_DILUTION_RISK" in flags or (
        dilution_context and "DOLLAR_LIQUIDITY_BELOW_250K" in flags
    )
    if hard_risk:
        stage = "AVOID_RISK"
    elif score >= 78 and rvol >= 2.0 and dollar_volume >= 250_000 and float_shares > 0:
        stage = "PRIORITY"
    elif score >= 64:
        stage = "WATCH"
    else:
        stage = "RESEARCH"

    return MicrocapAssessment(
        symbol=symbol,
        score=round(score, 2),
        stage=stage,
        risk_penalty=round(risk_penalty, 2),
        float_score=round(float_component, 2),
        rvol_score=round(rvol_component, 2),
        liquidity_score=round(liquidity_component, 2),
        market_cap_score=round(market_cap_component, 2),
        earlyness_score=round(early_component, 2),
        supply_score=round(supply, 2),
        catalyst_score=round(catalyst, 2),
        dilution_context=dilution_context,
        reverse_split_context=reverse_split_context,
        official_sec_catalyst=official_sec,
        flags=tuple(flags),
        reasons=tuple(reasons),
    )
