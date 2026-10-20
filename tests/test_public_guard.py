import json
import re
import sys
from pathlib import Path

import pytest

from options_radar import public_guard as guard
from options_radar import source_permissions as sp

ROOT = Path(__file__).resolve().parents[1]
CLOSED = ["yahoo", "nasdaq_web", "cboe_delayed", "community_gex"]


@pytest.fixture(autouse=True)
def closed_gates(monkeypatch):
    for gate in sp.GATES.values():
        monkeypatch.delenv(gate["variable"], raising=False)


def latest_payload():
    return {
        "generated_at": "2026-10-20T18:00:00+00:00",
        "stocks": [{"symbol": "AMD", "price": 649.4}],
        "charts": {"AMD": {"bars": [[1, 2, 3, 4, 5]]}},
        "catalysts": [{"headline": "8-K filed", "source": "SEC EDGAR"},
                      {"headline": "rumour", "source": "Yahoo Finance news"}],
        "omega": {"summary": {"day_opportunities": 1},
                  "omega_day": [{"symbol": "RIVN", "price": 14.87}],
                  "explosion_radar": {"upside": [{"symbol": "IOVA", "price": 7.1}]},
                  "target_maps": {"RIVN": {"symbol": "RIVN", "entry": {"low": 14.77, "high": 15.12}}}},
        "provider_audit": [{"provider": "yahoo/yfinance", "ok": False}],
        "health": {"status": "degraded"},
    }


def test_closed_gates_are_reported():
    assert set(guard.closed_families()) == set(CLOSED)


def test_latest_loses_every_price_and_closed_source_object():
    out = guard.guard_payload(latest_payload(), kind="latest")
    text = json.dumps(out)
    assert out["stocks"] == [] and out["charts"] == {}
    assert out["omega"]["omega_day"] == [] and out["omega"]["explosion_radar"]["upside"] == []
    assert out["omega"]["target_maps"] == {}
    assert out["omega"]["summary"] == {"day_opportunities": 1}
    assert [c["source"] for c in out["catalysts"]] == ["SEC EDGAR"]
    assert out["provider_audit"] == []
    assert not re.search(r'"(price|low|high)": \d', text)
    info = out["public_license_guard"]
    assert info["data_state"] == "LICENSE_BLOCKED" and info["redacted_objects"]["yahoo"] == 2
    assert "omega.target_maps" in info["price_sections_emptied"]


def test_guardian_rows_without_permitted_quotes_become_identity_stubs():
    report = {"active": [{"contract_symbol": "AMD261030C00655000", "symbol": "AMD", "side": "CALL",
                          "strike": 655.0, "expiration": "2026-10-30", "entry_premium_reference": 30.15,
                          "entry_underlying": 649.42, "stage": "ACTIVE", "quote_snapshots": [],
                          "unstamped_research_observations": [{"source": "yahoo/yfinance", "indicative_bid": 29.0}]}],
              "terminal_recent": [], "active_count": 1}
    out = guard.guard_payload(report, kind="guardian")
    row = out["active"][0]
    assert row["stage"] == "LICENSE_BLOCKED" and row["strike"] == 655.0
    assert "entry_premium_reference" not in row and "entry_underlying" not in row
    assert out["active_count"] == 0 and out["license_blocked_count"] == 1


def test_permitted_stamped_quotes_keep_a_guardian_row():
    row = {"contract_symbol": "X", "stage": "ACTIVE", "entry_premium_reference": 1.2,
           "quote_snapshots": [{"source": "tradier", "provider_quote_timestamp": "2026-10-20T18:00:00Z", "bid": 1.1}]}
    out = guard.guard_payload({"active": [row], "terminal_recent": []}, kind="guardian")
    assert out["active"][0]["entry_premium_reference"] == 1.2 and out["active_count"] == 1


def test_open_gates_leave_payload_unchanged(monkeypatch):
    for gate in sp.GATES.values():
        monkeypatch.setenv(gate["variable"], "true")
    payload = latest_payload()
    assert guard.guard_payload(payload, kind="latest") == payload


def test_vault_publishes_guarded_public_files(tmp_path, monkeypatch):
    from scripts import runtime_state_vault as vault

    repo, vault_root = tmp_path / "repo", tmp_path / "vault"
    (repo / "public/data").mkdir(parents=True)
    (repo / "public/data/latest.json").write_text(json.dumps(latest_payload()))
    (repo / "public/data/health.json").write_text(json.dumps({"status": "degraded"}))
    vault.publish_runtime_state(repo_root=repo, vault_root=vault_root)
    published = json.loads((vault_root / "public/data/latest.json").read_text())
    assert published["stocks"] == [] and "public_license_guard" in published
    # The working copy used by later steps of the same job is untouched.
    assert json.loads((repo / "public/data/latest.json").read_text())["stocks"]
    assert json.loads((vault_root / "public/data/health.json").read_text()) == {"status": "degraded"}


@pytest.mark.parametrize("name", ["latest.json", "decision_brief.json", "index_radar.json", "spx_dashboard.json"])
def test_site_fallback_files_carry_no_closed_source_prices(name):
    data = json.loads((ROOT / "public/data" / name).read_text(encoding="utf-8"))
    text = json.dumps(data).lower()
    if data.get("status") == "SOURCE_TERMS_BLOCKED":
        assert data.get("symbols", {}) == {} and data.get("spot") is None
        return
    assert "public_license_guard" in data
    assert not re.search(r'"(price|spot|entry_premium_reference|last_underlying_price)": \d', text)


def test_spx_dashboard_blocked_without_any_request(monkeypatch, tmp_path):
    from scripts import build_spx_dashboard as spx

    monkeypatch.setattr(spx, "live_snapshot", lambda now: pytest.fail("no Yahoo request allowed"))
    out = tmp_path / "spx.json"
    monkeypatch.setattr(sys, "argv", ["x", "--output", str(out)])
    assert spx.main() == 0
    data = json.loads(out.read_text())
    assert data["status"] == "SOURCE_TERMS_BLOCKED" and data["spot"] is None
    assert data["trade_map"]["state"] == "DATA_UNAVAILABLE"


def test_no_workflow_calls_a_gated_provider_inline():
    offenders = []
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\byf\.(download|Ticker)\(|import yfinance|from yahooquery|api\.nasdaq\.com/api", line):
                offenders.append(f"{path.name}:{number}")
    assert not offenders, offenders
