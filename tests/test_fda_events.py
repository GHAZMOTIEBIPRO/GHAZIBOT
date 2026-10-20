import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("fda_under_test", ROOT / "options_radar" / "fda_events.py")
fda = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fda)

ALIASES = {"VRTX": "Vertex Pharmaceuticals Inc", "PFE": "Pfizer Inc", "ABC": "Alpha Labs Inc", "XYZ": "Alpha Labs Corp"}
INDEX = fda.build_name_index(ALIASES)
START, END = date(2026, 9, 21), date(2026, 10, 20)


def test_name_matching_is_conservative():
    assert fda.match_ticker("VERTEX PHARMACEUTICALS INCORPORATED", INDEX) == ("VRTX", "exact_normalised_name")
    assert fda.match_ticker("Pfizer Labs", INDEX) == ("PFE", "exact_normalised_name")
    # Two tickers share a normalised name: no guess.
    assert fda.match_ticker("Alpha Labs", INDEX) == (None, "unmatched")
    assert fda.match_ticker("Teva Pharmaceuticals USA", INDEX) == (None, "unmatched")
    assert fda.match_ticker("", INDEX) == (None, "no_name")


def test_approvals_keep_only_ap_in_window_and_rank_originals():
    rows = [{"application_number": "NDA217123", "sponsor_name": "VERTEX PHARMACEUTICALS INC",
             "products": [{"brand_name": "NEWDRUG"}],
             "submissions": [
                 {"submission_type": "ORIG", "submission_number": "1", "submission_status": "AP",
                  "submission_status_date": "20261015", "review_priority": "PRIORITY",
                  "submission_class_code_description": "Type 1 - New Molecular Entity"},
                 {"submission_type": "SUPPL", "submission_number": "2", "submission_status": "AP",
                  "submission_status_date": "20261001", "submission_class_code_description": "Efficacy"},
                 {"submission_type": "SUPPL", "submission_number": "3", "submission_status": "TA",
                  "submission_status_date": "20261002"},
                 {"submission_type": "SUPPL", "submission_number": "4", "submission_status": "AP",
                  "submission_status_date": "20250101"}]}]
    events = fda.approval_events(rows, INDEX, START, END)
    assert [e["event_type"] for e in events] == ["APPROVAL_ORIGINAL", "APPROVAL_SUPPLEMENT"]
    assert events[0]["ticker"] == "VRTX" and events[0]["importance"] == "HIGH"
    assert events[1]["importance"] == "MEDIUM"
    assert events[0]["official_url"].endswith("ApplNo=217123")
    assert events[0]["date"] == "2026-10-15"


def test_recalls_classified_and_deduplicated():
    row = {"recall_number": "D-0001-2027", "recalling_firm": "Pfizer Inc.", "classification": "Class I",
           "report_date": "20261014", "product_description": "x", "reason_for_recall": "y"}
    events = fda.recall_events([row, dict(row)], INDEX)
    assert len(events) == 1 and events[0]["importance"] == "HIGH" and events[0]["ticker"] == "PFE"


def test_report_policy():
    report = fda.build([], [], generated_at="2026-10-20T20:00:00+00:00", start=START, end=END)
    assert report["schema"] == "ghazi.fda_events.v1"
    assert report["decision_authority"] is False and "CC0" in report["rights"]
    json.dumps(report, allow_nan=False)


def test_script_keeps_previous_file_when_both_endpoints_fail(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("build_fda_under_test", ROOT / "scripts" / "build_fda_events.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    out = tmp_path / "fda.json"
    out.write_text('{"keep": true}')
    monkeypatch.setattr(script, "_get", lambda path, params, attempts=3: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(sys, "argv", ["x", "--output", str(out)])
    assert script.main() == 1 and json.loads(out.read_text()) == {"keep": True}
    monkeypatch.setattr(script, "_get", lambda path, params, attempts=3: [])
    assert script.main() == 0
    assert json.loads(out.read_text())["counts"]["approvals"] == 0
