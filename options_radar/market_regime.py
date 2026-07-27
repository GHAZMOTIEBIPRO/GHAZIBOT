from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from .hybrid_fetcher import DataFetcher, DataUnavailableError, FetchResult, _now_riyadh
from .settings import Settings

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketRegimeSnapshot:
    label: str
    prefer_side: str
    vix: float
    spy_close: float
    spy_ema50: float
    spy_ema200: float
    qqq_close: float
    qqq_ema50: float
    qqq_ema200: float
    call_min_score: float
    put_min_score: float
    call_score_adjustment: float
    put_score_adjustment: float
    reasons: tuple[str, ...]
    sources: dict[str, str]
    fetched_at: str
    data_quality: str
    audit: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload

    def minimum_score(self, side: str) -> float:
        return self.put_min_score if side.lower() == "put" else self.call_min_score

    def score_adjustment(self, side: str) -> float:
        return self.put_score_adjustment if side.lower() == "put" else self.call_score_adjustment

    def accepts(self, side: str, score: float) -> bool:
        return float(score) >= self.minimum_score(side)


class MarketRegimeEngine:
    """Quantitative market-state filter for directional stock/option signals."""

    def __init__(self, settings: Settings | None = None, fetcher: DataFetcher | None = None):
        self.settings = settings or Settings()
        self.fetcher = fetcher or DataFetcher(self.settings)

    @staticmethod
    def _last_close_and_emas(frame: pd.DataFrame) -> tuple[float, float, float]:
        if frame is None or frame.empty or "Close" not in frame:
            raise ValueError("Market regime history is empty")
        close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
        if len(close) < 200:
            raise ValueError(f"At least 200 closes are required; received {len(close)}")
        ema50 = close.ewm(span=50, adjust=False, min_periods=50).mean()
        ema200 = close.ewm(span=200, adjust=False, min_periods=200).mean()
        return float(close.iloc[-1]), float(ema50.iloc[-1]), float(ema200.iloc[-1])

    def _vix(self) -> tuple[float, FetchResult[Any]]:
        try:
            result = self.fetcher.fetch_stock_bars("^VIX", interval="1d")
            close = pd.to_numeric(result.data["Close"], errors="coerce").dropna()
            if close.empty:
                raise ValueError("VIX close is empty")
            return float(close.iloc[-1]), result
        except Exception as market_exc:
            LOGGER.warning("Market-data VIX failed; attempting FRED VIXCLS: %s", market_exc)
            fred = self.fetcher.fetch_fred_series("VIXCLS", limit=10)
            values = pd.to_numeric(fred.data["value"], errors="coerce").dropna()
            if values.empty:
                raise DataUnavailableError("market_regime_vix", fred.attempts)
            return float(values.iloc[-1]), fred

    def evaluate(self) -> MarketRegimeSnapshot:
        spy_result = self.fetcher.fetch_stock_bars("SPY", interval="1d")
        qqq_result = self.fetcher.fetch_stock_bars("QQQ", interval="1d")
        vix, vix_result = self._vix()
        spy_close, spy_ema50, spy_ema200 = self._last_close_and_emas(spy_result.data)
        qqq_close, qqq_ema50, qqq_ema200 = self._last_close_and_emas(qqq_result.data)
        return self.from_values(
            vix=vix,
            spy_close=spy_close,
            spy_ema50=spy_ema50,
            spy_ema200=spy_ema200,
            qqq_close=qqq_close,
            qqq_ema50=qqq_ema50,
            qqq_ema200=qqq_ema200,
            base_min_score=float(getattr(self.settings, "min_score", 65.0)),
            sources={
                "SPY": spy_result.source,
                "QQQ": qqq_result.source,
                "VIX": vix_result.source,
            },
            audit={
                "SPY": spy_result.audit_dict(),
                "QQQ": qqq_result.audit_dict(),
                "VIX": vix_result.audit_dict(),
            },
            risk_off_vix=float(getattr(self.settings, "vix_risk_off_threshold", 25.0)),
            risk_on_vix=float(getattr(self.settings, "vix_risk_on_threshold", 18.0)),
        )

    @staticmethod
    def from_values(
        *,
        vix: float,
        spy_close: float,
        spy_ema50: float,
        spy_ema200: float,
        qqq_close: float,
        qqq_ema50: float,
        qqq_ema200: float,
        base_min_score: float = 65.0,
        sources: dict[str, str] | None = None,
        audit: dict[str, Any] | None = None,
        risk_off_vix: float = 25.0,
        risk_on_vix: float = 18.0,
    ) -> MarketRegimeSnapshot:
        reasons: list[str] = []
        defensive = vix > risk_off_vix or spy_close < spy_ema200
        constructive = vix < risk_on_vix and spy_close > spy_ema50

        if defensive:
            label = "risk_off"
            prefer_side = "put"
            call_min = base_min_score + 10.0
            put_min = max(0.0, base_min_score - 4.0)
            call_adjustment = -10.0
            put_adjustment = 5.0
            if vix > risk_off_vix:
                reasons.append(f"VIX {vix:.2f} > {risk_off_vix:.2f}")
            if spy_close < spy_ema200:
                reasons.append("SPY below EMA200")
        elif constructive:
            label = "risk_on"
            prefer_side = "call"
            call_min = max(0.0, base_min_score - 3.0)
            put_min = base_min_score + 4.0
            call_adjustment = 5.0
            put_adjustment = -3.0
            reasons.extend([
                f"VIX {vix:.2f} < {risk_on_vix:.2f}",
                "SPY above EMA50",
            ])
        else:
            label = "mixed"
            prefer_side = "neutral"
            call_min = base_min_score + 2.0
            put_min = base_min_score + 2.0
            call_adjustment = 0.0
            put_adjustment = 0.0
            reasons.append("Neither hard risk-on nor hard risk-off condition is active")

        # QQQ is a confirmation layer, not an override of the user's hard SPY/VIX rules.
        if label == "risk_on" and qqq_close > qqq_ema50:
            call_adjustment += 2.0
            reasons.append("QQQ confirms above EMA50")
        elif label == "risk_on" and qqq_close < qqq_ema200:
            call_min += 3.0
            reasons.append("QQQ divergence: below EMA200")
        elif label == "risk_off" and qqq_close < qqq_ema200:
            put_adjustment += 2.0
            reasons.append("QQQ confirms below EMA200")
        elif label == "risk_off" and qqq_close > qqq_ema50:
            put_min += 2.0
            reasons.append("QQQ divergence: above EMA50")

        data_quality = "complete" if all((sources or {}).get(key) for key in ("SPY", "QQQ", "VIX")) else "partial"
        return MarketRegimeSnapshot(
            label=label,
            prefer_side=prefer_side,
            vix=round(float(vix), 4),
            spy_close=round(float(spy_close), 4),
            spy_ema50=round(float(spy_ema50), 4),
            spy_ema200=round(float(spy_ema200), 4),
            qqq_close=round(float(qqq_close), 4),
            qqq_ema50=round(float(qqq_ema50), 4),
            qqq_ema200=round(float(qqq_ema200), 4),
            call_min_score=round(call_min, 2),
            put_min_score=round(put_min, 2),
            call_score_adjustment=round(call_adjustment, 2),
            put_score_adjustment=round(put_adjustment, 2),
            reasons=tuple(reasons),
            sources=sources or {},
            fetched_at=_now_riyadh(),
            data_quality=data_quality,
            audit=audit or {},
        )
