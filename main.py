from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from options_radar.catalysts import CatalystScanner
from options_radar.providers import load_universe
from options_radar.reporting import dispatch_daily_report
from options_radar.scanner import OptionsRadar
from options_radar.settings import Settings
from options_radar.stocks import StockRadar


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Free-data scanner for US stocks, catalysts and options."
    )
    parser.add_argument("--symbols", nargs="*", help="Defaults to data/universe.txt")
    parser.add_argument("--universe", default="data/universe.txt")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument(
        "--mode", choices=["all", "stocks", "options", "catalysts"], default="all"
    )
    parser.add_argument("--send-alerts", action="store_true")
    parser.add_argument("--send-report", action="store_true")
    parser.add_argument("--send-email", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def _print_frame(name: str, frame: pd.DataFrame, output: str) -> None:
    print(f"\n{name}")
    if frame.empty:
        print("No candidates passed the filters.")
        return
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 260)
    print(frame.head(20).to_string(index=False))
    print(f"CSV: {Path(output).resolve()}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    settings = Settings()
    settings.validate()
    symbols = args.symbols or load_universe(args.universe)
    catalysts = pd.DataFrame()
    stocks = pd.DataFrame()
    options = pd.DataFrame()

    if args.mode in {"all", "catalysts", "stocks", "options"}:
        catalysts = CatalystScanner(settings).scan(symbols, lookback_days=7)
        if args.mode in {"all", "catalysts"}:
            _print_frame("CATALYSTS", catalysts, "results/catalysts_latest.csv")

    stock_result = None
    if args.mode in {"all", "stocks", "options"}:
        stock_result = StockRadar(settings).scan(
            symbols,
            catalysts=catalysts,
            top=max(args.top, 10),
            output_csv="results/stocks_latest.csv",
        )
        stocks = stock_result.opportunities
        if args.mode in {"all", "stocks"}:
            print(f"Market regime: {stock_result.regime}")
            _print_frame("TOP STOCKS", stocks, "results/stocks_latest.csv")

    option_result = None
    if args.mode in {"all", "options"}:
        option_symbols = (
            stocks["symbol"].head(max(8, args.top)).tolist()
            if not stocks.empty
            else symbols[:12]
        )
        option_result = OptionsRadar(settings).scan(
            option_symbols,
            top=args.top,
            send_alerts=args.send_alerts,
            output_csv="results/options_latest.csv",
            catalysts=catalysts,
        )
        options = option_result.opportunities
        print(
            f"Options provider: {option_result.provider} | "
            f"Market regime: {option_result.regime}"
        )
        _print_frame("TOP OPTIONS", options, "results/options_latest.csv")
        if option_result.alerts:
            print("\n" + "\n\n".join(option_result.alerts))
        if option_result.errors:
            for symbol, error in option_result.errors.items():
                print(f"Option error {symbol}: {error}", file=sys.stderr)

    if args.send_report or args.send_email:
        status = dispatch_daily_report(
            settings,
            stocks,
            options,
            send_email=args.send_email or args.send_report,
            send_telegram=args.send_report,
        )
        print(f"Report delivery: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
