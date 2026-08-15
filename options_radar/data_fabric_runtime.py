from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from .data_fabric import (
    health_from_env,
    parallel_fetch,
    reconcile_option_chains,
    reconcile_stock_bars,
)


def _provider_list(raw: str) -> list[str]:
    output: list[str] = []
    aliases = {
        "twelve": "twelve_data",
        "twelvedata": "twelve_data",
        "alpha": "alpha_vantage",
        "alphavantage": "alpha_vantage",
        "yfinance": "yahoo",
    }
    for item in str(raw or "").split(","):
        name = aliases.get(item.strip().lower(), item.strip().lower())
        if name and name not in output:
            output.append(name)
    return output


def install_data_fabric() -> None:
    """Replace first-success fetching with resilient multi-provider reconciliation.

    This patch is idempotent and intentionally changes data acquisition only.
    Stock and options decision engines remain independent and unchanged.
    """
    from options_radar import hybrid_fetcher as hybrid
    from options_radar import market_bars
    from options_radar.providers import AlpacaEnricher, MarketDataProvider

    DataFetcher = hybrid.DataFetcher
    if getattr(DataFetcher, "_ghazi_data_fabric_v4", False):
        return

    original_alpaca_enrich = AlpacaEnricher.enrich

    def guarded_alpaca_enrich(self: Any, chain: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Use free Alpaca indicative data as Greek context, not a fake OPRA quote."""
        if chain is None or chain.empty:
            return chain
        base = chain.copy()
        out = original_alpaca_enrich(self, chain, symbol)
        feed = str(getattr(self.settings, "alpaca_options_feed", "indicative") or "indicative").lower()
        if feed == "opra":
            if "fabric_source_tier" in out:
                out["fabric_source_tier"] = "LIVE_OR_LICENSED"
            return out

        # Alpaca documents the free option feed as indicative; trades are delayed.
        # Preserve the pre-existing quote pair and timestamp. Alpaca still enriches
        # IV/Greeks, but it cannot silently become the execution quote source.
        for column in ("bid", "ask", "last", "updated_at"):
            if column in base and column in out:
                out[column] = base[column]
        base_quality = pd.to_numeric(base.get("data_quality"), errors="coerce").fillna(0.0)
        out["data_quality"] = base_quality.clip(upper=0.78)
        if "source" in base:
            out["source"] = base["source"].astype(str) + " + alpaca_indicative_greeks"
        if "freshness_label" in base:
            out["freshness_label"] = base["freshness_label"].astype(str) + " | Alpaca indicative Greeks context"
        out["fabric_source_tier"] = out.get(
            "fabric_source_tier", pd.Series("DELAYED_OR_INDICATIVE", index=out.index)
        )
        return out

    def fabric_stock_bars(
        self: Any,
        symbol: str,
        *,
        start: datetime | date | None = None,
        end: datetime | date | None = None,
        interval: str = "1d",
        providers: list[str] | None = None,
    ):
        symbol = str(symbol or "").strip().upper()
        end_dt = hybrid._utc_timestamp(end)
        start_value = start or (end_dt - pd.Timedelta(days=420 if interval == "1d" else 30))
        start_dt = hybrid._utc_timestamp(start_value)
        raw_order = (
            self.settings.daily_provider_order
            if interval == "1d"
            else self.settings.intraday_provider_order
        )
        order = providers or _provider_list(raw_order)
        if not order:
            order = ["yahoo"]

        freshness: dict[str, str] = {}

        def load_provider(name: str):
            result = market_bars._call_provider(
                name,
                self.settings,
                symbol,
                interval=interval,
                start=start_dt.to_pydatetime(),
                end=end_dt.to_pydatetime(),
                period="1y" if interval == "1d" else "1mo",
            )
            freshness[name] = result.freshness
            return result

        loaders = {name: (lambda name=name: load_provider(name)) for name in order}
        health = health_from_env()
        fetched = parallel_fetch(
            loaders,
            operation=f"stock_bars:{interval}",
            row_counter=lambda result: len(result.frame),
            health=health,
            max_workers=int(os.getenv("DATA_FABRIC_MAX_WORKERS", "5")),
        )
        attempts = [
            hybrid.FetchAttempt(
                provider=item.provider,
                operation="stock_bars",
                success=item.attempt.success,
                elapsed_ms=item.attempt.elapsed_ms,
                rows=item.attempt.rows,
                error=item.attempt.error,
            )
            for item in fetched
        ]
        frames = {
            item.provider: item.value.frame
            for item in fetched
            if item.attempt.success and item.value is not None and not item.value.frame.empty
        }
        if not frames:
            raise hybrid.DataUnavailableError(f"stock_bars:{symbol}", attempts)
        frame, selected, audit = reconcile_stock_bars(
            frames,
            freshness=freshness,
            max_close_divergence_pct=float(os.getenv("DATA_FABRIC_MAX_STOCK_DIVERGENCE_PCT", "0.025")),
        )
        if frame.empty:
            raise hybrid.DataUnavailableError(f"stock_bars:{symbol}", attempts)
        selected_freshness = freshness.get(selected, "data-fabric selected feed")
        return hybrid.FetchResult(
            frame,
            selected,
            selected_freshness,
            hybrid._now_riyadh(),
            attempts,
            {
                "symbol": symbol,
                "interval": interval,
                "data_fabric": audit,
                "provider_health": health.snapshot(),
            },
        )

    def fabric_option_chain(
        self: Any,
        symbol: str,
        *,
        min_dte: int | None = None,
        max_dte: int | None = None,
        providers: list[str] | None = None,
        apply_guards: bool = True,
    ):
        symbol = str(symbol or "").strip().upper()
        min_days = int(min_dte if min_dte is not None else self.settings.min_dte)
        max_days = int(max_dte if max_dte is not None else self.settings.max_dte)
        order = providers or _provider_list(self.settings.options_provider_order)
        if not order:
            order = ["yahoo"]

        freshness = {
            "tradier": (
                "Tradier sandbox: 15-minute delayed; provider Greeks unavailable"
                if "sandbox" in str(self.settings.tradier_base_url).lower()
                else "Tradier brokerage feed"
            ),
            "marketdata": "MarketData.app account feed; entitlement/delay apply",
            "finnhub": "Finnhub account entitlement",
            "yahoo": "unofficial fallback; may be delayed",
        }
        loaders: dict[str, Any] = {}
        for name in order:
            if name == "tradier":
                loaders[name] = lambda: self._tradier_chain(symbol, min_days, max_days)
            elif name == "marketdata":
                loaders[name] = lambda: MarketDataProvider(self.settings).get_chain(symbol, min_days, max_days)
            elif name == "finnhub":
                loaders[name] = lambda: self._finnhub_chain(symbol, min_days, max_days)
            elif name == "yahoo":
                loaders[name] = lambda: self._yahoo_chain(symbol, min_days, max_days)

        if not loaders:
            raise hybrid.DataUnavailableError(f"option_chain:{symbol}", [])
        health = health_from_env()
        fetched = parallel_fetch(
            loaders,
            operation="option_chain",
            row_counter=len,
            health=health,
            max_workers=int(os.getenv("DATA_FABRIC_MAX_WORKERS", "5")),
        )
        attempts = [
            hybrid.FetchAttempt(
                provider=item.provider,
                operation="option_chain",
                success=item.attempt.success,
                elapsed_ms=item.attempt.elapsed_ms,
                rows=item.attempt.rows,
                error=item.attempt.error,
            )
            for item in fetched
        ]
        frames: dict[str, pd.DataFrame] = {}
        for item in fetched:
            if not item.attempt.success or item.value is None or item.value.empty:
                continue
            frame = self._fill_missing_greeks(item.value)
            if not frame.empty:
                frames[item.provider] = frame
        if not frames:
            raise hybrid.DataUnavailableError(f"option_chain:{symbol}", attempts)

        frame, audit = reconcile_option_chains(
            frames,
            freshness=freshness,
            max_quote_divergence_pct=float(os.getenv("DATA_FABRIC_MAX_OPTION_DIVERGENCE_PCT", "0.08")),
        )
        if apply_guards:
            frame, _ = self.apply_option_quality_guards(frame, symbol)
        if frame.empty:
            attempts.append(
                hybrid.FetchAttempt(
                    provider="data_fabric",
                    operation="option_chain",
                    success=False,
                    elapsed_ms=0,
                    rows=0,
                    error="all reconciled contracts rejected by quality guards",
                )
            )
            raise hybrid.DataUnavailableError(f"option_chain:{symbol}", attempts)
        source = "fabric:" + "+".join(audit.get("sources") or list(frames))
        return hybrid.FetchResult(
            frame.reset_index(drop=True),
            source,
            "multi-provider exact-contract reconciliation",
            hybrid._now_riyadh(),
            attempts,
            {
                "symbol": symbol,
                "min_dte": min_days,
                "max_dte": max_days,
                "data_fabric": audit,
                "provider_health": health.snapshot(),
            },
        )

    DataFetcher.fetch_stock_bars = fabric_stock_bars
    DataFetcher.fetch_option_chain = fabric_option_chain
    AlpacaEnricher.enrich = guarded_alpaca_enrich
    DataFetcher._ghazi_data_fabric_v4 = True
