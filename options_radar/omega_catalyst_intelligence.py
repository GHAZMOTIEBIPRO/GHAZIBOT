from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Iterable

PRIMARY_SOURCE_MARKERS = ("sec", "edgar", "fda", "drugs@fda", "clinicaltrials", "company ir", "investor relations")
LICENSED_SOURCE_MARKERS = ("polygon", "massive", "tradier", "benzinga", "finnhub", "tiingo", "alpaca")
SECONDARY_SOURCE_MARKERS = ("yahoo", "finviz", "reuters", "news")

DILUTION_FORMS = {"S-1", "S-1/A", "S-3", "S-3/A", "F-1", "F-3", "424B3", "424B4", "424B5"}
OWNERSHIP_FORMS = {"SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"}
FORM4_FORMS = {"4", "4/A"}

CATEGORY_RULES: tuple[tuple[str, tuple[str, ...], str, int], ...] = (
    ("FDA_APPROVAL", ("fda approval", "approved by the fda", "approval record", "submission_status:\"ap\""), "bullish", 95),
    ("FDA_CRL", ("complete response letter", " crl ", "received a crl"), "bearish", 95),
    ("FDA_HOLD_LIFTED", ("clinical hold lifted", "lifted the clinical hold"), "bullish", 88),
    ("FDA_BREAKTHROUGH", ("breakthrough therapy designation",), "bullish", 78),
    ("FDA_FAST_TRACK", ("fast track designation",), "bullish", 70),
    ("FDA_ORPHAN_DRUG", ("orphan drug designation",), "bullish", 62),
    ("FDA_PRIORITY_REVIEW", ("priority review",), "bullish", 74),
    ("FDA_RMAT", ("regenerative medicine advanced therapy", "rmat designation"), "bullish", 74),
    ("FDA_PDUFA", ("pdufa date", "prescription drug user fee act date"), "mixed", 66),
    ("FDA_CLINICAL_HOLD", ("clinical hold", "placed on clinical hold"), "bearish", 90),
    ("TRIAL_POSITIVE", ("met its primary endpoint", "met the primary endpoint", "positive topline", "positive top-line"), "bullish", 86),
    ("TRIAL_FAILED", ("failed to meet", "did not meet the primary endpoint", "missed the primary endpoint"), "bearish", 92),
    ("MERGER_TERMINATED", ("termination of the merger agreement", "terminated merger", "merger terminated"), "bearish", 94),
    ("MERGER_DEFINITIVE", ("definitive merger agreement", "entered into a merger agreement", "merger agreement"), "bullish", 92),
    ("TENDER_OFFER", ("tender offer",), "bullish", 88),
    ("ACQUISITION", ("to acquire", "acquisition of", "acquire all outstanding"), "bullish", 82),
    ("MATERIAL_CONTRACT", ("material definitive agreement", "major customer", "government contract", "contract award", "multi-year contract"), "mixed", 76),
    ("PARTNERSHIP", ("strategic partnership", "collaboration agreement", "license agreement", "licensing agreement", "joint venture"), "mixed", 72),
    ("BUYBACK", ("share repurchase", "stock repurchase", "repurchase program"), "bullish", 72),
    ("DIVIDEND", ("special dividend", "declared a dividend", "dividend increase"), "bullish", 62),
    ("GUIDANCE_RAISE", ("raises guidance", "raised guidance", "increases outlook"), "bullish", 72),
    ("GUIDANCE_CUT", ("cuts guidance", "lowered guidance", "reduces outlook"), "bearish", 82),
    ("DEBT_REFINANCING", ("debt refinancing", "refinanced", "credit facility"), "mixed", 58),
    ("ATM", ("at-the-market offering", "at the market offering", "sales agreement"), "bearish", 92),
    ("REGISTERED_DIRECT", ("registered direct offering",), "bearish", 94),
    ("PUBLIC_OFFERING", ("public offering", "underwritten offering"), "bearish", 90),
    ("CONVERTIBLE_FINANCING", ("convertible notes", "convertible senior notes", "convertible financing"), "bearish", 78),
    ("WARRANT_OVERHANG", ("warrant exercise", "warrants to purchase"), "bearish", 70),
    ("REVERSE_SPLIT", ("reverse stock split",), "bearish", 80),
    ("GOING_CONCERN", ("going concern",), "bearish", 90),
    ("DELISTING", ("delisting notice", "noncompliance notice", "minimum bid price"), "bearish", 88),
    ("BANKRUPTCY", ("bankruptcy", "chapter 11", "chapter 7"), "bearish", 98),
)

NOISE_TOKENS = {
    "inc", "corp", "corporation", "company", "co", "ltd", "limited", "plc", "holdings",
    "announces", "reports", "update", "updates", "the", "and", "for", "with", "from",
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numeric):
        return default
    return numeric


def _source_reliability(source: str) -> int:
    lowered = str(source or "").lower()
    if any(marker in lowered for marker in PRIMARY_SOURCE_MARKERS):
        return 100
    if any(marker in lowered for marker in LICENSED_SOURCE_MARKERS):
        return 82
    if any(marker in lowered for marker in SECONDARY_SOURCE_MARKERS):
        return 55
    return 62


def _freshness_score(value: Any, today: date | None = None) -> tuple[int, int | None]:
    today = today or datetime.now(timezone.utc).date()
    text = str(value or "")[:10]
    try:
        event_date = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return 35, None
    age = max(0, (today - event_date).days)
    if age <= 1:
        return 100, age
    if age <= 3:
        return 92, age
    if age <= 7:
        return 80, age
    if age <= 14:
        return 62, age
    if age <= 30:
        return 42, age
    return 20, age


def _clean_tokens(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return {token for token in tokens if len(token) > 2 and token not in NOISE_TOKENS}


def _event_text(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in ("category", "headline", "evidence", "purpose", "form")
    ).lower()


def _form4_semantics(text: str) -> tuple[str, str, int, int]:
    compact = re.sub(r"\s+", "", text.lower())
    purchase = (
        "transactioncode>p<" in compact
        or "transactioncodep" in compact
        or "open-marketpurchase" in compact
        or "open market purchase" in text.lower()
    )
    sale = (
        "transactioncode>s<" in compact
        or "transactioncodes" in compact
        or "open-marketsale" in compact
        or "open market sale" in text.lower()
    )
    derivative = any(
        phrase in text.lower()
        for phrase in ("option exercise", "exercise of option", "grant", "award", "restricted stock", "automatic sale", "10b5-1")
    )
    if purchase and not derivative:
        return "INSIDER_OPEN_MARKET_PURCHASE", "bullish", 82, 12
    if sale:
        return "INSIDER_SALE", "bearish", 58, 0
    if derivative:
        return "INSIDER_DERIVATIVE_OR_GRANT", "neutral", 35, 0
    return "FORM4_UNVERIFIED", "neutral", 25, 0


def classify_catalyst_event(row: dict[str, Any]) -> dict[str, Any]:
    """Classify one event without treating a keyword as a profit probability."""

    form = str(row.get("form") or "").upper().strip()
    source = str(row.get("source") or "")
    text = _event_text(row)
    raw_score = _number(row.get("score"))
    confidence = _number(row.get("confidence"), 0.0)
    if confidence <= 0:
        confidence = _source_reliability(source) / 100.0

    category = "UNCLASSIFIED"
    directional_bias = "neutral"
    materiality = min(72, max(25, int(abs(raw_score) * 3)))
    dilution_risk = 0

    if form in FORM4_FORMS:
        category, directional_bias, materiality, dilution_risk = _form4_semantics(text)
    elif form in {"SC 13D", "SC 13D/A"}:
        category = "STRATEGIC_OWNERSHIP_13D"
        directional_bias = "mixed"
        materiality = 78
    elif form in {"SC 13G", "SC 13G/A"}:
        category = "PASSIVE_OWNERSHIP_13G"
        directional_bias = "neutral"
        materiality = 52
    elif form in DILUTION_FORMS:
        category = "DILUTION_REGISTRATION"
        directional_bias = "bearish"
        materiality = 80 if form.startswith(("S-", "F-")) else 90
        dilution_risk = 90 if form == "424B5" else 78

    for rule_category, patterns, bias, rule_materiality in CATEGORY_RULES:
        if any(pattern in f" {text} " for pattern in patterns):
            category = rule_category
            directional_bias = bias
            materiality = max(materiality, rule_materiality)
            if rule_category in {"ATM", "REGISTERED_DIRECT", "PUBLIC_OFFERING", "CONVERTIBLE_FINANCING", "WARRANT_OVERHANG"}:
                dilution_risk = max(dilution_risk, rule_materiality)
            break

    if raw_score < 0 and directional_bias == "neutral" and category not in {"INSIDER_DERIVATIVE_OR_GRANT", "FORM4_UNVERIFIED"}:
        directional_bias = "bearish"
    elif raw_score > 0 and directional_bias == "neutral" and category not in {
        "PASSIVE_OWNERSHIP_13G",
        "FORM4_UNVERIFIED",
        "INSIDER_DERIVATIVE_OR_GRANT",
    }:
        directional_bias = "mixed"

    reliability = _source_reliability(source)
    freshness, age_days = _freshness_score(row.get("event_date"))
    specificity = 90 if form not in {"", "NEWS"} else 58
    if category == "UNCLASSIFIED":
        specificity = min(specificity, 35)
    novelty = freshness
    economic_magnitude = materiality
    price_sensitivity = min(100, int(0.7 * materiality + 0.3 * abs(raw_score) * 4))
    confirmation_count = max(1, int(_number(row.get("confirmation_count"), 1)))
    confirmation_score = min(100, 52 + (confirmation_count - 1) * 16)
    already_priced_risk = 0

    quality_components = {
        "source_reliability": reliability,
        "event_materiality": materiality,
        "novelty": novelty,
        "freshness": freshness,
        "specificity": specificity,
        "economic_magnitude": economic_magnitude,
        "price_sensitivity": price_sensitivity,
        "dilution_risk": dilution_risk,
        "already_priced_in_risk": already_priced_risk,
        "confirmation_count": confirmation_count,
        "confirmation_score": confirmation_score,
    }
    positive_quality = (
        reliability * 0.20
        + materiality * 0.20
        + novelty * 0.12
        + freshness * 0.13
        + specificity * 0.12
        + economic_magnitude * 0.10
        + price_sensitivity * 0.08
        + confirmation_score * 0.05
    )
    catalyst_quality = max(0.0, min(100.0, positive_quality))

    return {
        **row,
        "raw_category": row.get("category"),
        "category": category,
        "category_normalized": category,
        "directional_bias": directional_bias,
        "materiality": materiality,
        "source_reliability": reliability,
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "dilution_risk": dilution_risk,
        "age_days": age_days,
        "quality_dimensions": quality_components,
        "catalyst_quality": round(catalyst_quality, 1),
        "quality_label": "RANKING_ONLY",
    }


def _similar_headline(left: str, right: str) -> float:
    a, b = _clean_tokens(left), _clean_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _parse_date(value: Any) -> date | None:
    try:
        return datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def cluster_catalyst_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate multi-source mentions into event clusters instead of score multiplication."""

    classified = [classify_catalyst_event(dict(event)) for event in events]
    classified.sort(
        key=lambda row: (
            str(row.get("symbol") or ""),
            -_number(row.get("catalyst_quality")),
            str(row.get("event_date") or ""),
        )
    )
    clusters: list[dict[str, Any]] = []
    for event in classified:
        symbol = str(event.get("symbol") or "").upper()
        category = str(event.get("category_normalized") or "UNCLASSIFIED")
        event_date = _parse_date(event.get("event_date"))
        match: dict[str, Any] | None = None
        for cluster in reversed(clusters):
            if cluster["symbol"] != symbol or cluster["category"] != category:
                continue
            cluster_date = _parse_date(cluster.get("event_date"))
            days_apart = abs((event_date - cluster_date).days) if event_date and cluster_date else 99
            similarity = _similar_headline(
                str(event.get("headline") or ""),
                str(cluster.get("headline") or ""),
            )
            if days_apart <= 2 and (similarity >= 0.28 or category != "UNCLASSIFIED"):
                match = cluster
                break
        if match is None:
            clusters.append(
                {
                    "cluster_id": f"{symbol}:{category}:{str(event.get('event_date') or '')}",
                    "symbol": symbol,
                    "category": category,
                    "directional_bias": event["directional_bias"],
                    "event_date": event.get("event_date"),
                    "headline": event.get("headline"),
                    "primary_source": event.get("source"),
                    "primary_url": event.get("url"),
                    "form": event.get("form"),
                    "catalyst_quality": event["catalyst_quality"],
                    "materiality": event["materiality"],
                    "dilution_risk": event["dilution_risk"],
                    "confidence": event["confidence"],
                    "confirmation_count": 1,
                    "confirmations": [event.get("source")],
                    "evidence": [event.get("evidence")] if event.get("evidence") else [],
                    "members": [event],
                }
            )
            continue
        match["members"].append(event)
        source = str(event.get("source") or "")
        if source and source not in match["confirmations"]:
            match["confirmations"].append(source)
        match["confirmation_count"] = len(match["confirmations"])
        if event["source_reliability"] > _source_reliability(str(match.get("primary_source") or "")):
            match["primary_source"] = event.get("source")
            match["primary_url"] = event.get("url")
            match["headline"] = event.get("headline")
            match["form"] = event.get("form")
        match["catalyst_quality"] = round(
            min(100.0, max(_number(match["catalyst_quality"]), _number(event["catalyst_quality"])) + min(8, (match["confirmation_count"] - 1) * 3)),
            1,
        )
        match["materiality"] = max(int(match["materiality"]), int(event["materiality"]))
        match["dilution_risk"] = max(int(match["dilution_risk"]), int(event["dilution_risk"]))
        if event.get("evidence") and event.get("evidence") not in match["evidence"]:
            match["evidence"].append(event.get("evidence"))

    for cluster in clusters:
        cluster["confirmations"] = [value for value in cluster["confirmations"] if value]
        cluster["members_count"] = len(cluster["members"])
    return clusters


def _stock_lookup(stocks: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("symbol") or "").upper(): row
        for row in stocks
        if str(row.get("symbol") or "").strip()
    }


def _reaction_state(cluster: dict[str, Any], stock: dict[str, Any] | None) -> tuple[str, int, list[str]]:
    if not stock:
        return "UNKNOWN", 45, ["No current market-reaction record in payload"]
    gap = _number(stock.get("gap_pct"))
    rvol = _number(stock.get("finviz_relative_volume"), _number(stock.get("relative_volume"), 1.0))
    distance = abs(_number(stock.get("distance_to_trigger_atr")))
    setup_side = str(stock.get("setup_side") or "").lower()
    bias = str(cluster.get("directional_bias") or "neutral")
    risks: list[str] = []
    if abs(gap) >= 12 or distance >= 1.8:
        risks.append("Price is extended versus the reference structure")
        return "EXTENDED_CHASING_RISK", 82, risks
    if bias == "bullish" and setup_side == "put":
        risks.append("Market reaction conflicts with positive catalyst")
        return "FAILED_REACTION", 75, risks
    if bias == "bearish" and setup_side == "call":
        risks.append("Market reaction conflicts with negative catalyst")
        return "FAILED_REACTION", 75, risks
    if rvol >= 1.5 or abs(gap) >= 2:
        return "REPRICING", 40, risks
    return "NOT_YET_REPRICED", 20, risks


def build_catalyst_intelligence(
    catalysts: Iterable[dict[str, Any]] | None,
    stocks: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    events = [dict(row) for row in (catalysts or []) if isinstance(row, dict)]
    stock_map = _stock_lookup(stocks or [])
    clusters = cluster_catalyst_events(events)
    by_symbol: dict[str, dict[str, Any]] = {}
    for cluster in clusters:
        symbol = cluster["symbol"]
        reaction, chase_penalty, reaction_risks = _reaction_state(cluster, stock_map.get(symbol))
        cluster["reaction_state"] = reaction
        cluster["catalyst_chase_penalty"] = chase_penalty
        cluster["already_priced_in_risk"] = chase_penalty
        why_move = [
            f"Materiality {cluster['materiality']}/100",
            f"Primary source: {cluster.get('primary_source') or 'unknown'}",
        ]
        if cluster["confirmation_count"] > 1:
            why_move.append(f"{cluster['confirmation_count']} independent source labels observed")
        why_fail = list(reaction_risks)
        if cluster["dilution_risk"] >= 60:
            why_fail.append(f"Dilution/financing overhang {cluster['dilution_risk']}/100")
        if reaction == "EXTENDED_CHASING_RISK":
            why_fail.append("Good catalyst does not justify chasing an extended price")
        cluster["why_it_may_move"] = why_move
        cluster["why_it_may_fail"] = why_fail or ["Directional outcome remains ambiguous until price/liquidity confirm"]
        cluster["causal_firewall"] = {
            "catalyst_quality": cluster["catalyst_quality"],
            "directional_setup": str(stock_map.get(symbol, {}).get("setup_side") or "unknown"),
            "probability_of_profit": None,
            "status": "RANKING_ONLY",
        }
        existing = by_symbol.get(symbol)
        if existing is None or _number(cluster["catalyst_quality"]) > _number(existing["catalyst_quality"]):
            by_symbol[symbol] = cluster

    dilution_symbols = sorted(
        {
            cluster["symbol"]
            for cluster in clusters
            if _number(cluster.get("dilution_risk")) >= 60
        }
    )
    return {
        "research_status": "RANKING_ONLY",
        "probability_calibrated": False,
        "events_received": len(events),
        "event_clusters": len(clusters),
        "duplicates_collapsed": max(0, len(events) - len(clusters)),
        "dilution_flagged_symbols": dilution_symbols,
        "clusters": clusters,
        "by_symbol": by_symbol,
    }
