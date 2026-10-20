import json
import sys

import pytest

from options_radar import free_gex_validation as fgv
from options_radar.source_permissions import cboe_delayed_automation_allowed
from scripts import build_options_analytics as boa
from scripts.build_data_hub import REGISTRY, assess


def test_gate_is_off_unless_explicitly_true(monkeypatch):
    monkeypatch.delenv("CBOE_DELAYED_AUTOMATION_APPROVED", raising=False)
    assert cboe_delayed_automation_allowed() is False
    for value in ("false", "1", "yes", ""):
        monkeypatch.setenv("CBOE_DELAYED_AUTOMATION_APPROVED", value)
        assert cboe_delayed_automation_allowed() is False
    monkeypatch.setenv("CBOE_DELAYED_AUTOMATION_APPROVED", "true")
    assert cboe_delayed_automation_allowed() is True


def test_blocked_options_analytics_makes_no_request_and_overwrites_old_file(monkeypatch, tmp_path):
    monkeypatch.delenv("CBOE_DELAYED_AUTOMATION_APPROVED", raising=False)
    out = tmp_path / "options_analytics.json"
    out.write_text(json.dumps({"symbols": {"SPY": {"expected_move": {"move_pct": 0.5}}}}))
    monkeypatch.setattr(boa, "fetch_chain", lambda s: pytest.fail("no Cboe request allowed"))
    monkeypatch.setattr(sys, "argv", ["x", "--output", str(out)])
    assert boa.main() == 0
    report = json.loads(out.read_text())
    assert report["status"] == "SOURCE_TERMS_BLOCKED" and report["symbols"] == {}


def test_blocked_gex_validation_makes_no_cboe_request_and_drops_stored_levels(monkeypatch, tmp_path):
    monkeypatch.delenv("CBOE_DELAYED_AUTOMATION_APPROVED", raising=False)
    history = tmp_path / "h.json"
    history.write_text(json.dumps([{"generated_at": "2026-10-20T04:00:00+00:00",
                                    "engine_levels": {"spot": 7690, "call_wall": 7800}}]))
    monkeypatch.setattr(fgv, "HISTORY", history)
    monkeypatch.setattr(fgv, "OUT", tmp_path / "out.json")
    monkeypatch.setattr(fgv, "fetch_cboe", lambda url: pytest.fail("no Cboe request allowed"))
    monkeypatch.setattr(fgv, "build_ghazi_gex", lambda: pytest.fail("no Cboe request allowed"))
    monkeypatch.setattr(fgv, "get", lambda url, timeout=15: (_ for _ in ()).throw(OSError("offline")))
    payload = fgv.build()
    engine = payload["integrated_engines"]["ghazi_gex_multi"]
    assert engine["available"] is False and engine["status"] == "SOURCE_TERMS_BLOCKED"
    assert all(e["engine_levels"] is None for e in json.loads(history.read_text()))


def test_data_hub_reports_rights_separately_from_freshness():
    entry = next(e for e in REGISTRY if e["file"] == "options_analytics.json")
    from datetime import datetime, timezone
    now = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
    row = assess(entry, {"generated_at": "2026-10-20T14:50:00+00:00", "status": "SOURCE_TERMS_BLOCKED"}, now)
    assert row["freshness"] == "FRESH"
    assert row["rights_status"] == "BLOCKED_PENDING_PERMISSION"
    yahoo = next(e for e in REGISTRY if e["file"] == "stock_watch_charts.json")
    assert assess(yahoo, {"generated_at": "2026-10-20T14:50:00+00:00"}, now)["rights_status"] == "NOT_AUTHORISED_FALLBACK"
