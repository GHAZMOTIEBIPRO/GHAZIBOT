from __future__ import annotations

import json
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


class FreeContractVolumeStore:
    """Durable zero-key research history from provider-reported option volume.

    A row is stored only when the chain supplies an explicit last-trade
    timestamp. The collection timestamp is never substituted for market time.
    This history is research-only and cannot validate quote freshness, trade
    initiation, sweeps, opening/closing intent, or execution prices.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        max_sessions_per_contract: int = 30,
        max_contracts: int = 5000,
    ) -> None:
        self.path = Path(path)
        self.max_sessions_per_contract = max(5, int(max_sessions_per_contract))
        self.max_contracts = max(100, int(max_contracts))
        self._lock = threading.RLock()
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("schema_version", 1)
        payload.setdefault("updated_at", None)
        payload.setdefault("contracts", {})
        if not isinstance(payload["contracts"], dict):
            payload["contracts"] = {}
        return payload

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state["updated_at"] = datetime.now(timezone.utc).isoformat()
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(self.path)

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _trade_timestamp(row: pd.Series | dict[str, Any]) -> pd.Timestamp | None:
        raw = row.get("last_trade_timestamp")
        stamp = pd.to_datetime(raw, utc=True, errors="coerce")
        if pd.isna(stamp):
            return None
        return stamp

    def record_chain(
        self,
        frame: pd.DataFrame,
        *,
        collected_at: datetime | None = None,
        max_contracts_per_call: int = 120,
    ) -> dict[str, Any]:
        if frame is None or frame.empty:
            return {
                "seen": 0,
                "recorded": 0,
                "skipped_missing_trade_time": 0,
                "skipped_missing_volume": 0,
            }
        now = (collected_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        working = frame.copy()
        if "volume" in working:
            working["_free_store_volume"] = pd.to_numeric(
                working["volume"], errors="coerce"
            )
            working = working.sort_values(
                "_free_store_volume", ascending=False
            ).head(max(1, int(max_contracts_per_call)))

        audit = {
            "seen": int(len(working)),
            "recorded": 0,
            "skipped_missing_trade_time": 0,
            "skipped_missing_volume": 0,
            "skipped_missing_contract": 0,
            "research_only": True,
        }

        with self._lock:
            contracts = self._state.setdefault("contracts", {})
            for _, row in working.iterrows():
                contract = str(row.get("contract_symbol") or "").upper().replace(
                    " ", ""
                )
                if not contract:
                    audit["skipped_missing_contract"] += 1
                    continue
                volume = self._number(row.get("volume"))
                if volume is None or volume <= 0:
                    audit["skipped_missing_volume"] += 1
                    continue
                trade_time = self._trade_timestamp(row)
                if trade_time is None:
                    audit["skipped_missing_trade_time"] += 1
                    continue
                source = str(row.get("source") or "").strip() or "unknown"
                session_date = (
                    trade_time.tz_convert("America/New_York").date().isoformat()
                )
                contract_state = contracts.setdefault(
                    contract,
                    {
                        "symbol": str(row.get("symbol") or "").upper(),
                        "sessions": {},
                        "last_observed_at": None,
                    },
                )
                sessions = contract_state.setdefault("sessions", {})
                prior = (
                    sessions.get(session_date)
                    if isinstance(sessions.get(session_date), dict)
                    else {}
                )
                prior_volume = self._number(prior.get("volume"))
                stored_volume = max(volume, prior_volume or 0.0)
                sessions[session_date] = {
                    "volume": stored_volume,
                    "source": source,
                    "last_trade_timestamp": trade_time.isoformat(),
                    "observed_at": now.isoformat(),
                    "execution_grade": False,
                    "evidence": "explicit_last_trade_timestamp",
                    "note": (
                        "provider-reported daily option volume; unofficial/"
                        "delayed sources remain research-only"
                    ),
                }
                contract_state["last_observed_at"] = now.isoformat()
                contract_state["symbol"] = str(
                    row.get("symbol") or contract_state.get("symbol") or ""
                ).upper()
                ordered_dates = sorted(sessions)
                for old_date in ordered_dates[:-self.max_sessions_per_contract]:
                    sessions.pop(old_date, None)
                audit["recorded"] += 1

            if len(contracts) > self.max_contracts:
                ranked = sorted(
                    contracts.items(),
                    key=lambda item: str(
                        item[1].get("last_observed_at") or ""
                    ),
                    reverse=True,
                )
                self._state["contracts"] = dict(
                    ranked[: self.max_contracts]
                )
            self._save()
        return audit

    def history_frame(
        self,
        contract_symbol: str,
        *,
        maximum_sessions: int = 30,
    ) -> pd.DataFrame:
        contract = str(contract_symbol or "").upper().replace(" ", "")
        with self._lock:
            row = self._state.get("contracts", {}).get(contract, {})
            sessions = row.get("sessions", {}) if isinstance(row, dict) else {}
            if not isinstance(sessions, dict):
                return pd.DataFrame(columns=["Volume"])
            items = sorted(sessions.items())[-max(1, int(maximum_sessions)) :]

        records: list[dict[str, Any]] = []
        index: list[pd.Timestamp] = []
        for session_date, payload in items:
            if not isinstance(payload, dict):
                continue
            volume = self._number(payload.get("volume"))
            if volume is None or volume <= 0:
                continue
            stamp = pd.to_datetime(session_date, utc=True, errors="coerce")
            if pd.isna(stamp):
                continue
            index.append(stamp)
            records.append(
                {
                    "Volume": volume,
                    "source": payload.get("source"),
                    "last_trade_timestamp": payload.get(
                        "last_trade_timestamp"
                    ),
                    "execution_grade": False,
                }
            )
        if not records:
            return pd.DataFrame(columns=["Volume"])
        return pd.DataFrame(
            records, index=pd.DatetimeIndex(index)
        ).sort_index()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._state))
