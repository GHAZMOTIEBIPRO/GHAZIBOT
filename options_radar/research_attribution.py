from __future__ import annotations

import math
from importlib import import_module
from typing import Any

import pandas as pd

from .open_source_research import build_hindsight_safe_smc_snapshot


DECISIVE = frozenset({"success", "failed"})


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _signal_time(value: Any) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    return None if pd.isna(parsed) else parsed


def _normalise_daily(history: pd.DataFrame) -> pd.DataFrame:
    if history is None or history.empty:
        return pd.DataFrame()
    frame = history.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    frame.index = pd.to_datetime(frame.index, utc=True, errors="coerce")
    frame = frame[~frame.index.isna()].sort_index()
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["Open", "High", "Low", "Close"])


def history_before_signal(history: pd.DataFrame, signal_time: Any) -> pd.DataFrame:
    """Use completed daily bars strictly before the signal session.

    Intraday signals must not see the signal day's final daily high/low/close.
    """
    frame = _normalise_daily(history)
    stamp = _signal_time(signal_time)
    if frame.empty or stamp is None:
        return pd.DataFrame()
    signal_date = stamp.date()
    return frame[pd.Index(frame.index.date) < signal_date].copy()


def build_chart_research_features(history: pd.DataFrame, direction: str) -> dict[str, Any]:
    frame = _normalise_daily(history)
    if len(frame) < 55:
        return {
            "available": False,
            "direction_alignment": None,
            "reason": "insufficient_completed_daily_bars",
        }
    close = frame["Close"].astype(float)
    ema9 = close.ewm(span=9, adjust=False, min_periods=9).mean().iloc[-1]
    ema21 = close.ewm(span=21, adjust=False, min_periods=21).mean().iloc[-1]
    ema50 = close.ewm(span=50, adjust=False, min_periods=50).mean().iloc[-1]
    current = float(close.iloc[-1])
    prior_high = float(frame["High"].shift(1).rolling(20).max().iloc[-1])
    prior_low = float(frame["Low"].shift(1).rolling(20).min().iloc[-1])

    bullish_stack = current > ema9 > ema21 > ema50
    bearish_stack = current < ema9 < ema21 < ema50
    side = str(direction or "up").lower()
    aligned = bullish_stack if side == "up" else bearish_stack
    breakout_aligned = current >= prior_high if side == "up" else current <= prior_low
    return {
        "available": True,
        "direction_alignment": bool(aligned),
        "breakout_alignment": bool(breakout_aligned),
        "bullish_stack": bool(bullish_stack),
        "bearish_stack": bool(bearish_stack),
        "completed_bar_date": str(frame.index[-1].date()),
        "close": round(current, 6),
        "ema9": round(float(ema9), 6),
        "ema21": round(float(ema21), 6),
        "ema50": round(float(ema50), 6),
        "prior_high_20": round(prior_high, 6),
        "prior_low_20": round(prior_low, 6),
    }


def build_smc_research_features(history: pd.DataFrame, direction: str) -> dict[str, Any]:
    frame = _normalise_daily(history)
    try:
        snapshot = build_hindsight_safe_smc_snapshot(frame, swing_length=20)
    except (ImportError, AttributeError, ValueError) as exc:
        return {
            "available": False,
            "direction_alignment": None,
            "reason": f"{type(exc).__name__}: {exc}",
        }

    event = snapshot.get("last_confirmed_fvg")
    fvg_value = _number((event or {}).get("FVG"), 0.0) if isinstance(event, dict) else 0.0
    fvg_side = "bullish" if fvg_value > 0 else "bearish" if fvg_value < 0 else "unknown"
    desired = "bullish" if str(direction or "up").lower() == "up" else "bearish"
    aligned = None if fvg_side == "unknown" else fvg_side == desired
    return {
        "available": True,
        "direction_alignment": aligned,
        "fvg_side": fvg_side,
        "last_confirmed_fvg": event,
        "last_confirmed_swing": snapshot.get("last_confirmed_swing"),
        "swing_confirmation_lag_bars": snapshot.get("swing_confirmation_lag_bars"),
        "fvg_confirmation_lag_bars": snapshot.get("fvg_confirmation_lag_bars"),
        "live_decision_authority": False,
    }


def _sec_features(record: dict[str, Any]) -> dict[str, Any]:
    source = str(record.get("cause_source") or "")
    url = str(record.get("cause_url") or "")
    official = record.get("official_cause") is True
    sec_identified = "sec" in source.lower() or "sec.gov" in url.lower()
    return {
        "source_metadata_available": bool(source or url),
        "source": source[:160],
        "url": url[:300],
        "official_cause": official,
        "sec_identified": sec_identified,
        "official_sec_evidence": bool(official and sec_identified),
        "cause_tier": str(record.get("cause_tier") or "unknown"),
        "entry_evidence_state": str(record.get("entry_evidence_state") or "unknown"),
    }


def build_stock_research_features(
    record: dict[str, Any],
    history: pd.DataFrame,
) -> dict[str, Any]:
    completed = history_before_signal(history, record.get("signal_time"))
    direction = str(record.get("direction") or "up").lower()
    chart = build_chart_research_features(completed, direction)
    smc = build_smc_research_features(completed, direction)
    sec = _sec_features(record)

    aligned_count = sum(
        (
            sec.get("official_sec_evidence") is True,
            chart.get("direction_alignment") is True,
            smc.get("direction_alignment") is True,
        )
    )
    available_count = sum(
        (
            sec.get("source_metadata_available") is True,
            chart.get("available") is True,
            smc.get("available") is True and smc.get("direction_alignment") is not None,
        )
    )
    return {
        "version": "OPEN_SOURCE_ATTRIBUTION_V1",
        "asof_signal_time": record.get("signal_time"),
        "completed_daily_bars": len(completed),
        "decision_authority": False,
        "live_alert_weights_changed": False,
        "sec": sec,
        "chart": chart,
        "smc": smc,
        "aligned_evidence_count": int(aligned_count),
        "available_evidence_count": int(available_count),
    }


def _qualified_60m(record: dict[str, Any]) -> bool:
    coverage = record.get("coverage") if isinstance(record.get("coverage"), dict) else {}
    if coverage.get("60m") is True:
        return True
    checkpoints = record.get("checkpoints") if isinstance(record.get("checkpoints"), dict) else {}
    point = checkpoints.get("60m") if isinstance(checkpoints.get("60m"), dict) else {}
    return point.get("coverage_qualified") is True


def _return_60m(record: dict[str, Any]) -> float | None:
    checkpoints = record.get("checkpoints") if isinstance(record.get("checkpoints"), dict) else {}
    point = checkpoints.get("60m") if isinstance(checkpoints.get("60m"), dict) else {}
    value = point.get("directional_return_pct")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "n": 0,
            "success_rate": None,
            "positive_60m_rate": None,
            "mean_60m_return_pct": None,
        }
    returns = [value for row in rows if (value := _return_60m(row)) is not None]
    successes = sum(row.get("audit_status") == "success" for row in rows)
    return {
        "n": len(rows),
        "success_rate": round(successes / len(rows), 4),
        "positive_60m_rate": (
            round(sum(value > 0 for value in returns) / len(returns), 4)
            if returns
            else None
        ),
        "mean_60m_return_pct": (
            round(sum(returns) / len(returns), 4)
            if returns
            else None
        ),
    }


def _factor_report(
    rows: list[dict[str, Any]],
    predicate,
    *,
    minimum_sample: int,
) -> dict[str, Any]:
    present = [row for row in rows if predicate(row) is True]
    absent = [row for row in rows if predicate(row) is False]
    present_summary = _summary(present)
    absent_summary = _summary(absent)
    present_rate = present_summary.get("success_rate")
    absent_rate = absent_summary.get("success_rate")
    present_return = present_summary.get("mean_60m_return_pct")
    absent_return = absent_summary.get("mean_60m_return_pct")
    return {
        "present": present_summary,
        "absent": absent_summary,
        "minimum_sample_each_side": minimum_sample,
        "sample_ready": len(present) >= minimum_sample and len(absent) >= minimum_sample,
        "success_rate_lift_pp": (
            round((present_rate - absent_rate) * 100.0, 2)
            if present_rate is not None and absent_rate is not None
            else None
        ),
        "mean_60m_return_lift_pct": (
            round(present_return - absent_return, 4)
            if present_return is not None and absent_return is not None
            else None
        ),
    }


def evaluate_stock_research_attribution(
    audit: dict[str, Any],
    *,
    minimum_sample: int = 10,
) -> dict[str, Any]:
    records = audit.get("records") if isinstance(audit.get("records"), dict) else {}
    rows = [
        row
        for row in records.values()
        if isinstance(row, dict)
        and row.get("signal_session_valid") is True
        and row.get("audit_status") in DECISIVE
        and _qualified_60m(row)
        and isinstance(row.get("research_features"), dict)
    ]
    baseline = _summary(rows)

    def sec(row: dict[str, Any]) -> bool | None:
        features = row.get("research_features") or {}
        value = ((features.get("sec") or {}).get("official_sec_evidence"))
        return value if isinstance(value, bool) else None

    def chart(row: dict[str, Any]) -> bool | None:
        features = row.get("research_features") or {}
        value = ((features.get("chart") or {}).get("direction_alignment"))
        return value if isinstance(value, bool) else None

    def smc(row: dict[str, Any]) -> bool | None:
        features = row.get("research_features") or {}
        value = ((features.get("smc") or {}).get("direction_alignment"))
        return value if isinstance(value, bool) else None

    def combined(row: dict[str, Any]) -> bool:
        features = row.get("research_features") or {}
        return int(features.get("aligned_evidence_count") or 0) >= 2

    return {
        "version": "OPEN_SOURCE_ATTRIBUTION_V1",
        "decision_authority": False,
        "live_alert_weights_changed": False,
        "score_is_probability": False,
        "eligible_records": len(rows),
        "baseline": baseline,
        "factors": {
            "official_sec_evidence": _factor_report(rows, sec, minimum_sample=minimum_sample),
            "chart_direction_alignment": _factor_report(rows, chart, minimum_sample=minimum_sample),
            "smc_fvg_alignment": _factor_report(rows, smc, minimum_sample=minimum_sample),
            "two_of_three_alignment": _factor_report(rows, combined, minimum_sample=minimum_sample),
        },
        "policy": {
            "daily_bars_on_signal_date_excluded": True,
            "smc_confirmation_lag_enforced": True,
            "sec_evidence_uses_entry_time_frozen_source_metadata": True,
            "no_factor_changes_live_scores": True,
            "walk_forward_review_required_before_any_promotion": True,
        },
    }


def add_causal_replay_features(
    frame: pd.DataFrame,
    *,
    swing_length: int = 20,
) -> pd.DataFrame:
    """Add end-of-day causal chart/SMC features to an explosion replay frame."""
    if frame is None or frame.empty:
        return frame
    out = frame.copy()
    close = pd.to_numeric(out["Close"], errors="coerce")
    ema9 = close.ewm(span=9, adjust=False, min_periods=9).mean()
    ema21 = close.ewm(span=21, adjust=False, min_periods=21).mean()
    ema50 = close.ewm(span=50, adjust=False, min_periods=50).mean()
    out["research_chart_bullish"] = (close > ema9) & (ema9 > ema21) & (ema21 > ema50)

    try:
        module = import_module("smartmoneyconcepts")
        smc = getattr(module, "smc")
        ohlcv = pd.DataFrame(
            {
                "open": pd.to_numeric(out["Open"], errors="coerce"),
                "high": pd.to_numeric(out["High"], errors="coerce"),
                "low": pd.to_numeric(out["Low"], errors="coerce"),
                "close": close,
                "volume": pd.to_numeric(out["Volume"], errors="coerce"),
            },
            index=out.index,
        )
        fvg = smc.fvg(ohlcv, join_consecutive=False)
        swings = smc.swing_highs_lows(ohlcv, swing_length=swing_length)
        out["research_smc_bullish_fvg"] = (
            pd.to_numeric(fvg["FVG"], errors="coerce").shift(1) > 0
        )
        out["research_smc_confirmed_swing_low"] = (
            pd.to_numeric(swings["HighLow"], errors="coerce").shift(swing_length) < 0
        )
        out["research_smc_available"] = True
    except (ImportError, AttributeError, KeyError, ValueError):
        out["research_smc_bullish_fvg"] = False
        out["research_smc_confirmed_swing_low"] = False
        out["research_smc_available"] = False
    return out


def _binary_metrics(signal: pd.Series, positive: pd.Series) -> dict[str, Any]:
    signal = signal.fillna(False).astype(bool)
    positive = positive.fillna(False).astype(bool)
    tp = int((signal & positive).sum())
    fp = int((signal & ~positive).sum())
    fn = int((~signal & positive).sum())
    tn = int((~signal & ~positive).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    return {
        "signals": int(signal.sum()),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "false_positive_rate": round(fpr, 4),
    }


def evaluate_replay_feature_ablation(
    frame: pd.DataFrame,
    *,
    threshold: float,
) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {"available": False, "reason": "empty_frame"}
    valid = frame.dropna(subset=["replay_score", "future_5d_max_return_pct"]).copy()
    if valid.empty:
        return {"available": False, "reason": "no_labeled_rows"}
    positive = valid["explosion_label"].astype(bool)
    baseline = valid["replay_score"] >= threshold
    chart = baseline & valid.get("research_chart_bullish", False)
    smc_fvg = baseline & valid.get("research_smc_bullish_fvg", False)
    dual = chart & valid.get("research_smc_bullish_fvg", False)

    baseline_metrics = _binary_metrics(baseline, positive)
    variants = {
        "chart_confirmed": _binary_metrics(chart, positive),
        "smc_fvg_confirmed": _binary_metrics(smc_fvg, positive),
        "chart_and_smc_fvg": _binary_metrics(dual, positive),
    }
    for metrics in variants.values():
        metrics["precision_lift_pp_vs_baseline"] = round(
            (metrics["precision"] - baseline_metrics["precision"]) * 100.0, 2
        )
        metrics["recall_change_pp_vs_baseline"] = round(
            (metrics["recall"] - baseline_metrics["recall"]) * 100.0, 2
        )
        metrics["false_positive_rate_change_pp_vs_baseline"] = round(
            (metrics["false_positive_rate"] - baseline_metrics["false_positive_rate"]) * 100.0, 2
        )
    return {
        "available": True,
        "threshold": threshold,
        "decision_authority": False,
        "live_threshold_auto_changed": False,
        "baseline": baseline_metrics,
        "variants": variants,
        "sec_replay_status": "not_reconstructed_historically",
        "causal_guards": {
            "fvg_shift_bars": 1,
            "swing_shift_bars": 20,
            "forward_labels_not_used_in_features": True,
        },
    }
