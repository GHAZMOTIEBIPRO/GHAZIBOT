from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import refresh_structural_universe as base


def _valid_symbol(value: Any) -> bool:
    symbol = str(value or "").strip().upper()
    if not base.SYMBOL_RE.fullmatch(symbol):
        return False
    if symbol.endswith(("WS", "WT")):
        return False
    return symbol not in {"N/A", "NA", "NONE", "NULL", "SYMBOL", "TICKER"}


# Security-name filtering in the base scanner still removes warrants/units/rights.
base._valid_symbol = _valid_symbol


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
