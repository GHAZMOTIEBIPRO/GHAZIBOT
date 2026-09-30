from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build(
    fast_path: str | Path,
    output_path: str | Path,
    *,
    max_symbols: int = 40,
    min_score: float = 52.0,
) -> dict[str, Any]:
    source = Path(fast_path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    rows = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
    if not rows:
        rows = payload.get("actionable") if isinstance(payload.get("actionable"), list) else []

    ranked: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        stage = str(row.get("stage") or "WATCH").upper()
        score = max(number(row.get("score")), number(row.get("institutional_priority")))
        earlyness = number(row.get("institutional_earlyness"))
        if stage in {"EXTENDED"}:
            continue
        if score < min_score and earlyness < 50:
            continue
        ranked.append(
            {
                "symbol": symbol,
                "stage": stage,
                "score": round(score, 2),
                "earlyness": round(earlyness, 2),
                "move_pct": number(row.get("move_pct")),
                "turnover_pct": number(row.get("turnover_pct")),
                "supply_score": number(row.get("supply_score")),
            }
        )

    ranked.sort(
        key=lambda row: (
            {"EXPLOSION": 4, "IGNITION": 3, "PRESSURE_BUILDING": 2, "WATCH": 1}.get(row["stage"], 0),
            row["earlyness"],
            row["score"],
            row["turnover_pct"],
        ),
        reverse=True,
    )

    symbols: list[str] = []
    seen: set[str] = set()
    for row in ranked:
        symbol = row["symbol"]
        if symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
        if len(symbols) >= max(1, max_symbols):
            break

    output = {
        "generated_at": payload.get("generated_at"),
        "source": "BLACK BOX Omega fast full-market radar",
        "selection_policy": "early-pressure candidates for same-cycle options cross-check",
        "research_only": True,
        "automatic_execution": False,
        "symbols": symbols,
        "candidates": [row for row in ranked if row["symbol"] in symbols],
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    universe_path = destination.with_name("dynamic_options_universe.txt")
    universe_path.write_text("\n".join(symbols) + ("\n" if symbols else ""), encoding="utf-8")
    output["universe_path"] = str(universe_path)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build same-cycle options universe from early explosion candidates.")
    parser.add_argument("--fast", default="data/live/fast_explosion_scan.json")
    parser.add_argument("--output", default="data/live/dynamic_options_universe.json")
    parser.add_argument("--max-symbols", type=int, default=40)
    parser.add_argument("--min-score", type=float, default=52.0)
    args = parser.parse_args()
    result = build(args.fast, args.output, max_symbols=args.max_symbols, min_score=args.min_score)
    print(json.dumps({"symbols": len(result["symbols"]), "universe": result["universe_path"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
