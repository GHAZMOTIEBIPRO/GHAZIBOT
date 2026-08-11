from __future__ import annotations

from scripts import fast_explosion_scan as base


def _valid_common(symbol: str, name: str) -> bool:
    if not base.SYMBOL_RE.fullmatch(symbol):
        return False
    if symbol.endswith(("WS", "WT")):
        return False
    normalized = f" {name.lower()} "
    return not any(token in normalized for token in base.NON_COMMON_NAME_TOKENS)


# Patch the scanner policy at runtime without duplicating the full scanner.
base._valid_common = _valid_common
rank_market = base.rank_market
run = base.run


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
