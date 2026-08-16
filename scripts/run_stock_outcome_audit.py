from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from options_radar.durable_stock_state import restore_missing_durable_stock_state
from options_radar.free_autonomy import enforce_free_autonomy_environment
from options_radar.hybrid_fetcher import DataFetcher
from options_radar.settings import Settings
from options_radar.stock_outcome_backfill import StockOutcomeBackfillAuditor

DEFAULT_STOCK_OUTCOMES = Path(os.getenv("STOCK_OUTCOME_PATH", "data/live/stock_outcomes.json"))
DEFAULT_AUDIT = Path(os.getenv("STOCK_OUTCOME_AUDIT_PATH", "data/live/stock_outcome_audit.json"))
MIN_INDEPENDENT_SESSIONS = 10
MIN_60M_COVERAGE_PCT = 90.0


def _load(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(destination)


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _symbol_window(audit: dict[str, Any], symbol: str, now: datetime) -> tuple[datetime, datetime] | None:
    records = audit.get("records") if isinstance(audit.get("records"), dict) else {}
    times = [
        _parse_time(row.get("signal_time"))
        for row in records.values()
        if isinstance(row, dict) and str(row.get("symbol") or "").upper() == symbol.upper()
    ]
    times = [stamp for stamp in times if stamp is not None]
    if not times:
        return None
    start = min(times) - timedelta(minutes=5)
    # Historical 5m is only needed through the audit horizon, but asking through
    # now lets one request serve several events for the same symbol.
    latest_needed = max(times) + timedelta(days=4)
    return start, min(now, latest_needed)


def _apply_independent_session_gate(audit: dict[str, Any]) -> dict[str, Any]:
    records = audit.get("records") if isinstance(audit.get("records"), dict) else {}
    sessions: set[str] = set()
    for row in records.values():
        if not isinstance(row, dict):
            continue
        coverage = row.get("coverage") if isinstance(row.get("coverage"), dict) else {}
        if coverage.get("60m") is not True:
            continue
        stamp = _parse_time(row.get("signal_time"))
        if stamp is not None:
            sessions.add(stamp.date().isoformat())

    coverage = audit.get("coverage") if isinstance(audit.get("coverage"), dict) else {}
    records_count = int(coverage.get("records", 0) or 0)
    covered_60m = int(coverage.get("covered_60m", 0) or 0)
    coverage_pct = 100.0 * covered_60m / max(1, records_count)
    coverage["independent_60m_sessions"] = len(sessions)
    coverage["independent_60m_session_dates"] = sorted(sessions)
    audit["coverage"] = coverage

    gate = audit.get("promotion_gate") if isinstance(audit.get("promotion_gate"), dict) else {}
    gate.update(
        {
            "minimum_60m_coverage_pct": MIN_60M_COVERAGE_PCT,
            "minimum_independent_sessions": MIN_INDEPENDENT_SESSIONS,
            "coverage_ready": records_count >= 20
            and coverage_pct >= MIN_60M_COVERAGE_PCT
            and len(sessions) >= MIN_INDEPENDENT_SESSIONS,
            "walk_forward_required_after_coverage": True,
            "live_promotion_allowed": False,
        }
    )
    audit["promotion_gate"] = gate
    audit["bias_guard"] = {
        "survivorship_bias_addressed_by_following_disappeared_signals": True,
        "non_decisive_events_remain_in_denominator": True,
        "ambiguous_same_bar_events_remain_in_denominator": True,
        "independent_session_gate_required": True,
        "existing_79pct_snapshot_rate_is_not_treated_as_accuracy": True,
    }
    return audit


def run(
    *,
    stock_outcomes_path: str | Path = DEFAULT_STOCK_OUTCOMES,
    audit_path: str | Path = DEFAULT_AUDIT,
    maximum_symbols: int = 40,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)

    free = enforce_free_autonomy_environment()
    durable = restore_missing_durable_stock_state()
    stock_outcomes = _load(stock_outcomes_path)
    auditor = StockOutcomeBackfillAuditor(audit_path)
    audit = auditor.seed_events(stock_outcomes)
    symbols = auditor.symbols_needing_backfill(
        audit,
        now=current,
        maximum_symbols=max(1, int(maximum_symbols)),
    )

    settings = Settings()
    settings.validate()
    fetcher = DataFetcher(settings)
    errors: dict[str, str] = {}
    attempted = 0
    updated_records = 0

    for symbol in symbols:
        window = _symbol_window(audit, symbol, current)
        if window is None or window[1] <= window[0]:
            continue
        attempted += 1
        try:
            result = fetcher.fetch_stock_bars(
                symbol,
                start=window[0],
                end=window[1],
                interval="5m",
                # Explicitly constrain the audit to the free research fallback.
                # Paid/account-entitlement providers are never required here.
                providers=["yahoo"],
            )
            updated_records += auditor.apply_symbol_bars(
                audit,
                symbol=symbol,
                bars=result.data,
                now=current,
                source=f"{result.source} | {result.freshness}",
            )
        except Exception as exc:
            errors[symbol] = f"{type(exc).__name__}: {exc}"[:500]

    audit = auditor.finalise(
        audit,
        now=current,
        attempted_symbols=attempted,
        errors=errors,
    )
    audit = _apply_independent_session_gate(audit)
    audit["free_autonomy"] = {
        "enabled": free.enabled,
        "stock_feed": free.stock_stream_feed,
        "option_feed": free.option_stream_feed,
        "paid_market_data_allowed": free.paid_market_data_allowed,
        "audit_provider_order": ["yahoo"],
    }
    audit["updated_records_this_pass"] = updated_records
    audit["durable_stock_state"] = {
        "attempted": durable.attempted,
        "branch_available": durable.branch_available,
        "restored": list(durable.restored),
        "preserved_local": list(durable.preserved_local),
        "error": durable.error,
    }
    _save(audit_path, audit)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill stock outcomes from free historical 5m bars")
    parser.add_argument("--stock-outcomes", default=str(DEFAULT_STOCK_OUTCOMES))
    parser.add_argument("--audit", default=str(DEFAULT_AUDIT))
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=int(os.getenv("STOCK_OUTCOME_AUDIT_MAX_SYMBOLS", "40")),
    )
    args = parser.parse_args()
    audit = run(
        stock_outcomes_path=args.stock_outcomes,
        audit_path=args.audit,
        maximum_symbols=args.max_symbols,
    )
    coverage = audit.get("coverage") if isinstance(audit.get("coverage"), dict) else {}
    gate = audit.get("promotion_gate") if isinstance(audit.get("promotion_gate"), dict) else {}
    print(
        "Stock outcome audit: "
        f"records={int(coverage.get('records', 0) or 0)} "
        f"coverage60={float(coverage.get('coverage_60m_pct', 0.0) or 0.0):.1f}% "
        f"sessions={int(coverage.get('independent_60m_sessions', 0) or 0)} "
        f"decisive={int(coverage.get('decisive', 0) or 0)} "
        f"ambiguous={int(coverage.get('ambiguous', 0) or 0)} "
        f"non_decisive={int(coverage.get('non_decisive', 0) or 0)} "
        f"coverage_ready={bool(gate.get('coverage_ready'))}"
    )


if __name__ == "__main__":
    main()
