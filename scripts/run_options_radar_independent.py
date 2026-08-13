from __future__ import annotations

import argparse
import json
import math
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

# These defaults are set before importing Settings so the options path cannot
# accidentally share StockRadar state/journals/calibration.
os.environ.setdefault("DATABASE_PATH", "data/live/options_alert_state.json")
os.environ.setdefault("SIGNAL_JOURNAL_PATH", "data/live/options_signals.jsonl")
os.environ.setdefault("OUTCOME_PATH", "data/live/options_outcomes.json")
os.environ.setdefault("CALIBRATION_PATH", "data/live/options_calibration.json")

from options_radar.catalysts import CatalystScanner, best_catalyst_map
from options_radar.event_source_policy import event_source_evidence
from options_radar.optionable_universe import IndependentOptionableUniverse
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
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
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
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        output.append(symbol)
    return output


def _flow_semantics(row: dict[str, Any]) -> dict[str, Any]:
    position = str(row.get("aggressor_proxy") or "unknown").lower()
    volume = _number(row.get("volume"))
    oi = _number(row.get("open_interest"))
    ratio = _number(row.get("vol_to_oi_ratio") or row.get("vol_oi"))
    spike = _number(row.get("volume_spike_ratio"))

    if position == "ask":
        pressure_ar = "تنفيذ قرب جهة العرض يوحي بضغط شراء، لكنه تقدير من Snapshot وليس إثباتًا للمنفذ"
    elif position == "bid":
        pressure_ar = "تنفيذ قرب جهة الطلب يوحي بضغط بيع/إغلاق، لكنه تقدير من Snapshot وليس إثباتًا للمنفذ"
    else:
        pressure_ar = "التنفيذ داخل السبريد لا يعطي جهة منفذ واضحة"

    if oi > 0 and volume > oi:
        oi_ar = (
            f"حجم اليوم {volume:,.0f} أكبر من OI السابق {oi:,.0f} ({ratio:.2f}×)، "
            "وهذا نشاط غير طبيعي فقط؛ فتح مراكز جديدة لا يتأكد إلا من تغير OI بعد التسوية"
        )
    else:
        oi_ar = "Volume/OI عامل نشاط، وليس إثبات فتح أو إغلاق مركز خلال الجلسة"

    return {
        "execution_pressure_proxy": position,
        "execution_pressure_note_ar": pressure_ar,
        "volume_vs_prior_oi_note_ar": oi_ar,
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
            f"سياق الحدث: {catalyst.get('category', 'غير مصنف')} عبر {catalyst.get('source', 'مصدر غير معروف')}"
        )
    return reasons


def enrich_contracts(
    rows: list[dict[str, Any]], catalyst_by_symbol: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        symbol = str(row.get("symbol") or "").upper()
        catalyst = catalyst_by_symbol.get(symbol)
        row["flow_evidence"] = _flow_semantics(row)
        row["rationale_ar"] = _contract_reason(row, catalyst)
        row["research_only"] = True
        row["independent_from_stock_radar"] = True
        output.append(row)
    return output


def _catalyst_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records = _records(frame)
    for row in records:
        row["source_policy"] = event_source_evidence(row)
    return records


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

    # Catalysts enrich the underlying context but do not nominate the universe.
    # The options path remains options-native even if catalyst collection fails.
    try:
        catalysts = CatalystScanner(settings).scan(universe.symbols, lookback_days=7)
    except Exception as exc:
        catalysts = pd.DataFrame()
        universe.errors["catalysts"] = f"{type(exc).__name__}: {exc}"
    catalyst_map = best_catalyst_map(catalysts)

    result = OptionsRadar(settings).scan(
        universe.symbols,
        top=top_per_side,
        catalysts=catalysts,
    )

    calls = enrich_contracts(_records(result.top_calls), catalyst_map)
    puts = enrich_contracts(_records(result.top_puts), catalyst_map)
    contracts = sorted(
        [*calls, *puts],
        key=lambda row: (
            _number(row.get("flow_rank_score")),
            _number(row.get("flow_momentum_score")),
            _number(row.get("score")),
        ),
        reverse=True,
    )

    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "path": "options",
        "architecture": "independent_options_contract_radar_v1",
        "independent_from_stock_radar": True,
        "universe": universe.as_dict(),
        "summary": {
            "symbols_scanned": len(universe.symbols),
            "contracts_selected": len(contracts),
            "calls_selected": len(calls),
            "puts_selected": len(puts),
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
            "note_ar": (
                "الفلو دليل سياقي لا توصية مستقلة: الصفقة قد تكون فتحًا أو إغلاقًا أو Hedge أو Roll أو رجلًا من Spread."
            ),
        },
        "contracts": contracts,
        "top_calls": calls,
        "top_puts": puts,
        "rejected": _records(result.rejected.head(250)),
        "catalysts": _catalyst_records(catalysts),
        "provider_audit": result.provider_audit,
        "flow_summary": result.flow_summary,
        "market_regime_detail": result.market_regime_detail,
        "errors": {**universe.errors, **result.errors},
        "limitations": [
            *universe.limitations,
            "This path discovers contracts independently; StockRadar output is never an input to universe selection or contract scoring.",
            "With Yahoo/indicative snapshots, results are research/watchlist quality and cannot prove full OPRA tape flow.",
        ],
    }

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(destination)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the independent BLACK BOX options contract radar"
    )
    parser.add_argument("--universe", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=int(os.getenv("OPTIONS_INDEPENDENT_MAX_SYMBOLS", "80")),
    )
    parser.add_argument(
        "--top-per-side",
        type=int,
        default=int(os.getenv("OPTIONS_INDEPENDENT_TOP_PER_SIDE", "15")),
    )
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
        f"official_optionability={payload['summary']['official_optionability_verified']}"
    )


if __name__ == "__main__":
    main()
