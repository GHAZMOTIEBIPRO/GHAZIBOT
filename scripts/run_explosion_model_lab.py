"""Run the pre-registered explosion model lab and publish aggregate results.

Universe: every symbol the radar has recorded in the outcome audit, plus
the structural small-cap catalog and a few large-cap controls. This is a
radar-selected universe (selection bias toward movers is disclosed in the
report). Daily bars come from the existing research feed (Yahoo, labelled
research fallback); only aggregate statistics are published, never bars.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from options_radar.explosion_model_lab import HOLD, STOP_PCT, TARGET_PCT, collect, evaluate

CONTROLS = ("AAPL", "MSFT", "KO", "JNJ", "XOM", "NVDA", "AMD", "TSLA")
SCHEMA = "ghazi.explosion_model_lab.v1"


def universe_symbols(audit_path: Path, structural_path: Path, limit: int = 300) -> list[str]:
    symbols: list[str] = []
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        symbols += [str(r.get("symbol") or "").upper() for r in (audit.get("records") or {}).values()
                    if isinstance(r, dict)]
    except (OSError, ValueError):
        pass
    try:
        structural = json.loads(structural_path.read_text(encoding="utf-8"))
        symbols += [str(c.get("symbol") or "").upper() for c in structural.get("candidates") or []
                    if isinstance(c, dict)]
    except (OSError, ValueError):
        pass
    clean = sorted({s for s in symbols if s.isalpha() and 1 <= len(s) <= 5})
    return (clean[:limit]) + [c for c in CONTROLS if c not in clean]


def download(symbols: list[str], period: str = "2y") -> dict[str, pd.DataFrame]:
    import yfinance as yf

    out: dict[str, pd.DataFrame] = {}
    for start in range(0, len(symbols), 40):
        chunk = symbols[start:start + 40]
        try:
            data = yf.download(chunk, period=period, interval="1d", group_by="ticker",
                               auto_adjust=False, threads=False, progress=False)
        except Exception as exc:  # noqa: BLE001 - one failed chunk must not stop the lab
            print(f"chunk {start}: {type(exc).__name__}")
            continue
        for symbol in chunk:
            try:
                frame = data[symbol] if isinstance(data.columns, pd.MultiIndex) else data
                frame = frame[["Open", "High", "Low", "Close", "Volume"]].dropna()
            except KeyError:
                continue
            if len(frame) >= 80:
                out[symbol] = frame
        time.sleep(1.0)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", required=True)
    parser.add_argument("--structural", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    symbols = universe_symbols(Path(args.audit), Path(args.structural))
    bars = download(symbols + ["SPY"])
    bench = bars.pop("SPY", None)
    frame = collect(bars, bench["Close"] if bench is not None else None)
    result = evaluate(frame)
    report = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe": {"requested": len(symbols), "with_bars": len(bars),
                     "selection": "radar-recorded symbols + structural catalog + large-cap controls",
                     "selection_bias": "symbols were chosen because the radar flagged them; results "
                                       "do not represent the whole market"},
        "protocol": {"entry": "next session open", "target_pct": TARGET_PCT, "stop_pct": STOP_PCT,
                     "hold_sessions": HOLD, "same_bar_target_and_stop": "counted as loss",
                     "costs": "1.5% <$2, 0.6% $2-10, 0.2% >=$10 round trip (assumption)",
                     "rules_fitted": False, "split": "first half vs second half of dates"},
        **result,
        "source": "daily bars from the research feed (Yahoo, labelled fallback); aggregates only",
        "research_only": True, "decision_authority": False, "live_rules_changed": False,
        "score_is_probability": False,
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("Model lab:", json.dumps({k: v.get("all", v) for k, v in result.get("models", {}).items()},
                                   default=str)[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
