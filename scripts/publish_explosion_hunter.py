"""Publish a compact, research-only Explosion Hunter digest for the website.

Input is the fast radar's full-market state (data/live/fast_market_state.json).
Only explicit fields are copied: no price levels, no probabilities, no
inferred quote times. SEC links are kept only when they point at sec.gov.
"""
from __future__ import annotations

import argparse
import importlib.util
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


LOW_SAME_TIME_RVOL = 0.7


def _same_time_rvol(source: dict[str, Any]) -> tuple[float | None, int]:
    """Same-clock cumulative volume vs prior sessions, only when the scanner
    measured it. The plain `rvol` field is session-so-far volume divided by a
    full-day average and is low by construction early in the session."""
    profile = source.get("time_normalized_rvol")
    if not isinstance(profile, dict) or profile.get("available") is not True:
        return None, 0
    sessions = int(_num(profile.get("sample_sessions")) or 0)
    return _round(profile.get("ratio"), 2), sessions


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
        same_time, same_time_sessions = _same_time_rvol(source)
        rows.append({
            "symbol": str(symbol).upper()[:10],
            "stage": stage,
            "stage_ar": STAGE_AR[stage],
            "score": _round(source.get("score"), 1),
            "day_move_pct": _round(source.get("day_move_pct"), 2),
            "volume_vs_avg_day": _round(source.get("rvol"), 2),
            "rvol_same_time": same_time,
            "rvol_same_time_sessions": same_time_sessions,
            "volume_flag": ("PRESSURE_WITHOUT_SAME_TIME_VOLUME"
                            if stage == "PRESSURE_BUILDING" and same_time is not None
                            and same_time < LOW_SAME_TIME_RVOL else None),
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


SCHEMA_PUBLIC = "ghazi.explosion_hunter_public.v1"
MAX_SOURCE_AGE_HOURS = 3.0


def _permissions():
    # Loaded by path: the publisher job checks out the repo without installing it.
    path = Path(__file__).resolve().parents[1] / "options_radar" / "source_permissions.py"
    spec = importlib.util.spec_from_file_location("ghazi_source_permissions_explosion", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def withdrawn(now: datetime, *, status: str, reason: str, reason_ar: str, source_generated_at: str | None) -> dict:
    """Public digest with no candidates: blocked or too old to present."""
    return {
        "schema": SCHEMA_PUBLIC, "generated_at": now.isoformat(), "status": status,
        "reason": reason, "reason_ar": reason_ar, "source_generated_at": source_generated_at,
        "stage_counts": {}, "candidates": [], "research_only": True, "score_is_probability": False,
        "execution_authority": False, "price_levels_published": False,
    }


def _write(out: Path, digest: dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(digest, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n",
                   encoding="utf-8")
    tmp.replace(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/live/fast_market_state.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    permissions = _permissions()
    if not permissions.allowed("nasdaq_web"):
        # Discovery comes from the Nasdaq screener; candidates scanned before
        # the gate must not keep circulating with a fresh timestamp.
        block = permissions.block_record("nasdaq_web")
        _write(Path(args.output), withdrawn(now, status=block["status"], reason=block["reason"],
                                            reason_ar=block["reason_ar"], source_generated_at=None))
        print("Explosion digest: SOURCE_TERMS_BLOCKED (Nasdaq.com discovery not permitted); candidates withdrawn")
        return 0
    try:
        state = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Explosion digest: no valid fast-market state ({type(exc).__name__}); nothing published")
        return 0
    if not isinstance(state, dict) or not state.get("generated_at"):
        print("Explosion digest: state without generated_at; nothing published")
        return 0
    try:
        scanned = datetime.fromisoformat(str(state["generated_at"]).replace("Z", "+00:00"))
    except ValueError:
        scanned = None
    if scanned is None or scanned.tzinfo is None or (now - scanned).total_seconds() > MAX_SOURCE_AGE_HOURS * 3600:
        _write(Path(args.output), withdrawn(
            now, status="STALE", reason=f"source scan older than {MAX_SOURCE_AGE_HOURS:g} h or untimed",
            reason_ar="آخر مسح للسوق قديم؛ سُحبت المرشحات بدل عرضها كأنها حالية.",
            source_generated_at=str(state.get("generated_at"))))
        print("Explosion digest: source scan too old; candidates withdrawn")
        return 0
    digest = build_digest(state, now=now)
    _write(Path(args.output), digest)
    print(f"Explosion digest: published={len(digest['candidates'])} counts={digest['stage_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
