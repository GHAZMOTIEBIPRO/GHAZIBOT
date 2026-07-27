from __future__ import annotations

import sys
from pathlib import Path

from options_radar.phase51_export import (
    _attach_best_option,
    _best_options_by_symbol,
    _json_value,
    _records,
    _write_atomic,
    build_parser,
    main as phase51_main,
)
from options_radar.phase6_publisher import publish_phase6

__all__ = [
    "_attach_best_option",
    "_best_options_by_symbol",
    "_json_value",
    "_records",
    "_write_atomic",
    "build_parser",
    "main",
]


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    exit_code = phase51_main(arguments)
    if exit_code != 0:
        return exit_code
    parsed = build_parser().parse_args(arguments)
    output = Path(parsed.output)
    if output.exists():
        import json

        payload = json.loads(output.read_text(encoding="utf-8"))
        publish_phase6(payload)
        _write_atomic(output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
