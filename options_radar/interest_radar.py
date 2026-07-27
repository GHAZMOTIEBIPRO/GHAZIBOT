from __future__ import annotations

from typing import Any

import pandas as pd

from .interest_factors import finviz_style_profile
from .live_scanners import PublicStockRadar
from .stocks import StockRadar as BaseStockRadar


def _rating(score: float) -> str:
    if score >= 90:
        return "A+"
    if score >= 82:
        return "A"
    if score >= 74:
        return "B+"
    if score >= 65:
        return "B"
    return "C"


def _append_rejection(existing: str, reason: str) -> str:
    values = [value for value in str(existing or "").split(",") if value]
    if reason not in values:
        values.append(reason)
    return ",".join(values)


class InterestStockRadar(PublicStockRadar):
    """Add event attention and Finviz-style factors to the stock ranking.

    Finviz is used as a screening methodology reference. The implementation
    computes the filters locally from OHLCV data and does not scrape or
    redistribute Finviz content.
    """

    @staticmethod
    def _score(
        symbol: str,
        technical,
        history: pd.DataFrame,
        regime: str,
        catalyst: dict | None,
    ) -> dict[str, Any]:
        row = BaseStockRadar._score(symbol, technical, history, regime, catalyst)
        profile = finviz_style_profile(history)

        side = str(row.get("setup_side", "call"))
        directional_score = float(
            profile.get("call_interest_score", 0.0)
            if side == "call"
            else profile.get("put_interest_score", 0.0)
        )
        attention_score = float(profile.get("attention_score", 0.0))
        factors = list(
            profile.get("upside_factors", [])
            if side == "call"
            else profile.get("downside_factors", [])
        )
        attention_factors = list(profile.get("attention_factors", []))

        # The interest layer confirms an existing directional model; it does not
        # independently flip CALL to PUT or vice versa.
        interest_bonus = min(14.0, attention_score * 0.22 + directional_score * 0.36)
        original_score = float(row.get("score", 0.0))
        adjusted_score = original_score + interest_bonus

        catalyst_score = float(row.get("catalyst_score", 0.0) or 0.0)
        catalyst_confidence = float(row.get("catalyst_confidence", 0.0) or 0.0)
        catalyst_source = str(row.get("catalyst_source", ""))
        aligned_catalyst = catalyst_score > 0 if side == "call" else catalyst_score < 0
        if aligned_catalyst and catalyst_score:
            # Existing scoring includes the nominal catalyst score. Replace part
            # of the unverified portion with a confidence discount.
            adjusted_score -= abs(catalyst_score) * max(0.0, 1.0 - catalyst_confidence) * 0.65

        adjusted_score = max(0.0, min(100.0, adjusted_score))
        official_event = (
            "SEC" in catalyst_source
            and catalyst_confidence >= 0.80
            and abs(catalyst_score) >= 15
        )
        strong_interest = attention_score >= 8 and directional_score >= 12
        interest_tier = (
            "official_event"
            if official_event
            else "high_interest"
            if strong_interest
            else "developing"
            if attention_score >= 5 or directional_score >= 9
            else "low_attention"
        )

        reasons = [value for value in str(row.get("reasons", "")).split("؛ ") if value]
        if attention_factors:
            reasons.append("اهتمام سوقي: " + "، ".join(attention_factors[:3]))
        if factors:
            label = "عوامل صعود" if side == "call" else "عوامل هبوط"
            reasons.append(f"{label}: " + "، ".join(factors[:4]))
        if official_event:
            reasons.append("محفز SEC رسمي عالي الثقة")

        row["score"] = round(adjusted_score, 1)
        row["rating"] = _rating(adjusted_score)
        row["attention_score"] = round(attention_score, 2)
        row["directional_interest_score"] = round(directional_score, 2)
        row["call_interest_score"] = profile.get("call_interest_score", 0.0)
        row["put_interest_score"] = profile.get("put_interest_score", 0.0)
        row["interest_tier"] = interest_tier
        row["attention_factors"] = "؛ ".join(attention_factors)
        row["rise_factors"] = "؛ ".join(profile.get("upside_factors", []))
        row["fall_factors"] = "؛ ".join(profile.get("downside_factors", []))
        row["performance_day"] = profile.get("performance_day")
        row["performance_week"] = profile.get("performance_week")
        row["performance_month"] = profile.get("performance_month")
        row["performance_quarter"] = profile.get("performance_quarter")
        row["gap_pct"] = profile.get("gap_pct")
        row["atr_pct"] = profile.get("atr_pct")
        row["distance_52w_high"] = profile.get("distance_52w_high")
        row["distance_52w_low"] = profile.get("distance_52w_low")
        row["sma20"] = profile.get("sma20")
        row["sma50"] = profile.get("sma50")
        row["sma200"] = profile.get("sma200")
        row["finviz_relative_volume"] = profile.get("finviz_relative_volume")
        row["interest_method"] = "Finviz-style local OHLCV factors"
        row["reasons"] = "؛ ".join(dict.fromkeys(reasons))

        price = float(row.get("price", 0.0) or 0.0)
        avg_dollar_volume = float(row.get("avg_dollar_volume", 0.0) or 0.0)
        rejection = str(row.get("rejection_reason", ""))
        if price < 1.0:
            rejection = _append_rejection(rejection, "sub_dollar_stock")
        elif price < 2.0 and not official_event and avg_dollar_volume < 10_000_000:
            rejection = _append_rejection(rejection, "low_price_speculation")
        if not official_event and attention_score < 2 and adjusted_score < 58:
            rejection = _append_rejection(rejection, "insufficient_market_attention")

        if side == "put":
            target_1 = max(0.01, float(row.get("target_1", 0.01) or 0.01))
            target_2 = max(0.01, float(row.get("target_2", 0.01) or 0.01))
            row["target_1"] = round(target_1, 2)
            row["target_2"] = round(min(target_1, target_2), 2)

        row["rejection_reason"] = rejection
        row["new_stock_setup"] = bool(
            adjusted_score >= 74
            and str(row.get("entry_state", "")) != "too_late"
            and (official_event or strong_interest)
            and not rejection
        )
        if row["new_stock_setup"]:
            row["setup_status"] = "strong_setup"
        return row
