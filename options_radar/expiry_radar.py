from __future__ import annotations

import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .expiry_identity import classify_expiry, holding_horizon_bucket
from .hybrid_fetcher import DataFetcher, DataUnavailableError
from .settings import Settings


@dataclass(frozen=True)
class LiquidityProfile:
    key: str
    label: str
    min_volume: int
    min_open_interest: int
    max_spread_pct: float
    min_abs_delta: float
    max_abs_delta: float
    max_trade_age_minutes: int
    min_premium: float
    max_abs_moneyness_pct: float


LIQUIDITY_PROFILES: dict[str, LiquidityProfile] = {
    "0dte_index": LiquidityProfile(
        key="0dte_index",
        label="0DTE Index",
        min_volume=100,
        min_open_interest=50,
        max_spread_pct=0.10,
        min_abs_delta=0.25,
        max_abs_delta=0.70,
        max_trade_age_minutes=10,
        min_premium=0.25,
        max_abs_moneyness_pct=0.05,
    ),
    "weekly_index": LiquidityProfile(
        key="weekly_index",
        label="Weekly Index",
        min_volume=100,
        min_open_interest=100,
        max_spread_pct=0.12,
        min_abs_delta=0.25,
        max_abs_delta=0.70,
        max_trade_age_minutes=20,
        min_premium=0.20,
        max_abs_moneyness_pct=0.08,
    ),
    "weekly_equity": LiquidityProfile(
        key="weekly_equity",
        label="Weekly Equity",
        min_volume=50,
        min_open_interest=100,
        max_spread_pct=0.15,
        min_abs_delta=0.25,
        max_abs_delta=0.70,
        max_trade_age_minutes=30,
        min_premium=0.10,
        max_abs_moneyness_pct=0.12,
    ),
    "monthly_equity": LiquidityProfile(
        key="monthly_equity",
        label="Monthly Equity",
        min_volume=25,
        min_open_interest=100,
        max_spread_pct=0.18,
        min_abs_delta=0.20,
        max_abs_delta=0.75,
        max_trade_age_minutes=60,
        min_premium=0.10,
        max_abs_moneyness_pct=0.20,
    ),
    "catalyst_small_midcap": LiquidityProfile(
        key="catalyst_small_midcap",
        label="Catalyst Small/Mid Cap",
        min_volume=20,
        min_open_interest=25,
        max_spread_pct=0.25,
        min_abs_delta=0.15,
        max_abs_delta=0.80,
        max_trade_age_minutes=60,
        min_premium=0.05,
        max_abs_moneyness_pct=0.25,
    ),
}

_INDEX_ROOTS = {"SPX", "SPXW", "NDX", "XND"}
_PRIMARY_OPTION_HINTS = (
    "opra",
    "polygon_options",
    "polygon options",
    "massive",
    "tradier",
    "alpaca_options",
    "alpaca options",
    "marketdata",
    "finnhub",
)

_TAB_LABELS = {
    "zero_dte_daily": "0DTE / Daily",
    "weekly_series": "Weekly Series",
    "next_weekly": "Next Weekly",
    "standard_monthly": "Standard Monthly",
    "next_monthly": "Next Monthly",
    "all_expirations": "All Expirations",
    "longer_dated": "Longer-Dated",
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _optional_number(value: Any) -> float | None:
    number = _number(value, float("nan"))
    return number if math.isfinite(number) else None


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def expiry_bucket(dte: int | float | str | None) -> str:
    """Backward-compatible name for the holding-horizon bucket only.

    This function no longer identifies Weekly or Standard Monthly series. Expiry
    family is an independent contract identity produced by expiry_identity.py.
    """

    return holding_horizon_bucket(dte)


def _preferred_side(stock: dict[str, Any]) -> str | None:
    setup = str(stock.get("setup_side") or "").upper()
    direction = str(stock.get("technical_direction") or "").lower()
    if setup == "CALL" or direction == "bullish":
        return "call"
    if setup == "PUT" or direction == "bearish":
        return "put"
    return None


def _spread_pct(row: dict[str, Any]) -> float:
    bid = _number(row.get("bid"), -1.0)
    ask = _number(row.get("ask"), -1.0)
    if bid >= 0 and ask > bid:
        mid = (bid + ask) / 2.0
        return (ask - bid) / mid if mid > 0 else -1.0
    spread = _number(row.get("spread_pct"), -1.0)
    return spread if spread >= 0 else -1.0


def _trade_age_minutes(row: dict[str, Any]) -> float | None:
    explicit = row.get("last_trade_age_minutes")
    if explicit is not None and _number(explicit, -1.0) >= 0:
        return _number(explicit)
    stamp = pd.to_datetime(row.get("updated_at"), utc=True, errors="coerce")
    if pd.isna(stamp):
        return None
    return max(0.0, (pd.Timestamp.now(tz="UTC") - stamp).total_seconds() / 60.0)


def _is_primary_source(source: str) -> bool:
    text = source.lower()
    return any(hint in text for hint in _PRIMARY_OPTION_HINTS) and "yahoo" not in text


def _flow_sources(payload: dict[str, Any]) -> dict[str, list[str]]:
    contracts = ((payload.get("intelligence") or {}).get("contracts") or {})
    output: dict[str, list[str]] = {}
    if not isinstance(contracts, dict):
        return output
    for contract, item in contracts.items():
        if not isinstance(item, dict):
            continue
        sources = [str(value) for value in item.get("market_flow_sources") or [] if value]
        if sources:
            output[str(contract).replace("O:", "").replace(" ", "")] = sources
    return output


def _identity_fields(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("expiry_family") and row.get("classification_method"):
        family = str(row.get("expiry_family") or "UNKNOWN").upper()
        return {
            "expiration_date": str(row.get("expiration_date") or row.get("expiration") or "")[:10],
            "calendar_dte": int(_number(row.get("calendar_dte", row.get("dte")), -1)),
            "trading_dte": int(_number(row.get("trading_dte"), -1)),
            "dte_bucket": str(row.get("dte_bucket") or holding_horizon_bucket(row.get("dte"))),
            "expiry_family": family,
            "is_standard_monthly": bool(row.get("is_standard_monthly")),
            "is_weekly": bool(row.get("is_weekly")),
            "is_daily": bool(row.get("is_daily")),
            "is_quarterly": bool(row.get("is_quarterly")),
            "is_end_of_month": bool(row.get("is_end_of_month")),
            "is_leaps": bool(row.get("is_leaps")),
            "root_symbol": str(row.get("root_symbol") or row.get("symbol") or "").upper(),
            "option_root": str(row.get("option_root") or row.get("root_symbol") or "").upper(),
            "settlement_type": str(row.get("settlement_type") or "UNKNOWN"),
            "settlement_time": str(row.get("settlement_time") or "UNKNOWN"),
            "exercise_style": str(row.get("exercise_style") or "UNKNOWN"),
            "multiplier": int(_number(row.get("multiplier"), 100)),
            "expiry_source": str(row.get("expiry_source") or row.get("source") or "unknown"),
            "classification_confidence": _number(row.get("classification_confidence"), 0.0),
            "classification_method": str(row.get("classification_method") or "unknown"),
        }
    return classify_expiry(row).to_dict()


def _has_fresh_catalyst(stock: dict[str, Any]) -> bool:
    catalyst = stock.get("catalyst") or stock.get("best_catalyst")
    if not catalyst:
        return False
    age_hours = _optional_number(stock.get("catalyst_age_hours"))
    return age_hours is None or age_hours <= 72


def _liquidity_profile(row: dict[str, Any], stock: dict[str, Any], identity: dict[str, Any]) -> LiquidityProfile:
    root = str(identity.get("option_root") or identity.get("root_symbol") or row.get("symbol") or "").upper()
    dte = int(_number(identity.get("calendar_dte"), -1))
    family = str(identity.get("expiry_family") or "UNKNOWN").upper()
    if root in _INDEX_ROOTS and dte == 0:
        return LIQUIDITY_PROFILES["0dte_index"]
    if root in _INDEX_ROOTS:
        return LIQUIDITY_PROFILES["weekly_index"]
    if _has_fresh_catalyst(stock):
        return LIQUIDITY_PROFILES["catalyst_small_midcap"]
    if family in {"STANDARD_MONTHLY", "END_OF_MONTH", "QUARTERLY", "LEAPS"} or dte > 14:
        return LIQUIDITY_PROFILES["monthly_equity"]
    return LIQUIDITY_PROFILES["weekly_equity"]


def _option_expected_response(
    row: dict[str, Any],
    stock: dict[str, Any],
    *,
    entry_premium: float,
) -> dict[str, Any]:
    method = str(row.get("greeks_method") or "provider").lower()
    if "modeled" in method:
        return {
            "available": False,
            "method": "MODELED_GREEKS_NOT_USED_FOR_TARGETS",
            "reason": "Premium targets withheld because Greeks are modeled rather than provider-supplied.",
        }

    delta = _optional_number(row.get("delta"))
    gamma = _optional_number(row.get("gamma")) or 0.0
    if delta is None or entry_premium <= 0:
        return {
            "available": False,
            "method": "INSUFFICIENT_GREEKS",
            "reason": "Provider Delta is unavailable.",
        }

    spot = _optional_number(row.get("underlying_price"))
    entry_low = _optional_number(stock.get("entry_low"))
    entry_high = _optional_number(stock.get("entry_high"))
    underlying_entry = (
        (entry_low + entry_high) / 2.0
        if entry_low is not None and entry_high is not None
        else spot
    )
    if underlying_entry is None or underlying_entry <= 0:
        return {
            "available": False,
            "method": "NO_UNDERLYING_ENTRY",
            "reason": "Underlying entry reference is unavailable.",
        }

    def premium_at(price: Any) -> float | None:
        target = _optional_number(price)
        if target is None:
            return None
        move = target - underlying_entry
        estimate = entry_premium + delta * move + 0.5 * gamma * move * move
        return round(max(0.0, estimate), 4)

    t1 = premium_at(stock.get("target_1"))
    t2 = premium_at(stock.get("target_2"))
    t3 = premium_at(stock.get("target_3"))
    invalidation = premium_at(stock.get("invalidation") or stock.get("stop"))
    return {
        "available": any(value is not None for value in (t1, t2, t3, invalidation)),
        "method": "DELTA_GAMMA_STATIC_IV",
        "greeks_source": str(row.get("source") or "provider"),
        "iv": _optional_number(row.get("iv")),
        "underlying_entry": round(underlying_entry, 4),
        "underlying_invalidation": _optional_number(stock.get("invalidation") or stock.get("stop")),
        "underlying_t1": _optional_number(stock.get("target_1")),
        "underlying_t2": _optional_number(stock.get("target_2")),
        "underlying_t3": _optional_number(stock.get("target_3")),
        "option_at_invalidation": invalidation,
        "option_at_t1": t1,
        "option_at_t2": t2,
        "option_at_t3": t3,
        "assumptions": "Static IV; no theta/path adjustment; research estimate, not a promised premium target.",
    }


def _contract_candidate(
    row: dict[str, Any],
    stock: dict[str, Any],
    flow_sources: list[str],
) -> dict[str, Any] | None:
    side = str(row.get("option_type") or "").lower()
    preferred = _preferred_side(stock)
    if side not in {"call", "put"} or (preferred and side != preferred):
        return None

    identity = _identity_fields(row)
    dte = int(_number(identity.get("calendar_dte"), -999))
    if dte < 0:
        return None
    profile = _liquidity_profile(row, stock, identity)

    bid = _number(row.get("bid"), -1.0)
    ask = _number(row.get("ask"), -1.0)
    mid = (bid + ask) / 2.0 if bid > 0 and ask > bid else max(bid, ask, 0.0)
    volume = _number(row.get("volume"))
    open_interest = _number(row.get("open_interest"))
    raw_delta = _optional_number(row.get("delta"))
    abs_delta = abs(raw_delta) if raw_delta is not None else -1.0
    spread = _spread_pct(row)
    vol_oi = volume / open_interest if open_interest > 0 else 0.0
    age = _trade_age_minutes(row)
    source = str(row.get("source") or "unknown")
    primary = _is_primary_source(source)
    greeks_method = str(row.get("greeks_method") or "provider")
    provider_greeks = "modeled" not in greeks_method.lower()

    strike = _optional_number(row.get("strike"))
    spot = _optional_number(row.get("underlying_price"))
    moneyness = (
        (strike - spot) / spot
        if strike is not None and spot is not None and spot > 0
        else None
    )

    missing: list[str] = []
    if bid <= 0 or ask <= bid:
        missing.append("Bid/Ask غير صالح")
    if spread < 0 or spread > profile.max_spread_pct:
        missing.append(f"السبريد أعلى من {profile.max_spread_pct * 100:.0f}%")
    if volume < profile.min_volume:
        missing.append(f"الحجم أقل من {profile.min_volume}")
    if open_interest < profile.min_open_interest:
        missing.append(f"Open Interest أقل من {profile.min_open_interest}")
    if not profile.min_abs_delta <= abs_delta <= profile.max_abs_delta:
        missing.append("Delta خارج نطاق سيولة هذا المنتج")
    if mid < profile.min_premium:
        missing.append(f"Premium أقل من {profile.min_premium:.2f}")
    if moneyness is not None and abs(moneyness) > profile.max_abs_moneyness_pct:
        missing.append("العقد بعيد جدًا عن السعر الفوري")
    if age is None:
        missing.append("حداثة آخر صفقة غير متاحة")
    elif age > profile.max_trade_age_minutes:
        missing.append("آخر صفقة قديمة")
    if not primary:
        missing.append("مصدر Quote مرخص/أساسي غير متاح")
    if not provider_greeks:
        missing.append("Greeks MODELED وليست Provider Greeks")
    if not flow_sources:
        missing.append("مصدر Flow مستقل غير متاح")
    if str(identity.get("expiry_family")) == "UNKNOWN":
        missing.append("Expiry Family غير مؤكدة")

    stock_score = max(0.0, min(100.0, _number(stock.get("score"))))
    delta_fit = max(0.0, 1.0 - abs(abs_delta - 0.45) / 0.30) if abs_delta >= 0 else 0.0
    spread_fit = (
        max(0.0, 1.0 - spread / profile.max_spread_pct)
        if 0 <= spread <= profile.max_spread_pct
        else 0.0
    )
    freshness_fit = (
        0.0
        if age is None
        else max(0.0, 1.0 - age / max(profile.max_trade_age_minutes, 1))
    )
    rank_score = (
        0.20 * stock_score
        + 15.0 * min(volume / max(profile.min_volume * 3, 1), 1.0)
        + 10.0 * min(open_interest / max(profile.min_open_interest * 4, 1), 1.0)
        + 15.0 * spread_fit
        + 10.0 * min(vol_oi / 2.0, 1.0)
        + 10.0 * delta_fit
        + 5.0 * freshness_fit
        + (10.0 if primary else 2.0)
        + (5.0 if provider_greeks else 0.0)
    )
    rank_score = round(max(0.0, min(100.0, rank_score)), 2)

    execution_errors = (
        "Bid/Ask",
        "السبريد",
        "الحجم",
        "Open Interest",
        "Delta",
        "Premium",
        "العقد بعيد",
    )
    core_quality = not any(text.startswith(execution_errors) for text in missing)
    identity_confidence = _number(identity.get("classification_confidence"), 0.0)
    if (
        core_quality
        and primary
        and provider_greeks
        and flow_sources
        and age is not None
        and age <= profile.max_trade_age_minutes
        and identity_confidence >= 0.50
        and str(identity.get("expiry_family")) != "UNKNOWN"
        and rank_score >= 80
    ):
        tier = "A"
        decision = "A — عقد قابل للبحث بعد تحقق السعر والسيناريو"
    elif core_quality and rank_score >= 62:
        tier = "B"
        decision = "B — جودة جيدة لكن يوجد تأكيد ناقص"
    else:
        tier = "C"
        decision = "C — مراقبة فقط؛ التنفيذ أو البيانات غير مكتملة"

    contract = str(row.get("contract_symbol") or "").replace("O:", "").replace(" ", "")
    expected = _option_expected_response(row, stock, entry_premium=mid)
    reasons = [
        f"Stock setup {stock_score:.1f}",
        f"Vol/OI {vol_oi:.2f}x",
        f"Spread {max(spread, 0.0) * 100:.1f}% of mid",
        f"Expiry {identity.get('expiry_family')} via {identity.get('classification_method')}",
        f"Liquidity profile {profile.key}",
    ]
    if flow_sources:
        reasons.append("Flow مستقل: " + ", ".join(flow_sources[:3]))

    result = {
        "contract_symbol": contract,
        "symbol": str(row.get("symbol") or stock.get("symbol") or "").upper(),
        "option_type": side,
        "strike": strike,
        "expiration": str(row.get("expiration") or identity.get("expiration_date") or ""),
        "dte": dte,
        "expiry_bucket": str(identity.get("dte_bucket")),
        "expiry_bucket_label": f"{identity.get('expiry_family')} · {identity.get('dte_bucket')}",
        "rank_score": rank_score,
        "ranking_score_not_probability": True,
        "opportunity_tier": tier,
        "decision": decision,
        "bid": bid if bid >= 0 else None,
        "ask": ask if ask >= 0 else None,
        "mid": round(mid, 4) if mid > 0 else None,
        "last": _number(row.get("last"), 0.0) or None,
        "entry_price": round(mid, 4) if mid > 0 else None,
        "target_1": expected.get("option_at_t1") if expected.get("available") else None,
        "target_2": expected.get("option_at_t2") if expected.get("available") else None,
        "target_3": expected.get("option_at_t3") if expected.get("available") else None,
        "stop_price": expected.get("option_at_invalidation") if expected.get("available") else None,
        "option_expected_response": expected,
        "fixed_premium_targets_disabled": True,
        "volume": int(volume),
        "open_interest": int(open_interest),
        "vol_to_oi_ratio": round(vol_oi, 4),
        "spread_pct": round(spread, 6) if spread >= 0 else None,
        "delta": round(raw_delta, 4) if raw_delta is not None else None,
        "gamma": _optional_number(row.get("gamma")),
        "theta": _optional_number(row.get("theta")),
        "vega": _optional_number(row.get("vega")),
        "iv": _optional_number(row.get("iv")),
        "greeks_method": greeks_method,
        "greeks_source": "MODELED" if not provider_greeks else source,
        "quote_provenance": row.get("quote_provenance"),
        "greeks_provenance": row.get("greeks_provenance"),
        "underlying_price": spot,
        "moneyness_pct": round(moneyness, 6) if moneyness is not None else None,
        "last_trade_age_minutes": round(age, 1) if age is not None else None,
        "source": source,
        "freshness_label": str(row.get("freshness_label") or ""),
        "primary_or_licensed_quote": primary,
        "flow_sources": flow_sources,
        "liquidity_profile": profile.key,
        "liquidity_grade": "PASS" if core_quality else "REJECT",
        "stock_setup_score": stock_score,
        "stock_setup_side": preferred,
        "stock_entry_low": stock.get("entry_low"),
        "stock_entry_high": stock.get("entry_high"),
        "stock_invalidation": stock.get("invalidation") or stock.get("stop"),
        "stock_target_1": stock.get("target_1"),
        "stock_target_2": stock.get("target_2"),
        "stock_target_3": stock.get("target_3"),
        "missing_confirmations": list(dict.fromkeys(missing)),
        "reasons": reasons,
        "research_only": True,
        "automatic_execution": False,
    }
    result.update(identity)
    return result


def _upside_stocks(payload: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    recommendations = {
        str(item.get("symbol") or "").upper(): item
        for item in payload.get("stock_recommendations", []) or []
        if isinstance(item, dict)
    }
    rows: list[dict[str, Any]] = []
    for stock in payload.get("stocks", []) or []:
        if not isinstance(stock, dict) or _preferred_side(stock) != "call":
            continue
        symbol = str(stock.get("symbol") or "").upper()
        recommendation = recommendations.get(symbol, {})
        rows.append(
            {
                "symbol": symbol,
                "score": _number(stock.get("score")),
                "rating": stock.get("rating"),
                "opportunity_tier": recommendation.get("opportunity_tier")
                or stock.get("opportunity_tier")
                or "C",
                "decision": recommendation.get("decision") or "مراقبة اتجاه صاعد",
                "entry_low": stock.get("entry_low"),
                "entry_high": stock.get("entry_high"),
                "target_1": stock.get("target_1"),
                "target_2": stock.get("target_2"),
                "target_3": stock.get("target_3"),
                "invalidation": stock.get("invalidation") or stock.get("stop"),
                "rsi": stock.get("rsi"),
                "relative_volume": stock.get("finviz_relative_volume")
                or stock.get("relative_volume"),
                "catalyst": stock.get("catalyst"),
                "catalyst_source": stock.get("catalyst_source"),
                "missing_confirmations": recommendation.get("missing_confirmations") or [],
                "research_only": True,
            }
        )
    tier_order = {"A": 3, "B": 2, "C": 1}
    rows.sort(
        key=lambda item: (
            tier_order.get(str(item.get("opportunity_tier")), 0),
            _number(item.get("score")),
        ),
        reverse=True,
    )
    return rows[:limit]


def _unique_ordered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tier_order = {"A": 3, "B": 2, "C": 1}
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("contract_symbol") or "")
        current = unique.get(key)
        if current is None or _number(row.get("rank_score")) > _number(current.get("rank_score")):
            unique[key] = row
    return sorted(
        unique.values(),
        key=lambda row: (
            tier_order.get(str(row.get("opportunity_tier")), 0),
            _number(row.get("rank_score")),
        ),
        reverse=True,
    )


def _side_group(
    rows: list[dict[str, Any]],
    *,
    label: str,
    top_per_side: int,
) -> dict[str, Any]:
    ordered = _unique_ordered(rows)
    calls = [row for row in ordered if row.get("option_type") == "call"][:top_per_side]
    puts = [row for row in ordered if row.get("option_type") == "put"][:top_per_side]
    return {"label": label, "calls": calls, "puts": puts, "count": len(calls) + len(puts)}


def _nearest_family_expiry(rows: list[dict[str, Any]], family: str) -> str | None:
    expirations = sorted(
        {
            str(row.get("expiration_date") or row.get("expiration") or "")[:10]
            for row in rows
            if str(row.get("expiry_family") or "") == family and int(_number(row.get("dte"), -1)) >= 0
        }
    )
    return expirations[0] if expirations else None


def _build_tabs(rows: list[dict[str, Any]], top_per_side: int) -> dict[str, Any]:
    next_weekly = _nearest_family_expiry(rows, "WEEKLY")
    next_monthly = _nearest_family_expiry(rows, "STANDARD_MONTHLY")
    filters = {
        "zero_dte_daily": lambda row: int(_number(row.get("dte"), -1)) == 0
        or str(row.get("expiry_family")) == "DAILY",
        "weekly_series": lambda row: str(row.get("expiry_family")) == "WEEKLY",
        "next_weekly": lambda row: str(row.get("expiry_family")) == "WEEKLY"
        and str(row.get("expiration_date") or "") == next_weekly,
        "standard_monthly": lambda row: str(row.get("expiry_family")) == "STANDARD_MONTHLY",
        "next_monthly": lambda row: str(row.get("expiry_family")) == "STANDARD_MONTHLY"
        and str(row.get("expiration_date") or "") == next_monthly,
        "all_expirations": lambda row: True,
        "longer_dated": lambda row: int(_number(row.get("dte"), -1)) > 30
        or str(row.get("expiry_family")) == "LEAPS",
    }
    return {
        key: _side_group(
            [row for row in rows if predicate(row)],
            label=_TAB_LABELS[key],
            top_per_side=top_per_side,
        )
        for key, predicate in filters.items()
    }


def _fetch_one_symbol(
    settings: Settings,
    stock: dict[str, Any],
    min_dte: int,
    max_dte: int,
) -> tuple[str, Any, float]:
    symbol = str(stock.get("symbol") or "").upper()
    started = time.perf_counter()
    local_fetcher = DataFetcher(settings)
    try:
        result = local_fetcher.fetch_option_chain(
            symbol,
            min_dte=min_dte,
            max_dte=max_dte,
            apply_guards=False,
        )
        return symbol, result, round(time.perf_counter() - started, 4)
    except DataUnavailableError as exc:
        return symbol, exc, round(time.perf_counter() - started, 4)


def build_expiry_radar(
    payload: dict[str, Any],
    settings: Settings | None = None,
    *,
    fetcher: DataFetcher | None = None,
    max_symbols: int | None = None,
    top_per_side: int | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    settings = settings or Settings()
    supplied_fetcher = fetcher is not None
    fetcher = fetcher or DataFetcher(settings)
    max_symbols = max_symbols or int(os.getenv("EXPIRY_RADAR_MAX_SYMBOLS", "8"))
    top_per_side = top_per_side or int(os.getenv("EXPIRY_RADAR_TOP_PER_SIDE", "8"))
    min_dte = int(os.getenv("EXPIRY_RADAR_MIN_DTE", "0"))
    max_dte = int(os.getenv("EXPIRY_RADAR_MAX_DTE", "120"))
    workers = max(1, min(int(os.getenv("EXPIRY_RADAR_WORKERS", "3")), max_symbols))

    stocks = [row for row in payload.get("stocks", []) or [] if isinstance(row, dict)]
    stocks.sort(key=lambda row: _number(row.get("score")), reverse=True)
    directional = [row for row in stocks if _preferred_side(row) is not None][:max_symbols]
    stock_map = {str(row.get("symbol") or "").upper(): row for row in directional}
    flow_map = _flow_sources(payload)
    all_candidates: list[dict[str, Any]] = []
    provider_audit: dict[str, Any] = {}
    errors: dict[str, str] = {}
    symbol_seconds: dict[str, float] = {}

    fetched: list[tuple[str, Any, float]] = []
    if supplied_fetcher or len(directional) <= 1:
        for stock in directional:
            symbol = str(stock.get("symbol") or "").upper()
            symbol_started = time.perf_counter()
            try:
                result = fetcher.fetch_option_chain(
                    symbol,
                    min_dte=min_dte,
                    max_dte=max_dte,
                    apply_guards=False,
                )
                fetched.append((symbol, result, round(time.perf_counter() - symbol_started, 4)))
            except DataUnavailableError as exc:
                fetched.append((symbol, exc, round(time.perf_counter() - symbol_started, 4)))
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="expiry-radar") as executor:
            futures = [
                executor.submit(_fetch_one_symbol, settings, stock, min_dte, max_dte)
                for stock in directional
            ]
            for future in as_completed(futures):
                fetched.append(future.result())

    for symbol, outcome, elapsed in fetched:
        symbol_seconds[symbol] = elapsed
        if isinstance(outcome, DataUnavailableError):
            provider_audit[symbol] = {
                "success": False,
                "attempts": [attempt.to_dict() for attempt in outcome.attempts],
            }
            errors[symbol] = str(outcome)
            continue

        provider_audit[symbol] = {"success": True, **outcome.audit_dict()}
        frame = outcome.data if isinstance(outcome.data, pd.DataFrame) else pd.DataFrame()
        if frame.empty:
            continue
        stock = stock_map.get(symbol, {})
        for row in frame.to_dict(orient="records"):
            contract = str(row.get("contract_symbol") or "").replace("O:", "").replace(" ", "")
            candidate = _contract_candidate(row, stock, flow_map.get(contract, []))
            if candidate is not None:
                all_candidates.append(candidate)

    ordered = _unique_ordered(all_candidates)
    tabs = _build_tabs(ordered, top_per_side)
    profiles = {
        "daily": {
            **tabs["zero_dte_daily"],
            "config": {"identity_rule": "calendar_dte == 0 OR expiry_family == DAILY"},
        },
        "weekly": {
            **tabs["weekly_series"],
            "config": {"identity_rule": "expiry_family == WEEKLY"},
        },
        "monthly": {
            **tabs["standard_monthly"],
            "config": {"identity_rule": "expiry_family == STANDARD_MONTHLY"},
        },
    }

    unknown_count = sum(1 for row in ordered if row.get("expiry_family") == "UNKNOWN")
    fallback_count = sum(
        1 for row in ordered if "fallback" in str(row.get("classification_method") or "")
    )
    modeled_greeks = sum(1 for row in ordered if row.get("greeks_source") == "MODELED")
    total_seconds = round(time.perf_counter() - started, 4)

    return {
        "generated_at": _utc_iso(),
        "upside_stocks": _upside_stocks(payload),
        "profiles": profiles,
        "tabs": tabs,
        "provider_audit": provider_audit,
        "errors": errors,
        "liquidity_profiles": {key: asdict(value) for key, value in LIQUIDITY_PROFILES.items()},
        "performance": {
            "total_seconds": total_seconds,
            "bounded_symbol_concurrency": not supplied_fetcher and len(directional) > 1,
            "max_workers": workers if not supplied_fetcher else 1,
            "symbol_seconds": symbol_seconds,
        },
        "data_quality": {
            "unknown_expiry_family": unknown_count,
            "calendar_fallback_contracts": fallback_count,
            "modeled_greeks_contracts": modeled_greeks,
        },
        "summary": {
            "symbols_scanned": len(directional),
            "contracts_published": len(ordered),
            "daily": profiles["daily"]["count"],
            "weekly": profiles["weekly"]["count"],
            "monthly": profiles["monthly"]["count"],
            "unknown_expiry_family": unknown_count,
        },
        "policy": {
            "official_or_licensed_apis_only": True,
            "direct_exchange_site_scraping": False,
            "tier_a_requires_primary_quote_and_independent_flow": True,
            "tier_a_requires_provider_greeks": True,
            "yahoo_can_never_create_tier_a": True,
            "expiry_family_is_not_dte_bucket": True,
            "provider_metadata_wins_over_calendar": True,
            "calendar_inference_is_fallback": True,
            "daily_definition": "0DTE view or provider-classified DAILY series",
            "weekly_definition": "expiry_family == WEEKLY; independent of DTE",
            "monthly_definition": "expiry_family == STANDARD_MONTHLY; independent of DTE",
            "fixed_premium_targets": False,
            "underlying_targets_drive_option_response": True,
            "ranking_score_is_not_probability": True,
            "edge_not_yet_proven": True,
            "research_only": True,
            "automatic_execution": False,
            "profit_is_not_guaranteed": True,
        },
    }


def apply_expiry_radar(payload: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    radar = build_expiry_radar(payload, settings)
    payload["expiry_radar"] = radar
    summary = payload.setdefault("summary", {})
    summary["expiry_daily_contracts"] = radar["summary"]["daily"]
    summary["expiry_weekly_contracts"] = radar["summary"]["weekly"]
    summary["expiry_monthly_contracts"] = radar["summary"]["monthly"]
    summary["expiry_unknown_family"] = radar["summary"]["unknown_expiry_family"]
    summary["upside_stock_candidates"] = len(radar["upside_stocks"])
    payload.setdefault("recommendation_policy", {}).update(
        {
            "expiry_identity_engine": True,
            "expiry_family_separate_from_dte": True,
            "expiry_radar_research_only": True,
            "expiry_radar_no_profit_guarantee": True,
            "edge_not_yet_proven": True,
        }
    )
    return payload
