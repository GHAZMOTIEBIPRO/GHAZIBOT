from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yfinance as yf

from scripts.replay_explosion_lab import build_replay_frame, evaluate_replay

OUTPUT_PATH = Path("data/replay/explosion_replay_report.json")
DEFAULT_ARCHETYPES = "RGC,BNAI,ATXG,HOLO,MLGO"
DEFAULT_CONTROLS = "AAPL,MSFT,KO,JNJ,XOM"
DEFAULT_THRESHOLDS = "40,45,50,55,60,65,70,75,80"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _download_frame(symbol: str, period: str):
    history = yf.download(symbol, period=period, interval="1d", auto_adjust=False, progress=False, threads=False)
    return build_replay_frame(history)


def _aggregate(frames: dict[str, Any], threshold: float) -> dict[str, Any]:
    metrics = [evaluate_replay(frame, threshold=threshold) for frame in frames.values() if frame is not None and not frame.empty]
    tp = sum(int(row.get("true_positive", 0)) for row in metrics)
    fp = sum(int(row.get("false_positive", 0)) for row in metrics)
    fn = sum(int(row.get("false_negative", 0)) for row in metrics)
    tn = sum(int(row.get("true_negative", 0)) for row in metrics)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    # Calibration utility deliberately values early-event recall while heavily
    # penalizing false alarms. It is a research selector, not expected return.
    utility = recall * 0.60 + precision * 0.25 - fpr * 0.70
    return {
        "threshold": threshold,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "false_positive_rate": round(fpr, 4),
        "research_utility": round(utility, 4),
    }


def _largest_event(frame, threshold: float) -> dict[str, Any]:
    if frame is None or frame.empty or frame["day_move_pct"].dropna().empty:
        return {}
    event_date = frame["day_move_pct"].idxmax()
    event_position = frame.index.get_loc(event_date)
    pre = frame.iloc[max(0, event_position - 15):event_position]
    hits = pre[pre["replay_score"] >= threshold]
    first = hits.index[0] if not hits.empty else None
    return {
        "largest_up_day": str(event_date.date()),
        "largest_up_day_return_pct": round(float(frame.loc[event_date, "day_move_pct"]), 2),
        "max_pre_event_score_15d": round(float(pre["replay_score"].max()), 2) if not pre.empty else 0.0,
        "first_signal_date_15d": str(first.date()) if first is not None else None,
        "lead_trading_days": int(event_position - frame.index.get_loc(first)) if first is not None else None,
        "caught_before_largest_day": first is not None,
    }


def run(archetypes: list[str], controls: list[str], period: str, thresholds: list[float], output: Path) -> int:
    all_symbols = list(dict.fromkeys(archetypes + controls))
    frames: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for symbol in all_symbols:
        try:
            frame = _download_frame(symbol, period)
            if frame.empty:
                errors[symbol] = "empty history"
            else:
                frames[symbol] = frame
        except Exception as exc:
            errors[symbol] = f"{type(exc).__name__}: {exc}"

    sweep = [_aggregate(frames, threshold) for threshold in thresholds]
    viable = [row for row in sweep if row["false_positive_rate"] <= 0.12]
    pool = viable or sweep
    recommended = max(pool, key=lambda row: (row["research_utility"], row["recall"], row["precision"])) if pool else {}
    recommended_threshold = float(recommended.get("threshold", 60.0))

    per_symbol = []
    for symbol in all_symbols:
        frame = frames.get(symbol)
        if frame is None:
            per_symbol.append({"symbol": symbol, "role": "archetype" if symbol in archetypes else "negative_control", "error": errors.get(symbol, "unavailable")})
            continue
        metrics = evaluate_replay(frame, threshold=recommended_threshold)
        per_symbol.append(
            {
                "symbol": symbol,
                "role": "archetype" if symbol in archetypes else "negative_control",
                "metrics": metrics,
                "largest_event": _largest_event(frame, recommended_threshold),
            }
        )

    archetype_event_catches = [
        row.get("largest_event", {}).get("caught_before_largest_day")
        for row in per_symbol
        if row.get("role") == "archetype" and isinstance(row.get("largest_event"), dict)
    ]
    control_metrics = [row.get("metrics", {}) for row in per_symbol if row.get("role") == "negative_control" and isinstance(row.get("metrics"), dict)]
    control_signals = sum(int(row.get("signals", 0)) for row in control_metrics)
    control_rows = sum(int(row.get("rows", 0)) for row in control_metrics)

    payload = {
        "generated_at": _utc_now(),
        "purpose": "hindsight-safe threshold calibration with explosion archetypes and stable negative controls",
        "score_is_probability": False,
        "live_threshold_auto_changed": False,
        "warning": "Price/volume replay cannot reconstruct historical SEC float, catalyst or borrow state; recommendation is research-only.",
        "forward_label": "max close return over next 5 sessions >= 25%",
        "period": period,
        "archetypes": archetypes,
        "negative_controls": controls,
        "threshold_sweep": sweep,
        "recommended_research_threshold": recommended_threshold,
        "recommended_metrics": recommended,
        "archetype_largest_event_catch_rate": round(sum(bool(v) for v in archetype_event_catches) / len(archetype_event_catches), 4) if archetype_event_catches else 0.0,
        "negative_control_signal_rate": round(control_signals / control_rows, 4) if control_rows else 0.0,
        "errors": errors,
        "results": per_symbol,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(
        "Replay calibration:",
        f"symbols={len(frames)}/{len(all_symbols)}",
        f"recommended={recommended_threshold:.0f}",
        f"catch_rate={payload['archetype_largest_event_catch_rate']:.2%}",
        f"control_signal_rate={payload['negative_control_signal_rate']:.2%}",
    )
    return 0


def _csv(value: str) -> list[str]:
    return [token.strip().upper() for token in value.split(",") if token.strip()]


def _thresholds(value: str) -> list[float]:
    values = []
    for token in value.split(","):
        try:
            values.append(float(token.strip()))
        except ValueError:
            continue
    return sorted(set(values)) or [60.0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BLACK BOX Ω threshold calibration replay")
    parser.add_argument("--archetypes", default=os.getenv("REPLAY_SYMBOLS", DEFAULT_ARCHETYPES))
    parser.add_argument("--controls", default=os.getenv("REPLAY_CONTROL_SYMBOLS", DEFAULT_CONTROLS))
    parser.add_argument("--period", default=os.getenv("REPLAY_PERIOD", "2y"))
    parser.add_argument("--thresholds", default=os.getenv("REPLAY_THRESHOLDS", DEFAULT_THRESHOLDS))
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(
        archetypes=_csv(args.archetypes),
        controls=_csv(args.controls),
        period=args.period,
        thresholds=_thresholds(args.thresholds),
        output=Path(args.output),
    )


if __name__ == "__main__":
    raise SystemExit(main())
