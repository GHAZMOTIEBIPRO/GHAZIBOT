from copy import deepcopy
from datetime import datetime, timezone

import pytest

from options_radar.audit_quality import validate_audit
from scripts.build_reliability_report import build_report, read, update_ledger

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def audit():
    return {"mode": "HISTORICAL_5M_OUTCOME_AUDIT", "decision_authority": False,
            "records": {"a": {"signal_id": "a", "symbol": "AAPL",
                              "signal_time": "2026-10-22T15:00:00+00:00",
                              "audit_status": "pending", "entry_price": 100,
                              "decision_authority": False}}}


def test_valid_and_empty_are_distinct():
    assert validate_audit(audit(), now=NOW)["status"] == "VALID"
    data = audit()
    data["records"] = {}
    assert validate_audit(data, now=NOW)["status"] == "EMPTY"


@pytest.mark.parametrize("field,value", [("signal_time", "2026-10-22T15:00:00"),
    ("signal_time", "2030-01-01T00:00:00Z"), ("symbol", "<script>"),
    ("decision_authority", "false"), ("audit_status", "WIN"), ("signal_id", "other"), ("entry_price", -1), ("entry_price", True)])
def test_bad_observations_fail_closed(field, value):
    data = audit()
    data["records"]["a"][field] = value
    report, ledger = build_report(data, {}, {"status": "RESEARCH_METRICS_ONLY"}, now=NOW)
    assert report["quality"]["status"] == "INVALID"
    assert report["statistics_status"] == "WITHHELD"
    assert ledger == {}


def test_nan_return_rejected():
    data = audit()
    data["records"]["a"]["checkpoints"] = {"60m": {"directional_return_pct": float("nan")}}
    assert validate_audit(data, now=NOW)["status"] == "INVALID"


def test_first_entry_hash_stays_frozen_and_conflicts_sticky():
    data = audit()
    ledger, summary = update_ledger(data, {}, now=NOW)
    original = deepcopy(ledger)
    data["records"]["a"]["audit_status"] = "failed"
    same, summary = update_ledger(data, ledger, now=NOW)
    assert summary["conflicts_this_pass"] == 0
    assert same == original  # Outcomes can evolve without rewriting entry evidence.
    data["records"]["a"]["entry_price"] = 200
    changed, summary = update_ledger(data, same, now=NOW)
    assert summary["ever_changed"] == 1
    key = next(iter(changed["entries"]))
    assert changed["entries"][key]["entry_hash"] == original["entries"][key]["entry_hash"]
    data["records"]["a"]["entry_price"] = 100
    report, _ = build_report(data, changed, {"status": "RESEARCH_METRICS_ONLY"}, now=NOW)
    assert report["statistics_status"] == "WITHHELD"
    assert "AAPL" not in str(changed)


def test_corrupt_existing_ledger_is_not_silently_reset(tmp_path):
    file = tmp_path / "ledger.json"
    file.write_text("broken")
    with pytest.raises(ValueError):
        read(file, optional=True)
    with pytest.raises(ValueError):
        update_ledger(audit(), {"schema": "bad"}, now=NOW)
