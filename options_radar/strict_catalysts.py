from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

import pandas as pd

from .live_scanners import ResilientCatalystScanner
from .sec_efts import _cache_read, discover_sec_fulltext_events


class StrictCatalystScanner(ResilientCatalystScanner):
    """Prioritize grounded official events and demote secondary news."""

    def scan(self, symbols: Iterable[str], lookback_days: int = 7) -> pd.DataFrame:
        symbol_list = list(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()))
        frame = super().scan(symbol_list, lookback_days=lookback_days)

        # The dynamic-universe step normally refreshes EFTS first. Reuse that
        # cache here to avoid querying the SEC twice in one GitHub Actions run.
        fulltext_lookback = max(lookback_days, 14)
        cached_start = date.today() - timedelta(days=fulltext_lookback)
        efts_rows = _cache_read(cached_start)
        if not efts_rows:
            efts_rows = discover_sec_fulltext_events(
                self.settings,
                lookback_days=fulltext_lookback,
            )
        allowed = set(symbol_list)
        efts_rows = [
            row for row in efts_rows
            if str(row.get("symbol", "")).upper() in allowed
        ]
        if efts_rows:
            efts_frame = pd.DataFrame(efts_rows)
            frame = pd.concat([frame, efts_frame], ignore_index=True, sort=False)

        if frame.empty:
            for column in ("event_value", "confidence", "purpose"):
                frame[column] = pd.Series(dtype="object")
            return frame

        for column, default in (
            ("event_value", None),
            ("confidence", 0.0),
            ("purpose", ""),
            ("evidence", ""),
            ("category", ""),
            ("event_date", ""),
            ("source", ""),
            ("url", ""),
            ("form", ""),
        ):
            if column not in frame.columns:
                frame[column] = default

        yahoo = frame["source"].astype(str).str.contains("Yahoo", case=False, na=False)
        positive = yahoo & (pd.to_numeric(frame["score"], errors="coerce") > 0)
        negative = yahoo & (pd.to_numeric(frame["score"], errors="coerce") < 0)
        frame.loc[positive, "score"] = pd.to_numeric(
            frame.loc[positive, "score"], errors="coerce"
        ).clip(upper=8)
        frame.loc[negative, "score"] = pd.to_numeric(
            frame.loc[negative, "score"], errors="coerce"
        ).clip(lower=-12)
        frame.loc[yahoo, "confidence"] = 0.35
        frame.loc[yahoo, "purpose"] = "secondary_news"
        frame.loc[yahoo, "category"] = frame.loc[yahoo, "category"].astype(str).map(
            lambda value: f"Secondary mention — {value}"
        )
        frame.loc[yahoo, "evidence"] = frame.loc[yahoo, "evidence"].astype(str).map(
            lambda value: f"{value}; secondary source — verify SEC/company release"
        )

        fda = frame["source"].astype(str).str.contains("FDA", case=False, na=False)
        frame.loc[fda, "confidence"] = pd.to_numeric(
            frame.loc[fda, "confidence"], errors="coerce"
        ).fillna(0.62).clip(upper=0.72)
        frame.loc[fda & frame["purpose"].astype(str).eq(""), "purpose"] = "fda_record"

        frame["confidence"] = pd.to_numeric(frame["confidence"], errors="coerce").fillna(0.0)
        frame["score"] = pd.to_numeric(frame["score"], errors="coerce").fillna(0.0)
        frame["source_priority"] = frame["source"].astype(str).map(
            lambda value: 4 if "Full-Text" in value else 3 if "SEC" in value else 2 if "FDA" in value else 1
        )
        frame["absolute_score"] = frame["score"].abs()
        frame = frame.sort_values(
            ["event_date", "source_priority", "confidence", "absolute_score"],
            ascending=[False, False, False, False],
        )
        frame = frame.drop_duplicates(
            subset=["symbol", "url", "purpose"],
            keep="first",
        )
        return frame.drop(columns=["source_priority", "absolute_score"]).reset_index(drop=True)
