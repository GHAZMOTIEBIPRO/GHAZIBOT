from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from .indicators import TechnicalSnapshot
from .settings import Settings


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def approximate_greeks(
    spot: float,
    strike: float,
    t_years: float,
    iv: float,
    risk_free_rate: float,
    option_type: str,
) -> tuple[float, float]:
    """Return Black-Scholes delta and gamma as a screening approximation."""
    if min(spot, strike, t_years, iv) <= 0:
        return np.nan, np.nan
    sqrt_t = math.sqrt(t_years)
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate + 0.5 * iv * iv) * t_years
    ) / (iv * sqrt_t)
    call_delta = _norm_cdf(d1)
    delta = call_delta if option_type == "call" else call_delta - 1.0
    gamma = _norm_pdf(d1) / (spot * iv * sqrt_t)
    return delta, gamma


def _clip_score(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


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


def _trade_style(dte: int) -> str:
    if dte <= 7:
        return "Scalping / very short-term"
    if dte <= 21:
        return "Day trade / short momentum"
    return "Swing momentum"


def score_chain(
    chain: pd.DataFrame,
    technical: TechnicalSnapshot,
    regime: str,
    settings: Settings,
    external_catalyst: dict | None = None,
) -> pd.DataFrame:
    if chain.empty:
        return chain.copy()

    frame = chain.copy()
    frame["expiration"] = pd.to_datetime(frame["expiration"], errors="coerce")
    today = pd.Timestamp(date.today())
    frame["dte"] = (frame["expiration"].dt.normalize() - today).dt.days

    numeric = [
        "strike", "bid", "ask", "last", "volume", "open_interest", "iv",
        "delta", "gamma", "underlying_price", "data_quality",
    ]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame["mid"] = (frame["bid"] + frame["ask"]) / 2.0
    frame["spread"] = frame["ask"] - frame["bid"]
    frame["spread_pct"] = frame["spread"] / frame["mid"].replace(0, np.nan)
    frame["vol_oi"] = frame["volume"] / frame["open_interest"].replace(0, np.nan)
    frame["vol_oi"] = frame["vol_oi"].replace([np.inf, -np.inf], np.nan)

    for idx, row in frame[frame["delta"].isna() & frame["iv"].notna()].iterrows():
        spot = technical.close if pd.isna(row["underlying_price"]) else float(row["underlying_price"])
        delta, gamma = approximate_greeks(
            spot=spot,
            strike=float(row["strike"]),
            t_years=max(float(row["dte"]), 1.0) / 365.0,
            iv=float(row["iv"]),
            risk_free_rate=settings.risk_free_rate,
            option_type=str(row["option_type"]),
        )
        frame.at[idx, "delta"] = delta
        if pd.isna(frame.at[idx, "gamma"]):
            frame.at[idx, "gamma"] = gamma

    frame["abs_delta"] = frame["delta"].abs()
    rv = technical.realized_vol20 if technical.realized_vol20 > 0 else np.nan
    frame["iv_rv_ratio"] = frame["iv"] / rv
    frame["direction_match"] = (
        ((frame["option_type"] == "call") & (technical.direction == "bullish"))
        | ((frame["option_type"] == "put") & (technical.direction == "bearish"))
    )
    frame["regime_match"] = (
        ((frame["option_type"] == "call") & (regime == "risk_on"))
        | ((frame["option_type"] == "put") & (regime == "risk_off"))
        | (regime == "mixed")
    )

    valid = (
        frame["dte"].between(settings.min_dte, settings.max_dte)
        & (frame["bid"] > 0)
        & (frame["ask"] > frame["bid"])
        & (frame["volume"] >= settings.min_option_volume)
        & (frame["open_interest"] >= settings.min_open_interest)
        & (frame["spread_pct"] <= settings.max_spread_pct)
        & frame["abs_delta"].between(
            settings.min_abs_delta, settings.max_abs_delta, inclusive="both"
        )
        & frame["direction_match"]
    )
    frame = frame.loc[valid].copy()
    if frame.empty:
        return frame

    def liquidity_score(row: pd.Series) -> float:
        oi = _clip_score(math.log10(max(row["open_interest"], 1)) / 4.0)
        volume = _clip_score(math.log10(max(row["volume"], 1)) / 4.0)
        spread = _clip_score(1.0 - row["spread_pct"] / settings.max_spread_pct)
        return 25.0 * (0.35 * oi + 0.35 * volume + 0.30 * spread)

    def flow_score(row: pd.Series) -> float:
        ratio = _clip_score((row["vol_oi"] - 0.5) / 3.5) if pd.notna(row["vol_oi"]) else 0
        aggressor = {"ask": 1.0, "mid": 0.55, "bid": 0.15, "unknown": 0.35}.get(
            str(row["aggressor_proxy"]), 0.35
        )
        return 25.0 * (0.75 * ratio + 0.25 * aggressor)

    def greek_score(row: pd.Series) -> float:
        center = (settings.min_abs_delta + settings.max_abs_delta) / 2.0
        half = max((settings.max_abs_delta - settings.min_abs_delta) / 2.0, 0.01)
        delta_fit = _clip_score(1.0 - abs(row["abs_delta"] - center) / half)
        gamma_value = 0.0 if pd.isna(row["gamma"]) else float(row["gamma"])
        gamma_bonus = _clip_score(gamma_value / 0.08)
        return 15.0 * (0.8 * delta_fit + 0.2 * gamma_bonus)

    def iv_score(row: pd.Series) -> float:
        ratio = row["iv_rv_ratio"]
        if pd.isna(ratio) or ratio <= 0:
            return 6.0
        if 0.75 <= ratio <= 1.45:
            fit = 1.0
        elif ratio < 0.75:
            fit = _clip_score(ratio / 0.75)
        else:
            fit = _clip_score(1.0 - (ratio - 1.45) / 1.55)
        return 15.0 * fit

    frame["liquidity_score"] = frame.apply(liquidity_score, axis=1)
    frame["flow_score"] = frame.apply(flow_score, axis=1)
    frame["greeks_score"] = frame.apply(greek_score, axis=1)
    frame["iv_score"] = frame.apply(iv_score, axis=1)
    frame["technical_score"] = technical.catalyst_score
    external_catalyst = external_catalyst or {}
    catalyst_bonus = max(-25.0, min(20.0, float(external_catalyst.get("score", 0.0))))
    frame["news_catalyst_score"] = catalyst_bonus
    frame["regime_bonus"] = frame["regime_match"].astype(float) * 2.0
    frame["quality_penalty"] = (1.0 - frame["data_quality"].fillna(0.5)) * 10.0

    frame["score"] = (
        frame["liquidity_score"]
        + frame["flow_score"]
        + frame["greeks_score"]
        + frame["iv_score"]
        + frame["technical_score"]
        + frame["news_catalyst_score"]
        + frame["regime_bonus"]
        - frame["quality_penalty"]
    ).clip(0, 100)

    frame["rating"] = frame["score"].apply(_rating)
    frame["trade_style"] = frame["dte"].astype(int).apply(_trade_style)
    frame["entry_price"] = (frame["mid"] + 0.15 * frame["spread"]).clip(upper=frame["ask"])
    frame["target_1"] = frame["entry_price"] * 1.30
    frame["target_2"] = frame["entry_price"] * 1.60
    frame["stop_price"] = frame["entry_price"] * 0.75
    frame["underlying_invalidation"] = technical.ema21
    external_text = ""
    if external_catalyst:
        external_text = (
            f"{external_catalyst.get('category', '')}: "
            f"{external_catalyst.get('headline', '')}"
        ).strip(": ")
    frame["catalyst"] = external_text + (" | " if external_text else "") + technical.catalyst
    frame["catalyst_url"] = str(external_catalyst.get("url", ""))
    frame["catalyst_source"] = str(external_catalyst.get("source", ""))
    frame["technical_direction"] = technical.direction
    frame["market_regime"] = regime
    frame["new_setup_candidate"] = (
        (frame["vol_oi"] >= settings.alert_vol_oi)
        & (technical.breakout or catalyst_bonus >= 15)
        & (frame["score"] >= settings.alert_score)
        & frame["aggressor_proxy"].isin(["ask", "mid"])
    )

    return frame.loc[frame["score"] >= settings.min_score].sort_values(
        ["score", "vol_oi", "volume"], ascending=[False, False, False]
    )
