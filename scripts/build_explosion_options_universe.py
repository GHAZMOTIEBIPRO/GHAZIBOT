from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


DEFAULT_FAST = Path("data/live/fast_explosion_scan.json")
DEFAULT_JSON = Path("data/live/explosion_options_universe.json")
DEFAULT_TXT = Path("data/live/explosion_options_universe.txt")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _stage_rank(stage: str) -> int:
    return {
        "EXPLOSION": 5,
        "IGNITION": 4,
        "PRE_EXPLOSION": 3,
        "PRESSURE_BUILDING": 2,
        "WATCH": 1,
    }.get(str(stage or "").upper(), 0)


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("candidates", "actionable", "rows", "signals"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return [row for row in value if isinstance(row, dict)]
    return []


def build_dynamic_options_universe(
    payload: dict[str, Any],
    *,
    max_symbols: int = 30,
    watch_min_score: float = 60.0,
    confirmed_min_score: float = 68.0,
) -> dict[str, Any]:
    ranked: list[dict[str, Any]] = []
    for row in _rows(payload):
        symbol = str(row.get("symbol") or "").upper().strip()
        stage = str(row.get("stage") or row.get("alert_stage") or "WATCH").upper()
        if not symbol or stage == "EXTENDED":
            continue

        score = max(
            _number(row.get("score")),
            _number(row.get("institutional_priority")),
            _number(row.get("institutional_confidence")),
        )
        earlyness = max(
            _number(row.get("institutional_earlyness")),
            _number((row.get("institutional_memory") or {}).get("earlyness"))
            if isinstance(row.get("institutional_memory"), dict)
            else 0.0,
        )
        anomaly = max(
            _number(row.get("institutional_anomaly")),
            _number((row.get("institutional_memory") or {}).get("anomaly"))
            if isinstance(row.get("institutional_memory"), dict)
            else 0.0,
        )
        stage_type = "WATCH" if stage in {"WATCH", "PRESSURE_BUILDING", "PRE_EXPLOSION"} else "CONFIRMED"
        threshold = watch_min_score if stage_type == "WATCH" else confirmed_min_score

        # Preserve very early candidates even if aggregate score is still
        # forming; the options check is evidence collection, not stock promotion.
        if score < threshold and earlyness < 65 and anomaly < 70:
            continue

        explosion = row.get("explosion_cause") if isinstance(row.get("explosion_cause"), dict) else {}
        ranked.append(
            {
                "symbol": symbol,
                "stage": stage,
                "alert_stage": stage_type,
                "score": round(score, 2),
                "earlyness": round(earlyness, 2),
                "anomaly": round(anomaly, 2),
                "move_pct": round(_number(row.get("move_pct")), 3),
                "turnover_pct": round(_number(row.get("turnover_pct")), 3),
                "supply_score": round(_number(row.get("supply_score")), 2),
                "explosion_cause": explosion.get("primary"),
                "discovery_only": True,
            }
        )

    ranked.sort(
        key=lambda row: (
            _stage_rank(row["stage"]),
            row["earlyness"],
            row["anomaly"],
            row["score"],
            row["turnover_pct"],
        ),
        reverse=True,
    )

    symbols: list[str] = []
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in ranked:
        symbol = row["symbol"]
        if symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
        selected.append(row)
        if len(symbols) >= max(1, min(int(max_symbols), 60)):
            break

    fingerprint = hashlib.sha256("|".join(symbols).encode("utf-8")).hexdigest()[:20]
    return {
        "version": "EXPLOSION_OPTIONS_UNIVERSE_V2",
        "generated_at": payload.get("generated_at"),
        "source": "BLACK BOX Omega Fast Explosion Radar",
        "selection_policy": "WATCH/IGNITION candidates seeded into an options-only same-cycle cross-check",
        "symbols": symbols,
        "candidates": selected,
        "fingerprint": fingerprint,
        "research_only": True,
        "discovery_seed_only": True,
        "stock_signal_independent_from_options_result": True,
        "options_result_cannot_promote_stock_signal": True,
        "automatic_execution": False,
    }


def write_universe(
    payload: dict[str, Any],
    *,
    json_path: str | Path = DEFAULT_JSON,
    text_path: str | Path = DEFAULT_TXT,
    max_symbols: int = 30,
) -> dict[str, Any]:
    output = build_dynamic_options_universe(payload, max_symbols=max_symbols)
    destination = Path(json_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(text_path).write_text(
        "\n".join(output["symbols"]) + ("\n" if output["symbols"] else ""),
        encoding="utf-8",
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Build same-cycle options universe from Fast Explosion evidence.")
    parser.add_argument("--fast", default=str(DEFAULT_FAST))
    parser.add_argument("--json", default=str(DEFAULT_JSON))
    parser.add_argument("--text", default=str(DEFAULT_TXT))
    parser.add_argument("--max-symbols", type=int, default=30)
    args = parser.parse_args()

    try:
        payload = json.loads(Path(args.fast).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    result = write_universe(
        payload,
        json_path=args.json,
        text_path=args.text,
        max_symbols=args.max_symbols,
    )
    print(
        "Explosion options universe: "
        f"symbols={len(result['symbols'])} fingerprint={result['fingerprint']}"
    )


if __name__ == "__main__":
    main()
