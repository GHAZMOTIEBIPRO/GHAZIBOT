from __future__ import annotations

from typing import Any, Iterable

from .event_source_policy import cluster_evidence_summary, event_source_evidence
from .omega_catalyst_intelligence import build_catalyst_intelligence as _legacy_build


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _member_rank(member: dict[str, Any]) -> tuple[int, float, float]:
    evidence = event_source_evidence(member)
    return (
        int(evidence.get("source_rank", 0)),
        _number(member.get("catalyst_quality")),
        _number(member.get("materiality")),
    )


def _apply_cluster_policy(cluster: dict[str, Any]) -> dict[str, Any]:
    members = [dict(row) for row in cluster.get("members", []) if isinstance(row, dict)]
    enriched_members: list[dict[str, Any]] = []
    for member in members:
        enriched_members.append({**member, **event_source_evidence(member)})
    cluster["members"] = enriched_members

    evidence = cluster_evidence_summary(enriched_members)
    cluster.update(evidence)

    eligible = [row for row in enriched_members if row.get("can_establish_cause")]
    pool = eligible or enriched_members
    if pool:
        primary = max(pool, key=_member_rank)
        cluster["primary_source"] = primary.get("source")
        cluster["primary_url"] = primary.get("url")
        cluster["headline"] = primary.get("headline")
        cluster["form"] = primary.get("form")
        cluster["source_tier"] = primary.get("source_tier")
        cluster["source_family"] = primary.get("source_family")
        cluster["source_policy_note_ar"] = primary.get("source_policy_note_ar")

    independent_count = int(evidence.get("independent_confirmation_count", 0))
    cluster["confirmation_count"] = independent_count
    cluster["confirmations"] = list(evidence.get("independent_confirmation_families", []))

    base_quality = max((_number(row.get("catalyst_quality")) for row in enriched_members), default=0.0)
    confirmation_bonus = min(6.0, max(0, independent_count - 1) * 3.0)
    adjusted_quality = min(100.0, base_quality + confirmation_bonus)
    state = str(evidence.get("verification_state") or "UNCONFIRMED_SECONDARY")
    if state == "ATTENTION_ONLY":
        adjusted_quality = min(adjusted_quality, 45.0)
    elif state == "UNCONFIRMED_SECONDARY":
        adjusted_quality = min(adjusted_quality, 68.0)
    elif state == "ISSUER_PRIMARY_AWAITING_OFFICIAL_CROSSCHECK":
        adjusted_quality = min(adjusted_quality, 88.0)
    cluster["catalyst_quality"] = round(adjusted_quality, 1)

    if evidence.get("official_confirmed"):
        cluster["cause_status_ar"] = "سبب مؤكد رسميًا"
    elif evidence.get("issuer_primary"):
        cluster["cause_status_ar"] = "سبب صادر من الشركة وينتظر مطابقة رسمية"
    elif evidence.get("attention_only"):
        cluster["cause_status_ar"] = "اهتمام سوقي فقط — السبب غير مثبت"
    else:
        cluster["cause_status_ar"] = "سبب محتمل غير مثبت رسميًا"

    cluster.setdefault("causal_firewall", {})["verification_state"] = state
    cluster["causal_firewall"]["official_confirmed"] = bool(evidence.get("official_confirmed"))
    cluster["causal_firewall"]["primary_cause_eligible"] = bool(evidence.get("primary_cause_eligible"))
    return cluster


def build_catalyst_intelligence(
    catalysts: Iterable[dict[str, Any]] | None,
    stocks: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply an official-first evidence firewall to legacy catalyst intelligence.

    SEC/FDA/Nasdaq/issuer evidence may establish a cause according to policy.
    Finviz/Reddit/X/Stocktwits can nominate attention but cannot establish the
    underlying catalyst. Confirmation counts are source-family based so two SEC
    search paths are not misrepresented as two independent confirmations.
    """

    intelligence = _legacy_build(catalysts, stocks)
    clusters = [
        _apply_cluster_policy(dict(cluster))
        for cluster in intelligence.get("clusters", [])
        if isinstance(cluster, dict)
    ]

    by_symbol: dict[str, dict[str, Any]] = {}
    for cluster in clusters:
        symbol = str(cluster.get("symbol") or "").upper()
        if not symbol:
            continue
        current = by_symbol.get(symbol)
        key = (
            1 if cluster.get("official_confirmed") else 0,
            1 if cluster.get("primary_cause_eligible") else 0,
            _number(cluster.get("catalyst_quality")),
            _number(cluster.get("materiality")),
        )
        current_key = (
            1 if current and current.get("official_confirmed") else 0,
            1 if current and current.get("primary_cause_eligible") else 0,
            _number(current.get("catalyst_quality")) if current else -1.0,
            _number(current.get("materiality")) if current else -1.0,
        )
        if current is None or key > current_key:
            by_symbol[symbol] = cluster

    intelligence["clusters"] = clusters
    intelligence["by_symbol"] = by_symbol
    intelligence["official_confirmed_clusters"] = sum(bool(row.get("official_confirmed")) for row in clusters)
    intelligence["issuer_primary_clusters"] = sum(bool(row.get("issuer_primary")) for row in clusters)
    intelligence["attention_only_clusters"] = sum(bool(row.get("attention_only")) for row in clusters)
    intelligence["official_first_policy"] = True
    intelligence["confirmation_unit"] = "independent_source_family"
    return intelligence
