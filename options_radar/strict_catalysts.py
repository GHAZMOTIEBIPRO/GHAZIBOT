from __future__ import annotations

from typing import Iterable

import pandas as pd

from .live_scanners import ResilientCatalystScanner


class StrictCatalystScanner(ResilientCatalystScanner):
    """Treat secondary news as supporting context, not an official trigger."""

    def scan(self, symbols: Iterable[str], lookback_days: int = 7) -> pd.DataFrame:
        frame = super().scan(symbols, lookback_days=lookback_days)
        if frame.empty:
            return frame

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
        return frame.sort_values(["score", "event_date"], ascending=[False, False]).reset_index(drop=True)
