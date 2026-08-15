from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from .providers import maybe_enrich_with_alpaca
from .scoring import approximate_greeks
from .settings import Settings


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _source_quality(source: str) -> str:
    text = source.lower()
    if "alpaca" in text and "opra" in text:
        return "licensed_or_opra"
    if "tradier" in text and "sandbox" not in text:
        return "brokerage"
    if "marketdata" in text:
        return "delayed_structured"
    if "alpaca" in text:
        return "indicative"
    if "yahoo" in text or "yfinance" in text:
        return "unofficial"
    return "unknown"


@dataclass(frozen=True)
class GammaMap:
    symbol: str
    spot: float
    contracts_seen: int
    contracts_with_gamma: int
    contracts_with_oi: int
    gamma_coverage_pct: float
    oi_coverage_pct: float
    call_gex_proxy: float
    put_gex_proxy: float
    signed_gex_proxy: float
    call_share_pct: float
    put_share_pct: float
    call_wall: float | None
    put_wall: float | None
    nearest_gamma_strike: float | None
    gamma_balance: float
    context: str
    data_tier: str
    source_note: str
    by_strike: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def prepare_gamma_chain(chain: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """Prepare a chain for GEX-proxy analysis without inventing unavailable data.

    Missing delta/gamma can be approximated from IV with Black-Scholes. Open
    interest is never synthesized: contracts without OI contribute zero to GEX.
    """
    if chain is None or chain.empty:
        return pd.DataFrame()

    frame = chain.copy()
    for column in ("strike", "open_interest", "iv", "delta", "gamma", "underlying_price"):
        if column not in frame:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["expiration"] = pd.to_datetime(frame.get("expiration"), errors="coerce")
    today = pd.Timestamp.now().normalize()
    frame["dte"] = (frame["expiration"].dt.normalize() - today).dt.days
    frame = frame[frame["dte"].between(settings.min_dte, settings.max_dte)].copy()
    if frame.empty:
        return frame

    fallback_spot = float(frame["underlying_price"].dropna().median()) if frame["underlying_price"].notna().any() else 0.0
    for idx, row in frame.iterrows():
        gamma = _number(row.get("gamma"), float("nan"))
        delta = _number(row.get("delta"), float("nan"))
        iv = _number(row.get("iv"), float("nan"))
        spot = _number(row.get("underlying_price"), fallback_spot)
        strike = _number(row.get("strike"))
        dte = max(_number(row.get("dte")), 1.0)
        option_type = str(row.get("option_type") or "").lower()
        if (not math.isfinite(gamma) or not math.isfinite(delta)) and spot > 0 and strike > 0 and math.isfinite(iv) and iv > 0:
            approx_delta, approx_gamma = approximate_greeks(
                spot=spot,
                strike=strike,
                t_years=dte / 365.0,
                iv=iv,
                risk_free_rate=settings.risk_free_rate,
                option_type=option_type,
            )
            if not math.isfinite(delta):
                frame.at[idx, "delta"] = approx_delta
            if not math.isfinite(gamma):
                frame.at[idx, "gamma"] = approx_gamma
                frame.at[idx, "gamma_estimated"] = True
        elif math.isfinite(gamma):
            frame.at[idx, "gamma_estimated"] = False

    frame["gamma_estimated"] = frame.get("gamma_estimated", False).fillna(False).astype(bool)
    frame["open_interest"] = frame["open_interest"].fillna(0).clip(lower=0)
    frame["gamma"] = frame["gamma"].clip(lower=0)
    frame["spot_for_gex"] = frame["underlying_price"].fillna(fallback_spot)

    # Magnitude proxy: change in delta notional for a 1% underlying move.
    frame["gex_proxy"] = (
        frame["gamma"].fillna(0)
        * frame["open_interest"]
        * 100.0
        * frame["spot_for_gex"].pow(2)
        * 0.01
    )
    sides = frame["option_type"].astype(str).str.lower()
    frame["signed_gex_proxy"] = np.where(sides.eq("put"), -frame["gex_proxy"], frame["gex_proxy"])
    return frame


def build_gamma_map(symbol: str, chain: pd.DataFrame, settings: Settings) -> GammaMap:
    frame = prepare_gamma_chain(chain, settings)
    if frame.empty:
        return GammaMap(
            symbol=symbol.upper(), spot=0.0, contracts_seen=0, contracts_with_gamma=0,
            contracts_with_oi=0, gamma_coverage_pct=0.0, oi_coverage_pct=0.0,
            call_gex_proxy=0.0, put_gex_proxy=0.0, signed_gex_proxy=0.0,
            call_share_pct=0.0, put_share_pct=0.0, call_wall=None, put_wall=None,
            nearest_gamma_strike=None, gamma_balance=0.0, context="NO_DATA",
            data_tier="unavailable", source_note="No usable option chain in configured DTE window.",
            by_strike=(),
        )

    spot = _number(frame["spot_for_gex"].replace(0, np.nan).dropna().median()) if frame["spot_for_gex"].notna().any() else 0.0
    gamma_ok = frame["gamma"].notna() & (frame["gamma"] > 0)
    oi_ok = frame["open_interest"].fillna(0) > 0
    contracts_seen = len(frame)
    gamma_coverage = 100.0 * float(gamma_ok.sum()) / max(contracts_seen, 1)
    oi_coverage = 100.0 * float(oi_ok.sum()) / max(contracts_seen, 1)

    side = frame["option_type"].astype(str).str.lower()
    call_total = float(frame.loc[side.eq("call"), "gex_proxy"].sum())
    put_total = float(frame.loc[side.eq("put"), "gex_proxy"].sum())
    total_abs = call_total + put_total
    signed = call_total - put_total
    balance = signed / total_abs if total_abs > 0 else 0.0
    call_share = 100.0 * call_total / total_abs if total_abs > 0 else 0.0
    put_share = 100.0 * put_total / total_abs if total_abs > 0 else 0.0

    strike_rows: list[dict[str, Any]] = []
    for strike, group in frame.groupby("strike", dropna=True):
        group_side = group["option_type"].astype(str).str.lower()
        call_gex = float(group.loc[group_side.eq("call"), "gex_proxy"].sum())
        put_gex = float(group.loc[group_side.eq("put"), "gex_proxy"].sum())
        strike_rows.append(
            {
                "strike": round(float(strike), 4),
                "call_gex_proxy": round(call_gex, 2),
                "put_gex_proxy": round(put_gex, 2),
                "signed_gex_proxy": round(call_gex - put_gex, 2),
                "total_gex_proxy": round(call_gex + put_gex, 2),
            }
        )
    strike_rows.sort(key=lambda row: row["total_gex_proxy"], reverse=True)

    calls = [row for row in strike_rows if row["call_gex_proxy"] > 0]
    puts = [row for row in strike_rows if row["put_gex_proxy"] > 0]
    call_wall = max(calls, key=lambda row: row["call_gex_proxy"])["strike"] if calls else None
    put_wall = max(puts, key=lambda row: row["put_gex_proxy"])["strike"] if puts else None
    nearest = min(strike_rows, key=lambda row: abs(row["strike"] - spot))["strike"] if strike_rows and spot > 0 else None

    if total_abs <= 0:
        context = "NO_GEX"
    elif balance >= 0.18:
        context = "CALL_HEAVY_PROXY"
    elif balance <= -0.18:
        context = "PUT_HEAVY_PROXY"
    else:
        context = "BALANCED_PROXY"

    source_text = " | ".join(dict.fromkeys(frame.get("source", pd.Series(dtype=str)).dropna().astype(str)))
    tiers = {_source_quality(value) for value in frame.get("source", pd.Series(dtype=str)).dropna().astype(str)}
    if "licensed_or_opra" in tiers or "brokerage" in tiers:
        data_tier = "strong"
    elif "delayed_structured" in tiers or "indicative" in tiers:
        data_tier = "research_plus"
    else:
        data_tier = "research"

    estimated_ratio = 100.0 * float(frame["gamma_estimated"].sum()) / max(int(gamma_ok.sum()), 1)
    note = (
        f"GEX proxy from gamma×OI; gamma coverage {gamma_coverage:.0f}%, OI coverage {oi_coverage:.0f}%, "
        f"estimated gamma share {estimated_ratio:.0f}%. This is a positioning proxy, not verified dealer inventory. "
        f"Sources: {source_text or 'unknown'}."
    )
    return GammaMap(
        symbol=symbol.upper(),
        spot=round(spot, 4),
        contracts_seen=contracts_seen,
        contracts_with_gamma=int(gamma_ok.sum()),
        contracts_with_oi=int(oi_ok.sum()),
        gamma_coverage_pct=round(gamma_coverage, 2),
        oi_coverage_pct=round(oi_coverage, 2),
        call_gex_proxy=round(call_total, 2),
        put_gex_proxy=round(put_total, 2),
        signed_gex_proxy=round(signed, 2),
        call_share_pct=round(call_share, 2),
        put_share_pct=round(put_share, 2),
        call_wall=call_wall,
        put_wall=put_wall,
        nearest_gamma_strike=nearest,
        gamma_balance=round(balance, 5),
        context=context,
        data_tier=data_tier,
        source_note=note,
        by_strike=tuple(strike_rows[:30]),
    )


def analyze_free_gamma(
    symbol: str,
    *,
    settings: Settings,
    fetcher: Any,
) -> tuple[GammaMap, pd.DataFrame]:
    """Fetch a fresh research chain, enrich free Alpaca Greeks when configured, and map gamma."""
    result = fetcher.fetch_option_chain(
        symbol,
        min_dte=settings.min_dte,
        max_dte=settings.max_dte,
        apply_guards=False,
    )
    chain = result.data if hasattr(result, "data") else pd.DataFrame()
    if chain is None or chain.empty:
        return build_gamma_map(symbol, pd.DataFrame(), settings), pd.DataFrame()
    chain = maybe_enrich_with_alpaca(settings, chain, symbol)
    prepared = prepare_gamma_chain(chain, settings)
    return build_gamma_map(symbol, prepared, settings), prepared


def contract_gamma_metrics(row: dict[str, Any], gamma_map: dict[str, Any]) -> dict[str, Any]:
    strike = _number(row.get("strike"))
    option_type = str(row.get("option_type") or "").lower()
    by_strike = [item for item in gamma_map.get("by_strike", []) if isinstance(item, dict)]
    match = min(by_strike, key=lambda item: abs(_number(item.get("strike")) - strike)) if by_strike else {}
    total = sum(_number(item.get("total_gex_proxy")) for item in by_strike)
    side_value = _number(match.get("call_gex_proxy" if option_type == "call" else "put_gex_proxy"))
    concentration = 100.0 * side_value / total if total > 0 else 0.0
    balance = _number(gamma_map.get("gamma_balance"))
    alignment = balance if option_type == "call" else -balance
    return {
        "gamma_concentration_pct": round(concentration, 2),
        "gamma_context_alignment": round(alignment, 5),
        "gamma_context": str(gamma_map.get("context") or "NO_DATA"),
        "gamma_data_tier": str(gamma_map.get("data_tier") or "unavailable"),
        "call_wall": gamma_map.get("call_wall"),
        "put_wall": gamma_map.get("put_wall"),
        "gamma_coverage_pct": _number(gamma_map.get("gamma_coverage_pct")),
        "oi_coverage_pct": _number(gamma_map.get("oi_coverage_pct")),
    }
