from __future__ import annotations

import argparse
import json
import math
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

# Options state is isolated before Settings is imported.
os.environ.setdefault("DATABASE_PATH", "data/live/options_alert_state.json")
os.environ.setdefault("SIGNAL_JOURNAL_PATH", "data/live/options_signals.jsonl")
os.environ.setdefault("OUTCOME_PATH", "data/live/options_outcomes.json")
os.environ.setdefault("CALIBRATION_PATH", "data/live/options_calibration.json")

from options_radar.catalysts import best_catalyst_map
from options_radar.event_source_policy import event_source_evidence
from options_radar.free_gamma_engine import analyze_free_gamma, contract_gamma_metrics
from options_radar.occ_free_context import OccDailyVolumeClient, side_alignment
from options_radar.official_event_scan import scan_official_events
from options_radar.optionable_universe import IndependentOptionableUniverse
from options_radar.options_consensus import build_directional_signals
from options_radar.scanner import OptionsRadar
from options_radar.settings import Settings

DEFAULT_INPUT = Path("data/universe.txt")
DEFAULT_OUTPUT = Path("public/data/options_latest.json")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _records(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    return [
        {str(key): _json_value(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def load_configured_universe(path: str | Path) -> list[str]:
    source = Path(path)
    if not source.exists():
        return []
    output: list[str] = []
    seen: set[str] = set()
    for raw in source.read_text(encoding="utf-8").splitlines():
        symbol = raw.split("#", 1)[0].strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            output.append(symbol)
    return output


def _flow_semantics(row: dict[str, Any]) -> dict[str, Any]:
    position = str(row.get("aggressor_proxy") or "unknown").lower()
    volume = _number(row.get("volume"))
    oi = _number(row.get("open_interest"))
    ratio = _number(row.get("vol_to_oi_ratio") or row.get("vol_oi"))
    spike = _number(row.get("volume_spike_ratio"))
    pressure = {
        "ask": "تنفيذ قرب جهة العرض يوحي بضغط شراء، لكنه تقدير من Snapshot وليس إثباتًا للمنفذ",
        "bid": "تنفيذ قرب جهة الطلب يوحي بضغط بيع/إغلاق، لكنه تقدير من Snapshot وليس إثباتًا للمنفذ",
    }.get(position, "التنفيذ داخل السبريد لا يعطي جهة منفذ واضحة")
    oi_note = (
        f"حجم اليوم {volume:,.0f} أكبر من OI السابق {oi:,.0f} ({ratio:.2f}×)، وهذا نشاط غير طبيعي فقط؛ فتح مراكز جديدة لا يتأكد إلا من تغير OI بعد التسوية"
        if oi > 0 and volume > oi
        else "Volume/OI عامل نشاط، وليس إثبات فتح أو إغلاق مركز خلال الجلسة"
    )
    return {
        "execution_pressure_proxy": position,
        "execution_pressure_note_ar": pressure,
        "volume_vs_prior_oi_note_ar": oi_note,
        "volume_spike_ratio": spike if spike > 0 else None,
        "opening_position_confirmed": False,
        "sweep_confirmed": False,
        "next_session_oi_confirmation_required": True,
        "snapshot_limit": "لا يمكن إثبات Sweep أو Buy-to-Open من سلسلة Snapshot وحدها",
    }


def _contract_reason(row: dict[str, Any], catalyst: dict[str, Any] | None) -> list[str]:
    side = str(row.get("option_type") or "").upper()
    dte = int(_number(row.get("dte")))
    delta = abs(_number(row.get("delta")))
    spread = _number(row.get("spread_pct"))
    volume = int(_number(row.get("volume")))
    oi = int(_number(row.get("open_interest")))
    vol_oi = _number(row.get("vol_to_oi_ratio") or row.get("vol_oi"))
    flow_score = _number(row.get("flow_momentum_score"))
    score = _number(row.get("score"))
    reasons = [
        f"{side}: اتجاه الأصل الفني داخل محرك الأوبشن نفسه متوافق مع جهة العقد",
        f"الانتهاء بعد {dte} يوم ضمن نافذة الرادار المستقلة",
        f"Delta≈{delta:.2f} يعطي حساسية متوازنة للسعر ضمن فلتر العقد",
        f"Volume {volume:,} / OI {oi:,} / Vol-OI {vol_oi:.2f}×",
        f"جودة التنفيذ: Spread≈{spread * 100:.1f}%، Flow score≈{flow_score:.0f}، Contract score≈{score:.0f}",
    ]
    if catalyst:
        reasons.append(
            f"سياق رسمي: {catalyst.get('category', 'غير مصنف')} عبر {catalyst.get('source', 'مصدر رسمي غير معروف')}"
        )
    return reasons


def enrich_contracts(
    rows: list[dict[str, Any]], catalyst_by_symbol: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        symbol = str(row.get("symbol") or "").upper()
        row["flow_evidence"] = _flow_semantics(row)
        row["rationale_ar"] = _contract_reason(row, catalyst_by_symbol.get(symbol))
        row["research_only"] = True
        row["independent_from_stock_radar"] = True
        output.append(row)
    return output


def _catalyst_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records = _records(frame)
    for row in records:
        row["source_policy"] = event_source_evidence(row)
    return records


def _gamma_candidate_symbols(contracts: list[dict[str, Any]], maximum: int) -> list[str]:
    ranked = sorted(
        contracts,
        key=lambda row: (
            _number(row.get("flow_rank_score")),
            _number(row.get("flow_momentum_score")),
            _number(row.get("score")),
        ),
        reverse=True,
    )
    symbols: list[str] = []
    for row in ranked:
        symbol = str(row.get("symbol") or "").upper().strip()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
        if len(symbols) >= maximum:
            break
    return symbols


def _attach_gamma_and_occ(
    contracts: list[dict[str, Any]],
    *,
    settings: Settings,
    radar: OptionsRadar,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, str]]:
    max_symbols = max(1, min(20, int(os.getenv("OPTIONS_FREE_GAMMA_MAX_SYMBOLS", "10"))))
    symbols = _gamma_candidate_symbols(contracts, max_symbols)
    gamma_maps: dict[str, Any] = {}
    occ_contexts: dict[str, Any] = {}
    errors: dict[str, str] = {}
    occ_enabled = os.getenv("OCC_FREE_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
    occ_client = OccDailyVolumeClient(timeout=min(20, settings.request_timeout_seconds)) if occ_enabled else None

    for symbol in symbols:
        try:
            gamma_map, _ = analyze_free_gamma(symbol, settings=settings, fetcher=radar.fetcher)
            gamma_maps[symbol] = gamma_map.as_dict()
        except Exception as exc:
            errors[f"gamma:{symbol}"] = f"{type(exc).__name__}: {exc}"
            gamma_maps[symbol] = {
                "symbol": symbol,
                "context": "ERROR",
                "data_tier": "unavailable",
                "gamma_coverage_pct": 0.0,
                "oi_coverage_pct": 0.0,
                "by_strike": [],
            }
        if occ_client is not None:
            try:
                occ_contexts[symbol] = occ_client.fetch(symbol)
            except Exception as exc:
                errors[f"occ:{symbol}"] = f"{type(exc).__name__}: {exc}"
                occ_contexts[symbol] = {"success": False, "source": "OCC Volume Query", "error": str(exc)}

    enriched: list[dict[str, Any]] = []
    for raw in contracts:
        row = dict(raw)
        symbol = str(row.get("symbol") or "").upper().strip()
        side = str(row.get("option_type") or "").lower()
        gamma_map = gamma_maps.get(symbol)
        if isinstance(gamma_map, dict):
            row.update(contract_gamma_metrics(row, gamma_map))
        else:
            row.update(
                {
                    "gamma_concentration_pct": 0.0,
                    "gamma_context_alignment": 0.0,
                    "gamma_context": "NOT_ANALYZED",
                    "gamma_data_tier": "unavailable",
                    "gamma_coverage_pct": 0.0,
                    "oi_coverage_pct": 0.0,
                }
            )
        context = occ_contexts.get(symbol)
        row["occ_side_context"] = side_alignment(context, side) if isinstance(context, dict) else {"available": False, "bonus": 0.0}
        enriched.append(row)
    return enriched, gamma_maps, occ_contexts, errors


def run(
    *,
    universe_path: str | Path = DEFAULT_INPUT,
    output_path: str | Path = DEFAULT_OUTPUT,
    max_symbols: int = 80,
    top_per_side: int = 15,
) -> dict[str, Any]:
    settings = Settings()
    settings.validate()
    configured = load_configured_universe(universe_path)
    universe = IndependentOptionableUniverse(
        timeout=settings.request_timeout_seconds,
        user_agent=settings.sec_user_agent,
    ).build(
        configured,
        max_symbols=min(max_symbols, settings.max_universe_size),
        include_cboe_attention=True,
    )
    if not universe.symbols:
        raise RuntimeError("Independent options universe is empty")

    try:
        catalysts = scan_official_events(settings, universe.symbols, lookback_days=7)
    except Exception as exc:
        catalysts = pd.DataFrame()
        universe.errors["official_events"] = f"{type(exc).__name__}: {exc}"
    catalyst_map = best_catalyst_map(catalysts)

    radar = OptionsRadar(settings)
    result = radar.scan(
        universe.symbols,
        top=top_per_side,
        catalysts=catalysts,
    )
    calls = enrich_contracts(_records(result.top_calls), catalyst_map)
    puts = enrich_contracts(_records(result.top_puts), catalyst_map)
    raw_contracts = sorted(
        [*calls, *puts],
        key=lambda row: (
            _number(row.get("flow_rank_score")),
            _number(row.get("flow_momentum_score")),
            _number(row.get("score")),
        ),
        reverse=True,
    )

    contracts, gamma_maps, occ_contexts, context_errors = _attach_gamma_and_occ(
        raw_contracts,
        settings=settings,
        radar=radar,
    )
    strict_min = float(os.getenv("OPTIONS_STRICT_MIN_SCORE", "85"))
    side_edge = float(os.getenv("OPTIONS_STRICT_SIDE_EDGE", "6"))
    directional_signals = build_directional_signals(
        contracts,
        minimum_score=strict_min,
        minimum_side_edge=side_edge,
        max_signals=max(1, min(12, int(os.getenv("OPTIONS_STRICT_MAX_SIGNALS", "8")))),
    )
    top_calls = [row for row in contracts if str(row.get("option_type") or "").lower() == "call"]
    top_puts = [row for row in contracts if str(row.get("option_type") or "").lower() == "put"]

    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "path": "options",
        "architecture": "independent_options_contract_radar_v2_free_gamma",
        "independent_from_stock_radar": True,
        "universe": universe.as_dict(),
        "summary": {
            "symbols_scanned": len(universe.symbols),
            "contracts_selected": len(contracts),
            "calls_selected": len(top_calls),
            "puts_selected": len(top_puts),
            "directional_signals": len(directional_signals),
            "free_alert_eligible": sum(1 for row in directional_signals if row.get("free_alert_eligible") is True),
            "gamma_symbols_analyzed": len(gamma_maps),
            "occ_symbols_checked": len(occ_contexts),
            "contracts_rejected_reported": len(result.rejected),
            "provider": result.provider,
            "market_regime": result.regime,
            "official_optionability_verified": universe.official_verified,
        },
        "flow_policy": {
            "volume_over_oi_means_new_opening_position": False,
            "ask_side_snapshot_means_confirmed_buyer": False,
            "sweep_claim_allowed_from_snapshot_chain": False,
            "oi_confirmation": "next-session change in OI is needed to confirm net new positioning",
            "licensed_trade_quote_requirement": "trade+quote-level data is required before labeling a sweep/aggressor as confirmed",
            "gamma_policy": "GEX is a gamma-times-OI positioning proxy. Put sign is a modeling convention, not verified dealer inventory.",
            "one_side_policy": "A symbol can emit at most one strict CALL or PUT signal and one best contract per run.",
            "note_ar": "الفلو والقاما أدلة سياقية وليسا ضمانًا: لا نثبت Sweep أو Dealer positioning من البيانات المجانية.",
        },
        "contracts": contracts,
        "top_calls": top_calls,
        "top_puts": top_puts,
        "directional_signals": directional_signals,
        "gamma_maps": gamma_maps,
        "occ_daily_context": occ_contexts,
        "rejected": _records(result.rejected.head(250)),
        "official_catalysts": _catalyst_records(catalysts),
        "provider_audit": result.provider_audit,
        "flow_summary": result.flow_summary,
        "market_regime_detail": result.market_regime_detail,
        "errors": {**universe.errors, **result.errors, **context_errors},
        "limitations": [
            *universe.limitations,
            "StockRadar output is never an input to this options universe or contract scoring.",
            "Free gamma uses available chain OI and reported or Black-Scholes-estimated gamma; it is not a verified dealer-position dataset.",
            "OCC daily CALL/PUT volume is official aggregate context only, not a quote, sweep feed, or proof of buy-to-open.",
            "Yahoo/Alpaca indicative inputs remain research-grade; strict free alerts are labeled accordingly and use a higher threshold.",
        ],
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run independent BLACK BOX options contract radar")
    parser.add_argument("--universe", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--max-symbols", type=int, default=int(os.getenv("OPTIONS_INDEPENDENT_MAX_SYMBOLS", "80")))
    parser.add_argument("--top-per-side", type=int, default=int(os.getenv("OPTIONS_INDEPENDENT_TOP_PER_SIDE", "15")))
    args = parser.parse_args()
    payload = run(
        universe_path=args.universe,
        output_path=args.output,
        max_symbols=args.max_symbols,
        top_per_side=args.top_per_side,
    )
    print(
        "Independent options radar: "
        f"symbols={payload['summary']['symbols_scanned']} "
        f"calls={payload['summary']['calls_selected']} "
        f"puts={payload['summary']['puts_selected']} "
        f"strict={payload['summary']['directional_signals']} "
        f"gamma={payload['summary']['gamma_symbols_analyzed']} "
        f"official_optionability={payload['summary']['official_optionability_verified']}"
    )


if __name__ == "__main__":
    main()
