from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

from .market_bars import BarResult, get_intraday_history
from .settings import Settings

LOGGER = logging.getLogger(__name__)
CHECKPOINTS_MINUTES = {
    "30m": 30,
    "60m": 60,
    "1d": 24 * 60,
    "3d": 3 * 24 * 60,
    "5d": 5 * 24 * 60,
    "10d": 10 * 24 * 60,
}


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(result) else result


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _timestamp(value: Any) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    return None if pd.isna(parsed) else parsed


def evaluate_underlying_path(signal: dict[str, Any], bars: pd.DataFrame) -> dict[str, Any]:
    """Determine which underlying target/stop was touched first.

    Five-minute OHLC bars reduce snapshot bias. If target and stop are both touched
    inside the same bar, ordering is unknowable and the result is marked ambiguous.
    """

    if bars is None or bars.empty:
        return {"path_status": "no_bars", "bar_resolution": "5m"}
    signaled_at = _timestamp(signal.get("signal_time"))
    if signaled_at is None:
        return {"path_status": "invalid_signal_time", "bar_resolution": "5m"}
    frame = bars.copy()
    frame.index = pd.to_datetime(frame.index, utc=True, errors="coerce")
    frame = frame[frame.index >= signaled_at].dropna(subset=["High", "Low"])
    if frame.empty:
        return {"path_status": "no_bars_after_signal", "bar_resolution": "5m"}

    side = str(signal.get("option_type", "call")).lower()
    target_1 = _safe_float(signal.get("underlying_target_1"))
    target_2 = _safe_float(signal.get("underlying_target_2"))
    stop = _safe_float(signal.get("underlying_invalidation"))

    def first_touch(level: float | None, field: str, operator: str) -> pd.Timestamp | None:
        if level is None:
            return None
        values = pd.to_numeric(frame[field], errors="coerce")
        mask = values >= level if operator == ">=" else values <= level
        hits = frame.index[mask.fillna(False)]
        return hits[0] if len(hits) else None

    if side == "put":
        target_1_at = first_touch(target_1, "Low", "<=")
        target_2_at = first_touch(target_2, "Low", "<=")
        stop_at = first_touch(stop, "High", ">=")
    else:
        target_1_at = first_touch(target_1, "High", ">=")
        target_2_at = first_touch(target_2, "High", ">=")
        stop_at = first_touch(stop, "Low", "<=")

    same_bar = stop_at is not None and target_1_at is not None and stop_at == target_1_at
    if same_bar:
        order = "ambiguous_same_bar"
    elif stop_at is not None and (target_1_at is None or stop_at < target_1_at):
        order = "stop_first"
    elif target_2_at is not None and (stop_at is None or target_2_at < stop_at):
        order = "target_2_first"
    elif target_1_at is not None and (stop_at is None or target_1_at < stop_at):
        order = "target_1_first"
    else:
        order = "open"

    return {
        "path_status": "evaluated",
        "bar_resolution": "5m",
        "first_target_1_at": target_1_at.isoformat() if target_1_at is not None else None,
        "first_target_2_at": target_2_at.isoformat() if target_2_at is not None else None,
        "first_stop_at": stop_at.isoformat() if stop_at is not None else None,
        "ambiguous_same_bar": same_bar,
        "outcome_order": order,
        "bars_evaluated": int(len(frame)),
    }


class SignalJournal:
    """Persist signals, option snapshots and path-aware underlying outcomes."""

    def __init__(self, signals_path: Path, outcomes_path: Path, model_version: str):
        self.signals_path = Path(signals_path)
        self.outcomes_path = Path(outcomes_path)
        self.model_version = model_version
        self.settings = Settings()
        self.signals_path.parent.mkdir(parents=True, exist_ok=True)
        self.outcomes_path.parent.mkdir(parents=True, exist_ok=True)

    def _signal_id(self, row: pd.Series, generated_at: datetime) -> str:
        key = "|".join([
            generated_at.date().isoformat(),
            str(row.get("contract_symbol", "")),
            self.model_version,
        ])
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _signal_class(row: pd.Series) -> str:
        if bool(row.get("new_setup_candidate", False)):
            return "strong"
        score = _safe_float(row.get("score")) or 0.0
        return "qualified" if score >= 65 else "watchlist"

    def record(self, frame: pd.DataFrame, generated_at: datetime) -> int:
        if frame is None or frame.empty:
            return 0
        existing = {str(row.get("signal_id")) for row in _read_jsonl(self.signals_path)}
        new_rows: list[dict[str, Any]] = []
        for _, row in frame.iterrows():
            signal_id = self._signal_id(row, generated_at)
            if signal_id in existing:
                continue
            record = {
                "signal_id": signal_id,
                "model_version": self.model_version,
                "signal_time": generated_at.isoformat(),
                "signal_class": self._signal_class(row),
                "symbol": str(row.get("symbol", "")),
                "contract_symbol": str(row.get("contract_symbol", "")),
                "expiration": str(row.get("expiration", ""))[:10],
                "option_type": str(row.get("option_type", "")),
                "strike": _safe_float(row.get("strike")),
                "stock_price": _safe_float(row.get("underlying_price")),
                "bid": _safe_float(row.get("bid")),
                "ask": _safe_float(row.get("ask")),
                "entry_price": _safe_float(row.get("entry_price")),
                "target_1": _safe_float(row.get("target_1")),
                "target_2": _safe_float(row.get("target_2")),
                "stop_price": _safe_float(row.get("stop_price")),
                "underlying_target_1": _safe_float(row.get("underlying_target_1")),
                "underlying_target_2": _safe_float(row.get("underlying_target_2")),
                "underlying_invalidation": _safe_float(row.get("underlying_invalidation")),
                "score": _safe_float(row.get("score")),
                "rating": str(row.get("rating", "")),
                "dte": _safe_float(row.get("dte")),
                "delta": _safe_float(row.get("delta")),
                "iv": _safe_float(row.get("iv")),
                "spread_pct": _safe_float(row.get("spread_pct")),
                "vol_oi": _safe_float(row.get("vol_oi")),
                "market_regime": str(row.get("market_regime", "")),
                "catalyst": str(row.get("catalyst", "")),
                "source": str(row.get("source", "")),
                "freshness_label": str(row.get("freshness_label", "")),
                "data_status": str(row.get("data_status", "")),
                "last_trade_age_minutes": _safe_float(row.get("last_trade_age_minutes")),
            }
            new_rows.append(record)
            existing.add(signal_id)
        if new_rows:
            with self.signals_path.open("a", encoding="utf-8") as handle:
                for record in new_rows:
                    handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        return len(new_rows)

    def _read_outcomes(self) -> dict[str, Any]:
        if not self.outcomes_path.exists():
            return {"schema_version": 2, "updated_at": None, "signals": {}}
        try:
            payload = json.loads(self.outcomes_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {"schema_version": 2, "updated_at": None, "signals": {}}
        payload["schema_version"] = 2
        payload.setdefault("signals", {})
        return payload

    @staticmethod
    def _quote_mid(row: pd.Series) -> float | None:
        bid = _safe_float(row.get("bid"))
        ask = _safe_float(row.get("ask"))
        last = _safe_float(row.get("lastPrice"))
        if bid is not None and ask is not None and bid > 0 and ask > bid:
            return (bid + ask) / 2.0
        return last if last is not None and last > 0 else None

    def _fetch_quotes(self, signals: list[dict[str, Any]], max_groups: int = 24) -> dict[str, float]:
        groups: dict[tuple[str, str], list[str]] = {}
        for signal in signals:
            symbol = str(signal.get("symbol", ""))
            expiry = str(signal.get("expiration", ""))[:10]
            contract = str(signal.get("contract_symbol", ""))
            if symbol and expiry and contract:
                groups.setdefault((symbol, expiry), []).append(contract)
        quotes: dict[str, float] = {}
        for (symbol, expiry), contracts in list(groups.items())[:max_groups]:
            try:
                chain = yf.Ticker(symbol).option_chain(expiry)
            except Exception as exc:
                LOGGER.debug("Outcome quote failed for %s %s: %s", symbol, expiry, exc)
                continue
            frames = [frame for frame in (chain.calls, chain.puts) if frame is not None and not frame.empty]
            if not frames:
                continue
            combined = pd.concat(frames, ignore_index=True)
            if "contractSymbol" not in combined.columns:
                continue
            indexed = combined.set_index(combined["contractSymbol"].astype(str), drop=False)
            for contract in contracts:
                if contract not in indexed.index:
                    continue
                row = indexed.loc[contract]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                mid = self._quote_mid(row)
                if mid is not None:
                    quotes[contract] = mid
        return quotes

    def _fetch_paths(self, signals: list[dict[str, Any]], now: datetime,
                     max_symbols: int = 24) -> dict[str, BarResult]:
        earliest: dict[str, datetime] = {}
        for signal in signals:
            symbol = str(signal.get("symbol", ""))
            signaled_at = _timestamp(signal.get("signal_time"))
            if not symbol or signaled_at is None:
                continue
            value = signaled_at.to_pydatetime()
            earliest[symbol] = min(earliest.get(symbol, value), value)
        results: dict[str, BarResult] = {}
        for symbol, start in list(earliest.items())[:max_symbols]:
            try:
                results[symbol] = get_intraday_history(self.settings, symbol, start, now)
            except Exception as exc:
                LOGGER.debug("Intraday path failed for %s: %s", symbol, exc)
        return results

    def update_outcomes(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        signals = _read_jsonl(self.signals_path)
        active: list[dict[str, Any]] = []
        for signal in reversed(signals):
            signaled_at = _timestamp(signal.get("signal_time"))
            if signaled_at is None:
                continue
            age_days = (pd.Timestamp(now) - signaled_at).total_seconds() / 86400
            if -0.1 <= age_days <= 14:
                active.append(signal)
            if len(active) >= 200:
                break

        outcomes = self._read_outcomes()
        quotes = self._fetch_quotes(active)
        paths = self._fetch_paths(active, now)
        for signal in active:
            signal_id = str(signal["signal_id"])
            contract = str(signal.get("contract_symbol", ""))
            entry = _safe_float(signal.get("entry_price"))
            state = outcomes["signals"].setdefault(
                signal_id,
                {
                    "contract_symbol": contract,
                    "symbol": signal.get("symbol"),
                    "signal_time": signal.get("signal_time"),
                    "entry_price": entry,
                    "target_1": signal.get("target_1"),
                    "target_2": signal.get("target_2"),
                    "stop_price": signal.get("stop_price"),
                    "underlying_target_1": signal.get("underlying_target_1"),
                    "underlying_target_2": signal.get("underlying_target_2"),
                    "underlying_invalidation": signal.get("underlying_invalidation"),
                    "observations": 0,
                    "checkpoints": {},
                },
            )

            path = paths.get(str(signal.get("symbol", "")))
            if path is not None:
                state.update(evaluate_underlying_path(signal, path.frame))
                state["path_source"] = path.source
                state["path_freshness"] = path.freshness

            current = quotes.get(contract)
            if current is None or entry is None or entry <= 0:
                continue
            state["observations"] = int(state.get("observations", 0)) + 1
            state["last_updated"] = now.isoformat()
            state["last_observed"] = round(current, 6)
            previous_max = _safe_float(state.get("max_observed")) or current
            previous_min = _safe_float(state.get("min_observed")) or current
            state["max_observed"] = round(max(previous_max, current), 6)
            state["min_observed"] = round(min(previous_min, current), 6)
            state["mfe_pct"] = round((state["max_observed"] / entry - 1.0) * 100.0, 4)
            state["mae_pct"] = round((state["min_observed"] / entry - 1.0) * 100.0, 4)
            state["target_1_observed"] = bool(
                _safe_float(signal.get("target_1")) is not None
                and state["max_observed"] >= float(signal["target_1"])
            )
            state["target_2_observed"] = bool(
                _safe_float(signal.get("target_2")) is not None
                and state["max_observed"] >= float(signal["target_2"])
            )
            state["stop_observed"] = bool(
                _safe_float(signal.get("stop_price")) is not None
                and state["min_observed"] <= float(signal["stop_price"])
            )
            signaled_at = _timestamp(signal.get("signal_time"))
            if signaled_at is None:
                continue
            elapsed_minutes = (pd.Timestamp(now) - signaled_at).total_seconds() / 60.0
            checkpoints = state.setdefault("checkpoints", {})
            for label, threshold in CHECKPOINTS_MINUTES.items():
                if elapsed_minutes >= threshold and label not in checkpoints:
                    checkpoints[label] = {
                        "observed_at": now.isoformat(),
                        "price": round(current, 6),
                        "return_pct": round((current / entry - 1.0) * 100.0, 4),
                    }
        outcomes["updated_at"] = now.isoformat()
        _write_json(self.outcomes_path, outcomes)
        return self.summary(outcomes)

    @staticmethod
    def summary(outcomes: dict[str, Any]) -> dict[str, Any]:
        rows = list(outcomes.get("signals", {}).values())
        priced = [row for row in rows if int(row.get("observations", 0)) > 0]
        path_rows = [row for row in rows if row.get("path_status") == "evaluated"]
        mfe = [float(row.get("mfe_pct", 0.0)) for row in priced]
        mae = [float(row.get("mae_pct", 0.0)) for row in priced]
        return {
            "tracked_signals": len(rows),
            "priced_signals": len(priced),
            "target_1_observed": sum(bool(row.get("target_1_observed")) for row in priced),
            "target_2_observed": sum(bool(row.get("target_2_observed")) for row in priced),
            "stop_observed": sum(bool(row.get("stop_observed")) for row in priced),
            "path_evaluated": len(path_rows),
            "path_target_1_first": sum(row.get("outcome_order") == "target_1_first" for row in path_rows),
            "path_target_2_first": sum(row.get("outcome_order") == "target_2_first" for row in path_rows),
            "path_stop_first": sum(row.get("outcome_order") == "stop_first" for row in path_rows),
            "path_ambiguous": sum(row.get("outcome_order") == "ambiguous_same_bar" for row in path_rows),
            "average_mfe_pct": round(sum(mfe) / len(mfe), 4) if mfe else None,
            "average_mae_pct": round(sum(mae) / len(mae), 4) if mae else None,
            "measurement_note": (
                "Option prices are observed snapshots. Underlying target/stop order uses "
                "five-minute OHLC bars; same-bar touches remain ambiguous and are not wins."
            ),
        }
