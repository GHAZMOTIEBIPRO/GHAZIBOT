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
        description="Generate the public JSON feed for GHAZI Stocks & Options Radar."
    )
    parser.add_argument("--universe", default="data/universe.txt")
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--top-stocks", type=int, default=15)
    parser.add_argument("--top-options", type=int, default=15)
    parser.add_argument("--output", default="public/data/latest.json")
    parser.add_argument("--send-alerts", action="store_true")
    parser.add_argument("--send-report", action="store_true")
    parser.add_argument("--send-email", action="store_true")
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
    if pd.isna(value):
        return None
    return str(value)


def _records(frame: pd.DataFrame, columns: list[str] | None = None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    selected = frame if columns is None else frame[[c for c in columns if c in frame.columns]]
    return [
        {str(key): _json_value(value) for key, value in row.items()}
        for row in selected.to_dict(orient="records")
    ]


def _best_options_by_symbol(options: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if options.empty or "symbol" not in options.columns:
        return {}
    ordered = options.sort_values(
        [c for c in ["score", "vol_oi", "volume"] if c in options.columns],
        ascending=False,
    )
    best = ordered.drop_duplicates("symbol")
    fields = [
        "contract_symbol", "expiration", "strike", "option_type", "score", "rating",
        "entry_price", "target_1", "target_2", "stop_price", "underlying_invalidation",
        "volume", "open_interest", "vol_oi", "iv", "delta", "spread_pct",
        "aggressor_proxy", "source", "freshness_label", "catalyst_url",
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


def _attach_best_option(stocks: list[dict[str, Any]], best_options: dict[str, dict[str, Any]]) -> None:
    for stock in stocks:
        stock["best_option"] = best_options.get(str(stock.get("symbol", "")).upper())


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    # Heavy market-data modules are imported lazily so JSON helpers remain testable
    # without network-provider dependencies installed.
    from options_radar.catalysts import CatalystScanner
    from options_radar.providers import load_universe
    from options_radar.reporting import dispatch_daily_report
    from options_radar.scanner import OptionsRadar
    from options_radar.settings import Settings
    from options_radar.stocks import StockRadar

    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    settings = Settings()
    settings.validate()
    symbols = args.symbols or load_universe(args.universe)
    symbols = list(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()))

    catalysts = pd.DataFrame()
    stocks = pd.DataFrame()
    options = pd.DataFrame()
    alerts: list[str] = []
    errors: dict[str, str] = {}
    market_regime = "unknown"
    options_provider = "unknown"

    try:
        catalysts = CatalystScanner(settings).scan(symbols, lookback_days=7)
    except Exception as exc:  # Keep the public page available with partial data.
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
        market_regime = stock_result.regime
        errors.update({f"stock:{key}": value for key, value in stock_result.errors.items()})
    except Exception as exc:
        errors["stocks"] = str(exc)
        LOGGER.exception("Stock scan failed")

    option_symbols = (
        stocks["symbol"].head(max(8, args.top_options)).astype(str).tolist()
        if not stocks.empty and "symbol" in stocks.columns
        else symbols[:12]
    )
    try:
        option_result = OptionsRadar(settings).scan(
            option_symbols,
            top=max(1, args.top_options),
            send_alerts=args.send_alerts,
            output_csv="results/options_latest.csv",
            catalysts=catalysts,
        )
        options = option_result.opportunities
        alerts = option_result.alerts
        options_provider = option_result.provider
        if market_regime == "unknown":
            market_regime = option_result.regime
        errors.update({f"option:{key}": value for key, value in option_result.errors.items()})
    except Exception as exc:
        errors["options"] = str(exc)
        LOGGER.exception("Options scan failed")

    if not catalysts.empty:
        catalyst_sort_columns = [
            column for column in ["event_date", "score"] if column in catalysts.columns
        ]
        if catalyst_sort_columns:
            catalysts = catalysts.sort_values(
                catalyst_sort_columns,
                ascending=[False] * len(catalyst_sort_columns),
            )
        catalysts = catalysts.head(40)

    stock_columns = [
        "symbol", "score", "rating", "price", "entry_low", "entry_high", "target_1",
        "target_2", "stop", "rsi", "relative_volume", "avg_dollar_volume", "breakout",
        "technical_direction", "catalyst_score", "catalyst", "catalyst_source",
        "catalyst_url", "reasons", "market_regime", "new_stock_setup",
    ]
    option_columns = [
        "symbol", "contract_symbol", "expiration", "dte", "strike", "option_type", "score",
        "rating", "volume", "open_interest", "vol_oi", "iv", "delta", "gamma",
        "spread_pct", "aggressor_proxy", "entry_price", "target_1", "target_2",
        "stop_price", "underlying_invalidation", "trade_style", "catalyst", "catalyst_url",
        "catalyst_source", "source", "freshness_label", "new_setup_candidate",
    ]
    catalyst_columns = [
        "symbol", "company", "event_date", "category", "headline", "score", "source",
        "form", "url", "evidence",
    ]

    stock_records = _records(stocks, stock_columns)
    option_records = _records(options, option_columns)
    catalyst_records = _records(catalysts, catalyst_columns)
    _attach_best_option(stock_records, _best_options_by_symbol(options))

    report_delivery: dict[str, Any] | str | None = None
    if args.send_report or args.send_email:
        try:
            report_delivery = dispatch_daily_report(
                settings,
                stocks,
                options,
                send_email=args.send_email or args.send_report,
                send_telegram=args.send_report,
            )
        except Exception as exc:
            errors["report"] = str(exc)
            LOGGER.exception("Daily report delivery failed")

    generated_at = datetime.now(timezone.utc)
    payload = {
        "schema_version": 1,
        "generated_at": generated_at.isoformat(),
        "generated_at_unix": int(generated_at.timestamp()),
        "market_regime": market_regime,
        "options_provider": options_provider,
        "universe_size": len(symbols),
        "summary": {
            "stock_candidates": len(stock_records),
            "option_candidates": len(option_records),
            "catalyst_events": len(catalyst_records),
            "new_stock_setups": sum(bool(row.get("new_stock_setup")) for row in stock_records),
            "new_option_setups": sum(bool(row.get("new_setup_candidate")) for row in option_records),
        },
        "stocks": stock_records,
        "options": option_records,
        "catalysts": catalyst_records,
        "alerts": alerts,
        "errors": errors,
        "report_delivery": report_delivery,
        "disclaimer": (
            "إشارات بحثية مبنية على بيانات مجانية قد تكون متأخرة أو ناقصة. "
            "لا يوجد ضمان للربح، ويجب التحقق من السعر الحي قبل تنفيذ أي أمر."
        ),
    }
    output = Path(args.output)
    _write_atomic(output, payload)
    LOGGER.info(
        "Wrote %s with %d stocks, %d options and %d catalysts",
        output,
        len(stock_records),
        len(option_records),
        len(catalyst_records),
    )
    if errors:
        LOGGER.warning("Completed with %d source errors", len(errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
