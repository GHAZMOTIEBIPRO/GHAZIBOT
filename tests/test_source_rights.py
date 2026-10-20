import importlib.util
import json
from pathlib import Path

import pytest

from options_radar import source_permissions as sp

ROOT = Path(__file__).resolve().parents[1]
MATRIX = json.loads((ROOT / "data/source_rights.json").read_text(encoding="utf-8"))
RIGHTS = ("automated_access", "internal_analysis", "persistent_storage", "public_display_raw",
          "public_display_derived", "github_actions_automation", "commercial_use_on_free_tier")

_spec = importlib.util.spec_from_file_location("gate_rights", ROOT / "scripts/price_source_gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def test_matrix_shape_and_evidence():
    assert MATRIX["schema"] == "ghazi.source_rights.v1"
    assert MATRIX["status_values"] == ["VERIFIED", "RESTRICTED", "UNKNOWN"]
    assert MATRIX["evidence_run"] == "39478127523"
    for key, entry in MATRIX["providers"].items():
        assert entry["official_url"].startswith("https://"), key
        for right in RIGHTS:
            item = entry["rights"][right]
            assert item["status"] in MATRIX["status_values"], (key, right)
            if item["status"] != "UNKNOWN":
                # Every decision carries the official text (or the recorded basis) behind it.
                assert item.get("evidence") or item.get("basis"), (key, right)


@pytest.mark.parametrize("provider,gate_name", [("yahoo", "yahoo"), ("nasdaq_web", "nasdaq_web"),
                                                ("cboe_delayed", "cboe_delayed")])
def test_restricted_automation_matches_a_closed_gate(provider, gate_name, monkeypatch):
    monkeypatch.delenv(sp.GATES[gate_name]["variable"], raising=False)
    assert MATRIX["providers"][provider]["rights"]["automated_access"]["status"] == "RESTRICTED"
    assert sp.allowed(gate_name) is False


def test_no_free_price_provider_is_verified_for_public_display():
    price = [k for k, v in MATRIX["providers"].items() if v["category"] in {"price", "options"}]
    assert price
    for key in price:
        assert MATRIX["providers"][key]["rights"]["public_display_raw"]["status"] != "VERIFIED", key
    from options_radar.public_guard import PUBLIC_DISPLAY_VERIFIED_KEYS
    assert PUBLIC_DISPLAY_VERIFIED_KEYS == ()


def test_keys_follow_the_rights_matrix(monkeypatch):
    rights = MATRIX["providers"]
    monkeypatch.delenv("DATA_TERMS_CONFIRMED", raising=False)
    for key in gate.KEY_PROVIDER:
        monkeypatch.setenv(f"HAS_{key}", "true")
    # Personal-only terms that exclude research use can never be enabled.
    assert gate.key_usable("MARKETDATA_TOKEN", rights) is False
    monkeypatch.setenv("DATA_TERMS_CONFIRMED", "marketdata_app")
    assert gate.key_usable("MARKETDATA_TOKEN", rights) is False
    # Verified internal use counts; unknown terms need the owner's confirmation.
    assert gate.key_usable("TWELVE_DATA_API_KEY", rights) is True
    monkeypatch.setenv("DATA_TERMS_CONFIRMED", "")
    assert gate.key_usable("TIINGO_API_KEY", rights) is False
    monkeypatch.setenv("DATA_TERMS_CONFIRMED", "tiingo")
    assert gate.key_usable("TIINGO_API_KEY", rights) is True


def test_data_hub_publishes_rights():
    spec = importlib.util.spec_from_file_location("hub_rights", ROOT / "scripts/build_data_hub.py")
    hub = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hub)
    block = hub._source_rights()
    assert block["available"] is True and block["unknown_is_not_permission"] is True
    assert block["providers"]["openfda"]["rights"]["public_display_raw"] == "VERIFIED"
    assert block["providers"]["yahoo"]["rights"]["automated_access"] == "RESTRICTED"
