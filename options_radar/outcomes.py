from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .hybrid_fetcher import DataFetcher
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
_TERMINAL = {"failed", "success", "ambiguous"}


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(result) else result


def _timestamp(value: Any) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    return None if pd.isna(parsed) else parsed


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
            LOGGER.warning("Ignoring malformed JSONL row in %s", path)
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


def _normalise_path_bars(bars: pd.DataFrame, signaled_at: pd.Timestamp) -> pd.DataFrame:
    if bars is None or bars.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    frame = bars.copy()
    frame.index = pd.to_datetime(frame.index, utc=True, errors="coerce")
    for column in ("Open", "High", "Low", "Close"):
        frame[column] = pd.to_numeric(frame.get(column), errors="coerce")
    frame = frame[~frame.index.isna()]
    return frame[frame.index >= signaled_at].dropna(
        subset=["Open", "High", "Low", "Close"]
    ).sort_index()


def _path_result(
    *,
    bars: pd.DataFrame,
    signal_time: Any,
    target_1: float | None,
    target_2: float | None,
    stop: float | None,
    direction: str,
    bar_resolution: str,
    path_kind: str,
) -> dict[str, Any]:
    """Evaluate target/stop order without allowing a later close to erase a stop.

    `direction="up"` means targets are touched by High and stop by Low.
    `direction="down"` means targets are touched by Low and stop by High.
    A same-bar stop/target collision is explicitly ambiguous because OHLC data
    cannot reveal the intrabar sequence.
    """

    signaled_at = _timestamp(signal_time)
    if signaled_at is None:
        return {
            "path_status": "invalid_signal_time",
            "path_kind": path_kind,
            "bar_resolution": bar_resolution,
            "terminal_outcome": "open",
        }
    frame = _normalise_path_bars(bars, signaled_at)
    if frame.empty:
        return {
            "path_status": "no_bars_after_signal",
            "path_kind": path_kind,
            "bar_resolution": bar_resolution,
            "terminal_outcome": "open",
        }

    target_1_at: pd.Timestamp | None = None
    target_2_at: pd.Timestamp | None = None
    stop_at: pd.Timestamp | None = None
    collision_at: pd.Timestamp | None = None

    for timestamp, row in frame.iterrows():
        high = float(row["High"])
        low = float(row["Low"])
        if direction == "down":
            target_1_hit = target_1 is not None and low <= target_1
            target_2_hit = target_2 is not None and low <= target_2
            stop_hit = stop is not None and high >= stop
        else:
            target_1_hit = target_1 is not None and high >= target_1
            target_2_hit = target_2 is not None and high >= target_2
            stop_hit = stop is not None and low <= stop

        if target_1_at is None and target_1_hit:
            target_1_at = timestamp
        if target_2_at is None and target_2_hit:
            target_2_at = timestamp
        if stop_at is None and stop_hit:
            stop_at = timestamp
        if stop_hit and target_1_hit:
            collision_at = timestamp
            break
        if stop_hit or target_1_hit:
            # The first decisive bar determines the terminal classification.
            break

    if collision_at is not None:
        order = "ambiguous_same_bar"
        terminal = "ambiguous"
        reason = "stop_and_target_1_touched_same_bar"
        terminal_at = collision_at
    elif stop_at is not None and target_1_at is None:
        order = "stop_first"
        terminal = "failed"
        reason = "stopped_out_before_target_1"
        terminal_at = stop_at
    elif target_2_at is not None and stop_at is None:
        order = "target_2_first"
        terminal = "success"
        reason = "target_2_reached_before_stop"
        terminal_at = target_2_at
    elif target_1_at is not None and stop_at is None:
        order = "target_1_first"
        terminal = "success"
        reason = "target_1_reached_before_stop"
        terminal_at = target_1_at
    else:
        order = "open"
        terminal = "open"
        reason = "no_decisive_level_reached"
        terminal_at = None

    return {
        "path_status": "evaluated",
        "path_kind": path_kind,
        "bar_resolution": bar_resolution,
        "first_target_1_at": target_1_at.isoformat() if target_1_at is not None else None,
        "first_target_2_at": target_2_at.isoformat() if target_2_at is not None else None,
        "first_stop_at": stop_at.isoformat() if stop_at is not None else None,
        "ambiguous_same_bar": collision_at is not None,
        "outcome_order": order,
        "terminal_outcome": terminal,
        "terminal_reason": reason,
        "terminal_at": terminal_at.isoformat() if terminal_at is not None else None,
        "bars_evaluated": int(len(frame)),
    }


def evaluate_underlying_path(
    signal: dict[str, Any],
    bars: pd.DataFrame,
    *,
    bar_resolution: str = "5m",
) -> dict[str, Any]:
    side = str(signal.get("option_type", "call")).lower()
    return _path_result(
        bars=bars,
        signal_time=signal.get("signal_time"),
        target_1=_safe_float(signal.get("underlying_target_1")),
        target_2=_safe_float(signal.get("underlying_target_2")),
        stop=_safe_float(signal.get("underlying_invalidation")),
        direction="down" if side == "put" else "up",
        bar_resolution=bar_resolution,
        path_kind="underlying",
    )


def evaluate_option_path(
    signal: dict[str, Any],
    bars: pd.DataFrame,
    *,
    bar_resolution: str = "1d",
) -> dict[str, Any]:
    # CALL and PUT premiums both win by rising and stop by falling.
    return _path_result(
        bars=bars,
        signal_time=signal.get("signal_time"),
        target_1=_safe_float(signal.get("target_1")),
        target_2=_safe_float(signal.get("target_2")),
        stop=_safe_float(signal.get("stop_price")),
        direction="up",
        bar_resolution=bar_resolution,
        path_kind="option_contract",
    )


class SignalJournal:
    """Persist signals and path-dependent paper outcomes.

    Actual option-contract OHLC is preferred. Underlying OHLC is a documented
    proxy only when contract history is unavailable. Terminal outcomes are
    immutable: a stop-first failure cannot later become a win.
    """

    def __init__(
        self,
        signals_path: Path,
        outcomes_path: Path,
        model_version: str,
        *,
        settings: Settings | None = None,
        fetcher: DataFetcher | None = None,
    ):
        self.signals_path = Path(signals_path)
        self.outcomes_path = Path(outcomes_path)
        self.model_version = model_version
        self.settings = settings or Settings()
        self.fetcher = fetcher or DataFetcher(self.settings)
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
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
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
                "market_regime": row.get("market_regime", ""),
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
        default = {"schema_version": 3, "updated_at": None, "signals": {}}
        if not self.outcomes_path.exists():
            return default
        try:
            payload = json.loads(self.outcomes_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default
        if not isinstance(payload, dict):
            return default
        payload["schema_version"] = 3
        payload.setdefault("signals", {})
        return payload

    def _active_signals(self, now: datetime) -> list[dict[str, Any]]:
        max_age = int(getattr(self.settings, "outcome_max_age_days", 60))
        active: list[dict[str, Any]] = []
        for signal in reversed(_read_jsonl(self.signals_path)):
            signaled_at = _timestamp(signal.get("signal_time"))
            if signaled_at is None:
                continue
            age_days = (pd.Timestamp(now) - signaled_at).total_seconds() / 86400
            if -0.1 <= age_days <= max_age:
                active.append(signal)
            if len(active) >= 300:
                break
        return active

    def _fetch_option_chains(
        self, signals: list[dict[str, Any]]
    ) -> dict[str, Any]:
        symbols = list(dict.fromkeys(str(row.get("symbol", "")).upper() for row in signals if row.get("symbol")))
        results: dict[str, Any] = {}
        for symbol in symbols[:30]:
            try:
                results[symbol] = self.fetcher.fetch_option_chain(
                    symbol, apply_guards=False
                )
            except Exception as exc:
                LOGGER.warning("Outcome option-chain refresh failed for %s: %s", symbol, exc)
        return results

    @staticmethod
    def _mid(row: pd.Series) -> float | None:
        bid = _safe_float(row.get("bid"))
        ask = _safe_float(row.get("ask"))
        last = _safe_float(row.get("last"))
        if bid is not None and ask is not None and bid > 0 and ask > bid:
            return (bid + ask) / 2.0
        return last if last is not None and last > 0 else None

    def _current_quotes(
        self,
        signals: list[dict[str, Any]],
        chains: dict[str, Any],
    ) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
        quotes: dict[str, float] = {}
        audits: dict[str, dict[str, Any]] = {}
        for signal in signals:
            symbol = str(signal.get("symbol", "")).upper()
            contract = str(signal.get("contract_symbol", ""))
            result = chains.get(symbol)
            if result is None or result.data.empty:
                continue
            matches = result.data[result.data["contract_symbol"].astype(str) == contract]
            if matches.empty:
                continue
            mid = self._mid(matches.iloc[0])
            if mid is not None:
                quotes[contract] = mid
                audits[contract] = result.audit_dict()
        return quotes, audits

    def _option_path(
        self, signal: dict[str, Any], now: datetime
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        contract = str(signal.get("contract_symbol", ""))
        start = _timestamp(signal.get("signal_time"))
        if not contract or start is None:
            return None, None
        # Prefer 5-minute contract bars; daily is a fallback with explicit ambiguity.
        for interval in ("5m", "1d"):
            try:
                result = self.fetcher.fetch_option_history(
                    contract,
                    start=start.to_pydatetime(),
                    end=now,
                    interval=interval,
                )
                path = evaluate_option_path(signal, result.data, bar_resolution=interval)
                if path.get("path_status") == "evaluated":
                    return path, result.audit_dict()
            except Exception as exc:
                LOGGER.debug("Option path %s %s failed: %s", contract, interval, exc)
        return None, None

    def _underlying_path(
        self, signal: dict[str, Any], now: datetime
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        symbol = str(signal.get("symbol", "")).upper()
        start = _timestamp(signal.get("signal_time"))
        if not symbol or start is None:
            return None, None
        for interval in ("5m", "1d"):
            try:
                result = self.fetcher.fetch_stock_bars(
                    symbol,
                    start=start.to_pydatetime(),
                    end=now,
                    interval=interval,
                )
                path = evaluate_underlying_path(signal, result.data, bar_resolution=interval)
                if path.get("path_status") == "evaluated":
                    return path, result.audit_dict()
            except Exception as exc:
                LOGGER.debug("Underlying path %s %s failed: %s", symbol, interval, exc)
        return None, None

    @staticmethod
    def _choose_path(
        option_path: dict[str, Any] | None,
        underlying_path: dict[str, Any] | None,
    ) -> tuple[dict[str, Any] | None, str]:
        if option_path is not None:
            return option_path, "option_contract"
        if underlying_path is not None:
            return underlying_path, "underlying_proxy"
        return None, "unavailable"

    @staticmethod
    def _apply_terminal_state(
        state: dict[str, Any], path: dict[str, Any], basis: str
    ) -> None:
        existing = str(state.get("terminal_outcome", "open"))
        existing_basis = str(state.get("outcome_basis", ""))
        if existing in _TERMINAL and not (
            existing_basis == "underlying_proxy" and basis == "option_contract"
        ):
            # Preserve the first terminal classification within the best available basis.
            return
        state.update(path)
        state["outcome_basis"] = basis

    def update_outcomes(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        active = self._active_signals(now)
        outcomes = self._read_outcomes()
        chains = self._fetch_option_chains(active)
        quotes, quote_audits = self._current_quotes(active, chains)

        for signal in active:
            signal_id = str(signal.get("signal_id", ""))
            if not signal_id:
                continue
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
                    "terminal_outcome": "open",
                },
            )

            needs_contract_upgrade = state.get("outcome_basis") != "option_contract"
            if (
                str(state.get("terminal_outcome", "open")) not in _TERMINAL
                or needs_contract_upgrade
            ):
                option_path, option_audit = self._option_path(signal, now)
                underlying_path, underlying_audit = self._underlying_path(signal, now)
                path, basis = self._choose_path(option_path, underlying_path)
                if path is not None:
                    self._apply_terminal_state(state, path, basis)
                state["path_audit"] = {
                    "option_contract": option_audit,
                    "underlying_proxy": underlying_audit,
                }

            current = quotes.get(contract)
            if current is None or entry is None or entry <= 0:
                continue
            state["quote_audit"] = quote_audits.get(contract)
            state["observations"] = int(state.get("observations", 0)) + 1
            state["last_updated"] = now.isoformat()
            state["last_observed"] = round(current, 6)
            previous_max = _safe_float(state.get("max_observed")) or current
            previous_min = _safe_float(state.get("min_observed")) or current
            state["max_observed"] = round(max(previous_max, current), 6)
            state["min_observed"] = round(min(previous_min, current), 6)
            state["mfe_pct"] = round((state["max_observed"] / entry - 1.0) * 100.0, 4)
            state["mae_pct"] = round((state["min_observed"] / entry - 1.0) * 100.0, 4)
            state["target_1_observed_snapshot"] = bool(
                _safe_float(signal.get("target_1")) is not None
                and state["max_observed"] >= float(signal["target_1"])
            )
            state["target_2_observed_snapshot"] = bool(
                _safe_float(signal.get("target_2")) is not None
                and state["max_observed"] >= float(signal["target_2"])
            )
            state["stop_observed_snapshot"] = bool(
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
        rows = list((outcomes.get("signals") or {}).values())
        priced = [row for row in rows if int(row.get("observations", 0)) > 0]
        evaluated = [row for row in rows if row.get("path_status") == "evaluated"]
        mfe = [float(row.get("mfe_pct", 0.0)) for row in priced]
        mae = [float(row.get("mae_pct", 0.0)) for row in priced]
        return {
            "tracked_signals": len(rows),
            "priced_signals": len(priced),
            "path_evaluated": len(evaluated),
            "successful": sum(row.get("terminal_outcome") == "success" for row in evaluated),
            "stopped_out": sum(row.get("terminal_outcome") == "failed" for row in evaluated),
            "ambiguous": sum(row.get("terminal_outcome") == "ambiguous" for row in evaluated),
            "open": sum(row.get("terminal_outcome", "open") == "open" for row in rows),
            "option_contract_basis": sum(row.get("outcome_basis") == "option_contract" for row in evaluated),
            "underlying_proxy_basis": sum(row.get("outcome_basis") == "underlying_proxy" for row in evaluated),
            "average_mfe_pct": round(sum(mfe) / len(mfe), 4) if mfe else None,
            "average_mae_pct": round(sum(mae) / len(mae), 4) if mae else None,
            "measurement_note": (
                "Path-dependent paper tracking. Contract OHLC is preferred; underlying OHLC "
                "is a documented fallback. Stop-first is terminal. Same-bar stop/target is "
                "ambiguous and never counted as a win."
            ),
        }
