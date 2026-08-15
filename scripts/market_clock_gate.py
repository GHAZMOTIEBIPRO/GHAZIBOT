from __future__ import annotations

import argparse
import runpy
from pathlib import Path


def _market_clock_state():
    # Load the clock module by file path so lightweight notification workflows do
    # not execute options_radar/__init__.py and its full scanner dependency tree.
    root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(str(root / "options_radar" / "market_clock.py"))
    return namespace["market_clock_state"]()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Emit lightweight BLACK BOX market-clock gate values"
    )
    parser.add_argument(
        "--mode",
        choices=("regular", "extended"),
        default="extended",
    )
    args = parser.parse_args()
    state = _market_clock_state()
    is_open = (
        state.is_regular_open
        if args.mode == "regular"
        else state.is_extended_activity_open
    )
    print(f"open={'true' if is_open else 'false'}")
    print(f"date={state.session_date}")
    print(f"reason={state.reason}")


if __name__ == "__main__":
    main()
