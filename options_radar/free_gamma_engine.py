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


@dataclass(frozen=True)
class GammaMap:
    symbol: str
    spot: float
    contracts_seen: int
    contracts_with_gamma: int
    contracts_with_oi: int
    gamma_coverage_pct: float
    oi_coverage_pct: float
    estimated_gamma_pct: float
    call_gex_proxy: float
    put_gex_proxy: float
    signed_gex_proxy: float
    call_share_pct: float
    put_share_pct: float
    call_wall: float | None
    put_wall: float | None
    gamma_flip: float | None
    nearest_gamma_strike: float | None
    liquidity_strike: float | None
    top_oi_strikes: tuple[float, ...]
    top_volume_strikes: tuple[float, ...]
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
    numeric = (
        "strike",
        "open_interest",
        "volume",
        "iv",
        "delta",
        "gamma",
        "underlying_price",
    )
    for column in numeric:
        if column not in frame:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame["expiration"] = pd.to_datetime(
        frame.get("expiration"), errors="coerce", utc=True
    ).dt.tz_convert(None)
    today = pd.Timestamp.now().normalize()
    frame["dte"] = (frame["expiration"].dt.normalize() - today).dt.days
    frame = frame[frame["dte"].between(settings.min_dte, settings.max_dte)].copy()
    if frame.empty:
        return frame

    if "gamma_estimated" in frame:
        frame["gamma_estimated"] = frame["gamma_estimated"].fillna(False).astype(bool)
    else:
        frame["gamma_estimated"] = False

    fallback_spot = (
        float(frame["underlying_price"].dropna().median())
        if frame["underlying_price"].notna().any()
        else 0.0
    )
    for idx, row in frame.iterrows():
        gamma = _number(row.get("gamma"), float("nan"))
        delta = _number(row.get("delta"), float("nan"))
        iv = _number(row.get("iv"), float("nan"))
        spot = _number(row.get("underlying_price"), fallback_spot)
        strike = _number(row.get("strike"))
        dte = max(_number(row.get("dte")), 1.0)
        option_type = str(row.get("option_type") or "").lower()
        if (
            (not math.isfinite(gamma) or not math.isfinite(delta))
            and spot > 0
            and strike > 0
            and math.isfinite(iv)
            and iv > 0
        ):
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

    frame["gamma_estimated"] = frame["gamma_estimated"].fillna(False).astype(bool)
    frame["open_interest"] = frame["open_interest"].fillna(0).clip(lower=0)
    frame["volume"] = frame["volume"].fillna(0).clip(lower=0)
    frame["gamma"] = frame["gamma"].clip(lower=0)
    frame["spot_for_gex"] = frame["underlying_price"].fillna(fallback_spot)
    frame["gex_proxy"] = (
        frame["gamma"].fillna(0)
        * frame["open_interest"]
        * 100.0
        * frame["spot_for_gex"].pow(2)
        * 0.01
    )
    sides = frame["option_type"].astype(str).str.lower()
    frame["signed_gex_proxy"] = np.where(
        sides.eq("put"), -frame["gex_proxy"], frame["gex_proxy"]
    )
    return frame


def _gamma_flip(strike_rows: list[dict[str, Any]]) -> float | None:
    ordered = sorted(strike_rows, key=lambda row: _number(row.get("strike")))
    if len(ordered) < 2:
        return None
    cumulative = 0.0
    previous_cumulative: float | None = None
    previous_strike: float | None = None
    for row in ordered:
        strike = _number(row.get("strike"))
        cumulative += _number(row.get("signed_gex_proxy"))
        if previous_cumulative is not None and previous_strike is not None:
            crossed = (
                previous_cumulative < 0 <= cumulative
                or previous_cumulative > 0 >= cumulative
            )
            if crossed:
                return round(
                    previous_strike
                    if abs(previous_cumulative) <= abs(cumulative)
                    else strike,
                    4,
                )
        previous_cumulative = cumulative
        previous_strike = strike
    return None


def _liquidity_levels(
    strike_rows: list[dict[str, Any]],
) -> tuple[float | None, tuple[float, ...], tuple[float, ...]]:
    if not strike_rows:
        return None, (), ()
    top_oi_rows = sorted(
        strike_rows,
        key=lambda row: _number(row.get("total_oi")),
        reverse=True,
    )[:3]
    top_volume_rows = sorted(
        strike_rows,
        key=lambda row: _number(row.get("total_volume")),
        reverse=True,
    )[:3]
    max_oi = max((_number(row.get("total_oi")) for row in strike_rows), default=0.0)
    max_volume = max(
        (_number(row.get("total_volume")) for row in strike_rows), default=0.0
    )
    for row in strike_rows:
        oi_component = _number(row.get("total_oi")) / max_oi if max_oi > 0 else 0.0
        volume_component = (
            _number(row.get("total_volume")) / max_volume if max_volume > 0 else 0.0
        )
        row["liquidity_score"] = round(
            100.0 * (0.65 * oi_component + 0.35 * volume_component), 2
        )
    best = max(strike_rows, key=lambda row: _number(row.get("liquidity_score")))
    return (
        _number(best.get("strike")),
        tuple(_number(row.get("strike")) for row in top_oi_rows),
        tuple(_number(row.get("strike")) for row in top_volume_rows),
    )


def build_gamma_map(symbol: str, chain: pd.DataFrame, settings: Settings) -> GammaMap:
    frame = prepare_gamma_chain(chain, settings)
    if frame.empty:
        return GammaMap(
            symbol=symbol.upper(),
            spot=0.0,
            contracts_seen=0,
            contracts_with_gamma=0,
            contracts_with_oi=0,
            gamma_coverage_pct=0.0,
            oi_coverage_pct=0.0,
            estimated_gamma_pct=0.0,
            call_gex_proxy=0.0,
            put_gex_proxy=0.0,
            signed_gex_proxy=0.0,
            call_share_pct=0.0,
            put_share_pct=0.0,
            call_wall=None,
            put_wall=None,
            gamma_flip=None,
            nearest_gamma_strike=None,
            liquidity_strike=None,
            top_oi_strikes=(),
            top_volume_strikes=(),
            gamma_balance=0.0,
            context="NO_DATA",
            data_tier="unavailable",
            source_note="No usable option chain in configured DTE window.",
            by_strike=(),
        )

    spot = (
        _number(frame["spot_for_gex"].replace(0, np.nan).dropna().median())
        if frame["spot_for_gex"].notna().any()
        else 0.0
    )
    gamma_ok = frame["gamma"].notna() & (frame["gamma"] > 0)
    oi_ok = frame["open_interest"].fillna(0) > 0
    contracts_seen = len(frame)
    gamma_count = int(gamma_ok.sum())
    gamma_coverage = 100.0 * gamma_count / max(contracts_seen, 1)
    oi_coverage = 100.0 * float(oi_ok.sum()) / max(contracts_seen, 1)
    estimated_gamma_pct = (
        100.0
        * float((frame["gamma_estimated"] & gamma_ok).sum())
        / max(gamma_count, 1)
    )

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
        calls = group_side.eq("call")
        puts = group_side.eq("put")
        call_gex = float(group.loc[calls, "gex_proxy"].sum())
        put_gex = float(group.loc[puts, "gex_proxy"].sum())
        call_oi = float(group.loc[calls, "open_interest"].sum())
        put_oi = float(group.loc[puts, "open_interest"].sum())
        call_volume = float(group.loc[calls, "volume"].sum())
        put_volume = float(group.loc[puts, "volume"].sum())
        strike_rows.append(
            {
                "strike": round(float(strike), 4),
                "call_gex_proxy": round(call_gex, 2),
                "put_gex_proxy": round(put_gex, 2),
                "signed_gex_proxy": round(call_gex - put_gex, 2),
                "total_gex_proxy": round(call_gex + put_gex, 2),
                "call_oi": round(call_oi, 2),
                "put_oi": round(put_oi, 2),
                "total_oi": round(call_oi + put_oi, 2),
                "call_volume": round(call_volume, 2),
                "put_volume": round(put_volume, 2),
                "total_volume": round(call_volume + put_volume, 2),
            }
        )

    call_rows = [row for row in strike_rows if row["call_gex_proxy"] > 0]
    put_rows = [row for row in strike_rows if row["put_gex_proxy"] > 0]
    call_wall = (
        max(call_rows, key=lambda row: row["call_gex_proxy"])["strike"]
        if call_rows
        else None
    )
    put_wall = (
        max(put_rows, key=lambda row: row["put_gex_proxy"])["strike"]
        if put_rows
        else None
    )
    nearest = (
        min(strike_rows, key=lambda row: abs(row["strike"] - spot))["strike"]
        if strike_rows and spot > 0
        else None
    )
    gamma_flip = _gamma_flip(strike_rows)
    liquidity_strike, top_oi, top_volume = _liquidity_levels(strike_rows)
    strike_rows.sort(key=lambda row: row["total_gex_proxy"], reverse=True)

    if total_abs <= 0:
        context = "NO_GEX"
    elif balance >= 0.18:
        context = "CALL_HEAVY_PROXY"
    elif balance <= -0.18:
        context = "PUT_HEAVY_PROXY"
    else:
        context = "BALANCED_PROXY"

    sources = list(
        dict.fromkeys(frame.get("source", pd.Series(dtype=str)).dropna().astype(str))
    )
    freshness = list(
        dict.fromkeys(
            frame.get("freshness_label", pd.Series(dtype=str)).dropna().astype(str)
        )
    )
    source_text = " | ".join([*sources, *freshness])
    descriptor = source_text.lower()
    delayed_or_sandbox = any(
        token in descriptor
        for token in ("sandbox", "delayed", "at least 24h", "indicative")
    )
    if "alpaca" in descriptor and "opra" in descriptor and not delayed_or_sandbox:
        data_tier = "strong"
    elif "tradier" in descriptor and not delayed_or_sandbox:
        data_tier = "strong"
    elif any(
        token in descriptor
        for token in (
            "marketdata",
            "alpaca",
            "tradier",
            "sandbox",
            "delayed",
            "indicative",
        )
    ):
        data_tier = "research_plus"
    else:
        data_tier = "research"

    note = (
        f"GEX proxy from gamma×OI; gamma coverage {gamma_coverage:.0f}%, "
        f"OI coverage {oi_coverage:.0f}%, estimated gamma share "
        f"{estimated_gamma_pct:.0f}%. Gamma flip/walls and liquidity levels are "
        "derived positioning proxies, not verified dealer or institutional inventory. "
        f"Sources: {source_text or 'unknown'}."
    )
    return GammaMap(
        symbol=symbol.upper(),
        spot=round(spot, 4),
        contracts_seen=contracts_seen,
        contracts_with_gamma=gamma_count,
        contracts_with_oi=int(oi_ok.sum()),
        gamma_coverage_pct=round(gamma_coverage, 2),
        oi_coverage_pct=round(oi_coverage, 2),
        estimated_gamma_pct=round(estimated_gamma_pct, 2),
        call_gex_proxy=round(call_total, 2),
        put_gex_proxy=round(put_total, 2),
        signed_gex_proxy=round(signed, 2),
        call_share_pct=round(call_share, 2),
        put_share_pct=round(put_share, 2),
        call_wall=call_wall,
        put_wall=put_wall,
        gamma_flip=gamma_flip,
        nearest_gamma_strike=nearest,
        liquidity_strike=liquidity_strike,
        top_oi_strikes=top_oi,
        top_volume_strikes=top_volume,
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


def contract_gamma_metrics(
    row: dict[str, Any], gamma_map: dict[str, Any]
) -> dict[str, Any]:
    strike = _number(row.get("strike"))
    option_type = str(row.get("option_type") or "").lower()
    by_strike = [
        item for item in gamma_map.get("by_strike", []) if isinstance(item, dict)
    ]
    match = (
        min(by_strike, key=lambda item: abs(_number(item.get("strike")) - strike))
        if by_strike
        else {}
    )
    total = sum(_number(item.get("total_gex_proxy")) for item in by_strike)
    side_value = _number(
        match.get("call_gex_proxy" if option_type == "call" else "put_gex_proxy")
    )
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
        "gamma_flip": gamma_map.get("gamma_flip"),
        "liquidity_strike": gamma_map.get("liquidity_strike"),
        "top_oi_strikes": list(gamma_map.get("top_oi_strikes") or []),
        "top_volume_strikes": list(gamma_map.get("top_volume_strikes") or []),
        "strike_oi": _number(match.get("total_oi")),
        "strike_volume": _number(match.get("total_volume")),
        "strike_liquidity_score": _number(match.get("liquidity_score")),
        "gamma_coverage_pct": _number(gamma_map.get("gamma_coverage_pct")),
        "oi_coverage_pct": _number(gamma_map.get("oi_coverage_pct")),
        "estimated_gamma_pct": _number(gamma_map.get("estimated_gamma_pct")),
    }
