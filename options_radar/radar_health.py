from __future__ import annotations

from typing import Any


def _status(rank: int) -> str:
    return {0: "HEALTHY", 1: "DEGRADED", 2: "CRITICAL"}.get(rank, "CRITICAL")


def options_provider_readiness(payload: dict[str, Any]) -> dict[str, Any]:
    """Classify actual option-chain sources rather than the pipeline name."""
    audit = payload.get("provider_audit") if isinstance(payload.get("provider_audit"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    source_counts: dict[str, int] = {}
    usable = 0
    yahoo_only = 0
    delayed_primary = 0
    live_primary = 0
    opra_active = 0
    cross_source = 0

    for value in audit.values():
        if not isinstance(value, dict):
            continue
        source = str(value.get("source") or "").strip().lower()
        freshness = str(value.get("freshness") or "").strip().lower()
        if not source:
            continue
        usable += 1
        source_counts[source] = source_counts.get(source, 0) + 1
        pieces = {piece.strip() for piece in source.replace("+", "|").split("|") if piece.strip()}
        if len(pieces) > 1:
            cross_source += 1
        is_yahoo = "yahoo" in source or "yfinance" in source
        is_opra = any(token in source or token in freshness for token in ("opra", "polygon", "massive"))
        is_tradier = "tradier" in source
        is_delayed = any(token in freshness for token in ("delay", "delayed", "sandbox", "24h", "unofficial"))
        is_marketdata = "marketdata" in source

        if is_yahoo:
            yahoo_only += 1
        if is_opra:
            opra_active += 1
            live_primary += 1
        elif is_tradier and not is_delayed:
            live_primary += 1
        elif is_marketdata or is_delayed or "finnhub" in source:
            delayed_primary += 1

    # Backward-compatible synthetic/legacy payloads may only expose the provider
    # name. This inference is deliberately not used when a real per-symbol audit
    # exists, which is the production source of truth.
    audit_available = usable > 0
    if not audit_available:
        legacy_provider = str(summary.get("provider") or "").strip().lower()
        if legacy_provider and legacy_provider not in {"phase5_hybrid", "hybrid", "unknown"}:
            usable = 1
            source_counts[legacy_provider] = 1
            if "yahoo" in legacy_provider or "yfinance" in legacy_provider:
                yahoo_only = 1
            elif "tradier" in legacy_provider:
                live_primary = 1
            elif any(token in legacy_provider for token in ("opra", "polygon", "massive")):
                live_primary = 1
                opra_active = 1
            else:
                delayed_primary = 1

    fallback_only = usable > 0 and yahoo_only == usable
    return {
        "audit_available": audit_available,
        "usable_chains": usable,
        "source_counts": source_counts,
        "yahoo_only_chains": yahoo_only,
        "delayed_or_unverified_primary_chains": delayed_primary,
        "live_primary_chains": live_primary,
        "cross_source_chains": cross_source,
        "opra_active_chains": opra_active,
        "fallback_only": fallback_only,
        "production_quote_ready": live_primary > 0,
        "opra_flow_ready": opra_active > 0,
    }


def assess_stock_health(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    errors = [str(value) for value in payload.get("errors", []) if str(value).strip()]
    actionable = int(summary.get("fast_actionable", 0) or 0)
    validated = int(summary.get("stocks_deep_validated", 0) or 0)
    official = int(summary.get("official_causes", 0) or 0)
    rank = 0
    reasons: list[str] = []
    if actionable > 0 and validated == 0:
        rank = 2
        reasons.append("Fast radar produced candidates but deep stock validation produced none")
    if errors:
        rank = max(rank, 1)
        reasons.append(f"{len(errors)} stock-path data/source errors recorded")
    if actionable > 0 and official == 0:
        reasons.append("No candidate currently has an official primary cause; alerts must state cause unknown")
    if not reasons:
        reasons.append("Stock discovery and validation payload are internally consistent")
    return {
        "status": _status(rank),
        "critical": rank >= 2,
        "degraded": rank >= 1,
        "reasons": reasons,
        "metrics": {
            "fast_actionable": actionable,
            "deep_validated": validated,
            "official_causes": official,
            "errors": len(errors),
        },
    }


def assess_options_health(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    errors = payload.get("errors") if isinstance(payload.get("errors"), dict) else {}
    universe = payload.get("universe") if isinstance(payload.get("universe"), dict) else {}
    regime = payload.get("market_regime_detail") if isinstance(payload.get("market_regime_detail"), dict) else {}
    symbols = int(summary.get("symbols_scanned", 0) or 0)
    selected = int(summary.get("contracts_selected", 0) or 0)
    official_optionability = bool(summary.get("official_optionability_verified"))
    readiness = options_provider_readiness(payload)
    rank = 0
    reasons: list[str] = []
    if symbols <= 0:
        rank = 2
        reasons.append("Independent options universe is empty")
    if errors:
        ratio = len(errors) / max(1, symbols)
        rank = max(rank, 2 if ratio >= 0.5 else 1)
        reasons.append(f"{len(errors)} option-path source/symbol errors; ratio={ratio:.1%}")
    if not official_optionability:
        rank = max(rank, 1)
        reasons.append("OCC optionability verification is unavailable; fallback universe is in use")
    if readiness["fallback_only"]:
        rank = max(rank, 1)
        reasons.append(
            "FALLBACK_ONLY: every usable option chain came from Yahoo/YFinance; production quote readiness is false"
        )
    elif readiness["audit_available"] and readiness["usable_chains"] > 0 and not readiness["production_quote_ready"]:
        rank = max(rank, 1)
        reasons.append(
            "Option chains are available, but only delayed or entitlement-unverified primary sources are active"
        )
    if not readiness["opra_flow_ready"]:
        # Missing OPRA limits flow claims but does not make a verified live quote
        # service unhealthy. Keep capability readiness explicit in metrics.
        reasons.append("No OPRA-backed trade+quote source is active; sweep/aggressor flow remains unconfirmed")
    if regime and str(regime.get("data_quality") or "complete") != "complete":
        rank = max(rank, 1)
        reasons.append("Market-regime inputs are partial")
    if selected == 0 and symbols > 0:
        reasons.append("No contract passed current quality/flow/regime gates; this is not by itself a failure")
    if not reasons:
        reasons.append("Options universe, provider entitlement and regime inputs are healthy")
    return {
        "status": _status(rank),
        "critical": rank >= 2,
        "degraded": rank >= 1,
        "reasons": reasons,
        "metrics": {
            "symbols_scanned": symbols,
            "contracts_selected": selected,
            "official_optionability_verified": official_optionability,
            "provider": summary.get("provider"),
            "errors": len(errors),
            "attention_sources": universe.get("attention_sources", []),
            "provider_readiness": readiness,
        },
    }
