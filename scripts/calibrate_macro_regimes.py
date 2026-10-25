"""Reproducible calibration of options_radar.macro_regimes on synthetic series.

Synthetic only: these numbers describe the detector on simulated data with a
known truth. They are not an error rate on real markets.

Definitions:
- false alarm (per series): share of no-change series where at least one
  break was reported;
- false alarm (per point): reported breaks / (series x changes);
- power: share of series with one true drift shift where a break was
  reported within min_size of the true point;
- delay: for found shifts, periods between the true point and
  `detectable_from` (the first expanding-window checkpoint that already
  shows the break), i.e. what was knowable at the time.

Usage: python scripts/calibrate_macro_regimes.py [--trials 200]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
from pathlib import Path

import numpy as np

_spec = importlib.util.spec_from_file_location(
    "macro_regimes", Path(__file__).resolve().parents[1] / "options_radar" / "macro_regimes.py")
mr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mr)

LENGTH = {"daily": 450, "weekly": 155}
SHIFT_SIGMA = 0.5  # drift change of half a standard deviation of the per-period change
SEEDS = {(f, k): 100 * i + j for i, f in enumerate(LENGTH)
         for j, k in enumerate(("gaussian", "student_t3", "gaussian_with_2_jumps"))}


def noise(rng: np.random.Generator, kind: str, n: int) -> np.ndarray:
    if kind == "gaussian":
        return rng.normal(0, 1, n)
    if kind == "student_t3":
        return rng.standard_t(3, n) / np.sqrt(3)  # unit variance
    if kind == "gaussian_with_2_jumps":
        x = rng.normal(0, 1, n)
        x[[n // 4, 3 * n // 4]] += 8  # isolated jumps, not a drift change
        return x
    raise ValueError(kind)


def run(trials: int) -> dict:
    out: dict = {"trials_per_scenario": trials, "shift_sigma": SHIFT_SIGMA, "penalty_factor": mr.PENALTY_FACTOR,
                 "min_size": mr.MIN_SIZE, "max_breaks": mr.MAX_BREAKS, "length": LENGTH, "no_change": {}, "shift": {}}
    for freq, n in LENGTH.items():
        min_size = mr.MIN_SIZE[freq]
        for kind in ("gaussian", "student_t3", "gaussian_with_2_jumps"):
            rng = np.random.default_rng(SEEDS[(freq, kind)])
            breaks = [len(mr.change_breaks(noise(rng, kind, n), min_size)) for _ in range(trials)]
            out["no_change"][f"{freq}/{kind}"] = {
                "series_with_a_break": round(sum(b > 0 for b in breaks) / trials, 3),
                "breaks_per_point": round(sum(breaks) / (trials * n), 5)}
        rng = np.random.default_rng(7 if freq == "daily" else 11)
        found, delays = 0, []
        for _ in range(trials):
            x = noise(rng, "gaussian", n)
            x[n // 2:] += SHIFT_SIGMA
            cuts = mr.change_breaks(x, min_size)
            hit = [c for c in cuts if abs(c - n // 2) <= min_size]
            if hit:
                found += 1
                when = mr.detectable_from(x, hit[0], freq)
                if when is not None:
                    delays.append(when - n // 2)
        out["shift"][freq] = {"power": round(found / trials, 3),
                              "median_delay_periods": statistics.median(delays) if delays else None,
                              "found_only_in_hindsight": round(1 - len(delays) / found, 3) if found else None}
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=200)
    print(json.dumps(run(parser.parse_args().trials), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
