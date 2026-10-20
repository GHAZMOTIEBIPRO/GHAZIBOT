"""Publish a compact classical-direction digest (CALL / PUT / WAIT per company).

Input is the validated classical-direction-radar artifact. Direction is
underlying-only (no option chain, flow or greeks); levels and targets are
research references, never orders, fills or probabilities.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "ghazi.classical_direction_public.v1"
REQUIRED_POLICY_FALSE = ("option_chain_data_used_for_direction", "options_flow_used", "greeks_used")


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 4) if math.isfinite(number) and number > 0 else None


def _row(source: dict[str, Any]) -> dict[str, Any] | None:
    symbol = str(source.get("symbol") or "").upper()
    decision = str(source.get("decision") or "")
    if not symbol.isascii() or not symbol or decision not in {"CALL", "PUT", "WAIT"}:
        return None
    targets = source.get("targets") if isinstance(source.get("targets"), dict) else None
    frames = {}
    for key in ("daily", "hourly", "intraday"):
        view = source.get(key) if isinstance(source.get(key), dict) else {}
        frames[key] = str(view.get("direction") or "UNAVAILABLE")
    return {
        "symbol": symbol[:10],
        "decision": decision,
        "priority": str(source.get("priority") or "WAIT"),
        "trade_status": (str(source.get("trade_status")) if source.get("trade_status") in
                         {"ACTIONABLE", "NO_TRADE", "WAIT"} else ("WAIT" if decision == "WAIT" else "UNRATED")),
        "agreement_pct": source.get("agreement_pct") if isinstance(source.get("agreement_pct"), int) else None,
        "horizon": str(source.get("horizon") or "")[:40],
        "reference_close": _num(source.get("price")),
        "confirmation_level": _num(source.get("confirmation_level")),
        "invalidation_level": _num(source.get("invalidation_level")),
        "targets": ({k: v for k, v in targets.items() if isinstance(v, (int, float))}
                    if targets and decision != "WAIT" else None),
        "timeframes": frames,
        "scenarios_ar": [str(x)[:200] for x in (source.get("scenarios_ar") or [])][:3],
        "reasons_ar": [str(x)[:200] for x in (source.get("reasons_ar") or [])][:4],
    }


def build_digest(payload: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    policy = payload.get("policy") if isinstance(payload.get("policy"), dict) else {}
    if payload.get("path") != "classical_direction" or any(
            policy.get(key) is not False for key in REQUIRED_POLICY_FALSE):
        raise ValueError("payload is not an underlying-only classical direction report")
    rows = []
    for key in ("signals", "waits"):
        for source in payload.get(key) or []:
            if isinstance(source, dict) and (row := _row(source)):
                rows.append(row)
    order = {"CALL": 0, "PUT": 0, "WAIT": 1}
    rows.sort(key=lambda r: (order[r["decision"]], -(r["agreement_pct"] or 0), r["symbol"]))
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return {
        "schema": SCHEMA,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "source_generated_at": payload.get("generated_at"),
        "operational_status": str(summary.get("operational_status") or "UNKNOWN"),
        "counts": {d: sum(r["decision"] == d for r in rows) for d in ("CALL", "PUT", "WAIT")},
        "companies": rows,
        "method": "Classical underlying-only: Dow structure, swing S/R, trendlines, SMA20/50/200, volume, breakout/retest, classical patterns; 1D/1H/15m agreement.",
        "research_only": True,
        "execution_authority": False,
        "probability": None,
        "option_data_used_for_direction": False,
    }


def blocked_digest(now: datetime, reason: str) -> dict[str, Any]:
    """Withdraw the public digest while no permitted price source exists."""
    return {
        "schema": "ghazi.classical_direction_public.v1", "generated_at": now.isoformat(),
        "status": "SOURCE_TERMS_BLOCKED", "operational_status": "LICENSE_BLOCKED",
        "reason": reason,
        "reason_ar": ("لا يوجد مصدر أسعار مسموح: الجلب الآلي من Yahoo غير مسموح ولا يوجد مفتاح API لحساب مرخص؛ "
                      "سُحبت قراءات الاتجاه السابقة بدل عرضها كأنها حالية."),
        "counts": {}, "companies": [], "research_only": True, "execution_authority": False,
        "probability": None, "option_data_used_for_direction": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-blocked", default="", help="reason; publish a withdrawn digest instead")
    args = parser.parse_args()
    if args.source_blocked:
        digest = blocked_digest(datetime.now(timezone.utc), args.source_blocked)
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(digest, ensure_ascii=False) + "\n", encoding="utf-8")
        print("Classical digest: SOURCE_TERMS_BLOCKED; previous readings withdrawn")
        return 0
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    digest = build_digest(payload if isinstance(payload, dict) else {}, now=datetime.now(timezone.utc))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(digest, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n",
                   encoding="utf-8")
    tmp.replace(out)
    print(f"Classical digest: {digest['counts']} status={digest['operational_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
