from __future__ import annotations

from typing import Any


def _sign(value: float) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def build_spx_gamma_consensus(external: dict[str, Any]) -> dict[str, Any]:
    daily = external.get("daily_gamma") or {}
    intraday = external.get("intraday_0dte") or {}

    signals: list[dict[str, Any]] = []

    daily_gex = float(daily.get("net_gex_dollars") or 0)
    if daily.get("available"):
        signals.append({
            "source": "daily_gex",
            "direction": _sign(daily_gex),
            "value": daily_gex,
        })

    intraday_gex = float(intraday.get("net_0dte_gex") or 0)
    if intraday.get("available"):
        signals.append({
            "source": "0dte_gex",
            "direction": _sign(intraday_gex),
            "value": intraday_gex,
        })

    positives = sum(1 for row in signals if row["direction"] > 0)
    negatives = sum(1 for row in signals if row["direction"] < 0)
    nonzero = positives + negatives

    if nonzero == 0:
        verdict = "NEUTRAL"
    elif positives == negatives:
        verdict = "CONFLICT"
    elif positives > negatives:
        verdict = "POSITIVE_GAMMA"
    else:
        verdict = "NEGATIVE_GAMMA"

    return {
        "verdict": verdict,
        "sample_count": len(signals),
        "nonzero_count": nonzero,
        "agreement_ratio": round(max(positives, negatives) / nonzero, 3) if nonzero else 0.0,
        "signals": signals,
        "affects_signal_score": False,
        "policy": "shadow_context_only",
        "research_note_ar": (
            "إجماع GEX مستقل للبحث فقط؛ لا يرفع أو يخفض إشارة التداول "
            "قبل التحقق من النتائج المستقبلية."
        ),
    }
