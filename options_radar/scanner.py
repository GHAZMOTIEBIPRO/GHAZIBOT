from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .advanced_signals import is_standard_occ_contract
from .alerts import dispatch_new_alerts
from .catalysts import best_catalyst_map
from .indicators import TechnicalSnapshot, analyze_technical, market_regime
from .providers import get_price_history, maybe_enrich_with_alpaca, select_provider
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


class OptionsRadar:
    def __init__(self, settings: Settings):
        settings.validate()
        self.settings = settings
        self.provider = select_provider(settings)
        self.store = SignalStore(settings.database_path)

    def _technical(self, symbol: str) -> TechnicalSnapshot:
        return analyze_technical(symbol, get_price_history(symbol, period="1y"))

    def _market_regime(self) -> tuple[str, dict[str, TechnicalSnapshot], float]:
        spy = self._technical("SPY")
        qqq = self._technical("QQQ")
        vix_history = get_price_history("^VIX", period="3mo")
        vix_close = 20.0 if vix_history.empty else float(vix_history["Close"].dropna().iloc[-1])
        return market_regime(spy, qqq, vix_close), {"SPY": spy, "QQQ": qqq}, vix_close

    def _rejection_rows(self, chain: pd.DataFrame, accepted: pd.DataFrame) -> pd.DataFrame:
        if chain.empty:
            return pd.DataFrame()
        frame = chain.copy()
        numeric = ["bid", "ask", "volume", "open_interest", "data_quality", "updated_at"]
        for column in numeric[:-1]:
            if column not in frame:
                frame[column] = np.nan
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["mid"] = (frame["bid"] + frame["ask"]) / 2.0
        frame["spread_pct"] = (frame["ask"] - frame["bid"]) / frame["mid"].replace(0, np.nan)
        frame["updated_at"] = pd.to_datetime(frame.get("updated_at"), utc=True, errors="coerce")
        age = (pd.Timestamp.now(tz="UTC") - frame["updated_at"]).dt.total_seconds() / 60.0
        frame["last_trade_age_minutes"] = age.clip(lower=0)
        accepted_symbols = set(accepted.get("contract_symbol", pd.Series(dtype=str)).astype(str))

        def reason(row: pd.Series) -> str:
            contract = str(row.get("contract_symbol", ""))
            symbol = str(row.get("symbol", ""))
            if not is_standard_occ_contract(contract, symbol):
                return "adjusted_or_nonstandard_contract"
            if not (float(row.get("bid", 0) or 0) > 0 and float(row.get("ask", 0) or 0) > float(row.get("bid", 0) or 0)):
                return "invalid_bid_ask"
            if float(row.get("spread_pct", 99) or 99) > self.settings.max_spread_pct:
                return "spread_too_wide"
            if float(row.get("volume", 0) or 0) < self.settings.min_option_volume:
                return "option_volume_too_low"
            if float(row.get("open_interest", 0) or 0) < self.settings.min_open_interest:
                return "open_interest_too_low"
            if float(row.get("data_quality", 0) or 0) < self.settings.min_data_quality:
                return "data_quality_too_low"
            row_age = row.get("last_trade_age_minutes")
            if pd.notna(row_age) and float(row_age) > self.settings.max_last_trade_age_minutes:
                return "last_trade_too_old"
            if contract not in accepted_symbols:
                return "direction_delta_dte_or_score_filter"
            return ""

        frame["rejection_reason"] = frame.apply(reason, axis=1)
        rejected = frame[frame["rejection_reason"] != ""].copy()
        columns = [
            "symbol", "contract_symbol", "expiration", "strike", "option_type",
            "bid", "ask", "volume", "open_interest", "spread_pct",
            "last_trade_age_minutes", "source", "freshness_label", "rejection_reason",
        ]
        return rejected[[column for column in columns if column in rejected.columns]]

    def _scan_symbol(
        self,
        symbol: str,
        regime: str,
        cached_technicals: dict[str, TechnicalSnapshot],
        catalyst: dict | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        technical = cached_technicals.get(symbol) or self._technical(symbol)
        chain = self.provider.get_chain(
            symbol=symbol,
            min_dte=self.settings.min_dte,
            max_dte=self.settings.max_dte,
        )
        chain = maybe_enrich_with_alpaca(self.settings, chain, symbol)
        if chain.empty:
            return pd.DataFrame(), pd.DataFrame()
        chain = chain.copy()
        chain["standard_contract"] = [
            is_standard_occ_contract(contract, underlying)
            for contract, underlying in zip(
                chain.get("contract_symbol", pd.Series(dtype=str)),
                chain.get("symbol", pd.Series(dtype=str)),
                strict=False,
            )
        ]
        standard_chain = chain[chain["standard_contract"]].copy()
        scored = score_chain(standard_chain, technical, regime, self.settings, catalyst)
        rejected = self._rejection_rows(chain, scored)
        return scored, rejected

    def scan(
        self,
        symbols: list[str],
        top: int = 25,
        send_alerts: bool = False,
        output_csv: str | Path | None = None,
        catalysts: pd.DataFrame | None = None,
    ) -> ScanResult:
        symbols = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
        if not symbols:
            raise ValueError("At least one symbol is required")

        regime, cached_technicals, vix_close = self._market_regime()
        LOGGER.info("Market regime=%s, VIX=%.2f", regime, vix_close)
        catalyst_map = best_catalyst_map(catalysts if catalysts is not None else pd.DataFrame())

        frames: list[pd.DataFrame] = []
        rejected_frames: list[pd.DataFrame] = []
        errors: dict[str, str] = {}
        workers = max(1, min(self.settings.max_workers, len(symbols)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    self._scan_symbol,
                    symbol,
                    regime,
                    cached_technicals,
                    catalyst_map.get(symbol),
                ): symbol
                for symbol in symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    frame, rejected = future.result()
                    if not frame.empty:
                        frames.append(frame)
                    if not rejected.empty:
                        rejected_frames.append(rejected)
                except Exception as exc:
                    errors[symbol] = str(exc)
                    LOGGER.exception("Scan failed for %s", symbol)

        if frames:
            opportunities = pd.concat(frames, ignore_index=True)
            opportunities = opportunities.sort_values(
                ["score", "reward_risk_1", "vol_oi", "volume"],
                ascending=[False, False, False, False],
            ).drop_duplicates("contract_symbol")
            opportunities = opportunities.head(top).reset_index(drop=True)
        else:
            opportunities = pd.DataFrame()
        rejected = (
            pd.concat(rejected_frames, ignore_index=True)
            .drop_duplicates(["contract_symbol", "rejection_reason"])
            .head(200)
            .reset_index(drop=True)
            if rejected_frames
            else pd.DataFrame()
        )

        self.store.log_signals(opportunities)
        alerts = dispatch_new_alerts(
            opportunities, settings=self.settings, store=self.store, send=send_alerts
        )
        if output_csv:
            output_path = Path(output_csv)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            opportunities.to_csv(output_path, index=False)

        return ScanResult(
            opportunities=opportunities,
            alerts=alerts,
            errors=errors,
            regime=regime,
            provider=self.provider.name,
            rejected=rejected,
        )
