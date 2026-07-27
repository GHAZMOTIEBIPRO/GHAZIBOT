from __future__ import annotations

from typing import Any

import pandas as pd

from . import hybrid_fetcher, phase60_sources
from .hybrid_fetcher import DataUnavailableError, FetchAttempt, FetchResult
from .phase61_providers import polygon_option_chain

_ORIGINAL_OPTION_FETCH = hybrid_fetcher.DataFetcher.fetch_option_chain
_INSTALLED = False


def _phase61_option_fetch(
    self: hybrid_fetcher.DataFetcher,
    symbol: str,
    *,
    min_dte: int | None = None,
    max_dte: int | None = None,
    providers: list[str] | None = None,
    apply_guards: bool = True,
) -> FetchResult[pd.DataFrame]:
    symbol = str(symbol).strip().upper()
    min_days = int(min_dte if min_dte is not None else getattr(self.settings, "min_dte", 14))
    max_days = int(max_dte if max_dte is not None else getattr(self.settings, "max_dte", 60))
    attempts: list[FetchAttempt] = []
    frames: list[pd.DataFrame] = []
    successful_sources: list[str] = []

    try:
        base = _ORIGINAL_OPTION_FETCH(
            self,
            symbol,
            min_dte=min_days,
            max_dte=max_days,
            providers=providers,
            apply_guards=False,
        )
        attempts.extend(base.attempts)
        if base.data is not None and not base.data.empty:
            frames.append(base.data)
            successful_sources.extend(base.metadata.get("successful_sources") or [base.source])
    except DataUnavailableError as exc:
        attempts.extend(exc.attempts)

    if getattr(self.settings, "polygon_api_key", None):
        frame, attempt = self._attempt(
            "polygon_options",
            "option_chain",
            lambda: polygon_option_chain(self.settings, symbol, min_days, max_days, session=self.session),
            len,
        )
        attempts.append(attempt)
        if attempt.success and isinstance(frame, pd.DataFrame) and not frame.empty:
            frames.append(frame)
            successful_sources.append("polygon_options")

    if not frames:
        raise DataUnavailableError(f"option_chain:{symbol}", attempts)

    merged = phase60_sources._merge_option_frames(frames)
    if apply_guards:
        merged, _ = self.apply_option_quality_guards(merged, symbol)
    if merged.empty:
        raise DataUnavailableError(f"option_chain:{symbol}", attempts)

    successful_sources = list(dict.fromkeys(str(value) for value in successful_sources if value))
    metadata: dict[str, Any] = {
        "symbol": symbol,
        "min_dte": min_days,
        "max_dte": max_days,
        "successful_sources": successful_sources,
        "source_count": len(successful_sources),
        "cross_source_confirmed": len(successful_sources) >= 2,
        "contracts_after_merge": len(merged),
        "opra_source_active": "polygon_options" in successful_sources,
    }
    result = FetchResult(
        data=merged.reset_index(drop=True),
        source="multi-source" if len(successful_sources) >= 2 else successful_sources[0],
        freshness=" | ".join(
            str(value)
            for value in merged.get("freshness_label", pd.Series(dtype=str)).dropna().astype(str).unique()[:5]
        ),
        fetched_at=hybrid_fetcher._now_riyadh(),
        attempts=attempts,
        metadata=metadata,
    )
    phase60_sources._record_audit("options", symbol, result.audit_dict())
    return result


def install_phase61_fetching() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    hybrid_fetcher.DataFetcher.fetch_option_chain = _phase61_option_fetch
    _INSTALLED = True
