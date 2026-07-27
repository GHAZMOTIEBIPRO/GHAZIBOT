from __future__ import annotations

import argparse
import json
import logging
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate the Phase 5.1 public JSON feed for GHAZI Market Radar."
    )
    parser.add_argument("--universe", default="data/universe.txt")
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--top-stocks", type=int, default=15)
    parser.add_argument(
        "--top-options", type=int, default=15, help="Maximum per side"
    )
    parser.add_argument("--output", default="public/data/latest.json")
    parser.add_argument("--skip-closed", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        if isinstance(value, pd.Timestamp) and value.tzinfo is None:
            value = value.tz_localize("UTC")
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 6)
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _json_value(item) for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def _records(
    frame: pd.DataFrame,
    columns: list[str] | None = None,
) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    selected = (
        frame
        if columns is None
        else frame[[column for column in columns if column in frame.columns]]
    )
    return [
        {str(key): _json_value(value) for key, value in row.items()}
        for row in selected.to_dict(orient="records")
    ]


def _best_options_by_symbol(
    options: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    if options.empty or "symbol" not in options.columns:
        return {}
    sort_columns = [
        column
        for column in (
            "flow_rank_score",
            "flow_momentum_score",
            "score",
            "reward_risk_1",
            "vol_to_oi_ratio",
            "volume",
        )
        if column in options.columns
    ]
    ordered = options.sort_values(
        sort_columns,
        ascending=[False] * len(sort_columns),
        na_position="last",
    )
    best = ordered.drop_duplicates("symbol")
    fields = [
        "contract_symbol",
        "expiration",
        "strike",
        "option_type",
        "score",
        "rating",
        "flow_rank_score",
        "flow_momentum_score",
        "side_rank",
        "entry_price",
        "target_1",
        "target_2",
        "stop_price",
        "underlying_target_1",
        "underlying_target_2",
        "underlying_invalidation",
        "risk_pct",
        "reward_risk_1",
        "reward_risk_2",
        "volume",
        "open_interest",
        "vol_oi",
        "vol_to_oi_ratio",
        "buying_flow_type",
        "unusual_activity_flag",
        "high_accumulation",
        "volume_spike_ratio",
        "volume_spike_flag",
        "iv",
        "delta",
        "spread_pct",
        "aggressor_proxy",
        "source",
        "freshness_label",
        "data_status",
        "last_trade_age_minutes",
        "model_version",
        "catalyst_url",
    ]
    result: dict[str, dict[str, Any]] = {}
    for _, row in best.iterrows():
        symbol = str(row.get("symbol", "")).upper()
        result[symbol] = {
            key: _json_value(row.get(key))
            for key in fields
            if key in best.columns
        }
    return result


def _attach_best_option(
    stocks: list[dict[str, Any]],
    best_options: dict[str, dict[str, Any]],
) -> None:
    for stock in stocks:
        stock["best_option"] = best_options.get(
            str(stock.get("symbol", "")).upper()
        )


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def _closed_payload(
    settings: Any,
    clock: Any,
    generated_at: datetime,
) -> dict[str, Any]:
    return {
        "schema_version": 5,
        "phase": "5.1",
        "model_version": settings.model_version,
        "generated_at": generated_at.isoformat(),
        "market_regime": "closed",
        "market_regime_detail": {},
        "market_clock": clock.__dict__,
        "summary": {},
        "flow_summary": {},
        "provider_audit": {},
        "stocks": [],
        "options": [],
        "top_calls": [],
        "top_puts": [],
        "catalysts": [],
        "rejected": [],
        "calibration": {},
        "alerts": [],
        "errors": {},
        "performance": {},
        "disclaimer": "السوق مغلق؛ لم يتم تنفيذ فحص جديد.",
    }


def main(argv: list[str] | None = None) -> int:
    from options_radar.calibration import build_calibration_report
    from options_radar.catalysts import CatalystScanner
    from options_radar.journal import SignalJournal
    from options_radar.market_clock import market_clock_state
    from options_radar.providers import load_universe
    from options_radar.scanner import OptionsRadar
    from options_radar.settings import Settings
    from options_radar.stocks import StockRadar
    from options_radar.universe import build_dynamic_universe

    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    settings = Settings()
    settings.validate()
    clock = market_clock_state()
    output = Path(args.output)
    if args.skip_closed and not clock.is_regular_open:
        LOGGER.info("NYSE session closed; preserving the last published scan")
        if not output.exists():
            _write_atomic(
                output,
                _closed_payload(
                    settings,
                    clock,
                    datetime.now(timezone.utc),
                ),
            )
        return 0

    base_symbols = args.symbols or load_universe(args.universe)
    if args.symbols:
        symbols = list(
            dict.fromkeys(
                str(symbol).strip().upper()
                for symbol in base_symbols
                if str(symbol).strip()
            )
        )
        universe_sources = {
            "manual": len(symbols),
            "total": len(symbols),
        }
    else:
        symbols, universe_sources = build_dynamic_universe(
            base_symbols, settings
        )

    catalysts = pd.DataFrame()
    stocks = pd.DataFrame()
    options = pd.DataFrame()
    top_calls = pd.DataFrame()
    top_puts = pd.DataFrame()
    stock_rejected = pd.DataFrame()
    option_rejected = pd.DataFrame()
    dashboard_setups: list[str] = []
    errors: dict[str, str] = {}
    market_regime = "unknown"
    market_regime_detail: dict[str, Any] = {}
    options_provider = "unknown"
    provider_audit: dict[str, Any] = {}
    flow_summary: dict[str, Any] = {}

    try:
        catalysts = CatalystScanner(settings).scan(
            symbols, lookback_days=7
        )
    except Exception as exc:
        errors["catalysts"] = str(exc)
        LOGGER.exception("Catalyst scan failed")

    try:
        stock_result = StockRadar(settings).scan(
            symbols,
            catalysts=catalysts,
            top=max(1, args.top_stocks),
            output_csv="results/stocks_latest.csv",
        )
        stocks = stock_result.opportunities
        stock_rejected = stock_result.rejected
        market_regime = stock_result.regime
        errors.update(
            {
                f"stock:{key}": value
                for key, value in stock_result.errors.items()
            }
        )
    except Exception as exc:
        errors["stocks"] = str(exc)
        LOGGER.exception("Stock scan failed")

    option_symbols = (
        stocks["symbol"]
        .head(max(15, args.top_options * 2))
        .astype(str)
        .tolist()
        if not stocks.empty and "symbol" in stocks.columns
        else symbols[: max(15, args.top_options * 2)]
    )
    try:
        option_result = OptionsRadar(settings).scan(
            option_symbols,
            top=max(1, args.top_options),
            output_csv="results/options_latest.csv",
            catalysts=catalysts,
        )
        options = option_result.opportunities
        top_calls = option_result.top_calls
        top_puts = option_result.top_puts
        option_rejected = option_result.rejected
        dashboard_setups = option_result.alerts
        options_provider = option_result.provider
        provider_audit = option_result.provider_audit
        flow_summary = option_result.flow_summary
        market_regime_detail = option_result.market_regime_detail
        if market_regime == "unknown":
            market_regime = option_result.regime
        errors.update(
            {
                f"option:{key}": value
                for key, value in option_result.errors.items()
            }
        )
    except Exception as exc:
        errors["options"] = str(exc)
        LOGGER.exception("Options scan failed")

    if not catalysts.empty:
        catalyst_sort_columns = [
            column
            for column in ("event_date", "score")
            if column in catalysts
        ]
        if catalyst_sort_columns:
            catalysts = catalysts.sort_values(
                catalyst_sort_columns,
                ascending=[False] * len(catalyst_sort_columns),
            )
        catalysts = catalysts.head(60)

    stock_columns = [
        "symbol",
        "score",
        "rating",
        "setup_side",
        "setup_status",
        "entry_state",
        "trigger_type",
        "distance_to_trigger_atr",
        "price",
        "entry_low",
        "entry_high",
        "target_1",
        "target_2",
        "stop",
        "invalidation",
        "rsi",
        "relative_volume",
        "avg_dollar_volume",
        "breakout",
        "technical_direction",
        "catalyst_score",
        "catalyst",
        "catalyst_source",
        "catalyst_form",
        "catalyst_confidence",
        "catalyst_purpose",
        "event_value",
        "catalyst_url",
        "reasons",
        "market_regime",
        "new_stock_setup",
        "sector_etf",
        "sector_score",
        "relative_strength_5d",
        "relative_strength_20d",
        "sector_vs_market",
        "rejection_reason",
        "attention_score",
        "directional_interest_score",
        "interest_tier",
        "finviz_relative_volume",
        "rise_factors",
        "fall_factors",
    ]
    option_columns = [
        "symbol",
        "contract_symbol",
        "expiration",
        "dte",
        "strike",
        "option_type",
        "side_rank",
        "score",
        "rating",
        "flow_rank_score",
        "flow_momentum_score",
        "flow_volume_score",
        "ask_aggression_score",
        "flow_technical_score",
        "flow_contract_score",
        "bid",
        "ask",
        "last",
        "mid",
        "quote_position",
        "underlying_price",
        "volume",
        "open_interest",
        "vol_oi",
        "vol_to_oi_ratio",
        "prior_5d_avg_volume",
        "volume_spike_ratio",
        "volume_spike_flag",
        "volume_history_source",
        "buying_flow_type",
        "unusual_activity_flag",
        "high_accumulation",
        "accumulation_tier",
        "iv",
        "delta",
        "gamma",
        "theta",
        "spread_pct",
        "aggressor_proxy",
        "entry_price",
        "target_1",
        "target_2",
        "stop_price",
        "underlying_target_1",
        "underlying_target_2",
        "underlying_invalidation",
        "risk_pct",
        "reward_risk_1",
        "reward_risk_2",
        "trade_style",
        "catalyst",
        "catalyst_url",
        "catalyst_source",
        "source",
        "freshness_label",
        "data_status",
        "data_completeness",
        "last_trade_age_minutes",
        "market_regime_score_adjustment",
        "regime_min_score",
        "model_version",
        "new_setup_candidate",
    ]
    catalyst_columns = [
        "symbol",
        "company",
        "event_date",
        "category",
        "headline",
        "score",
        "source",
        "form",
        "url",
        "evidence",
        "event_value",
        "confidence",
        "purpose",
    ]
    stock_rejected_columns = [
        "symbol",
        "score",
        "rating",
        "setup_side",
        "setup_status",
        "entry_state",
        "price",
        "catalyst",
        "sector_etf",
        "sector_score",
        "rejection_reason",
        "reasons",
    ]
    option_rejected_columns = [
        "symbol",
        "contract_symbol",
        "expiration",
        "strike",
        "option_type",
        "bid",
        "ask",
        "last",
        "volume",
        "open_interest",
        "vol_to_oi_ratio",
        "volume_spike_ratio",
        "buying_flow_type",
        "flow_momentum_score",
        "spread_pct",
        "last_trade_age_minutes",
        "source",
        "freshness_label",
        "rejection_stage",
        "rejection_reason",
    ]

    generated_at = datetime.now(timezone.utc)
    journal = SignalJournal(
        settings.signal_journal_path,
        settings.outcome_path,
        settings.model_version,
    )
    new_signals_recorded = 0
    performance: dict[str, Any] = {}
    try:
        new_signals_recorded = journal.record(options, generated_at)
        performance = journal.update_outcomes(generated_at)
    except Exception as exc:
        errors["journal"] = str(exc)
        LOGGER.exception("Signal journal update failed")

    calibration: dict[str, Any] = {}
    try:
        calibration = build_calibration_report(
            settings.signal_journal_path,
            settings.outcome_path,
            settings.calibration_minimum_sample,
        )
        _write_atomic(settings.calibration_path, calibration)
    except Exception as exc:
        errors["calibration"] = str(exc)
        LOGGER.exception("Calibration report failed")

    stock_records = _records(stocks, stock_columns)
    option_records = _records(options, option_columns)
    call_records = _records(top_calls, option_columns)
    put_records = _records(top_puts, option_columns)
    catalyst_records = _records(catalysts, catalyst_columns)
    rejected_records = [
        {"kind": "stock", **row}
        for row in _records(stock_rejected, stock_rejected_columns)
    ] + [
        {"kind": "option", **row}
        for row in _records(
            option_rejected, option_rejected_columns
        )
    ]
    _attach_best_option(
        stock_records,
        _best_options_by_symbol(options),
    )

    payload = {
        "schema_version": 5,
        "phase": "5.1",
        "model_version": settings.model_version,
        "mode": (
            "free_swing" if settings.free_swing_mode else "custom"
        ),
        "delivery_mode": "dashboard_only",
        "generated_at": generated_at.isoformat(),
        "generated_at_unix": int(generated_at.timestamp()),
        "market_regime": market_regime,
        "market_regime_detail": _json_value(
            market_regime_detail
        ),
        "market_clock": clock.__dict__,
        "options_provider": options_provider,
        "provider_audit": _json_value(provider_audit),
        "flow_summary": _json_value(flow_summary),
        "universe_size": len(symbols),
        "universe_sources": universe_sources,
        "summary": {
            "stock_candidates": len(stock_records),
            "option_candidates": len(option_records),
            "top_call_contracts": len(call_records),
            "top_put_contracts": len(put_records),
            "unusual_activity_contracts": sum(
                bool(row.get("unusual_activity_flag"))
                for row in option_records
            ),
            "aggressive_buying_contracts": sum(
                row.get("buying_flow_type")
                == "Aggressive Buying"
                for row in option_records
            ),
            "catalyst_events": len(catalyst_records),
            "rejected_opportunities": len(rejected_records),
            "new_stock_setups": sum(
                bool(row.get("new_stock_setup"))
                for row in stock_records
            ),
            "new_option_setups": sum(
                bool(row.get("new_setup_candidate"))
                for row in option_records
            ),
            "new_signals_recorded": new_signals_recorded,
        },
        "performance": performance,
        "calibration": calibration,
        "stocks": stock_records,
        "options": option_records,
        "top_calls": call_records,
        "top_puts": put_records,
        "catalysts": catalyst_records,
        "rejected": rejected_records[:400],
        "alerts": dashboard_setups,
        "errors": errors,
        "disclaimer": (
            "رصد الشراء عند Ask هو تقدير مبني على موضع آخر صفقة "
            "داخل السبريد، وليس إثباتًا قطعيًا لهوية المشتري أو "
            "استبعادًا كاملًا لعمليات الكتابة. Tradier Sandbox "
            "متأخر 15 دقيقة، وقد تكون المصادر المجانية الأخرى "
            "متأخرة أو ناقصة. النتائج بحثية وورقية وليست تنفيذات "
            "مؤكدة أو ضمانًا للربح."
        ),
    }
    _write_atomic(output, payload)
    LOGGER.info(
        "Wrote %s: %d stocks, %d CALL, %d PUT, %d catalysts, "
        "%d rejected and %d new signals",
        output,
        len(stock_records),
        len(call_records),
        len(put_records),
        len(catalyst_records),
        len(rejected_records),
        new_signals_recorded,
    )
    if errors:
        LOGGER.warning(
            "Completed with %d source errors", len(errors)
        )
    return 0
