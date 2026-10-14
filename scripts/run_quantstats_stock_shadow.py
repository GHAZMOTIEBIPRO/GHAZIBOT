"""Optional QuantStats descriptive audit for *signals*, not portfolio P&L.

The 60m directional returns in stock_outcome_audit are benchmark observations,
not actual fills or daily capital-weighted portfolio returns. Consequently,
use only non-annualized event statistics. Never publish CAGR, Sharpe,
drawdown, win probabilities or executable option metrics from these samples.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from options_radar.stock_walk_forward import _eligible_decisive_rows

MIN_RECORDS = 20
MIN_SESSIONS = 10


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def build_quantstats_research(
    audit: dict[str, Any], *,
    minimum_records: int = MIN_RECORDS,
    minimum_sessions: int = MIN_SESSIONS,
    quantstats_module: Any | None = None,
) -> dict[str, Any]:
    coverage = audit.get("coverage") if isinstance(audit.get("coverage"), dict) else {}
    coverage_60 = _finite(coverage.get("coverage_60m_pct"))
    # Fails closed if audit record population is incomplete. This optional
    # tool cannot infer coverage by looking only at available scored records.
    rows = _eligible_decisive_rows(audit)
    qualified = [
        row for row in rows
        if row.get("_return_60m") is not None and _finite(row["_return_60m"]) is not None
    ]
    sessions = {str(row["signal_session_date"]) for row in qualified}
    base = {
        "schema": "quantstats_stock_signals_shadow_v1",
        "source": "stock_outcome_audit_60m",
        "provider": "QuantStats",
        "source_category": "RESEARCH_ONLY_UNOFFICIAL_YAHOO_BARS",
        "decision_authority": False,
        "live_alert_weights_changed": False,
        "execution_grade": False,
        "realized_portfolio_pnl": False,
        "strategy_returns": False,
        "annualized_metrics_allowed": False,
        "profit_factor_is_event_level_not_portfolio": True,
        "scope": "non-annualized, equally-weighted per-signal 60m directional percentage outcomes; not daily P&L",
        "counts": {
            "eligible_decisive_observations": len(qualified),
            "distinct_sessions": len(sessions),
            "coverage_60m_pct": coverage_60,
        },
        "minimums": {
            "qualified_records": max(1, int(minimum_records)),
            "independent_sessions": max(1, int(minimum_sessions)),
            "coverage_60m_pct": 90.0,
        },
        "metrics": {},
    }
    if (coverage_60 is None or coverage_60 < 90 or
            len(qualified) < max(1, int(minimum_records)) or
            len(sessions) < max(1, int(minimum_sessions))):
        return {**base, "status": "INSUFFICIENT_EVIDENCE", "reason": "coverage_or_sample_gate_not_met"}
    if quantstats_module is None:
        try:
            import quantstats as qs
            quantstats_module = qs
        except ImportError:
            return {**base, "status": "UNAVAILABLE", "reason": "quantstats_not_installed"}

    event_returns = pd.Series(
        [float(row["_return_60m"]) / 100.0 for row in qualified],
        dtype="float64",
    )
    # Prevent QS from ever treating this as a date-indexed portfolio curve.
    # Only call narrow event-descriptive functions.
    try:
        wins = _finite(quantstats_module.stats.win_rate(event_returns))
        profit = _finite(quantstats_module.stats.profit_factor(event_returns))
    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
        return {**base, "status": "UNAVAILABLE", "reason": "quantstats_metric_error"}

    positives = int((event_returns > 0).sum())
    negatives = int((event_returns < 0).sum())
    if wins is None or not 0 <= wins <= 1:
        return {**base, "status": "UNAVAILABLE", "reason": "invalid_win_rate"}
    # Profit factor is undefined when no losses; never publish inf as fact.
    if negatives == 0:
        profit = None
    base["metrics"] = {
        "event_win_rate": round(wins, 4),
        "event_profit_factor": round(profit, 4) if profit is not None and profit >= 0 else None,
        "event_mean_directional_return_pct": round(float(event_returns.mean()) * 100, 4),
        "event_positive_count": positives,
        "event_negative_count": negatives,
        "event_zero_count": int((event_returns == 0).sum()),
    }
    return {**base, "status": "RESEARCH_METRICS_ONLY", "reason": "not_portfolio_returns"}


def main() -> None:
    parser = argparse.ArgumentParser(description="QuantStats descriptive shadow metrics on matured 60m signal outcomes")
    parser.add_argument("--audit", default="data/live/stock_outcome_audit.json")
    parser.add_argument("--output", default="data/live/quantstats_stock_signals_shadow.json")
    args = parser.parse_args()

    audit_path = Path(args.audit)
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        audit = {}
    if not isinstance(audit, dict):
        audit = {}
    result = build_quantstats_research(audit)
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(path)
    print(
        "QuantStats signal shadow:"
        f" status={result['status']}"
        f" eligible={result['counts']['eligible_decisive_observations']}"
        f" sessions={result['counts']['distinct_sessions']}"
    )


if __name__ == "__main__":
    main()
