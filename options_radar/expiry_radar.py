from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .hybrid_fetcher import DataFetcher, DataUnavailableError
from .settings import Settings


@dataclass(frozen=True)
class ExpiryProfile:
    key: str
    label: str
    min_dte: int
    max_dte: int
    min_volume: int
    min_open_interest: int
    max_spread_pct: float
    min_abs_delta: float
    max_abs_delta: float
    max_trade_age_minutes: int
    target_1_pct: float
    target_2_pct: float
    stop_pct: float


EXPIRY_PROFILES: tuple[ExpiryProfile, ...] = (
    ExpiryProfile(
        key="daily",
        label="يومي / 0–2 DTE",
        min_dte=0,
        max_dte=2,
        min_volume=300,
        min_open_interest=200,
        max_spread_pct=0.12,
        min_abs_delta=0.35,
        max_abs_delta=0.60,
        max_trade_age_minutes=20,
        target_1_pct=0.18,
        target_2_pct=0.32,
        stop_pct=0.15,
    ),
    ExpiryProfile(
        key="weekly",
        label="أسبوعي / 3–10 DTE",
        min_dte=3,
        max_dte=10,
        min_volume=250,
        min_open_interest=150,
        max_spread_pct=0.15,
        min_abs_delta=0.30,
        max_abs_delta=0.60,
        max_trade_age_minutes=30,
        target_1_pct=0.20,
        target_2_pct=0.35,
        stop_pct=0.18,
    ),
    ExpiryProfile(
        key="monthly",
        label="شهري / 11–45 DTE",
        min_dte=11,
        max_dte=45,
        min_volume=200,
        min_open_interest=100,
        max_spread_pct=0.18,
        min_abs_delta=0.25,
        max_abs_delta=0.60,
        max_trade_age_minutes=60,
        target_1_pct=0.25,
        target_2_pct=0.45,
        stop_pct=0.20,
    ),
)

_PRIMARY_OPTION_HINTS = (
    "opra",
    "polygon_options",
    "polygon options",
    "massive",
    "tradier",
    "alpaca_options",
    "alpaca options",
    "marketdata",
)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def expiry_bucket(dte: int | float | str | None) -> str | None:
    days = int(_number(dte, -999))
    for profile in EXPIRY_PROFILES:
        if profile.min_dte <= days <= profile.max_dte:
            return profile.key
    return None


def _profile(key: str) -> ExpiryProfile:
    return next(profile for profile in EXPIRY_PROFILES if profile.key == key)


def _preferred_side(stock: dict[str, Any]) -> str | None:
    setup = str(stock.get("setup_side") or "").upper()
    direction = str(stock.get("technical_direction") or "").lower()
    if setup == "CALL" or direction == "bullish":
        return "call"
    if setup == "PUT" or direction == "bearish":
        return "put"
    return None


def _spread_pct(row: dict[str, Any]) -> float:
    spread = _number(row.get("spread_pct"), -1.0)
    if spread >= 0:
        return spread
    bid = _number(row.get("bid"), -1.0)
    ask = _number(row.get("ask"), -1.0)
    return (ask - bid) / ask if bid >= 0 and ask > 0 and ask >= bid else -1.0


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


def _contract_candidate(
    row: dict[str, Any],
    stock: dict[str, Any],
    profile: ExpiryProfile,
    flow_sources: list[str],
) -> dict[str, Any] | None:
    side = str(row.get("option_type") or "").lower()
    preferred = _preferred_side(stock)
    if side not in {"call", "put"} or (preferred and side != preferred):
        return None

    dte = int(_number(row.get("dte"), -999))
    if not profile.min_dte <= dte <= profile.max_dte:
        return None

    bid = _number(row.get("bid"), -1.0)
    ask = _number(row.get("ask"), -1.0)
    volume = _number(row.get("volume"))
    open_interest = _number(row.get("open_interest"))
    delta = abs(_number(row.get("delta"), -1.0))
    spread = _spread_pct(row)
    vol_oi = volume / open_interest if open_interest > 0 else 0.0
    age = _trade_age_minutes(row)
    source = str(row.get("source") or "unknown")
    primary = _is_primary_source(source)

    missing: list[str] = []
    if bid <= 0 or ask <= bid:
        missing.append("Bid/Ask غير صالح")
    if spread < 0 or spread > profile.max_spread_pct:
        missing.append(f"السبريد أعلى من {profile.max_spread_pct * 100:.0f}%")
    if volume < profile.min_volume:
        missing.append(f"الحجم أقل من {profile.min_volume}")
    if open_interest < profile.min_open_interest:
        missing.append(f"Open Interest أقل من {profile.min_open_interest}")
    if not profile.min_abs_delta <= delta <= profile.max_abs_delta:
        missing.append("Delta خارج النطاق المناسب")
    if age is None:
        missing.append("حداثة آخر صفقة غير متاحة")
    elif age > profile.max_trade_age_minutes:
        missing.append("آخر صفقة قديمة")
    if not primary:
        missing.append("مصدر OPRA/مرخص غير متاح")
    if not flow_sources:
        missing.append("مصدر Flow مستقل غير متاح")

    stock_score = max(0.0, min(100.0, _number(stock.get("score"))))
    delta_fit = max(0.0, 1.0 - abs(delta - 0.45) / 0.25) if delta >= 0 else 0.0
    spread_fit = max(0.0, 1.0 - max(spread, profile.max_spread_pct) / profile.max_spread_pct)
    if 0 <= spread <= profile.max_spread_pct:
        spread_fit = 1.0 - spread / profile.max_spread_pct
    freshness_fit = 0.0 if age is None else max(0.0, 1.0 - age / max(profile.max_trade_age_minutes, 1))
    rank_score = (
        0.25 * stock_score
        + 15.0 * min(volume / max(profile.min_volume * 3, 1), 1.0)
        + 10.0 * min(open_interest / max(profile.min_open_interest * 4, 1), 1.0)
        + 15.0 * spread_fit
        + 10.0 * min(vol_oi / 2.0, 1.0)
        + 10.0 * delta_fit
        + 5.0 * freshness_fit
        + (10.0 if primary else 3.0)
    )
    rank_score = round(max(0.0, min(100.0, rank_score)), 2)

    core_quality = not any(
        text.startswith(("Bid/Ask", "السبريد", "الحجم", "Open Interest", "Delta"))
        for text in missing
    )
    if core_quality and primary and flow_sources and age is not None and age <= profile.max_trade_age_minutes and rank_score >= 80:
        tier = "A"
        decision = "A — مرشح بحثي مكتمل بعد تحقق السعر"
    elif core_quality and rank_score >= 62:
        tier = "B"
        decision = "B — عقد قوي نسبيًا وينتظر تأكيد المصدر/Flow"
    else:
        tier = "C"
        decision = "C — مراقبة فقط؛ جودة التنفيذ أو التأكيد غير مكتمل"

    entry = (bid + ask) / 2.0 if bid > 0 and ask > bid else max(ask, bid, 0.0)
    contract = str(row.get("contract_symbol") or "").replace("O:", "").replace(" ", "")
    reasons = [
        f"درجة إعداد السهم {stock_score:.1f}",
        f"Vol/OI {vol_oi:.2f}x",
        f"Spread {max(spread, 0.0) * 100:.1f}%",
        f"Delta {delta:.2f}" if delta >= 0 else "Delta غير متاحة",
    ]
    if flow_sources:
        reasons.append("Flow مستقل: " + ", ".join(flow_sources[:3]))

    return {
        "contract_symbol": contract,
        "symbol": str(row.get("symbol") or stock.get("symbol") or "").upper(),
        "option_type": side,
        "expiration": str(row.get("expiration") or ""),
        "dte": dte,
        "expiry_bucket": profile.key,
        "expiry_bucket_label": profile.label,
        "rank_score": rank_score,
        "opportunity_tier": tier,
        "decision": decision,
        "bid": bid if bid >= 0 else None,
        "ask": ask if ask >= 0 else None,
        "last": _number(row.get("last"), 0.0) or None,
        "entry_price": round(entry, 4) if entry > 0 else None,
        "target_1": round(entry * (1.0 + profile.target_1_pct), 4) if entry > 0 else None,
        "target_2": round(entry * (1.0 + profile.target_2_pct), 4) if entry > 0 else None,
        "stop_price": round(entry * (1.0 - profile.stop_pct), 4) if entry > 0 else None,
        "volume": int(volume),
        "open_interest": int(open_interest),
        "vol_to_oi_ratio": round(vol_oi, 4),
        "spread_pct": round(spread, 6) if spread >= 0 else None,
        "delta": round(delta, 4) if delta >= 0 else None,
        "iv": _number(row.get("iv"), 0.0) or None,
        "last_trade_age_minutes": round(age, 1) if age is not None else None,
        "source": source,
        "freshness_label": str(row.get("freshness_label") or ""),
        "primary_or_licensed_quote": primary,
        "flow_sources": flow_sources,
        "stock_setup_score": stock_score,
        "stock_setup_side": preferred,
        "stock_entry_low": stock.get("entry_low"),
        "stock_entry_high": stock.get("entry_high"),
        "stock_target_1": stock.get("target_1"),
        "stock_target_2": stock.get("target_2"),
        "missing_confirmations": list(dict.fromkeys(missing)),
        "reasons": reasons,
        "research_only": True,
        "automatic_execution": False,
    }


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
                "opportunity_tier": recommendation.get("opportunity_tier") or stock.get("opportunity_tier") or "C",
                "decision": recommendation.get("decision") or "مراقبة اتجاه صاعد",
                "entry_low": stock.get("entry_low"),
                "entry_high": stock.get("entry_high"),
                "target_1": stock.get("target_1"),
                "target_2": stock.get("target_2"),
                "invalidation": stock.get("invalidation") or stock.get("stop"),
                "rsi": stock.get("rsi"),
                "relative_volume": stock.get("finviz_relative_volume") or stock.get("relative_volume"),
                "catalyst": stock.get("catalyst"),
                "catalyst_source": stock.get("catalyst_source"),
                "missing_confirmations": recommendation.get("missing_confirmations") or [],
                "research_only": True,
            }
        )
    tier_order = {"A": 3, "B": 2, "C": 1}
    rows.sort(key=lambda item: (tier_order.get(str(item.get("opportunity_tier")), 0), _number(item.get("score"))), reverse=True)
    return rows[:limit]


def build_expiry_radar(
    payload: dict[str, Any],
    settings: Settings | None = None,
    *,
    fetcher: DataFetcher | None = None,
    max_symbols: int | None = None,
    top_per_side: int | None = None,
) -> dict[str, Any]:
    settings = settings or Settings()
    fetcher = fetcher or DataFetcher(settings)
    max_symbols = max_symbols or int(os.getenv("EXPIRY_RADAR_MAX_SYMBOLS", "8"))
    top_per_side = top_per_side or int(os.getenv("EXPIRY_RADAR_TOP_PER_SIDE", "8"))

    stocks = [row for row in payload.get("stocks", []) or [] if isinstance(row, dict)]
    stocks.sort(key=lambda row: _number(row.get("score")), reverse=True)
    directional = [row for row in stocks if _preferred_side(row) is not None][:max_symbols]
    flow_map = _flow_sources(payload)
    candidates: dict[str, list[dict[str, Any]]] = {profile.key: [] for profile in EXPIRY_PROFILES}
    provider_audit: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for stock in directional:
        symbol = str(stock.get("symbol") or "").upper()
        if not symbol:
            continue
        try:
            result = fetcher.fetch_option_chain(
                symbol,
                min_dte=min(profile.min_dte for profile in EXPIRY_PROFILES),
                max_dte=max(profile.max_dte for profile in EXPIRY_PROFILES),
                apply_guards=False,
            )
        except DataUnavailableError as exc:
            provider_audit[symbol] = {
                "success": False,
                "attempts": [attempt.to_dict() for attempt in exc.attempts],
            }
            errors[symbol] = str(exc)
            continue

        provider_audit[symbol] = {"success": True, **result.audit_dict()}
        frame = result.data if isinstance(result.data, pd.DataFrame) else pd.DataFrame()
        if frame.empty:
            continue
        for row in frame.to_dict(orient="records"):
            bucket = expiry_bucket(row.get("dte"))
            if bucket is None:
                continue
            contract = str(row.get("contract_symbol") or "").replace("O:", "").replace(" ", "")
            candidate = _contract_candidate(row, stock, _profile(bucket), flow_map.get(contract, []))
            if candidate is not None:
                candidates[bucket].append(candidate)

    tier_order = {"A": 3, "B": 2, "C": 1}
    profiles: dict[str, Any] = {}
    total = 0
    for profile in EXPIRY_PROFILES:
        rows = candidates[profile.key]
        unique: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(row.get("contract_symbol") or "")
            current = unique.get(key)
            if current is None or _number(row.get("rank_score")) > _number(current.get("rank_score")):
                unique[key] = row
        ordered = sorted(
            unique.values(),
            key=lambda row: (tier_order.get(str(row.get("opportunity_tier")), 0), _number(row.get("rank_score"))),
            reverse=True,
        )
        calls = [row for row in ordered if row.get("option_type") == "call"][:top_per_side]
        puts = [row for row in ordered if row.get("option_type") == "put"][:top_per_side]
        total += len(calls) + len(puts)
        profiles[profile.key] = {
            "config": asdict(profile),
            "calls": calls,
            "puts": puts,
            "count": len(calls) + len(puts),
        }

    return {
        "generated_at": _utc_iso(),
        "upside_stocks": _upside_stocks(payload),
        "profiles": profiles,
        "provider_audit": provider_audit,
        "errors": errors,
        "summary": {
            "symbols_scanned": len(directional),
            "contracts_published": total,
            "daily": profiles["daily"]["count"],
            "weekly": profiles["weekly"]["count"],
            "monthly": profiles["monthly"]["count"],
        },
        "policy": {
            "official_or_licensed_apis_only": True,
            "direct_exchange_site_scraping": False,
            "tier_a_requires_primary_quote_and_independent_flow": True,
            "yahoo_can_never_create_tier_a": True,
            "daily_definition": "0-2 DTE",
            "weekly_definition": "3-10 DTE",
            "monthly_definition": "11-45 DTE",
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
    summary["upside_stock_candidates"] = len(radar["upside_stocks"])
    payload.setdefault("recommendation_policy", {}).update(
        {
            "daily_weekly_monthly_contract_radar": True,
            "expiry_radar_research_only": True,
            "expiry_radar_no_profit_guarantee": True,
        }
    )
    return payload
