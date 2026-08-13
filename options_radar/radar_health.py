from __future__ import annotations

from typing import Any


def _status(rank: int) -> str:
    return {0: "HEALTHY", 1: "DEGRADED", 2: "CRITICAL"}.get(rank, "CRITICAL")


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
    provider = str(summary.get("provider") or "").lower()
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
    if "yahoo" in provider or "yfinance" in provider or not provider:
        rank = max(rank, 1)
        reasons.append("Options data is fallback/snapshot quality rather than licensed OPRA trade+quote flow")
    if regime and str(regime.get("data_quality") or "complete") != "complete":
        rank = max(rank, 1)
        reasons.append("Market-regime inputs are partial")
    if selected == 0 and symbols > 0:
        reasons.append("No contract passed current quality/flow/regime gates; this is not by itself a failure")
    if not reasons:
        reasons.append("Options universe, provider and regime inputs are healthy")
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
        },
    }
