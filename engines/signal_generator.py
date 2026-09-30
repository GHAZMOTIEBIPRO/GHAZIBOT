"""BLACK BOX signal fusion engine.

This module is intentionally provider-agnostic. It accepts normalized market
records and delegates hard quote validation to ``validators.options_validator``.
It never imports Yahoo/yfinance and never places orders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from math import isnan
from typing import Any, Mapping, Sequence

from validators.options_validator import DataSource, OptionsValidator, ValidatorResult


@dataclass(frozen=True)
class Signal:
    symbol: str
    direction: str
    strike: float
    expiration: str
    horizon: str
    target: float
    score: float
    decision_authority: bool
    catalysts: tuple[str, ...] = ()
    data_lineage: Mapping[str, Any] = field(default_factory=dict)
    rejection_reasons: tuple[str, ...] = ()

    def to_alert(self) -> str:
        """Render a concise Arabic manual-review alert."""
        side = "CALL" if self.direction == "CALL" else "PUT"
        catalysts = "، ".join(self.catalysts) or "لا توجد محفزات كافية"
        authority = "TRUE" if self.decision_authority else "FALSE"
        return (
            f"🎯 <b>{side} | {self.symbol}</b>\n"
            f"السترايك: ${self.strike:.2f} | الانتهاء: {self.expiration}\n"
            f"الأفق: {self.horizon} | الهدف: ${self.target:.2f}\n"
            f"المحفزات: {catalysts}\n"
            f"الدرجة: {self.score:.1f}/100 | decision_authority: {authority}\n"
            f"المصدر: {self.data_lineage.get('source', 'unknown')}"
        )


class SignalGenerator:
    """Generate a scored signal from normalized bars, flow, and option quote."""

    def __init__(self, options_validator: OptionsValidator | None = None,
                 min_score: float = 60.0, min_sec_confidence: float = 0.85):
        self.options_validator = options_validator or OptionsValidator()
        self.min_score = min_score
        self.min_sec_confidence = min_sec_confidence

    def generate(self, *, quote: Mapping[str, Any], bars: Sequence[Mapping[str, float]],
                 sec_verification: Mapping[str, Any], gex: float = 0.0,
                 flow: float = 0.0, volume_ratio: float = 0.0,
                 now: datetime | None = None) -> Signal | None:
        """Return a signal only when hard validation and evidence gates pass.

        ``flow`` is positive for call-dominant flow and negative for put-dominant
        flow. ``gex`` is an evidence value, not a probability or guarantee.
        """
        if not bars or len(bars) < 2:
            return None
        symbol = str(quote["symbol"]).upper()
        source = self._source(quote.get("source"))
        validation: ValidatorResult = self.options_validator.validate(
            symbol=symbol, contract_type=str(quote["contract_type"]).upper(),
            expiration=str(quote["expiration"]), strike_price=float(quote["strike"]),
            bid=float(quote["bid"]), ask=float(quote["ask"]),
            last=float(quote.get("last", quote["ask"])), source=source,
            feed_name=quote.get("feed_name"), provider_id=quote.get("provider_id"),
            last_trade_timestamp=self._timestamp(quote.get("quote_timestamp")),
        )
        sec_score = float(sec_verification.get("confidence_score", 0.0))
        if not validation.decision_authority or sec_score < self.min_sec_confidence:
            reasons = tuple(validation.rejection_reasons) + (
                ("SEC confidence below threshold",) if sec_score < self.min_sec_confidence else ()
            )
            return None

        closes = [float(row["close"]) for row in bars]
        fast, slow = self._ema(closes, 9), self._ema(closes, 21)
        bullish = fast > slow and closes[-1] >= closes[-2]
        bearish = fast < slow and closes[-1] <= closes[-2]
        direction = "CALL" if bullish and flow >= 0 else "PUT" if bearish and flow <= 0 else None
        if direction is None:
            return None
        evidence = 40.0 + min(abs(flow) * 10.0, 20.0) + min(abs(gex) / 1_000_000, 20.0)
        evidence += 10.0 if volume_ratio >= 3.0 else 0.0
        evidence += 10.0 if sec_score >= 0.95 else 0.0
        if evidence < self.min_score:
            return None
        expiration = str(quote["expiration"])
        horizon = self._horizon(expiration, now or datetime.now(timezone.utc))
        target = closes[-1] + (abs(closes[-1] - closes[-2]) * (1 if direction == "CALL" else -1))
        catalysts = tuple(filter(None, (
            "تدفق CALL قوي" if flow > 0 else "تدفق PUT قوي" if flow < 0 else "",
            "Gamma Exposure" if gex else "",
            "سيولة غير اعتيادية" if volume_ratio >= 3.0 else "",
        )))
        return Signal(symbol, direction, float(quote["strike"]), expiration, horizon,
                      round(target, 2), min(evidence, 100.0), True, catalysts,
                      validation.lineage.to_dict())

    @staticmethod
    def _ema(values: Sequence[float], period: int) -> float:
        alpha = 2 / (period + 1)
        result = float(values[0])
        for value in values[1:]:
            result = alpha * float(value) + (1 - alpha) * result
        return result

    @staticmethod
    def _horizon(expiration: str, now: datetime) -> str:
        days = (date.fromisoformat(expiration) - now.date()).days
        return "0DTE" if days == 0 else "Weekly" if days <= 14 else "Monthly"

    @staticmethod
    def _source(value: Any) -> DataSource:
        try:
            return DataSource(str(value).lower())
        except ValueError:
            return DataSource.UNKNOWN

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        raise ValueError("quote_timestamp is required for freshness validation")
