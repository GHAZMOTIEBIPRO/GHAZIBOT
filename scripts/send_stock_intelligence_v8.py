from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
from typing import Any

from options_radar.catalyst_selection import best_catalyst_map
from options_radar.catalysts import CatalystScanner
from options_radar.event_source_policy import event_source_evidence
from options_radar.intelligence_grading import grade_alerts, register_alert
from options_radar.settings import Settings
from options_radar.telegram_transport import send_html_message
from scripts import send_stock_intelligence_v7 as v7


def _current_prices(payload: dict[str, Any]) -> dict[str, float]:
    rows: list[dict[str, Any]] = []
    for key in ("top", "actionable"):
        values = payload.get(key) if isinstance(payload.get(key), list) else []
        rows.extend(row for row in values if isinstance(row, dict))
    prices: dict[str, float] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").upper().strip()
        price = v7._number(row.get("price"))
        if symbol and price > 0:
            prices[symbol] = price
    return prices


def _alert_id(symbol: str, fingerprint: str, sent_at: datetime) -> str:
    raw = f"{symbol}|{fingerprint}|{int(sent_at.timestamp())}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def send(payload: dict[str, Any], state: dict[str, Any]) -> int:
    max_age = v7._number(__import__("os").getenv("STOCK_INTEL_MAX_PAYLOAD_AGE_MINUTES", "35"), 35.0)
    age = v7._payload_age_minutes(payload)
    if age is None or age > max_age:
        state.update(
            {
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "last_sent_count": 0,
                "blocked_reason": "STALE_FAST_PAYLOAD",
                "payload_age_minutes": age,
            }
        )
        return 0

    scorecard = grade_alerts(state, underlying_prices=_current_prices(payload))
    rows = v7._candidate_rows(payload)
    symbols = [str(row.get("symbol") or "").upper() for row in rows[:30]]
    if not symbols:
        state.update(
            {
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "last_sent_count": 0,
                "candidate_count": 0,
                "self_grading_scorecard": scorecard,
            }
        )
        return 0

    settings = Settings()
    catalysts = CatalystScanner(settings).scan(symbols, lookback_days=3)
    catalyst_map = best_catalyst_map(catalysts)
    sent_state = state.setdefault("sent", {})
    import os

    maximum = max(1, min(5, int(v7._number(os.getenv("STOCK_INTEL_MAX_ALERTS", "3"), 3))))
    sent = 0

    for row in rows:
        if sent >= maximum:
            break
        symbol = str(row.get("symbol") or "").upper()
        catalyst = catalyst_map.get(symbol)
        if not isinstance(catalyst, dict):
            continue
        evidence = event_source_evidence(catalyst)
        if not v7._strong_enough(row, catalyst, evidence):
            continue
        fingerprint = v7._fingerprint(row, catalyst)
        previous = sent_state.get(symbol) if isinstance(sent_state.get(symbol), dict) else {}
        if str(previous.get("fingerprint") or "") == fingerprint:
            continue
        send_html_message(v7._message(row, catalyst, evidence))
        sent_at = datetime.now(timezone.utc)
        alert_id = _alert_id(symbol, fingerprint, sent_at)
        register_alert(
            state,
            alert_id=alert_id,
            kind="stock",
            symbol=symbol,
            direction="UP",
            baseline_underlying=v7._number(row.get("price")),
            score=v7._number(row.get("score")),
            evidence_signature="|".join(
                [
                    str(catalyst.get("category") or "catalyst"),
                    str(evidence.get("source_tier") or "unknown"),
                    str(row.get("stage") or "WATCH"),
                ]
            ),
            sent_at=sent_at,
        )
        sent_state[symbol] = {
            "fingerprint": fingerprint,
            "sent_at": sent_at.isoformat(),
            "score": round(v7._number(row.get("score")), 2),
            "headline": str(catalyst.get("headline") or "")[:220],
            "source": str(catalyst.get("source") or ""),
            "verification_state": evidence.get("verification_state"),
            "alert_id": alert_id,
        }
        sent += 1

    state.update(
        {
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_sent_count": sent,
            "candidate_count": len(rows),
            "payload_age_minutes": round(age, 2),
            "self_grading_scorecard": scorecard,
            "architecture": "standalone_stock_news_explosion_v8_self_grading",
        }
    )
    state.pop("blocked_reason", None)
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="Send BLACK BOX V8 verified stock catalyst alerts with self grading")
    parser.add_argument("--payload", default="data/live/fast_explosion_scan.json")
    parser.add_argument("--state", default="data/live/stock_intelligence_v8_state.json")
    args = parser.parse_args()
    payload = v7._load(args.payload, {})
    state = v7._load(args.state, {"sent": {}, "outcomes": {}})
    if not isinstance(payload, dict):
        payload = {}
    if not isinstance(state, dict):
        state = {"sent": {}, "outcomes": {}}
    try:
        sent = send(payload, state)
    finally:
        v7._save(args.state, state)
    print(
        "Stock intelligence v8: "
        f"sent={sent} candidates={state.get('candidate_count', 0)} "
        f"outcomes={state.get('self_grading_scorecard', {}).get('alert_records', 0)}"
    )


if __name__ == "__main__":
    main()
