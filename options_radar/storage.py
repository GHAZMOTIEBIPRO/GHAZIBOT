from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


class SignalStore:
    """Persist alert deduplication and recent scans.

    JSON mode is used by default because GitHub Actions runners are ephemeral and
    the text file can be committed back to the repository. SQLite remains
    supported for local installations that explicitly configure a .sqlite3 path.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.json_mode = self.path.suffix.lower() == ".json"
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        if self.json_mode:
            if not self.path.exists():
                self._write_json({"schema_version": 1, "alerted_contracts": {}, "scan_signals": []})
            return
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS alerted_contracts (
                    contract_symbol TEXT PRIMARY KEY,
                    first_alerted_at TEXT NOT NULL,
                    score REAL NOT NULL,
                    vol_oi REAL,
                    source TEXT
                );
                CREATE TABLE IF NOT EXISTS scan_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scanned_at TEXT NOT NULL,
                    contract_symbol TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    score REAL NOT NULL,
                    rating TEXT,
                    entry_price REAL,
                    target_1 REAL,
                    target_2 REAL,
                    stop_price REAL,
                    source TEXT,
                    payload_json TEXT
                );
                """
            )
            connection.commit()

    def _read_json(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            payload = {"schema_version": 1, "alerted_contracts": {}, "scan_signals": []}
        payload.setdefault("schema_version", 1)
        payload.setdefault("alerted_contracts", {})
        payload.setdefault("scan_signals", [])
        return payload

    def _write_json(self, payload: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return None if pd.isna(result) else result

    def was_alerted(self, contract_symbol: str) -> bool:
        if self.json_mode:
            return contract_symbol in self._read_json()["alerted_contracts"]
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT 1 FROM alerted_contracts WHERE contract_symbol = ?",
                (contract_symbol,),
            ).fetchone()
        return row is not None

    def mark_alerted(
        self,
        contract_symbol: str,
        score: float,
        vol_oi: float | None,
        source: str,
    ) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        if self.json_mode:
            payload = self._read_json()
            payload["alerted_contracts"].setdefault(
                contract_symbol,
                {
                    "first_alerted_at": timestamp,
                    "score": float(score),
                    "vol_oi": self._safe_float(vol_oi),
                    "source": source,
                },
            )
            self._write_json(payload)
            return
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO alerted_contracts "
                "(contract_symbol, first_alerted_at, score, vol_oi, source) VALUES (?, ?, ?, ?, ?)",
                (
                    contract_symbol,
                    timestamp,
                    float(score),
                    None if pd.isna(vol_oi) else float(vol_oi),
                    source,
                ),
            )
            connection.commit()

    def log_signals(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        scanned_at = datetime.now(timezone.utc).isoformat()
        if self.json_mode:
            payload = self._read_json()
            rows = payload["scan_signals"]
            for _, row in frame.iterrows():
                rows.append(
                    {
                        "scanned_at": scanned_at,
                        "contract_symbol": str(row["contract_symbol"]),
                        "symbol": str(row["symbol"]),
                        "score": float(row["score"]),
                        "rating": str(row.get("rating", "")),
                        "entry_price": self._safe_float(row.get("entry_price")),
                        "target_1": self._safe_float(row.get("target_1")),
                        "target_2": self._safe_float(row.get("target_2")),
                        "stop_price": self._safe_float(row.get("stop_price")),
                        "source": str(row.get("source", "")),
                        "model_version": str(row.get("model_version", "")),
                    }
                )
            payload["scan_signals"] = rows[-2000:]
            self._write_json(payload)
            return

        rows = []
        for _, row in frame.iterrows():
            rows.append(
                (
                    scanned_at,
                    str(row["contract_symbol"]),
                    str(row["symbol"]),
                    float(row["score"]),
                    str(row.get("rating", "")),
                    float(row.get("entry_price", 0) or 0),
                    float(row.get("target_1", 0) or 0),
                    float(row.get("target_2", 0) or 0),
                    float(row.get("stop_price", 0) or 0),
                    str(row.get("source", "")),
                    row.to_json(date_format="iso", force_ascii=False),
                )
            )
        with closing(self._connect()) as connection:
            connection.executemany(
                "INSERT INTO scan_signals "
                "(scanned_at, contract_symbol, symbol, score, rating, entry_price, target_1, "
                "target_2, stop_price, source, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            connection.commit()
