import importlib.util
from pathlib import Path

import pytest
import yaml

from options_radar import free_data_health as health
from options_radar import free_gex_validation as fgv
from options_radar import source_permissions as sp
from options_radar import spx_external_gamma as spx_gamma
from scripts import telegram_watchdog_status as watchdog

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("price_gate_under_test", ROOT / "scripts/price_source_gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


@pytest.fixture(autouse=True)
def closed_gates(monkeypatch):
    for item in sp.GATES.values():
        monkeypatch.delenv(item["variable"], raising=False)
    for keys in gate.ACCOUNT_KEYS.values():
        for key in keys:
            monkeypatch.delenv(f"HAS_{key}", raising=False)
    monkeypatch.delenv("DATA_TERMS_CONFIRMED", raising=False)


def test_gate_requires_every_input(monkeypatch):
    assert gate.evaluate(["price"]) == (False, ["price"])
    monkeypatch.setenv("HAS_TRADIER_TOKEN", "true")
    # Tradier's terms page was not readable (UNKNOWN): a key alone is not enough.
    assert gate.evaluate(["options", "price"]) == (False, ["options", "price"])
    monkeypatch.setenv("DATA_TERMS_CONFIRMED", "tradier")
    assert gate.evaluate(["options", "price"]) == (True, [])
    assert gate.evaluate(["discovery", "price"]) == (False, ["discovery"])
    monkeypatch.setenv("NASDAQ_WEB_AUTOMATION_APPROVED", "true")
    assert gate.evaluate(["discovery", "price"]) == (True, [])


def test_gate_writes_outputs(monkeypatch, tmp_path, capsys):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr("sys.argv", ["x", "--require", "options,price"])
    assert gate.main() == 0
    assert "usable=false" in out.read_text()
    assert "SOURCE_TERMS_BLOCKED" in capsys.readouterr().out


@pytest.mark.parametrize("name,job", [("stock-radar.yml", "deep-stock-validation"),
                                      ("options-contract-radar.yml", "scan-options"),
                                      ("explosion-options-crosscheck.yml", "crosscheck")])
def test_price_workflows_skip_through_the_gate_job(name, job):
    doc = yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))
    jobs = doc["jobs"]
    assert "source-gate" in jobs
    assert jobs[job]["needs"] == ["source-gate"]
    assert "needs.source-gate.outputs.usable == 'true'" in str(jobs[job]["if"])
    step_env = jobs["source-gate"]["steps"][-1]["env"]
    assert all(value.endswith("!= '' }}") for value in step_env.values() if "secrets." in value)
    assert step_env["DATA_TERMS_CONFIRMED"].startswith("${{ vars.")


def test_watchdog_reports_a_gated_skip_as_paused_not_recovered():
    jobs = [{"name": "source-gate", "conclusion": "success"}, {"name": "scan-options", "conclusion": "skipped"}]
    assert watchdog.paused_by_source_gate(jobs) is True
    assert watchdog.paused_by_source_gate([{"name": "scan-options", "conclusion": "success"}]) is False
    assert watchdog.paused_by_source_gate(jobs[:1] + [{"name": "scan-options", "conclusion": "success"}]) is False
    text = watchdog.render_message("paused", {"name": "Options", "id": "1"}, 7)
    assert "ليس تعافيًا" in text and "⏸️" in text


def test_community_gex_feeds_make_no_request(monkeypatch, tmp_path):
    monkeypatch.setattr(fgv, "OUT", tmp_path / "free_gex_validation.json")
    def no_request(*_args, **_kwargs):
        pytest.fail("no request to an unlicensed feed")

    monkeypatch.setattr(spx_gamma, "_get", no_request)
    context = spx_gamma.build_spx_external_context()
    assert context["available"] is False and "SOURCE_TERMS_BLOCKED" in context["errors"]["daily_gamma"]
    monkeypatch.setattr(fgv, "fetch_json_source", no_request)
    monkeypatch.setattr(fgv, "fetch_archive", no_request)
    monkeypatch.setattr(fgv, "get", lambda url, timeout=15: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(fgv, "HISTORY", tmp_path / "history.json")
    rows = fgv.build()["sources"]
    community = [r for r in rows if r.get("source") in fgv.SOURCES]
    assert len(community) == 2 and all(r["status"] == "SOURCE_TERMS_BLOCKED" for r in community)
    assert not any(r.get("available") for r in rows)
    monkeypatch.setattr(health, "_request", no_request)
    checked = [health.check(s) for s in health.SOURCES if s.get("gate")]
    assert len(checked) == 2 and all(row["license_blocked"] for row in checked)
