"""Black Box Omega evidence fusion layer."""
from __future__ import annotations
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

@dataclass(frozen=True)
class FusionPolicy:
    version: str = "omega-fusion-v1"
    min_independent_classes: int = 2
    max_candidates: int = 25

EVIDENCE_CAPS = {
    "chart": 24.0, "explosion": 24.0, "options": 22.0,
    "news": 18.0, "fundamental": 12.0, "flow": 16.0,
}

def _num(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return n if math.isfinite(n) else default

def _symbol(row: dict[str, Any]) -> str:
    for key in ("symbol", "ticker", "underlying"):
        value = str(row.get(key) or "").upper().strip()
        if value:
            return value
    return ""

def _direction(row: dict[str, Any]) -> str:
    raw = str(row.get("direction") or row.get("preferred_side") or row.get("side") or row.get("bias") or "").upper()
    if raw in {"CALL", "BULLISH", "LONG", "BUY", "UP"}:
        return "BULLISH"
    if raw in {"PUT", "BEARISH", "SHORT", "SELL", "DOWN"}:
        return "BEARISH"
    return "NEUTRAL"

def _quality_rejection_reason(row: dict[str, Any]) -> str | None:
    """Reject only explicit bad-quality evidence; never invent validity."""
    if row.get("valid") is False or row.get("is_valid") is False:
        return "explicit_invalid"
    if row.get("stale") is True or row.get("is_stale") is True:
        return "explicit_stale"
    status = str(row.get("freshness_status") or row.get("data_status") or "").strip().lower()
    if status in {"stale", "expired", "invalid", "rejected", "failed", "error"}:
        return status
    quality = row.get("data_quality")
    if isinstance(quality, dict):
        qstatus = str(quality.get("status") or quality.get("state") or "").strip().lower()
        if qstatus in {"stale", "expired", "invalid", "rejected", "failed", "error"}:
            return f"data_quality:{qstatus}"
        if quality.get("valid") is False:
            return "data_quality:invalid"
    age = _num(row.get("age_seconds"), -1.0)
    max_age = _num(row.get("max_age_seconds"), -1.0)
    if age >= 0 and max_age >= 0 and age > max_age:
        return "age_exceeds_max"
    return None

def _bounded_score(row: dict[str, Any]) -> float:
    for key in ("score", "strict_score", "signal_score", "explosion_score", "confidence"):
        if row.get(key) is not None:
            return max(0.0, min(100.0, _num(row.get(key))))
    return 0.0

def _rows(payload: Any, keys: Iterable[str]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    found: list[dict[str, Any]] = []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            found.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            found.extend(item for item in value.values() if isinstance(item, dict))
    return found

def _evidence(rows: list[dict[str, Any]], kind: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        symbol = _symbol(row)
        if not symbol:
            continue
        item = dict(row)
        rejection = _quality_rejection_reason(item)
        if rejection:
            continue
        item["evidence_class"] = kind
        item["provenance_present"] = bool(
            item.get("provenance") or item.get("source") or item.get("provider")
        )
        item["direction"] = _direction(item)
        item["evidence_score"] = _bounded_score(item)
        out.setdefault(symbol, []).append(item)
    return out

def fuse_evidence(*, latest: dict[str, Any] | None = None,
                  explosion: dict[str, Any] | None = None,
                  flow: dict[str, Any] | None = None,
                  policy: FusionPolicy | None = None) -> dict[str, Any]:
    """Fuse independent evidence; scores are not win probabilities."""
    policy = policy or FusionPolicy()
    latest, explosion, flow = latest or {}, explosion or {}, flow or {}
    classes = {
        "chart": _rows(latest, ("stock_recommendations", "stocks", "chart_signals")),
        "options": _rows(latest, ("contract_recommendations", "option_recommendations", "options")),
        "news": _rows(latest, ("news", "catalysts", "news_recommendations")),
        "fundamental": _rows(latest, ("fundamentals", "fundamental_recommendations")),
        "explosion": _rows(explosion, ("candidates", "signals", "opportunities", "rows")),
        "flow": _rows(flow, ("signals", "theses", "candidates", "rows")),
    }
    grouped = {name: _evidence(rows, name) for name, rows in classes.items()}
    symbols = sorted({s for group in grouped.values() for s in group})
    candidates = []
    for symbol in symbols:
        total = 0.0
        directions = {"BULLISH": 0.0, "BEARISH": 0.0}
        independent: list[str] = []
        reasons: list[str] = []
        raw: dict[str, Any] = {}
        for kind, by_symbol in grouped.items():
            rows = by_symbol.get(symbol, [])
            if not rows:
                continue
            best = max(rows, key=_bounded_score)
            raw[kind] = best
            score = _bounded_score(best)
            contribution = min(EVIDENCE_CAPS[kind], score * EVIDENCE_CAPS[kind] / 100.0)
            total += contribution
            independent.append(kind)
            direction = _direction(best)
            if direction != "NEUTRAL":
                directions[direction] += contribution
            if score > 0:
                provenance_note = "" if best.get("provenance_present") else ":no-provenance"
                reasons.append(f"{kind}:{score:.0f}{provenance_note}")
        bullish, bearish = directions["BULLISH"], directions["BEARISH"]
        direction = "BULLISH" if bullish > bearish else "BEARISH" if bearish > bullish else "NEUTRAL"
        edge = abs(bullish - bearish)
        class_count = len(set(independent))
        state = "RESEARCH_CANDIDATE" if class_count >= policy.min_independent_classes and edge >= 6 else "WATCH"
        candidates.append({
            "symbol": symbol,
            "fusion_score": round(min(100.0, total), 2),
            "direction": direction,
            "bullish_evidence": round(bullish, 2),
            "bearish_evidence": round(bearish, 2),
            "side_edge": round(edge, 2),
            "independent_evidence_classes": sorted(set(independent)),
            "independent_class_count": class_count,
            "research_state": state,
            "reasons": reasons,
            "evidence": raw,
            "quality_gate": {
                "explicit_bad_quality_rows_excluded": True,
                "freshness_checked_when_declared": True,
                "provenance_presence_recorded": True,
            },
            "automatic_execution": False,
            "score_is_probability": False,
            "research_only": True,
        })
    candidates.sort(key=lambda x: (x["research_state"] == "RESEARCH_CANDIDATE",
                                   x["fusion_score"], x["side_edge"], x["independent_class_count"]),
                    reverse=True)
    return {
        "version": policy.version,
        "policy": {"minimum_independent_classes": policy.min_independent_classes,
                   "score_is_probability": False, "automatic_execution": False,
                   "missing_data_reduces_evidence": True, "research_only": True},
        "candidate_count": len(candidates[:policy.max_candidates]),
        "candidates": candidates[:policy.max_candidates],
    }

def load_json(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}

def fuse_paths(*, latest_path: str | Path = "public/data/latest.json",
               explosion_path: str | Path = "data/live/fast_explosion_scan.json",
               flow_path: str | Path = "data/live/delta_signals.json",
               output_path: str | Path = "data/live/black_box_omega.json",
               policy: FusionPolicy | None = None) -> dict[str, Any]:
    result = fuse_evidence(latest=load_json(latest_path), explosion=load_json(explosion_path),
                           flow=load_json(flow_path), policy=policy)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(destination)
    return result
