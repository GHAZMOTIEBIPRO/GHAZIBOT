"""Per-symbol signal follow-up from the stock outcome audit (stdlib only).

For each symbol: its most recent recorded radar signals with time, stage,
entry price, its own target and stop, and the audited status (target
reached first, stop first, not decisive, still pending). Outcomes are the
audit's, from completed 5-minute bars; nothing is re-scored here. The
walk-forward workflow loads this file by path and installs no packages.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

SCHEMA = "ghazi.signal_tracking.v1"
PER_SYMBOL = 5
STATUS_AR = {"success": "بلغ الهدف قبل الوقف", "failed": "ضرب الوقف أولًا",
             "non_decisive": "انتهت المدة دون هدف أو وقف", "pending": "مفتوحة / قيد القياس",
             "ambiguous": "غامضة (الهدف والوقف في نفس الشمعة)", "unavailable": "بيانات غير متاحة"}


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build(audit: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    records = audit.get("records") if isinstance(audit.get("records"), dict) else {}
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in records.values():
        if not isinstance(row, dict) or row.get("signal_session_valid") is False:
            continue
        symbol = str(row.get("symbol") or "").upper()
        if not symbol.isascii() or not symbol.replace(".", "").isalnum() or len(symbol) > 10:
            continue
        status = str(row.get("audit_status") or "pending")
        by_symbol.setdefault(symbol, []).append({
            "signal_time": row.get("signal_time"),
            "stage": row.get("entry_stage"),
            "entry_price": _num(row.get("entry_price")),
            "target_pct": _num(row.get("follow_through_target_pct")),
            "stop_pct": _num(row.get("failure_threshold_pct")),
            "status": status,
            "status_ar": STATUS_AR.get(status, status),
            "max_favourable_pct": _num(row.get("audit_mfe_pct")),
            "max_adverse_pct": _num(row.get("audit_mae_pct")),
            "resolved_at": row.get("audit_terminal_at"),
        })
    symbols = {}
    for symbol, rows in by_symbol.items():
        rows.sort(key=lambda r: str(r["signal_time"] or ""), reverse=True)
        decisive = [r for r in rows if r["status"] in {"success", "failed"}]
        symbols[symbol] = {
            "recent": rows[:PER_SYMBOL],
            "totals": {"signals": len(rows), "decisive": len(decisive),
                       "target_first": sum(r["status"] == "success" for r in decisive),
                       "stop_first": sum(r["status"] == "failed" for r in decisive),
                       "pending": sum(r["status"] == "pending" for r in rows)},
        }
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "source_audit_updated_at": audit.get("updated_at"),
        "symbols": symbols,
        "method": "audited outcomes from completed 5-minute bars; each signal uses its own stage target/stop",
        "research_only": True,
        "decision_authority": False,
        "is_win_probability": False,
    }
