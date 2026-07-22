from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from options_radar.providers import load_universe
from options_radar.scanner import OptionsRadar
from options_radar.settings import Settings

DISPLAY_COLUMNS = [
    "symbol", "contract_symbol", "expiration", "strike", "option_type",
    "score", "rating", "volume", "open_interest", "vol_oi", "iv",
    "delta", "spread_pct", "aggressor_proxy", "entry_price", "target_1",
    "target_2", "stop_price", "trade_style", "catalyst", "source",
    "freshness_label",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Source-aware scanner for liquid US option contracts."
    )
    parser.add_argument("--symbols", nargs="*", help="Defaults to data/universe.txt")
    parser.add_argument("--universe", default="data/universe.txt")
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--output", default="results/latest.csv")
    parser.add_argument("--send-alerts", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    symbols = args.symbols or load_universe(args.universe)
    result = OptionsRadar(Settings()).scan(
        symbols=symbols,
        top=max(1, args.top),
        send_alerts=args.send_alerts,
        output_csv=args.output,
    )
    print(f"Provider: {result.provider} | Market regime: {result.regime}")
    if result.alerts:
        print("\n" + "\n\n".join(result.alerts))
    if result.opportunities.empty:
        print("No contracts passed all filters.")
    else:
        columns = [c for c in DISPLAY_COLUMNS if c in result.opportunities.columns]
        table = result.opportunities[columns].copy()
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 240)
        print(table.to_string(index=False))
        print(f"\nCSV: {Path(args.output).resolve()}")
    if result.errors:
        print("\nProvider/data errors:", file=sys.stderr)
        for symbol, error in result.errors.items():
            print(f"- {symbol}: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
