"""Publish a tiny, causal GHAZI RADAR briefing and frozen first-sighting journal.

No new feed, no executable options, no third-party text injected as HTML.
Journal records first observed RESEARCH candidates; it does NOT infer wins.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_JOURNAL_EVENTS = 1800


def timestamp(value: Any) -> datetime | None:
    try:
        val = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if val.tzinfo is None:
            return None  # Missing timezone is not safe evidence.
        return val.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
        return round(n, 4) if math.isfinite(n) else None
    except (ValueError, TypeError, OverflowError):
        return None


def as_mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def safe_link(value: Any) -> str | None:
    from urllib.parse import urlparse
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    # No non-HTTPS or obscure user-provided link protocols in public briefs.
    if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
        return raw[:700]
    return None


def stock_summary(raw: Any) -> dict | None:
    row = as_mapping(raw)
    symbol = str(row.get("symbol") or "").strip().upper()
    import re
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", symbol):
        return None
    direction = str(row.get("setup_side") or "UNKNOWN").upper()
    if direction not in {"CALL", "PUT", "UP", "DOWN"}:
        direction = "UNKNOWN"
    source = str(row.get("catalyst_source") or "").strip()[:80]
    return {
        "symbol": symbol,
        "direction_research": direction,
        "rating": str(row.get("rating") or "UNKNOWN")[:16],
        "stage": str(row.get("setup_status") or "UNKNOWN")[:42],
        "score": finite(row.get("score")),
        "observed_price": finite(row.get("price")),
        "entry_low": finite(row.get("entry_low")),
        "entry_high": finite(row.get("entry_high")),
        "target_1": finite(row.get("target_1")),
        "target_2": finite(row.get("target_2")),
        "invalidation": finite(row.get("invalidation") or row.get("stop")),
        "rvol": finite(row.get("relative_volume")),
        "catalyst_source": source,
        "catalyst_form": str(row.get("catalyst_form") or "")[:40],
        "catalyst_url": safe_link(row.get("catalyst_url")),
        "catalyst_confidence": str(row.get("catalyst_confidence") or "UNVERIFIED")[:64],
        "is_verified_official_catalyst": bool(row.get("catalyst_official_confirmed") is True),
        "source_kind": "EXISTING_RADAR_STOCK_ROW",
        "decision_authority": False,
    }


def catalyst_summary(raw: Any) -> dict | None:
    row = as_mapping(raw)
    symbol = str(row.get("symbol") or "").upper().strip()
    import re
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", symbol):
        return None
    url = safe_link(row.get("url") or row.get("catalyst_url"))
    evidence = str(row.get("source_tier") or row.get("verification_state") or
                   row.get("source") or "UNVERIFIED")[:70]
    return {
        "symbol": symbol,
        "headline": str(row.get("headline") or row.get("title") or row.get("catalyst") or "")[:170],
        "source": str(row.get("source") or "")[:75],
        "source_tier_reported": evidence,
        "source_url": url,
        "published_at": str(row.get("published_at") or row.get("event_date") or "")[:40],
        "status": "UNVERIFIED_CONTEXT_ONLY",
        "research_only": True,
    }


def record_id(row: dict, date: str) -> str:
    core = "|".join([date, row["symbol"], row["direction_research"], row["stage"]])
    return hashlib.sha256(core.encode("utf-8")).hexdigest()[:24]


def build_brief(payload: dict, ledger: dict | None, *, now: datetime) -> tuple[dict, dict]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    as_of = timestamp(payload.get("generated_at"))
    if as_of is None or as_of > now.astimezone(timezone.utc):
        raise ValueError("missing, timezone-naive, or future source timestamp")
    age_min = (now.astimezone(timezone.utc) - as_of).total_seconds() / 60
    if age_min > 180:
        raise ValueError("radar snapshot older than 180 minutes; preserve previous output")
    stocks = [x for raw in payload.get("stocks", []) if (x := stock_summary(raw))]
    cats = [x for raw in payload.get("catalysts", []) if (x := catalyst_summary(raw))]
    journal = as_mapping(ledger)
    previous = as_mapping(journal.get("records"))
    # Fail closed instead of silently overwriting corrupt/incompatible audit journals.
    if journal and journal.get("schema") != "ghazi.first_observed.v1":
        raise ValueError("journal schema mismatch")
    records = {key: dict(value) for key, value in previous.items()
               if isinstance(value, dict) and len(key) == 24 and all(c in "0123456789abcdef" for c in key)}
    seen_now = []
    for row in stocks:
        if row["observed_price"] is None or row["observed_price"] <= 0:
            continue
        key = record_id(row, as_of.date().isoformat())
        if key not in records:
            # These values are frozen forever while retained. Repeated scans
            # cannot rewrite the original observed price, date, score or side.
            records[key] = {
                "event_id": key, "first_seen_at": as_of.isoformat(),
                "kind": "STOCK_RESEARCH_CANDIDATE",
                "symbol": row["symbol"], "direction_research": row["direction_research"],
                "stage": row["stage"], "rating": row["rating"], "score_at_first_sighting": row["score"],
                "price_at_first_sighting": row["observed_price"],
                "source_time": as_of.isoformat(), "status": "NOT_PERFORMANCE_VALIDATED",
                "is_trade": False, "future_outcome": None,
            }
        seen_now.append(key)
    # Keep a fixed reproducible sliding retention set, not an all-time performance population.
    retention = sorted(records.items(), key=lambda t: (str(t[1].get("first_seen_at") or ""), t[0]))
    records = dict(retention[-MAX_JOURNAL_EVENTS:])
    brief = {
        "schema": "ghazi.public_decision.v1",
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "source_generated_at": as_of.isoformat(),
        "source_age_minutes_at_build": round(age_min, 2),
        "source": "existing GHAZIBOT latest.json + official source-policy annotations",
        "authority": "RESEARCH_ONLY_NO_AUTOMATED_CALL_PUT",
        "live_trade_quotes_verified": False,
        "stocks": stocks[:30], "catalysts": cats[:40],
        "journal": {
            "record_count_retained": len(records),
            "first_observed_ids_in_current_snapshot": seen_now[:40],
            "last_observed": [records[k] for k in seen_now[:10] if k in records],
            "outcomes_graded_here": 0,
            "true_win_rate": None,
            "net_trading_return": None,
            "status": "FIRST_SIGHTING_ONLY__NOT_OUTCOME_BACKTEST",
        },
        "important": "No retrospective outcome or profitability is inferred from the appearance of a research row.",
    }
    return brief, {
        "schema": "ghazi.first_observed.v1",
        "updated_at": now.astimezone(timezone.utc).isoformat(),
        "retention_cap": MAX_JOURNAL_EVENTS,
        "scope": "rolling first observed research candidates; not a trading performance archive",
        "records": records,
    }


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("public/data/latest.json"))
    parser.add_argument("--brief", type=Path, default=Path("public/data/decision_brief.json"))
    parser.add_argument("--journal", type=Path, default=Path("data/live/public_first_sightings.json"))
    args = parser.parse_args()
    payload = json.loads(args.source.read_text(encoding="utf-8"))
    old = json.loads(args.journal.read_text(encoding="utf-8")) if args.journal.exists() else {}
    report, ledger = build_brief(payload, old, now=datetime.now(timezone.utc))
    # Both payloads are validated before either is written.
    atomic_json(args.journal, ledger)
    atomic_json(args.brief, report)
    print(f"Public brief: {len(report['stocks'])} stocks, {len(report['catalysts'])} catalysts; "
          f"{len(ledger['records'])} frozen sightings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
