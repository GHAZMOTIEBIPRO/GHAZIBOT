from __future__ import annotations

from typing import Iterable

import pandas as pd

from .catalysts import CatalystEvent
from .settings import Settings
from .strict_catalysts import StrictCatalystScanner


def scan_official_events(
    settings: Settings,
    symbols: Iterable[str],
    *,
    lookback_days: int = 7,
) -> pd.DataFrame:
    """Scan SEC, FDA and ClinicalTrials.gov without secondary-news dependency.

    This is intentionally a thin official-only view over the existing catalyst
    scanner. Secondary/news/social sources can still nominate attention elsewhere,
    but failure or slowness of those sources cannot delay official validation.
    """

    allowed = {
        str(symbol).strip().upper()
        for symbol in symbols
        if str(symbol).strip()
    }
    if not allowed:
        return pd.DataFrame(columns=list(CatalystEvent.__dataclass_fields__))

    scanner = StrictCatalystScanner(settings)
    events: list[CatalystEvent] = []

    try:
        events.extend(scanner._sec_events(allowed))
    except Exception:
        # SEC and FDA fail independently. Evidence gaps are represented by the
        # absence of an official event rather than substituting an aggregator.
        pass

    company_names: dict[str, str] = {}
    try:
        _, company_names = scanner._ticker_map()
        events.extend(scanner._fda_events(allowed, company_names, lookback_days))
    except Exception:
        pass

    try:
        events.extend(
            scanner._clinicaltrials_events(
                allowed,
                company_names,
                lookback_days,
            )
        )
    except Exception:
        pass

    if not events:
        return pd.DataFrame(columns=list(CatalystEvent.__dataclass_fields__))

    frame = pd.DataFrame([event.__dict__ for event in events])

    def metadata(row: pd.Series) -> dict:
        key = (
            str(row.get("symbol") or ""),
            str(row.get("url") or ""),
            str(row.get("form") or ""),
        )
        meta = scanner._event_meta.get(key, {})
        return meta if isinstance(meta, dict) else {}

    meta_rows = frame.apply(metadata, axis=1, result_type="expand")
    for column in (
        "event_value",
        "share_count",
        "confidence",
        "purpose",
        "accession_number",
        "published_at",
        "observed_at",
    ):
        frame[column] = meta_rows[column] if column in meta_rows else None

    frame["event_date"] = pd.to_datetime(
        frame["event_date"], errors="coerce"
    ).dt.date.astype(str)
    frame["event_key"] = (
        frame["symbol"].fillna("")
        + "|"
        + frame["source"].fillna("")
        + "|"
        + frame["headline"].fillna("")
    )
    return (
        frame.sort_values(["score", "event_date"], ascending=[False, False])
        .drop_duplicates("event_key")
        .drop(columns="event_key")
        .reset_index(drop=True)
    )
