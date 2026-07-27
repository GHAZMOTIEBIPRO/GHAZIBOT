"""Backward-compatible facade for the Phase 5 outcome engine."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .outcomes import (
    CHECKPOINTS_MINUTES,
    SignalJournal as _SignalJournal,
    evaluate_option_path,
    evaluate_underlying_path as _evaluate_underlying_path,
)


def _first_touch(
    bars: pd.DataFrame,
    signal_time: Any,
    *,
    column: str,
    level: float | None,
    comparison: str,
) -> str | None:
    if level is None or bars is None or bars.empty or column not in bars:
        return None
    signaled_at = pd.to_datetime(signal_time, utc=True, errors="coerce")
    if pd.isna(signaled_at):
        return None
    frame = bars.copy()
    frame.index = pd.to_datetime(frame.index, utc=True, errors="coerce")
    frame = frame[(~frame.index.isna()) & (frame.index >= signaled_at)]
    values = pd.to_numeric(frame[column], errors="coerce")
    mask = values <= level if comparison == "le" else values >= level
    touched = frame.index[mask.fillna(False)]
    return touched[0].isoformat() if len(touched) else None


def evaluate_underlying_path(
    signal: dict[str, Any],
    bars: pd.DataFrame,
    *,
    bar_resolution: str = "5m",
) -> dict[str, Any]:
    """Preserve Phase 4 audit timestamps while using Phase 5 terminal logic."""
    result = _evaluate_underlying_path(
        signal, bars, bar_resolution=bar_resolution
    )
    side = str(signal.get("option_type", "call")).lower()
    try:
        stop = float(signal.get("underlying_invalidation"))
    except (TypeError, ValueError):
        stop = None
    if result.get("first_stop_at") is None:
        result["first_stop_at"] = _first_touch(
            bars,
            signal.get("signal_time"),
            column="High" if side == "put" else "Low",
            level=stop,
            comparison="ge" if side == "put" else "le",
        )
    return result


class SignalJournal(_SignalJournal):
    """Compatibility hooks for Phase 4 tests and integrations."""

    def _fetch_quotes(self, signals: list[dict[str, Any]]) -> dict[str, float]:
        chains = super()._fetch_option_chains(signals)
        quotes, audits = super()._current_quotes(signals, chains)
        self._compat_quote_audits = audits
        return quotes

    def _fetch_option_chains(self, signals: list[dict[str, Any]]) -> dict[str, Any]:
        # Route the base updater through the legacy quote hook so callers can
        # monkeypatch `_fetch_quotes` without creating network traffic.
        return {"__phase5_quotes__": self._fetch_quotes(signals)}

    def _current_quotes(
        self,
        signals: list[dict[str, Any]],
        chains: dict[str, Any],
    ) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
        if "__phase5_quotes__" in chains:
            return (
                chains["__phase5_quotes__"],
                getattr(self, "_compat_quote_audits", {}),
            )
        return super()._current_quotes(signals, chains)


__all__ = [
    "CHECKPOINTS_MINUTES",
    "SignalJournal",
    "evaluate_option_path",
    "evaluate_underlying_path",
]
