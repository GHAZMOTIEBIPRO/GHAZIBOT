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


def _trade_style(dte: int, free_swing_mode: bool) -> str:
    if free_swing_mode:
        return "Free-data swing"
    if dte <= 7:
        return "Scalping / very short-term"
    if dte <= 21:
        return "Day trade / short momentum"
    return "Swing momentum"


def _data_status(row: pd.Series, settings: Settings) -> str:
    if not bool(row.get("bid_ask_valid", False)):
        return "rejected_invalid_quote"
    if float(row.get("data_completeness", 0.0)) < 0.75:
        return "rejected_incomplete"
    if float(row.get("data_quality", 0.0) or 0.0) < settings.min_data_quality:
        return "rejected_low_quality"
    age = row.get("last_trade_age_minutes")
    if pd.notna(age) and float(age) > settings.max_last_trade_age_minutes:
        return "rejected_stale_trade"
    freshness = str(row.get("freshness_label", "")).lower()
    if "24h delayed" in freshness:
        return "delayed_24h"
    if "sandbox" in freshness or "delayed" in freshness:
        return "delayed"
    if "unofficial" in freshness or "indicative" in freshness:
        return "unofficial_or_indicative"
    return "verified_by_source"


def _dynamic_targets(
    row: pd.Series,
    technical: TechnicalSnapshot,
) -> pd.Series:
    entry = float(row["entry_price"])
    spot = float(row["underlying_price"])
    option_type = str(row["option_type"])
    direction = 1.0 if option_type == "call" else -1.0
    atr = max(float(technical.atr14), spot * 0.005)

    if option_type == "call":
        underlying_target_1 = max(spot + 1.25 * atr, technical.resistance20 + 0.20 * atr)
        underlying_target_2 = max(spot + 2.50 * atr, technical.resistance20 + 1.20 * atr)
        invalidation = max(technical.support20, spot - 1.50 * atr)
        invalidation = min(invalidation, spot * 0.985)
    else:
        underlying_target_1 = min(spot - 1.25 * atr, technical.support20 - 0.20 * atr)
        underlying_target_2 = min(spot - 2.50 * atr, technical.support20 - 1.20 * atr)
        invalidation = min(technical.resistance20, spot + 1.50 * atr)
        invalidation = max(invalidation, spot * 1.015)

    delta = abs(float(row.get("delta", 0.0) or 0.0))
    gamma = max(0.0, float(row.get("gamma", 0.0) or 0.0))
    theta = abs(float(row.get("theta", 0.0) or 0.0))
    expected_hold_days = min(max(float(row.get("dte", 14)) * 0.12, 1.0), 5.0)

    def projected_price(target_spot: float, minimum_gain: float) -> float:
        move = abs(target_spot - spot)
        premium_change = delta * move + 0.5 * gamma * move * move
        premium_change -= theta * expected_hold_days
        return max(entry * (1.0 + minimum_gain), entry + max(0.0, premium_change))

    target_1 = min(entry * 2.5, projected_price(underlying_target_1, 0.15))
    target_2 = min(entry * 3.5, projected_price(underlying_target_2, 0.30))

    invalidation_move = abs(spot - invalidation)
    estimated_loss = max(0.0, delta * invalidation_move - 0.5 * gamma * invalidation_move**2)
    stop_price = max(entry * 0.45, entry - max(estimated_loss, entry * 0.15))
    stop_price = min(stop_price, entry * 0.85)
    risk = max(entry - stop_price, 0.01)

    return pd.Series(
        {
            "underlying_target_1": round(underlying_target_1, 4),
            "underlying_target_2": round(underlying_target_2, 4),
            "underlying_invalidation": round(invalidation, 4),
            "target_1": round(target_1, 4),
            "target_2": round(max(target_2, target_1), 4),
            "stop_price": round(stop_price, 4),
            "risk_pct": round((entry - stop_price) / entry, 6),
            "reward_risk_1": round((target_1 - entry) / risk, 4),
            "reward_risk_2": round((max(target_2, target_1) - entry) / risk, 4),
            "direction_sign": direction,
        }
    )


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
        "strike",
        "bid",
        "ask",
        "last",
        "volume",
        "open_interest",
        "iv",
        "delta",
        "gamma",
        "theta",
        "vega",
        "underlying_price",
        "data_quality",
    ]
    for column in numeric:
        if column not in frame.columns:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame["mid"] = (frame["bid"] + frame["ask"]) / 2.0
    frame["spread"] = frame["ask"] - frame["bid"]
    frame["spread_pct"] = frame["spread"] / frame["mid"].replace(0, np.nan)
    frame["vol_oi"] = frame["volume"] / frame["open_interest"].replace(0, np.nan)
    frame["vol_oi"] = frame["vol_oi"].replace([np.inf, -np.inf], np.nan)

    frame["updated_at"] = pd.to_datetime(frame.get("updated_at"), utc=True, errors="coerce")
    now_utc = pd.Timestamp.now(tz="UTC")
    frame["last_trade_age_minutes"] = (
        (now_utc - frame["updated_at"]).dt.total_seconds() / 60.0
    ).clip(lower=0)
    frame["bid_ask_valid"] = (
        (frame["bid"] > 0)
        & (frame["ask"] > frame["bid"])
        & frame["mid"].between(settings.min_option_price, settings.max_option_price)
    )
    completeness_columns = [
        "contract_symbol",
        "expiration",
        "strike",
        "option_type",
        "bid",
        "ask",
        "volume",
        "open_interest",
        "iv",
        "underlying_price",
    ]
    frame["data_completeness"] = frame[completeness_columns].notna().mean(axis=1)

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
    frame["data_status"] = frame.apply(_data_status, axis=1, settings=settings)
    frame["data_gate_pass"] = ~frame["data_status"].str.startswith("rejected_")

    valid = (
        frame["dte"].between(settings.min_dte, settings.max_dte)
        & frame["bid_ask_valid"]
        & (frame["volume"] >= settings.min_option_volume)
        & (frame["open_interest"] >= settings.min_open_interest)
        & (frame["spread_pct"] <= settings.max_spread_pct)
        & frame["abs_delta"].between(
            settings.min_abs_delta, settings.max_abs_delta, inclusive="both"
        )
        & frame["direction_match"]
        & frame["data_gate_pass"]
    )
    frame = frame.loc[valid].copy()
    if frame.empty:
        return frame

    def execution_score(row: pd.Series) -> float:
        oi = _clip_score(math.log10(max(row["open_interest"], 1)) / 4.0)
        volume = _clip_score(math.log10(max(row["volume"], 1)) / 4.0)
        spread = _clip_score(1.0 - row["spread_pct"] / settings.max_spread_pct)
        price_fit = 1.0 if 0.50 <= row["mid"] <= 15.0 else 0.65
        return 30.0 * (0.30 * oi + 0.25 * volume + 0.30 * spread + 0.15 * price_fit)

    def activity_score(row: pd.Series) -> float:
        ratio = _clip_score((row["vol_oi"] - 0.5) / 3.5) if pd.notna(row["vol_oi"]) else 0
        aggressor = {"ask": 1.0, "mid": 0.55, "bid": 0.15, "unknown": 0.35}.get(
            str(row.get("aggressor_proxy", "unknown")), 0.35
        )
        return 10.0 * (0.75 * ratio + 0.25 * aggressor)

    def contract_fit_score(row: pd.Series) -> float:
        center = (settings.min_abs_delta + settings.max_abs_delta) / 2.0
        half = max((settings.max_abs_delta - settings.min_abs_delta) / 2.0, 0.01)
        delta_fit = _clip_score(1.0 - abs(row["abs_delta"] - center) / half)
        gamma_value = 0.0 if pd.isna(row["gamma"]) else float(row["gamma"])
        gamma_bonus = _clip_score(gamma_value / 0.08)
        dte_center = 35.0 if settings.free_swing_mode else 18.0
        dte_fit = _clip_score(1.0 - abs(float(row["dte"]) - dte_center) / max(dte_center, 1.0))
        return 20.0 * (0.55 * delta_fit + 0.15 * gamma_bonus + 0.30 * dte_fit)

    def iv_risk_score(row: pd.Series) -> float:
        ratio = row["iv_rv_ratio"]
        if pd.isna(ratio) or ratio <= 0:
            return 6.0
        if 0.75 <= ratio <= 1.35:
            fit = 1.0
        elif ratio < 0.75:
            fit = _clip_score(ratio / 0.75)
        else:
            fit = _clip_score(1.0 - (ratio - 1.35) / 1.65)
        return 15.0 * fit

    frame["execution_score"] = frame.apply(execution_score, axis=1)
    frame["options_activity_score"] = frame.apply(activity_score, axis=1)
    frame["contract_fit_score"] = frame.apply(contract_fit_score, axis=1)
    frame["iv_risk_score"] = frame.apply(iv_risk_score, axis=1)
    frame["technical_score"] = min(20.0, float(technical.catalyst_score))
    external_catalyst = external_catalyst or {}
    catalyst_bonus = max(-20.0, min(15.0, float(external_catalyst.get("score", 0.0))))
    frame["news_catalyst_score"] = catalyst_bonus
    frame["regime_bonus"] = frame["regime_match"].astype(float) * 5.0
    frame["quality_penalty"] = (1.0 - frame["data_quality"].fillna(0.5)) * 10.0

    frame["score"] = (
        frame["execution_score"]
        + frame["options_activity_score"]
        + frame["contract_fit_score"]
        + frame["iv_risk_score"]
        + frame["technical_score"]
        + frame["news_catalyst_score"]
        + frame["regime_bonus"]
        - frame["quality_penalty"]
    ).clip(0, 100)

    frame["rating"] = frame["score"].apply(_rating)
    frame["trade_style"] = frame["dte"].astype(int).apply(
        lambda value: _trade_style(value, settings.free_swing_mode)
    )
    frame["entry_price"] = (frame["mid"] + 0.12 * frame["spread"]).clip(upper=frame["ask"])
    targets = frame.apply(_dynamic_targets, axis=1, technical=technical)
    frame = pd.concat([frame, targets], axis=1)
    frame["model_version"] = settings.model_version

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
        & (technical.breakout or catalyst_bonus >= 12)
        & (frame["score"] >= settings.alert_score)
        & frame["aggressor_proxy"].isin(["ask", "mid"])
        & frame["data_gate_pass"]
        & (frame["reward_risk_1"] >= 1.0)
    )

    return frame.loc[frame["score"] >= settings.min_score].sort_values(
        ["score", "reward_risk_1", "vol_oi", "volume"],
        ascending=[False, False, False, False],
    )
