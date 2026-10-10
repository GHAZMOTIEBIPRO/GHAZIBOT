from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

_SHARE_CONCEPT = "EntityCommonStockSharesOutstanding"
_DILUTION_FORMS = {
    "S-1",
    "S-1/A",
    "S-3",
    "S-3/A",
    "F-1",
    "F-1/A",
    "F-3",
    "F-3/A",
    "424B3",
    "424B5",
    "424B7",
    "EFFECT",
}
_ACTIVE_FINANCING_TOKENS = (
    "at-the-market",
    "atm offering",
    "equity distribution agreement",
    "registered direct",
    "public offering",
    "underwritten offering",
    "warrant",
    "convertible",
)
_REVERSE_SPLIT_TOKENS = ("reverse split", "reverse stock split")
_SHARE_PATTERNS = (
    re.compile(
        r"(?:warrants?\s+(?:to\s+purchase|exercisable\s+for)|convertible\s+into|"
        r"issuable\s+upon\s+(?:exercise|conversion)\s+of)[^0-9]{0,80}"
        r"([0-9][0-9,]*(?:\.[0-9]+)?)\s+(?:shares?|common shares?|ordinary shares?)",
        re.I,
    ),
    re.compile(
        r"up\s+to\s+([0-9][0-9,]*(?:\.[0-9]+)?)\s+"
        r"(?:shares?|common shares?|ordinary shares?)",
        re.I,
    ),
)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _parse_date(value: Any) -> date | None:
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _as_of_date(value: date | datetime | None) -> date:
    if value is None:
        return datetime.now(timezone.utc).date()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("as_of datetime must be timezone-aware")
        return value.astimezone(timezone.utc).date()
    return value


def _shares_rows(company_facts: dict[str, Any], *, as_of: date) -> list[dict[str, Any]]:
    facts = company_facts.get("facts") if isinstance(company_facts, dict) else {}
    dei = facts.get("dei") if isinstance(facts, dict) else {}
    concept = dei.get(_SHARE_CONCEPT) if isinstance(dei, dict) else {}
    units = concept.get("units") if isinstance(concept, dict) else {}
    rows = units.get("shares") if isinstance(units, dict) else []
    output: list[dict[str, Any]] = []
    for raw in rows if isinstance(rows, list) else []:
        if not isinstance(raw, dict):
            continue
        value = _number(raw.get("val"), float("nan"))
        end = _parse_date(raw.get("end"))
        filed = _parse_date(raw.get("filed"))
        if not math.isfinite(value) or value <= 0 or end is None or filed is None:
            continue
        # Point-in-time guard: a fact can only be used after it was filed.
        if filed > as_of:
            continue
        output.append(
            {
                "value": float(value),
                "end": end,
                "filed": filed,
                "form": str(raw.get("form") or ""),
                "frame": str(raw.get("frame") or ""),
            }
        )
    output.sort(key=lambda row: (row["end"], row["filed"], row["value"]))
    return output


def _latest_unique_share_points(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_end: dict[date, dict[str, Any]] = {}
    for row in rows:
        previous = by_end.get(row["end"])
        if previous is None or row["filed"] >= previous["filed"]:
            by_end[row["end"]] = row
    return [by_end[key] for key in sorted(by_end)]


def _baseline_for_horizon(
    points: list[dict[str, Any]],
    *,
    latest_end: date,
    horizon_days: int,
) -> dict[str, Any] | None:
    target = latest_end - timedelta(days=horizon_days)
    older = [row for row in points if row["end"] <= target]
    return older[-1] if older else None


def _growth_pct(latest: float, baseline: float) -> float | None:
    if latest <= 0 or baseline <= 0:
        return None
    return (latest / baseline - 1.0) * 100.0


def share_count_history(
    company_facts: dict[str, Any],
    *,
    as_of: date | datetime | None = None,
) -> dict[str, Any]:
    """Extract point-in-time common-share history from official SEC Company Facts.

    Only the DEI EntityCommonStockSharesOutstanding concept is used. Weighted-
    average diluted shares are intentionally not substituted because they are not
    the same legal/economic quantity.
    """

    cutoff = _as_of_date(as_of)
    points = _latest_unique_share_points(_shares_rows(company_facts, as_of=cutoff))
    if not points:
        return {
            "available": False,
            "source": "SEC Company Facts / DEI EntityCommonStockSharesOutstanding",
            "as_of": cutoff.isoformat(),
            "point_count": 0,
            "growth_pct": {"30d": None, "90d": None, "365d": None},
        }

    latest = points[-1]
    growth: dict[str, float | None] = {}
    baselines: dict[str, dict[str, Any] | None] = {}
    for label, days in (("30d", 30), ("90d", 90), ("365d", 365)):
        baseline = _baseline_for_horizon(
            points,
            latest_end=latest["end"],
            horizon_days=days,
        )
        baselines[label] = baseline
        value = _growth_pct(latest["value"], baseline["value"]) if baseline else None
        growth[label] = round(value, 4) if value is not None else None

    return {
        "available": True,
        "source": "SEC Company Facts / DEI EntityCommonStockSharesOutstanding",
        "as_of": cutoff.isoformat(),
        "latest_shares": round(latest["value"], 4),
        "latest_period_end": latest["end"].isoformat(),
        "latest_filed_at": latest["filed"].isoformat(),
        "latest_form": latest["form"],
        "point_count": len(points),
        "growth_pct": growth,
        "baseline_periods": {
            label: (
                {
                    "shares": round(row["value"], 4),
                    "period_end": row["end"].isoformat(),
                    "filed_at": row["filed"].isoformat(),
                    "form": row["form"],
                }
                if row
                else None
            )
            for label, row in baselines.items()
        },
        "split_adjusted": False,
        "warning": (
            "Share-count changes are observed reported values and are not adjusted "
            "for stock splits. Positive growth is treated as dilution-risk evidence; "
            "share-count decreases never create a bullish reward."
        ),
    }


def _event_text(event: dict[str, Any]) -> str:
    return re.sub(
        r"\s+",
        " ",
        " ".join(
            str(event.get(key) or "")
            for key in (
                "form",
                "purpose",
                "category",
                "category_normalized",
                "headline",
                "evidence",
            )
        ).lower(),
    ).strip()


def explicit_share_overhang(events: list[dict[str, Any]]) -> dict[str, Any]:
    counts: list[float] = []
    sources: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        text = _event_text(event)
        for pattern in _SHARE_PATTERNS:
            for match in pattern.finditer(text):
                value = _number(match.group(1).replace(",", ""))
                if value > 0:
                    counts.append(value)
                    sources.append(str(event.get("form") or event.get("purpose") or "filing"))
    return {
        "available": bool(counts),
        "maximum_explicit_shares": round(max(counts), 4) if counts else None,
        "matched_values": [round(value, 4) for value in sorted(set(counts), reverse=True)[:8]],
        "source_labels": list(dict.fromkeys(sources))[:8],
        "note": (
            "Only explicit share counts found in filing-derived evidence are used. "
            "Dollar financing amounts are never converted into shares without an explicit price."
        ),
    }


def financing_overhang(
    events: list[dict[str, Any]],
    *,
    market_cap: float,
    float_shares: float,
) -> dict[str, Any]:
    relevant: list[dict[str, Any]] = []
    maximum_dollars = 0.0
    active_financing = False
    reverse_split = False

    for event in events:
        if not isinstance(event, dict):
            continue
        form = str(event.get("form") or "").upper()
        text = _event_text(event)
        purpose = str(event.get("purpose") or "").lower()
        category = str(
            event.get("category_normalized") or event.get("category") or ""
        ).upper()
        is_financing = (
            form in _DILUTION_FORMS
            or purpose == "dilution"
            or "DILUTION" in category
            or any(token in text for token in _ACTIVE_FINANCING_TOKENS)
        )
        if not is_financing and not any(token in text for token in _REVERSE_SPLIT_TOKENS):
            continue

        value = max(0.0, _number(event.get("event_value")))
        maximum_dollars = max(maximum_dollars, value)
        active_financing = active_financing or any(
            token in text for token in _ACTIVE_FINANCING_TOKENS
        )
        reverse_split = reverse_split or any(
            token in text for token in _REVERSE_SPLIT_TOKENS
        )
        relevant.append(
            {
                "form": form,
                "purpose": purpose,
                "category": str(
                    event.get("category_normalized") or event.get("category") or ""
                ),
                "event_date": str(event.get("event_date") or ""),
                "event_value": value or None,
                "source": str(event.get("source") or ""),
                "url": str(event.get("url") or ""),
            }
        )

    shares = explicit_share_overhang(events)
    overhang_shares = _number(shares.get("maximum_explicit_shares"))
    return {
        "event_count": len(relevant),
        "active_financing_context": active_financing,
        "reverse_split_context": reverse_split,
        "announced_financing_capacity_usd": round(maximum_dollars, 2)
        if maximum_dollars > 0
        else None,
        "announced_capacity_to_market_cap": round(maximum_dollars / market_cap, 4)
        if maximum_dollars > 0 and market_cap > 0
        else None,
        "explicit_share_overhang": shares,
        "explicit_overhang_to_float": round(overhang_shares / float_shares, 4)
        if overhang_shares > 0 and float_shares > 0
        else None,
        "events": relevant[:12],
        "remaining_capacity_verified": False,
        "remaining_capacity_note": (
            "A filing's announced maximum amount is not treated as remaining capacity "
            "unless a filing-derived field explicitly proves the remaining amount."
        ),
    }


@dataclass(frozen=True)
class SecDilutionAssessment:
    risk_score: float
    risk_label: str
    share_growth_risk: float
    financing_risk: float
    overhang_risk: float
    reverse_split_risk: float
    confidence: float
    share_history: dict[str, Any]
    financing: dict[str, Any]
    reasons: tuple[str, ...]
    research_only: bool = True
    decision_authority: bool = False
    score_is_probability: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


def _growth_risk(history: dict[str, Any]) -> tuple[float, list[str]]:
    growth = history.get("growth_pct") if isinstance(history, dict) else {}
    growth = growth if isinstance(growth, dict) else {}
    risk = 0.0
    reasons: list[str] = []
    for label, value in growth.items():
        number = _number(value, float("nan"))
        if not math.isfinite(number) or number <= 0:
            continue
        if label == "30d":
            component = 42 if number >= 25 else 30 if number >= 10 else 15 if number >= 5 else 0
        elif label == "90d":
            component = 38 if number >= 50 else 28 if number >= 20 else 15 if number >= 10 else 0
        else:
            component = 34 if number >= 100 else 24 if number >= 50 else 12 if number >= 20 else 0
        risk = max(risk, float(component))
        if component:
            reasons.append(f"reported shares +{number:.1f}% over {label}")
    return risk, reasons


def assess_sec_dilution(
    company_facts: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    market_cap: float,
    float_shares: float,
    as_of: date | datetime | None = None,
) -> SecDilutionAssessment:
    history = share_count_history(company_facts, as_of=as_of)
    financing = financing_overhang(
        events,
        market_cap=market_cap,
        float_shares=float_shares,
    )

    share_risk, reasons = _growth_risk(history)

    capacity_ratio = _number(financing.get("announced_capacity_to_market_cap"))
    if capacity_ratio >= 1.0:
        financing_risk = 38.0
    elif capacity_ratio >= 0.50:
        financing_risk = 30.0
    elif capacity_ratio >= 0.25:
        financing_risk = 22.0
    elif capacity_ratio > 0:
        financing_risk = 12.0
    elif financing.get("active_financing_context"):
        financing_risk = 16.0
    else:
        financing_risk = 0.0

    if capacity_ratio > 0:
        reasons.append(f"announced financing / market cap {capacity_ratio:.0%}")
    elif financing.get("active_financing_context"):
        reasons.append("active financing/dilution filing context")

    overhang_ratio = _number(financing.get("explicit_overhang_to_float"))
    if overhang_ratio >= 1.0:
        overhang_risk = 38.0
    elif overhang_ratio >= 0.50:
        overhang_risk = 30.0
    elif overhang_ratio >= 0.25:
        overhang_risk = 20.0
    elif overhang_ratio > 0:
        overhang_risk = 10.0
    else:
        overhang_risk = 0.0
    if overhang_ratio > 0:
        reasons.append(f"explicit issuable-share overhang / float {overhang_ratio:.0%}")

    reverse_risk = 14.0 if financing.get("reverse_split_context") else 0.0
    if reverse_risk:
        reasons.append("recent reverse-split context")

    # Independent risk dimensions combine additively but are capped. This is a
    # research severity index, never a probability of dilution or price decline.
    score = _clamp(share_risk + financing_risk + overhang_risk + reverse_risk)

    evidence_dimensions = sum(
        (
            history.get("available") is True,
            financing.get("event_count", 0) > 0,
            capacity_ratio > 0,
            overhang_ratio > 0,
        )
    )
    confidence = _clamp(35.0 + evidence_dimensions * 15.0)
    label = "HIGH" if score >= 70 else "ELEVATED" if score >= 45 else "MODERATE" if score >= 20 else "LOW"

    return SecDilutionAssessment(
        risk_score=round(score, 2),
        risk_label=label,
        share_growth_risk=round(share_risk, 2),
        financing_risk=round(financing_risk, 2),
        overhang_risk=round(overhang_risk, 2),
        reverse_split_risk=round(reverse_risk, 2),
        confidence=round(confidence, 2),
        share_history=history,
        financing=financing,
        reasons=tuple(reasons),
    )
