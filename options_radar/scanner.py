from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .alerts import dispatch_new_alerts
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
        vix = get_price_history("^VIX", period="3mo")
        vix_close = 20.0 if vix.empty else float(vix["Close"].dropna().iloc[-1])
        return market_regime(spy, qqq, vix_close), {"SPY": spy, "QQQ": qqq}, vix_close

    def _scan_symbol(self, symbol: str, regime: str,
                     cached: dict[str, TechnicalSnapshot]) -> pd.DataFrame:
        technical = cached.get(symbol) or self._technical(symbol)
        chain = self.provider.get_chain(symbol, self.settings.min_dte, self.settings.max_dte)
        chain = maybe_enrich_with_alpaca(self.settings, chain, symbol)
        return score_chain(chain, technical, regime, self.settings)

    def scan(self, symbols: list[str], top: int = 25, send_alerts: bool = False,
             output_csv: str | Path | None = None) -> ScanResult:
        symbols = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
        if not symbols:
            raise ValueError("At least one symbol is required")
        regime, cached, vix_close = self._market_regime()
        LOGGER.info("Market regime=%s, VIX=%.2f", regime, vix_close)
        frames: list[pd.DataFrame] = []
        errors: dict[str, str] = {}
        workers = max(1, min(self.settings.max_workers, len(symbols)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(self._scan_symbol, symbol, regime, cached): symbol for symbol in symbols}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    frame = future.result()
                    if not frame.empty:
                        frames.append(frame)
                except Exception as exc:
                    errors[symbol] = str(exc)
                    LOGGER.exception("Scan failed for %s", symbol)
        if frames:
            opportunities = pd.concat(frames, ignore_index=True)
            opportunities = opportunities.sort_values(
                ["score", "vol_oi", "volume"], ascending=[False, False, False]
            ).drop_duplicates("contract_symbol").head(top).reset_index(drop=True)
        else:
            opportunities = pd.DataFrame()
        self.store.log_signals(opportunities)
        alerts = dispatch_new_alerts(opportunities, self.settings, self.store, send=send_alerts)
        if output_csv:
            path = Path(output_csv)
            path.parent.mkdir(parents=True, exist_ok=True)
            opportunities.to_csv(path, index=False)
        return ScanResult(opportunities, alerts, errors, regime, self.provider.name)
