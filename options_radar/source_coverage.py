"""Auditable coverage summary for public reporting. No trading authority.

A market-price provider is not interchangeable with an event, earnings,
regulatory, academic, or macro source. Only successful reports may be
described as active. Upstream aliases count as one family.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

_PRICE_FAMILIES = {
    "yahoo": "yahoo",
    "yfinance": "yahoo",
    "yahoo/yfinance": "yahoo",
    "yahooquery": "yahoo",
    "alpaca": "alpaca",
    "tradier": "tradier",
    "tiingo": "tiingo",
    "finnhub": "finnhub",
    "twelve_data": "twelve_data",
    "twelve data": "twelve_data",
    "alpha_vantage": "alpha_vantage",
    "alpha vantage": "alpha_vantage",
    "polygon": "polygon_massive",
    "polygon / massive": "polygon_massive",
    "polygon options": "polygon_massive",
    "opra عبر polygon / massive": "polygon_massive",
    "massive": "polygon_massive",
    "marketdata": "marketdata",
    "marketdata.app": "marketdata",
}


def _family(name: Any) -> str | None:
    return _PRICE_FAMILIES.get(str(name or "").strip().lower())


def _reported_active(row: dict[str, Any]) -> bool:
    return row.get("used_successfully") is True or row.get("active") is True


def _stock_roles(network: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (market-price-family names, non-price context sources)."""
    markets: set[str] = set()
    context: set[str] = set()
    for raw in network.get("stocks", []) or []:
        if not isinstance(raw, dict) or not _reported_active(raw):
            continue
        name = str(raw.get("name") or "").strip()
        family = _family(name)
        if family:
            markets.add(family)
        elif name:
            context.add(name)
    return sorted(markets), sorted(context)


def coverage_diagnostics(
    source_network: dict[str, Any] | None,
    provider_readiness: dict[str, Any] | None,
    rejected: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    network = source_network if isinstance(source_network, dict) else {}
    readiness = provider_readiness if isinstance(provider_readiness, dict) else {}
    stock_price, context = _stock_roles(network)
    # The published overview may have optimistic legacy "active" flags; do
    # not promote these reports to execution-grade proof or independent quorum.
    option_source_families = sorted({
        family for name in readiness.get("sources", []) or []
        if (family := _family(name)) is not None
    })
    option_unsupported = sorted({
        str(name) for name in readiness.get("sources", []) or []
        if _family(name) is None
    })
    rejected_reasons: Counter[str] = Counter()
    for item in rejected or []:
        if not isinstance(item, dict) or str(item.get("kind") or "").lower() not in {"option", "options", "contract"}:
            continue
        for part in str(item.get("rejection_reason") or "").split(","):
            key = part.strip()
            if key:
                rejected_reasons[key] += 1

    option_quotes = readiness.get("production_quote_ready") is True
    option_flow = readiness.get("production_flow_ready") is True
    blockers: list[str] = []
    if not option_source_families:
        blockers.append("NO_VERIFIED_OPTION_PROVIDER_FAMILY")
    if int(readiness.get("fallback_only_chains") or 0):
        blockers.append("YAHOO_RESEARCH_ONLY")
    if int(readiness.get("cross_source_chains") or 0) < 1:
        blockers.append("NO_INDEPENDENT_CROSS_SOURCE_CHAIN")
    if not option_quotes:
        blockers.append("NO_EXECUTION_GRADE_OPTION_QUOTE")
    if not option_flow:
        blockers.append("NO_VERIFIED_OPTION_TRADE_FLOW")

    return {
        "reporting_scope": "REPORTED_SOURCES_NOT_EXCHANGE_ENTITLEMENTS",
        "stock_price_source_families_reported": stock_price,
        "stock_non_price_context_sources_reported": context,
        "stock_primary_non_yahoo_families_reported": [name for name in stock_price if name != "yahoo"],
        "option_chain_source_families": option_source_families,
        "option_chain_unclassified_sources": option_unsupported,
        "option_live_primary_chains_reported": int(readiness.get("live_primary_chains") or 0),
        "option_cross_source_chains_reported": int(readiness.get("cross_source_chains") or 0),
        "option_fallback_only_chains_reported": int(readiness.get("fallback_only_chains") or 0),
        "options_execution_quote_ready": option_quotes,
        "options_trade_flow_ready": option_flow,
        "blocking_codes": blockers,
        "top_option_rejection_reasons": dict(rejected_reasons.most_common(6)),
        "public_licensing_notice": (
            "Personal-use brokerage API access does not grant public market-data "
            "redistribution rights. Do not expose tokens or unlicensed raw quotes."
        ),
    }
