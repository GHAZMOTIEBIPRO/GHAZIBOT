"""Structural breaks in public macro series (ruptures, BSD-2-Clause).

Inputs are the dated series written by scripts/build_public_macro.py from
U.S. government publications: the Treasury 10Y-2Y spread and 10Y yield
(daily) and CFTC asset-manager / leveraged-fund net positions in index
futures (weekly).

Method: ruptures Binseg with the l2 cost (shifts in the mean level), a
minimum segment length per frequency, and a BIC-style penalty
pen = 2 * sigma^2 * ln(n), with sigma the noise level estimated robustly
from first differences (MAD / 0.6745 / sqrt(2)). At most MAX_BREAKS
breaks are kept. The output describes past segments; it does not forecast
the next break, is not a direction signal and feeds no score.

Loaded by file path so the job does not import the options_radar package
(its __init__ needs pandas).
"""
from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

import numpy as np
import ruptures as rpt

SCHEMA = "ghazi.macro_regimes.v1"
MAX_BREAKS = 5
MIN_SIZE = {"daily": 20, "weekly": 8}
MIN_OBSERVATIONS = {"daily": 120, "weekly": 52}
LABEL_AR = {
    "treasury_10y_2y_bp": "فارق عائد 10 سنوات − سنتين (نقطة أساس)",
    "treasury_10y_pct": "عائد الخزانة لأجل 10 سنوات (%)",
}


def noise_sigma(values: np.ndarray) -> float:
    diffs = np.diff(values)
    if diffs.size == 0:
        return 0.0
    mad = float(np.median(np.abs(diffs - np.median(diffs))))
    sigma = mad / 0.6745 / math.sqrt(2)
    return sigma if sigma > 0 else float(np.std(diffs)) / math.sqrt(2)


def breaks(values: list[float], frequency: str) -> tuple[list[int], dict[str, Any]]:
    """Indices where a new segment starts (excluding 0), plus the method record."""
    signal = np.asarray(values, dtype=float).reshape(-1, 1)
    n = signal.shape[0]
    sigma = noise_sigma(signal[:, 0])
    pen = 2 * sigma ** 2 * math.log(n) if n > 1 else 0.0
    min_size = MIN_SIZE[frequency]
    method = {"library": "ruptures", "version": rpt.__version__ if hasattr(rpt, "__version__") else None,
              "algorithm": "Binseg", "cost": "l2", "min_size": min_size,
              "penalty": "2 * sigma^2 * ln(n)", "sigma": round(sigma, 6), "pen": round(pen, 6),
              "max_breaks": MAX_BREAKS}
    if sigma == 0 or n < 2 * min_size:
        return [], method
    algo = rpt.Binseg(model="l2", min_size=min_size, jump=1).fit(signal)
    found = algo.predict(pen=pen)[:-1]
    if len(found) > MAX_BREAKS:
        found = algo.predict(n_bkps=MAX_BREAKS)[:-1]
        method["capped"] = True
    return sorted(found), method


def regime_report(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    dates, values, frequency = spec.get("dates") or [], spec.get("values") or [], spec.get("frequency")
    base = {"label_ar": LABEL_AR.get(name) or spec.get("label_ar") or name, "unit": spec.get("unit"),
            "frequency": frequency, "source": spec.get("source"), "observations": len(values)}
    if (frequency not in MIN_SIZE or len(dates) != len(values)
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)):
        return {**base, "available": False, "reason": "series malformed"}
    if len(values) < MIN_OBSERVATIONS[frequency]:
        return {**base, "available": False, "reason": f"fewer than {MIN_OBSERVATIONS[frequency]} observations"}
    cuts, method = breaks(values, frequency)
    edges = [0, *cuts, len(values)]
    segments = []
    for start, end in pairwise(edges):
        chunk = values[start:end]
        segments.append({"start": dates[start], "end": dates[end - 1], "observations": end - start,
                         "mean": round(sum(chunk) / len(chunk), 3)})
    current = segments[-1]
    previous = segments[-2] if len(segments) > 1 else None
    return {
        **base, "available": True, "first_date": dates[0], "last_date": dates[-1],
        "latest_value": values[-1], "method": method,
        "change_points": [dates[i] for i in cuts],
        "segments": segments,
        "current_regime": {
            "since": current["start"], "observations": current["observations"], "mean": current["mean"],
            "previous_mean": previous["mean"] if previous else None,
            "shift": round(current["mean"] - previous["mean"], 3) if previous else None,
        },
    }


def build(history: dict[str, Any], *, generated_at: str) -> dict[str, Any]:
    series = history.get("series") if isinstance(history, dict) else None
    reports = {name: regime_report(name, spec) for name, spec in (series or {}).items() if isinstance(spec, dict)}
    return {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "history_generated_at": history.get("generated_at") if isinstance(history, dict) else None,
        "status": "AVAILABLE" if any(r.get("available") for r in reports.values()) else "DATA_UNAVAILABLE",
        "series": reports,
        "notes_ar": [
            "تقسيم وصفي لتاريخ السلسلة إلى أنظمة بمتوسطات مختلفة؛ لا يتنبأ بالانكسار التالي ولا يحدد اتجاه السوق.",
            "مراكز CFTC أسبوعية (الثلاثاء)؛ انكسار في صافي المراكز سياق لمن يحمل العقود وليس توقيتًا.",
        ],
        "rights": "U.S. government publications (Treasury, CFTC); derived segmentation published with the sources cited",
        "research_only": True,
        "decision_authority": False,
        "execution_authority": False,
    }
