from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


class SignalStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
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

    def was_alerted(self, contract_symbol: str) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT 1 FROM alerted_contracts WHERE contract_symbol = ?",
                (contract_symbol,),
            ).fetchone()
        return row is not None

    def mark_alerted(self, contract_symbol: str, score: float,
                     vol_oi: float | None, source: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO alerted_contracts "
                "(contract_symbol, first_alerted_at, score, vol_oi, source) VALUES (?, ?, ?, ?, ?)",
                (contract_symbol, datetime.now(timezone.utc).isoformat(), float(score),
                 None if pd.isna(vol_oi) else float(vol_oi), source),
            )
            connection.commit()

    def log_signals(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        scanned_at = datetime.now(timezone.utc).isoformat()
        rows = []
        for _, row in frame.iterrows():
            rows.append((
                scanned_at, str(row["contract_symbol"]), str(row["symbol"]),
                float(row["score"]), str(row.get("rating", "")),
                float(row.get("entry_price", 0) or 0), float(row.get("target_1", 0) or 0),
                float(row.get("target_2", 0) or 0), float(row.get("stop_price", 0) or 0),
                str(row.get("source", "")), row.to_json(date_format="iso", force_ascii=False),
            ))
        with closing(self._connect()) as connection:
            connection.executemany(
                "INSERT INTO scan_signals "
                "(scanned_at, contract_symbol, symbol, score, rating, entry_price, target_1, "
                "target_2, stop_price, source, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            connection.commit()
