"""Changes in the drift of public macro series (ruptures, BSD-2-Clause).

Inputs are the dated series written by scripts/build_public_macro.py from
U.S. government publications: the Treasury 10Y-2Y spread and 10Y yield
(daily) and CFTC asset-manager / leveraged-fund net positions in index
futures (weekly).

Method (reviewed 2026-10-25). The first version segmented the LEVELS
with an l2 cost; on simulated random walks with no change at all it found
the maximum five breaks in 100% of runs, so its output was false alarms
by construction. It now works on the period-to-period CHANGES:

- ruptures Binseg, l2 cost: a break is a shift in the average change per
  period (drift).
- penalty pen = 2 * var(changes) * ln(n) with the sample variance.
  Calibration is reproducible with scripts/calibrate_macro_regimes.py
  (seeded; 200 synthetic series per scenario; daily 450 / weekly 155
  changes). With no change, the share of SERIES with any break was 0.5-2.5%
  daily and 0.5-6% weekly (Gaussian, Student-t(3), Gaussian with two isolated
  jumps; about +/-3 points of sampling uncertainty at 200 series). A drift shift of 0.5 standard deviations was found in 77% (daily)
  and 37.5% (weekly) of series, with a median of 35.5 sessions / 18 weeks
  before it was knowable. These are synthetic results, not an error rate on
  real markets; tests/test_macro_regimes.py keeps the no-change cases.
- minimum segment 20 sessions / 8 weeks; at most MAX_BREAKS breaks.
- missing values are not filled: rows without both yields, or CFTC weeks
  without both legs, are left out upstream.
- known-at-the-time: each break is re-tested on expanding windows that end
  at checkpoints, and `detectable_from` is the first checkpoint (plus the
  publication lag: CFTC positions are as of Tuesday and released on
  Friday) whose own data already showed a break near it. A break found
  only with the full history is labelled hindsight.

The output describes the past; it does not forecast the next break, is
not a direction signal and feeds no score. Loaded by file path so the job
does not import the options_radar package (its __init__ needs pandas).
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from itertools import pairwise
from typing import Any

import numpy as np
import ruptures as rpt

SCHEMA = "ghazi.macro_regimes.v2"
MAX_BREAKS = 5
PENALTY_FACTOR = 2.0
MIN_SIZE = {"daily": 20, "weekly": 8}
MIN_OBSERVATIONS = {"daily": 120, "weekly": 52}
CHECKPOINT_STEP = {"daily": 5, "weekly": 1}
LABEL_AR = {
    "treasury_10y_2y_bp": "فارق عائد 10 سنوات − سنتين (نقطة أساس)",
    "treasury_10y_pct": "عائد الخزانة لأجل 10 سنوات (%)",
}


def change_breaks(changes: np.ndarray, min_size: int) -> list[int]:
    """Indices into `changes` where a new drift segment starts (excluding 0)."""
    n = changes.shape[0]
    variance = float(np.var(changes))
    if n < 2 * min_size or variance <= 0:
        return []
    pen = PENALTY_FACTOR * variance * math.log(n)
    algo = rpt.Binseg(model="l2", min_size=min_size, jump=1).fit(changes.reshape(-1, 1))
    found = algo.predict(pen=pen)[:-1]
    if len(found) > MAX_BREAKS:
        found = algo.predict(n_bkps=MAX_BREAKS)[:-1]
    return sorted(found)


def detectable_from(changes: np.ndarray, cut: int, frequency: str) -> int | None:
    """First expanding-window end (index into changes, exclusive) that already shows this break."""
    min_size, step = MIN_SIZE[frequency], CHECKPOINT_STEP[frequency]
    for end in range(cut + min_size, changes.shape[0] + 1, step):
        if any(abs(b - cut) <= min_size for b in change_breaks(changes[:end], min_size)):
            return end
    return None


def _shift_date(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def regime_report(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    dates, values, frequency = spec.get("dates") or [], spec.get("values") or [], spec.get("frequency")
    lag = int(spec.get("release_lag_days") or 0)
    base = {"label_ar": LABEL_AR.get(name) or spec.get("label_ar") or name, "unit": spec.get("unit"),
            "frequency": frequency, "source": spec.get("source"), "observations": len(values),
            "release_lag_days": lag}
    if (frequency not in MIN_SIZE or len(dates) != len(values)
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)):
        return {**base, "available": False, "reason": "series malformed"}
    if len(values) < MIN_OBSERVATIONS[frequency]:
        return {**base, "available": False, "reason": f"fewer than {MIN_OBSERVATIONS[frequency]} observations"}
    level = np.asarray(values, dtype=float)
    changes = np.diff(level)
    cuts = change_breaks(changes, MIN_SIZE[frequency])
    edges = [0, *cuts, changes.shape[0]]
    segments = []
    for start, end in pairwise(edges):
        chunk = changes[start:end]
        segments.append({
            "start": dates[start + 1], "end": dates[end],
            "periods": int(end - start),
            "mean_change": round(float(np.mean(chunk)), 4),
            "std_change": round(float(np.std(chunk)), 4),
            "level_start": values[start], "level_end": values[end],
        })
    breaks = []
    for cut in cuts:
        seen = detectable_from(changes, cut, frequency)
        breaks.append({
            "date": dates[cut + 1],
            "detectable_from": _shift_date(dates[seen], lag) if seen is not None else None,
            "hindsight_only": seen is None,
        })
    current = segments[-1]
    previous = segments[-2] if len(segments) > 1 else None
    return {
        **base, "available": True, "first_date": dates[0], "last_date": dates[-1],
        "latest_value": values[-1],
        "method": {"library": "ruptures", "algorithm": "Binseg", "cost": "l2", "input": "period changes",
                   "penalty": "2 * var(changes) * ln(n)", "min_size": MIN_SIZE[frequency],
                   "max_breaks": MAX_BREAKS, "calibration_false_alarm_rate": "3-5% (synthetic, no change)"},
        "breaks": breaks,
        "segments": segments,
        "current_regime": {
            "since": current["start"], "periods": current["periods"],
            "mean_change": current["mean_change"],
            "previous_mean_change": previous["mean_change"] if previous else None,
            "detectable_from": breaks[-1]["detectable_from"] if breaks else None,
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
            "يرصد تغيّر متوسط التغير لكل فترة (الانجراف) في السلسلة؛ وصف للماضي لا يتنبأ بالانكسار التالي ولا يحدد اتجاهًا.",
            "«قابل للرصد منذ» هو أول تاريخ كانت بياناته وحدها تُظهر الانكسار (مع تأخر نشر CFTC ثلاثة أيام)؛ ما قبله رؤية بأثر رجعي.",
            "مراكز CFTC أسبوعية كما في الثلاثاء وتُنشر الجمعة؛ سياق لمن يحمل العقود وليست توقيتًا.",
        ],
        # Descriptive macro context only. Breaks are knowable late (synthetic median
        # 35.5 sessions / 18 weeks), so they are not an early speculative signal and
        # feed no short-term opportunity score until out-of-sample value is shown.
        "use": {"role": "DESCRIPTIVE_MACRO_CONTEXT", "feeds_scores": False,
                "synthetic_calibration": {"script": "scripts/calibrate_macro_regimes.py", "series_per_scenario": 200,
                                          "false_break_series_pct": {"daily": "0.5-2.5", "weekly": "0.5-6"},
                                          "power_at_0_5_sigma_pct": {"daily": 77, "weekly": 37.5},
                                          "median_delay": {"daily_sessions": 35.5, "weekly_weeks": 18},
                                          "note": "simulated series with known truth; not an accuracy on real markets"},
                "note_ar": "سياق اقتصادي وصفي فقط؛ يُكتشف التغيّر متأخرًا (وسيط 35.5 جلسة أو 18 أسبوعًا في اختبار اصطناعي)، "
                           "فلا يصلح تنبيهًا مبكرًا ولا يدخل في أي درجة فرصة."},
        "rights": "U.S. government publications (Treasury, CFTC); derived segmentation published with the sources cited",
        "research_only": True,
        "decision_authority": False,
        "execution_authority": False,
    }
