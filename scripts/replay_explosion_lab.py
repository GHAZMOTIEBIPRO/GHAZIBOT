from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

OUTPUT_PATH = Path("data/replay/explosion_replay_report.json")
DEFAULT_SYMBOLS = "RGC,BNAI,ATXG,HOLO,MLGO"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp_series(series: pd.Series) -> pd.Series:
    return series.clip(lower=0.0, upper=100.0)


def build_replay_frame(history: pd.DataFrame) -> pd.DataFrame:
    """Build hindsight-safe daily features; forward returns are labels only."""
    if history.empty:
        return pd.DataFrame()
    frame = history.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    frame = frame[list(required)].sort_index().dropna(subset=["Close", "Volume"])
    if len(frame) < 30:
        return pd.DataFrame()

    previous_close = frame["Close"].shift(1)
    frame["day_move_pct"] = (frame["Close"] / previous_close - 1.0) * 100.0
    baseline_volume = frame["Volume"].shift(1).rolling(20, min_periods=10).mean()
    frame["rvol"] = frame["Volume"] / baseline_volume.replace(0, np.nan)
    previous_volume = frame["Volume"].shift(1)
    frame["volume_ratio_1d"] = frame["Volume"] / previous_volume.replace(0, np.nan)
    previous_volume_ratio = previous_volume / frame["Volume"].shift(2).replace(0, np.nan)
    frame["volume_accel"] = frame["volume_ratio_1d"] / previous_volume_ratio.replace(0, np.nan)

    prior_high_10 = frame["High"].shift(1).rolling(10, min_periods=5).max()
    prior_low_10 = frame["Low"].shift(1).rolling(10, min_periods=5).min()
    prior_mid = (prior_high_10 + prior_low_10) / 2.0
    frame["compression_pct"] = ((prior_high_10 - prior_low_10) / prior_mid.replace(0, np.nan)) * 100.0
    prior_high_20 = frame["High"].shift(1).rolling(20, min_periods=10).max()
    frame["distance_to_20d_high_pct"] = ((prior_high_20 - frame["Close"]) / prior_high_20.replace(0, np.nan)) * 100.0

    rvol_component = _clamp_series(25.0 + frame["rvol"].fillna(0) * 24.0)
    volume_component = _clamp_series(30.0 + (frame["volume_accel"].fillna(0) - 0.8) * 45.0)
    price_lag_component = pd.Series(30.0, index=frame.index)
    early_mask = frame["day_move_pct"].between(-2.5, 8.0) & (frame["rvol"] >= 1.15)
    price_lag_component.loc[early_mask] = 100.0
    started_mask = frame["day_move_pct"].between(2.0, 15.0) & (frame["rvol"] >= 1.3)
    price_lag_component.loc[started_mask] = np.maximum(price_lag_component.loc[started_mask], 78.0)
    price_lag_component.loc[frame["day_move_pct"] > 30.0] = 5.0

    compression_component = _clamp_series(100.0 - frame["compression_pct"].fillna(30.0) * 3.0)
    near_high_component = _clamp_series(100.0 - frame["distance_to_20d_high_pct"].abs().fillna(30.0) * 4.0)

    frame["replay_score"] = (
        rvol_component * 0.28
        + volume_component * 0.26
        + price_lag_component * 0.22
        + compression_component * 0.14
        + near_high_component * 0.10
    ).clip(0, 100)

    # Labels are forward-looking and deliberately computed only after signal features exist.
    future_closes = pd.concat([frame["Close"].shift(-offset) for offset in range(1, 6)], axis=1)
    frame["future_5d_max_close"] = future_closes.max(axis=1)
    frame["future_5d_max_return_pct"] = (frame["future_5d_max_close"] / frame["Close"] - 1.0) * 100.0
    frame["explosion_label"] = frame["future_5d_max_return_pct"] >= 25.0
    return frame.replace([np.inf, -np.inf], np.nan)


def evaluate_replay(frame: pd.DataFrame, threshold: float = 60.0) -> dict[str, Any]:
    if frame.empty:
        return {"rows": 0, "signals": 0, "positive_windows": 0, "true_positive": 0, "false_positive": 0}
    valid = frame.dropna(subset=["replay_score", "future_5d_max_return_pct"]).copy()
    signal = valid["replay_score"] >= threshold
    positive = valid["explosion_label"].astype(bool)
    tp = int((signal & positive).sum())
    fp = int((signal & ~positive).sum())
    fn = int((~signal & positive).sum())
    tn = int((~signal & ~positive).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    false_positive_rate = fp / (fp + tn) if fp + tn else 0.0
    return {
        "rows": int(len(valid)),
        "threshold": threshold,
        "signals": int(signal.sum()),
        "positive_windows": int(positive.sum()),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "false_positive_rate": round(false_positive_rate, 4),
    }


def _largest_event(frame: pd.DataFrame, threshold: float) -> dict[str, Any]:
    if frame.empty:
        return {}
    day_returns = frame["day_move_pct"].dropna()
    if day_returns.empty:
        return {}
    event_date = day_returns.idxmax()
    event_position = frame.index.get_loc(event_date)
    start = max(0, event_position - 10)
    pre = frame.iloc[start:event_position]
    signals = pre[pre["replay_score"] >= threshold]
    first_signal = signals.index[0] if not signals.empty else None
    lead_days = int(event_position - frame.index.get_loc(first_signal)) if first_signal is not None else None
    return {
        "largest_up_day": str(pd.Timestamp(event_date).date()),
        "largest_up_day_return_pct": round(_number(frame.loc[event_date, "day_move_pct"]), 2),
        "max_pre_event_score_10d": round(_number(pre["replay_score"].max()), 2) if not pre.empty else 0.0,
        "first_signal_date_10d": str(pd.Timestamp(first_signal).date()) if first_signal is not None else None,
        "lead_trading_days": lead_days,
        "caught_before_largest_day": first_signal is not None,
    }


def replay_symbol(symbol: str, period: str, threshold: float) -> dict[str, Any]:
    try:
        history = yf.download(symbol, period=period, interval="1d", auto_adjust=False, progress=False, threads=False)
    except Exception as exc:
        return {"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"}
    frame = build_replay_frame(history)
    metrics = evaluate_replay(frame, threshold=threshold)
    largest = _largest_event(frame, threshold=threshold)
    recent_signals = []
    if not frame.empty:
        candidates = frame[frame["replay_score"] >= threshold].tail(8)
        for index, row in candidates.iterrows():
            recent_signals.append(
                {
                    "date": str(pd.Timestamp(index).date()),
                    "score": round(_number(row.get("replay_score")), 2),
                    "rvol": round(_number(row.get("rvol")), 2),
                    "volume_accel": round(_number(row.get("volume_accel")), 2),
                    "day_move_pct": round(_number(row.get("day_move_pct")), 2),
                    "future_5d_max_return_pct": round(_number(row.get("future_5d_max_return_pct")), 2),
                }
            )
    return {"symbol": symbol, "metrics": metrics, "largest_event": largest, "recent_signals": recent_signals}


def run(symbols: list[str], period: str, threshold: float, output: Path) -> int:
    results = [replay_symbol(symbol, period=period, threshold=threshold) for symbol in symbols]
    valid_metrics = [row.get("metrics") for row in results if isinstance(row.get("metrics"), dict) and row["metrics"].get("rows")]
    aggregate: dict[str, Any] = {"symbols": len(results), "valid_symbols": len(valid_metrics)}
    if valid_metrics:
        tp = sum(int(row.get("true_positive", 0)) for row in valid_metrics)
        fp = sum(int(row.get("false_positive", 0)) for row in valid_metrics)
        fn = sum(int(row.get("false_negative", 0)) for row in valid_metrics)
        tn = sum(int(row.get("true_negative", 0)) for row in valid_metrics)
        aggregate.update(
            {
                "true_positive": tp,
                "false_positive": fp,
                "false_negative": fn,
                "true_negative": tn,
                "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
                "recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
                "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0,
            }
        )
    payload = {
        "generated_at": _utc_now(),
        "purpose": "hindsight-safe price/volume replay; catalyst/float history is not reconstructed when unavailable",
        "score_is_probability": False,
        "forward_label": "max close return over next 5 sessions >= 25%",
        "threshold": threshold,
        "period": period,
        "aggregate": aggregate,
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(f"Replay lab: symbols={len(results)} aggregate={aggregate}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BLACK BOX Ω historical explosion replay lab")
    parser.add_argument("--symbols", default=os.getenv("REPLAY_SYMBOLS", DEFAULT_SYMBOLS))
    parser.add_argument("--period", default=os.getenv("REPLAY_PERIOD", "2y"))
    parser.add_argument("--threshold", type=float, default=_number(os.getenv("REPLAY_SIGNAL_THRESHOLD", "60"), 60.0))
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    symbols = [token.strip().upper() for token in str(args.symbols).split(",") if token.strip()]
    return run(symbols=symbols, period=args.period, threshold=args.threshold, output=Path(args.output))


if __name__ == "__main__":
    raise SystemExit(main())
