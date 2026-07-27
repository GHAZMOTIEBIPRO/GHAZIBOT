from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .alerts import collect_new_setups
from .catalysts import best_catalyst_map
from .flow_analyzer import FlowAnalyzer
from .hybrid_fetcher import DataFetcher
from .indicators import TechnicalSnapshot, analyze_technical, market_regime
from .market_regime import MarketRegimeEngine, MarketRegimeSnapshot
from .providers import get_price_history, maybe_enrich_with_alpaca
from .scoring import score_chain
from .settings import Settings
from .storage import SignalStore

LOGGER = logging.getLogger(__name__)


@dataclass
class ScanResult:
    opportunities: pd.DataFrame
    alerts: list[str]
    errors: dict[str, str]
    regime: str
    provider: str
    rejected: pd.DataFrame = field(default_factory=pd.DataFrame)
    top_calls: pd.DataFrame = field(default_factory=pd.DataFrame)
    top_puts: pd.DataFrame = field(default_factory=pd.DataFrame)
    provider_audit: dict[str, Any] = field(default_factory=dict)
    flow_summary: dict[str, Any] = field(default_factory=dict)
    market_regime_detail: dict[str, Any] = field(default_factory=dict)


def _rating(score: float) -> str:
    if score >= 88:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 72:
        return "B+"
    if score >= 65:
        return "B"
    if score >= 55:
        return "C"
    return "D"


class _HybridOptionsProvider:
    name = "phase5_hybrid"

    def __init__(self, fetcher: DataFetcher):
        self.fetcher = fetcher
        self.audit: dict[str, dict[str, Any]] = {}

    def get_chain(self, symbol: str, min_dte: int, max_dte: int) -> pd.DataFrame:
        result = self.fetcher.fetch_option_chain(
            symbol,
            min_dte=min_dte,
            max_dte=max_dte,
            apply_guards=False,
        )
        self.audit[symbol] = result.audit_dict()
        return result.data


class OptionsRadar:
    def __init__(self, settings: Settings):
        settings.validate()
        self.settings = settings
        self.fetcher = DataFetcher(settings)
        self.provider = _HybridOptionsProvider(self.fetcher)
        self.flow_analyzer = FlowAnalyzer(settings)
        self.regime_engine = MarketRegimeEngine(settings, self.fetcher)
        self.store = SignalStore(settings.database_path)

    def _technical(self, symbol: str) -> TechnicalSnapshot:
        try:
            history = self.fetcher.fetch_stock_bars(symbol, interval="1d").data
        except Exception as exc:
            LOGGER.warning(
                "Phase 5 stock fetch failed for %s; using legacy fallback: %s",
                symbol,
                exc,
            )
            history = get_price_history(symbol, period="1y")
        return analyze_technical(symbol, history)

    def _market_regime(
        self,
    ) -> tuple[
        str,
        dict[str, TechnicalSnapshot],
        float,
        MarketRegimeSnapshot | None,
    ]:
        try:
            snapshot = self.regime_engine.evaluate()
            return snapshot.label, {}, snapshot.vix, snapshot
        except Exception as exc:
            LOGGER.warning(
                "Phase 5 market regime failed; using legacy filter: %s", exc
            )
            spy = self._technical("SPY")
            qqq = self._technical("QQQ")
            vix_history = get_price_history("^VIX", period="3mo")
            vix_close = (
                20.0
                if vix_history.empty
                else float(vix_history["Close"].dropna().iloc[-1])
            )
            label = market_regime(spy, qqq, vix_close)
            return label, {"SPY": spy, "QQQ": qqq}, vix_close, None

    def _option_history_loader(self, contract_symbol: str):
        end = datetime.now(timezone.utc)
        start = end - timedelta(
            days=self.settings.flow_history_lookback_days
        )
        return self.fetcher.fetch_option_history(
            contract_symbol,
            start=start,
            end=end,
            interval="1d",
        )

    @staticmethod
    def _prepare_chain_dates(chain: pd.DataFrame) -> pd.DataFrame:
        out = chain.copy()
        if "expiration" in out:
            expiration = pd.to_datetime(out["expiration"], errors="coerce")
            out["expiration"] = expiration
            if (
                "dte" not in out
                or pd.to_numeric(out["dte"], errors="coerce").isna().all()
            ):
                today = pd.Timestamp.now().normalize()
                out["dte"] = (
                    expiration.dt.normalize() - today
                ).dt.days
        return out

    @staticmethod
    def _rejection_view(frames: list[pd.DataFrame]) -> pd.DataFrame:
        usable = [
            frame for frame in frames if frame is not None and not frame.empty
        ]
        if not usable:
            return pd.DataFrame()
        combined = pd.concat(usable, ignore_index=True, sort=False)
        if "rejection_reason" not in combined:
            combined["rejection_reason"] = "unknown_rejection"
        combined["rejection_reason"] = (
            combined["rejection_reason"].fillna("").astype(str)
        )
        combined = combined[combined["rejection_reason"].ne("")]
        if combined.empty:
            return combined
        keys = [
            column
            for column in ("contract_symbol", "rejection_reason")
            if column in combined
        ]
        if keys:
            combined = combined.drop_duplicates(keys)
        columns = [
            "symbol",
            "contract_symbol",
            "expiration",
            "strike",
            "option_type",
            "bid",
            "ask",
            "last",
            "volume",
            "open_interest",
            "vol_to_oi_ratio",
            "volume_spike_ratio",
            "buying_flow_type",
            "flow_momentum_score",
            "spread_pct",
            "last_trade_age_minutes",
            "source",
            "freshness_label",
            "rejection_stage",
            "rejection_reason",
        ]
        return combined[
            [column for column in columns if column in combined.columns]
        ]

    def _apply_regime_gate(
        self,
        scored: pd.DataFrame,
        snapshot: MarketRegimeSnapshot | None,
    ) -> pd.DataFrame:
        if scored.empty:
            return scored
        out = scored.copy()
        sides = out["option_type"].astype(str).str.lower()
        if snapshot is None:
            out["market_regime_score_adjustment"] = 0.0
            out["regime_min_score"] = float(self.settings.min_score)
        else:
            out["market_regime_score_adjustment"] = np.where(
                sides.eq("put"),
                snapshot.put_score_adjustment,
                snapshot.call_score_adjustment,
            )
            out["regime_min_score"] = np.where(
                sides.eq("put"),
                snapshot.put_min_score,
                snapshot.call_min_score,
            )
        out["score"] = (
            pd.to_numeric(out["score"], errors="coerce").fillna(0.0)
            + out["market_regime_score_adjustment"]
        ).clip(0.0, 100.0)
        out["rating"] = out["score"].map(_rating)
        out["flow_rank_score"] = (
            0.65
            * pd.to_numeric(
                out["flow_momentum_score"], errors="coerce"
            ).fillna(0.0)
            + 0.35 * out["score"]
        ).round(4)
        new_setup = out.get(
            "new_setup_candidate", pd.Series(False, index=out.index)
        ).astype(bool)
        unusual = out.get(
            "unusual_activity_flag", pd.Series(False, index=out.index)
        ).astype(bool)
        out["new_setup_candidate"] = new_setup & unusual
        return out[
            out["score"] >= out["regime_min_score"]
        ].copy()

    def _scan_symbol(
        self,
        symbol: str,
        regime: str,
        cached_technicals: dict[str, TechnicalSnapshot],
        regime_snapshot: MarketRegimeSnapshot | None,
        catalyst: dict | None = None,
    ) -> tuple[
        pd.DataFrame,
        pd.DataFrame,
        dict[str, Any],
        dict[str, Any],
    ]:
        technical = cached_technicals.get(symbol) or self._technical(symbol)
        chain = self.provider.get_chain(
            symbol=symbol,
            min_dte=self.settings.min_dte,
            max_dte=self.settings.max_dte,
        )
        chain = maybe_enrich_with_alpaca(self.settings, chain, symbol)
        if chain.empty:
            return pd.DataFrame(), pd.DataFrame(), {}, {}
        chain = self._prepare_chain_dates(chain)

        quality_accepted, quality_rejected = (
            self.fetcher.apply_option_quality_guards(chain, symbol)
        )
        if not quality_rejected.empty:
            quality_rejected = quality_rejected.copy()
            quality_rejected["rejection_stage"] = "quality"

        history_loader = (
            self._option_history_loader
            if self.settings.tradier_token
            else None
        )
        flow_result = self.flow_analyzer.analyze(
            quality_accepted,
            technical_direction=technical.direction,
            history_loader=history_loader,
        )
        flow_rejected = flow_result.rejected.copy()
        if not flow_rejected.empty:
            flow_rejected["rejection_stage"] = "flow"

        audit = getattr(self.provider, "audit", {}).get(symbol, {})
        if flow_result.accepted.empty:
            rejected = self._rejection_view(
                [quality_rejected, flow_rejected]
            )
            return pd.DataFrame(), rejected, flow_result.summary, audit

        # Score every flow-qualified row, then apply the side-specific Phase 5
        # regime threshold. min_score=0 prevents a generic early cutoff from
        # deleting risk-off PUT candidates before their regime bonus.
        scoring_settings = replace(self.settings, min_score=0.0)
        scored = score_chain(
            flow_result.accepted,
            technical,
            regime,
            scoring_settings,
            catalyst,
        )
        scored = self._apply_regime_gate(scored, regime_snapshot)

        selected_contracts = set(
            scored.get(
                "contract_symbol", pd.Series(dtype=str)
            ).astype(str)
        )
        score_rejected = flow_result.accepted[
            ~flow_result.accepted["contract_symbol"]
            .astype(str)
            .isin(selected_contracts)
        ].copy()
        if not score_rejected.empty:
            score_rejected["rejection_stage"] = "score_regime"
            score_rejected["rejection_reason"] = (
                "score_or_regime_below_minimum"
            )

        rejected = self._rejection_view(
            [quality_rejected, flow_rejected, score_rejected]
        )
        return scored, rejected, flow_result.summary, audit

    def scan(
        self,
        symbols: list[str],
        top: int = 15,
        output_csv: str | Path | None = None,
        catalysts: pd.DataFrame | None = None,
    ) -> ScanResult:
        symbols = list(
            dict.fromkeys(
                symbol.strip().upper()
                for symbol in symbols
                if symbol.strip()
            )
        )
        if not symbols:
            raise ValueError("At least one symbol is required")

        regime, cached_technicals, vix_close, regime_snapshot = (
            self._market_regime()
        )
        LOGGER.info("Market regime=%s, VIX=%.2f", regime, vix_close)
        catalyst_map = best_catalyst_map(
            catalysts if catalysts is not None else pd.DataFrame()
        )

        frames: list[pd.DataFrame] = []
        rejected_frames: list[pd.DataFrame] = []
        errors: dict[str, str] = {}
        provider_audit: dict[str, Any] = {}
        flow_by_symbol: dict[str, Any] = {}
        workers = max(1, min(self.settings.max_workers, len(symbols)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    self._scan_symbol,
                    symbol,
                    regime,
                    cached_technicals,
                    regime_snapshot,
                    catalyst_map.get(symbol),
                ): symbol
                for symbol in symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    frame, rejected, flow_summary, audit = future.result()
                    if not frame.empty:
                        frames.append(frame)
                    if not rejected.empty:
                        rejected_frames.append(rejected)
                    if flow_summary:
                        flow_by_symbol[symbol] = flow_summary
                    if audit:
                        provider_audit[symbol] = audit
                except Exception as exc:
                    errors[symbol] = str(exc)
                    LOGGER.exception("Scan failed for %s", symbol)

        if frames:
            all_opportunities = pd.concat(
                frames, ignore_index=True, sort=False
            )
            sort_columns = [
                column
                for column in (
                    "flow_rank_score",
                    "flow_momentum_score",
                    "score",
                    "vol_to_oi_ratio",
                    "volume",
                )
                if column in all_opportunities
            ]
            all_opportunities = (
                all_opportunities.sort_values(
                    sort_columns,
                    ascending=[False] * len(sort_columns),
                    na_position="last",
                ).drop_duplicates("contract_symbol")
            )
        else:
            all_opportunities = pd.DataFrame()

        per_side = max(
            1, min(int(top), self.settings.flow_top_per_side)
        )
        top_calls, top_puts = self.flow_analyzer.top_by_side(
            all_opportunities, limit=per_side
        )
        if not top_calls.empty:
            top_calls["side_rank"] = range(1, len(top_calls) + 1)
        if not top_puts.empty:
            top_puts["side_rank"] = range(1, len(top_puts) + 1)
        opportunities = pd.concat(
            [top_calls, top_puts], ignore_index=True, sort=False
        )

        rejected = (
            pd.concat(
                rejected_frames, ignore_index=True, sort=False
            )
            .drop_duplicates(
                ["contract_symbol", "rejection_reason"], keep="first"
            )
            .head(400)
            .reset_index(drop=True)
            if rejected_frames
            else pd.DataFrame()
        )

        aggregate_flow = {
            "symbols_scanned": len(symbols),
            "contracts_analyzed": sum(
                int(value.get("analyzed", 0))
                for value in flow_by_symbol.values()
            ),
            "contracts_flow_qualified": sum(
                int(value.get("accepted", 0))
                for value in flow_by_symbol.values()
            ),
            "aggressive_buying": sum(
                int(value.get("aggressive_buying", 0))
                for value in flow_by_symbol.values()
            ),
            "high_accumulation": sum(
                int(value.get("high_accumulation", 0))
                for value in flow_by_symbol.values()
            ),
            "volume_spikes": sum(
                int(value.get("volume_spikes", 0))
                for value in flow_by_symbol.values()
            ),
            "history_enriched": sum(
                int(value.get("history_enriched", 0))
                for value in flow_by_symbol.values()
            ),
            "top_calls": len(top_calls),
            "top_puts": len(top_puts),
            "by_symbol": flow_by_symbol,
        }

        self.store.log_signals(opportunities)
        setups = collect_new_setups(opportunities, store=self.store)
        if output_csv:
            output_path = Path(output_csv)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            opportunities.to_csv(output_path, index=False)
            top_calls.to_csv(
                output_path.with_name("options_calls_latest.csv"),
                index=False,
            )
            top_puts.to_csv(
                output_path.with_name("options_puts_latest.csv"),
                index=False,
            )

        sources = list(
            dict.fromkeys(
                opportunities.get(
                    "source", pd.Series(dtype=str)
                )
                .dropna()
                .astype(str)
            )
        )
        provider_name = (
            " + ".join(sources) if sources else self.provider.name
        )
        return ScanResult(
            opportunities=opportunities,
            alerts=setups,
            errors=errors,
            regime=regime,
            provider=provider_name,
            rejected=rejected,
            top_calls=top_calls,
            top_puts=top_puts,
            provider_audit=provider_audit,
            flow_summary=aggregate_flow,
            market_regime_detail=(
                regime_snapshot.to_dict()
                if regime_snapshot is not None
                else {}
            ),
        )
