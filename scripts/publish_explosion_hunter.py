"""Publish a compact, research-only Explosion Hunter digest for the website.

Input is the fast radar's full-market state (data/live/fast_market_state.json).
Only explicit fields are copied: no price levels, no probabilities, no
inferred quote times. SEC links are kept only when they point at sec.gov.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCHEMA = "ghazi.explosion_hunter_public.v1"
STAGE_ORDER = {"WATCH": 0, "PRESSURE_BUILDING": 1, "IGNITION": 2, "EXPLOSION": 3, "EXTENDED": 4}
STAGE_AR = {
    "WATCH": "مراقبة",
    "PRESSURE_BUILDING": "ضغط يتكوّن",
    "IGNITION": "بداية اشتعال",
    "EXPLOSION": "انفجار مؤكد بالحركة",
    "EXTENDED": "ممتد · خطر مطاردة",
}
MAX_ROWS = 30


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sec_url(value: Any) -> str | None:
    try:
        url = urlparse(str(value or ""))
    except ValueError:
        return None
    host = (url.hostname or "").lower()
    return url.geturl() if url.scheme == "https" and host in {"www.sec.gov", "sec.gov"} else None


def _round(value: Any, digits: int) -> float | None:
    number = _num(value)
    return round(number, digits) if number is not None else None


def build_digest(state: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    symbols = state.get("symbols") if isinstance(state.get("symbols"), dict) else {}
    counts = {stage: 0 for stage in STAGE_ORDER}
    rows = []
    for symbol, source in symbols.items():
        if not isinstance(source, dict) or not str(symbol).isascii():
            continue
        stage = str(source.get("stage") or "")
        if stage not in STAGE_ORDER:
            continue
        counts[stage] += 1
        if stage == "WATCH":
            continue
        microcap = source.get("microcap_hunter") if isinstance(source.get("microcap_hunter"), dict) else {}
        rows.append({
            "symbol": str(symbol).upper()[:10],
            "stage": stage,
            "stage_ar": STAGE_AR[stage],
            "score": _round(source.get("score"), 1),
            "day_move_pct": _round(source.get("day_move_pct"), 2),
            "rvol": _round(source.get("rvol"), 2),
            "float_shares": _round(source.get("float_shares"), 0),
            "dollar_volume": _round(source.get("dollar_volume"), 0),
            "market_cap": _round(source.get("market_cap"), 0),
            "turnover_pct": _round(source.get("turnover_pct"), 3),
            "acceleration": _round(source.get("acceleration"), 1),
            "earlyness": _round(source.get("earlyness"), 1),
            "confidence": str(source.get("confidence") or "")[:2] or None,
            "catalyst_event_type": str(source.get("catalyst_event_type") or "")[:60] or None,
            "catalyst_headline": str(source.get("catalyst_headline") or source.get("news_headline") or "")[:160] or None,
            "official_catalyst_url": _sec_url(source.get("official_catalyst_url")),
            "dilution_risk": _round(source.get("dilution_risk"), 1),
            "microcap_stage": str(microcap.get("stage") or "")[:20] or None,
        })
    rows.sort(key=lambda r: (STAGE_ORDER[r["stage"]] if r["stage"] != "EXTENDED" else 0.5,
                             r["score"] or 0.0), reverse=True)
    return {
        "schema": SCHEMA,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "source_generated_at": state.get("generated_at"),
        "source": "Fast radar full-market scan (unofficial screener and Yahoo data, may be delayed)",
        "stage_counts": counts,
        "candidates": rows[:MAX_ROWS],
        "research_only": True,
        "score_is_probability": False,
        "execution_authority": False,
        "price_levels_published": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/live/fast_market_state.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        state = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Explosion digest: no valid fast-market state ({type(exc).__name__}); nothing published")
        return 0
    if not isinstance(state, dict) or not state.get("generated_at"):
        print("Explosion digest: state without generated_at; nothing published")
        return 0
    digest = build_digest(state, now=datetime.now(timezone.utc))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(digest, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n",
                   encoding="utf-8")
    tmp.replace(out)
    print(f"Explosion digest: published={len(digest['candidates'])} counts={digest['stage_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
