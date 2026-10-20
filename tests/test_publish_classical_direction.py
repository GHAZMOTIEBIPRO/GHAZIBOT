"""Classical direction digest: underlying-only, no probability, WAIT has no targets."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.publish_classical_direction import SCHEMA, build_digest

NOW = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
POLICY = {"option_chain_data_used_for_direction": False, "options_flow_used": False,
          "greeks_used": False}


def _payload(**extra):
    return {"path": "classical_direction", "generated_at": "2026-10-20T14:55:00+00:00",
            "policy": dict(POLICY), "summary": {"operational_status": "READY"},
            "signals": [{"symbol": "NVDA", "decision": "CALL", "priority": "HIGH", "agreement_pct": 100,
                         "price": 181.2, "confirmation_level": 182.0, "invalidation_level": 176.5,
                         "targets": {"t1": 186.0, "t2": 190.0, "risk_per_share": 4.7, "note": "x"},
                         "daily": {"direction": "BULLISH"}, "hourly": {"direction": "BULLISH"},
                         "intraday": {"direction": "BULLISH"},
                         "scenarios_ar": ["a", "b", "c", "d"], "reasons_ar": ["r"] * 6}],
            "waits": [{"symbol": "AAPL", "decision": "WAIT", "agreement_pct": 33,
                       "targets": {"t1": 1.0}, "price": 250.0},
                      {"symbol": "BAD", "decision": "BUY"}], **extra}


def test_digest_keeps_calls_first_strips_non_numeric_targets_and_wait_targets():
    digest = build_digest(_payload(), now=NOW)
    assert digest["schema"] == SCHEMA
    assert [c["symbol"] for c in digest["companies"]] == ["NVDA", "AAPL"]
    nvda, aapl = digest["companies"]
    assert nvda["targets"] == {"t1": 186.0, "t2": 190.0, "risk_per_share": 4.7}
    assert aapl["targets"] is None
    assert len(nvda["scenarios_ar"]) == 3 and len(nvda["reasons_ar"]) == 4
    assert nvda["timeframes"] == {"daily": "BULLISH", "hourly": "BULLISH", "intraday": "BULLISH"}
    assert digest["counts"] == {"CALL": 1, "PUT": 0, "WAIT": 1}
    assert digest["probability"] is None and digest["execution_authority"] is False


def test_option_data_in_direction_or_wrong_path_is_refused():
    bad = _payload()
    bad["policy"]["greeks_used"] = True
    with pytest.raises(ValueError):
        build_digest(bad, now=NOW)
    with pytest.raises(ValueError):
        build_digest({**_payload(), "path": "options"}, now=NOW)
    with pytest.raises(ValueError):
        build_digest(_payload(), now=NOW.replace(tzinfo=None))


def test_trade_status_passes_through_and_unknown_values_are_not_trusted():
    payload = _payload()
    payload["signals"][0]["trade_status"] = "NO_TRADE"
    rows = {r["symbol"]: r for r in build_digest(payload, now=NOW)["companies"]}
    assert rows["NVDA"]["trade_status"] == "NO_TRADE"
    assert rows["AAPL"]["trade_status"] == "WAIT"
    payload["signals"][0]["trade_status"] = "YOLO"
    rows = {r["symbol"]: r for r in build_digest(payload, now=NOW)["companies"]}
    assert rows["NVDA"]["trade_status"] == "UNRATED"
